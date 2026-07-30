"""
Extraction Agent — section-aware source parse into a fact-ID knowledge base.

Deterministic first: the detailed parser + structured store already handle any
input length linearly (a 20-page resume never hits one prompt). An LLM
map-reduce fallback runs per chunk only when the deterministic parse found
almost nothing to work with.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.agents.tools.llm_client import llm_call_json_with_metrics
from app.core.logging import logger
from app.services.structured_resume_store import build_structured_resume

from app.agent_pipeline.state import Budgets, ResumeKB

_CHUNK_CHARS = 6500
_MAX_EXTRACT_CALLS = 4

_EXTRACT_SYSTEM = """You extract resume facts from ONE text chunk. Return ONLY valid JSON.
Rules:
1) Extract only what is literally present in the chunk. Never invent or infer.
2) Keep original wording for bullets; do not summarize or merge achievements.
3) A chunk may contain partial roles — extract whatever fields are present.
"""


def build_kb(candidate_data: dict[str, Any], budgets: Budgets) -> ResumeKB:
    """Build the knowledge base, using LLM chunk extraction only as a fallback."""
    store = build_structured_resume(candidate_data)

    raw_text = str(candidate_data.get("raw_resume_text") or "")
    if not (store.get("experience") or []) and len(raw_text) > 1500:
        extracted = _llm_extract_from_chunks(raw_text, budgets)
        if extracted:
            merged = dict(candidate_data)
            for key in ("experience", "education", "projects", "certifications"):
                if not merged.get(key) and extracted.get(key):
                    merged[key] = extracted[key]
            if not merged.get("skills") and extracted.get("skills"):
                merged["skills"] = extracted["skills"]
            if not merged.get("summary") and extracted.get("summary"):
                merged["summary"] = extracted["summary"]
            store = build_structured_resume(merged)

    kb = ResumeKB(store=store)
    _index_facts(kb)
    kb.build_grounding_blob()
    logger.info(
        "agent_kb_built",
        facts=len(kb.facts),
        roles=len(store.get("experience") or []),
        bullets=(store.get("stats") or {}).get("experience_bullets"),
        raw_chars=(store.get("stats") or {}).get("raw_chars"),
    )
    return kb


def _index_facts(kb: ResumeKB) -> None:
    store = kb.store

    summary = str(store.get("summary") or "").strip()
    if summary:
        for i, sentence in enumerate(re.split(r"(?<=[.!?])\s+", summary)):
            if sentence.strip():
                kb.add_fact(f"summary.s{i}", "summary", sentence)

    for cat, values in (store.get("skills_by_category") or {}).items():
        for j, skill in enumerate(values or []):
            kb.add_fact(f"skill.{cat}.{j}", "skills", str(skill), category=str(cat))

    for i, role in enumerate(store.get("experience") or []):
        if not isinstance(role, dict):
            continue
        identity = " | ".join(
            str(role.get(k) or "") for k in ("company", "title", "duration")
        ).strip(" |")
        kb.add_fact(f"exp{i}", "experience", identity, role_index=i, kind="role")
        for j, bullet in enumerate(role.get("description") or []):
            kb.add_fact(f"exp{i}.b{j}", "experience", str(bullet), role_index=i, kind="bullet")
        for j, tech in enumerate(role.get("technologies") or []):
            kb.add_fact(f"exp{i}.t{j}", "experience", str(tech), role_index=i, kind="tech")

    for i, edu in enumerate(store.get("education") or []):
        if isinstance(edu, dict):
            text = " | ".join(
                str(edu.get(k) or "") for k in ("degree", "institution", "year")
            ).strip(" |")
            kb.add_fact(f"edu{i}", "education", text)

    for i, proj in enumerate(store.get("projects") or []):
        if not isinstance(proj, dict):
            continue
        kb.add_fact(f"proj{i}", "projects", str(proj.get("name") or ""), kind="name")
        for j, bullet in enumerate(proj.get("description") or []):
            kb.add_fact(f"proj{i}.b{j}", "projects", str(bullet), kind="bullet")

    for i, cert in enumerate(store.get("certifications") or []):
        kb.add_fact(f"cert{i}", "certifications", str(cert))
    for i, ach in enumerate(store.get("achievements") or []):
        kb.add_fact(f"ach{i}", "achievements", str(ach))


def _split_chunks(text: str) -> list[str]:
    """Split on paragraph boundaries so roles/sections stay intact per chunk."""
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for para in paragraphs:
        para = para.strip("\n")
        if size + len(para) > _CHUNK_CHARS and current:
            chunks.append("\n\n".join(current))
            current, size = [], 0
        current.append(para)
        size += len(para)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _llm_extract_from_chunks(raw_text: str, budgets: Budgets) -> dict[str, Any] | None:
    """Map: extract facts per chunk. Reduce: merge lists in source order."""
    chunks = _split_chunks(raw_text)
    if not chunks:
        return None

    merged: dict[str, Any] = {
        "summary": "",
        "skills": [],
        "experience": [],
        "education": [],
        "projects": [],
        "certifications": [],
    }
    calls = 0
    for chunk in chunks:
        if calls >= _MAX_EXTRACT_CALLS or not budgets.allow_llm(min_time_left_s=20.0):
            logger.info("agent_extract_budget_stop", chunks_done=calls, chunks_total=len(chunks))
            break
        try:
            result = llm_call_json_with_metrics(
                _EXTRACT_SYSTEM,
                "\n".join(
                    [
                        "Extract resume facts from this chunk.",
                        "Return JSON schema:",
                        json.dumps(
                            {
                                "summary": "string or empty",
                                "skills": ["skill"],
                                "experience": [
                                    {
                                        "company": "",
                                        "title": "",
                                        "duration": "",
                                        "location": "",
                                        "description": ["original bullet"],
                                        "technologies": [],
                                    }
                                ],
                                "education": [{"degree": "", "institution": "", "year": ""}],
                                "projects": [{"name": "", "description": []}],
                                "certifications": ["cert"],
                            },
                            ensure_ascii=True,
                        ),
                        "",
                        "CHUNK:",
                        chunk,
                    ]
                ),
                repair_attempts=1,
                max_tokens=4096,
            )
            calls += 1
            budgets.spend_llm()
            data = result.data
            if str(data.get("summary") or "").strip() and not merged["summary"]:
                merged["summary"] = str(data["summary"]).strip()
            for key in ("skills", "experience", "education", "projects", "certifications"):
                values = data.get(key)
                if isinstance(values, list):
                    merged[key].extend(values)
        except Exception as exc:
            logger.warning("agent_extract_chunk_failed", error=str(exc))
            calls += 1
            budgets.spend_llm()

    if not merged["experience"] and not merged["skills"]:
        return None
    logger.info(
        "agent_extract_map_reduce_complete",
        chunks=calls,
        roles=len(merged["experience"]),
        skills=len(merged["skills"]),
    )
    return merged
