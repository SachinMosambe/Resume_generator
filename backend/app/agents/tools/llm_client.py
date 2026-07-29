"""
LLM factory — AWS Bedrock only (Google Gemma 3 27B).
"""
import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable

from langchain_core.messages import HumanMessage, SystemMessage
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import logger


JsonValidator = Callable[[dict], list[str]]


@dataclass
class LLMJsonCallResult:
    """Parsed JSON plus reliability metrics for the caller's agent checkpoint."""

    data: dict
    metrics: dict


def is_rate_limit_error(exc: BaseException) -> bool:
    """True when Bedrock rejected the call due to rate limiting / throttling."""
    message = str(exc).lower()
    return (
        "429" in message
        or "rate limit" in message
        or "too many requests" in message
        or "throttling" in message
    )


def is_auth_error(exc: BaseException) -> bool:
    """True when Bedrock rejected the call due to invalid/missing credentials."""
    message = str(exc).lower()
    return (
        "401" in message
        or "unauthorized" in message
        or "authentication" in message
        or "bearer" in message and "not configured" in message
    )


def _messages_to_dicts(messages: list) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            out.append({"role": "system", "content": str(msg.content or "")})
        elif isinstance(msg, HumanMessage):
            out.append({"role": "user", "content": str(msg.content or "")})
        else:
            role = getattr(msg, "type", None) or "user"
            if role == "human":
                role = "user"
            out.append({"role": str(role), "content": str(getattr(msg, "content", "") or "")})
    return out


_bedrock_client = None
_bedrock_client_lock = threading.Lock()


def _get_bedrock_client():
    global _bedrock_client
    with _bedrock_client_lock:
        if _bedrock_client is None:
            from app.services.interview_llm.bedrock_client import BedrockInterviewClient

            _bedrock_client = BedrockInterviewClient()
        return _bedrock_client


@retry(
    retry=retry_if_exception(is_rate_limit_error),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=8, max=60),
    reraise=True,
)
def _invoke_bedrock_sync(messages: list, model: str, max_tokens: int | None) -> str:
    """Synchronous Bedrock call for Celery / LangGraph agents."""
    import asyncio

    client = _get_bedrock_client()
    msg_dicts = _messages_to_dicts(messages)
    token_budget = max_tokens or settings.LLM_MAX_TOKENS

    async def _run() -> str:
        return await client.chat_completion(
            model=model,
            messages=msg_dicts,
            max_tokens=token_budget,
            temperature=0.0,
            json_mode=False,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run())

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _run()).result()


def llm_call(
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> str:
    """Make a Bedrock chat completion call and return the raw string response.

    ``provider`` is accepted for call-site compatibility but ignored — Bedrock only.
    """
    del provider  # Bedrock-only; kept for backward-compatible call sites
    model = model or settings.bedrock_model

    started = time.perf_counter()
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    content = _invoke_bedrock_sync(messages, model, max_tokens)
    if len(str(content or "").strip()) < 8:
        raise ValueError("empty_llm_response")
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "llm_call_complete",
        elapsed_ms=elapsed_ms,
        provider="bedrock",
        model=model,
        input_chars=len(system_prompt or "") + len(user_prompt or ""),
        output_chars=len(content or ""),
    )
    return content


def _estimate_tokens(chars: int) -> int:
    """Cheap token estimate for observability when provider token usage is unavailable."""
    return max(1, int(chars / 4)) if chars > 0 else 0


def _clean_json_text(raw: str) -> str:
    """Strip common markdown wrappers around JSON."""
    return re.sub(r"```(?:json)?", "", raw or "").strip().rstrip("```").strip()


def _parse_json_text(raw: str) -> dict:
    """Parse a JSON object from a model response."""
    cleaned = _clean_json_text(raw)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
        else:
            raise

    if not isinstance(parsed, dict):
        raise ValueError("LLM JSON response must be an object")
    return parsed


def _looks_truncated_json(raw: str) -> bool:
    """Heuristic: truncated model output often ends mid-string / with unbalanced braces."""
    text = _clean_json_text(raw)
    if len(text) < 40:
        return True
    # Unbalanced braces/brackets strongly suggest max_tokens cut the response.
    if text.count("{") > text.count("}"):
        return True
    if text.count("[") > text.count("]"):
        return True
    # Cut mid-word / mid-escape (common when stopReason=max_tokens).
    stripped = text.rstrip()
    if stripped and stripped[-1] not in "{}],\"'":
        # Allow trailing digits/letters only if JSON already balanced (checked above).
        if stripped[-1].isalnum() or stripped[-1] in "\\":
            return True
    return False


def _repair_json_prompt(raw: str, validation_errors: list[str] | None = None) -> tuple[str, str]:
    system_prompt = (
        "You repair JSON for a production API. Return ONLY one valid JSON object. "
        "Do not add markdown, commentary, or extra keys unless needed to satisfy errors. "
        "Preserve ALL resume sections, roles, and bullets from the input — never shrink content."
    )
    error_block = ""
    if validation_errors:
        error_block = "VALIDATION ERRORS:\n" + "\n".join(f"- {e}" for e in validation_errors) + "\n\n"
    # Keep almost the full payload; clipping to 6k was destroying long resumes.
    payload = (raw or "")[:48000]
    user_prompt = (
        f"{error_block}"
        "Repair this response into valid JSON while preserving the intended data:\n"
        f"{payload}"
    )
    return system_prompt, user_prompt


def llm_call_json_with_metrics(
    system_prompt: str,
    user_prompt: str,
    *,
    validate: JsonValidator | None = None,
    repair_attempts: int = 1,
    validation_attempts: int = 1,
    max_tokens: int | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> LLMJsonCallResult:
    """Call Bedrock, parse JSON, repair malformed JSON, and optionally repair invalid data."""
    metrics = {
        "retry_count": 0,
        "json_repair_count": 0,
        "validation_retry_count": 0,
        "validation_errors": [],
        "input_chars": len(system_prompt or "") + len(user_prompt or ""),
        "output_chars": 0,
        "input_tokens_est": _estimate_tokens(len(system_prompt or "") + len(user_prompt or "")),
        "output_tokens_est": 0,
        "truncated_output": False,
    }

    raw = llm_call(
        system_prompt, user_prompt, max_tokens=max_tokens, model=model, provider=provider
    )
    metrics["output_chars"] += len(raw or "")
    if _looks_truncated_json(raw):
        metrics["truncated_output"] = True
        logger.warning(
            "llm_json_truncated_output_detected",
            output_chars=len(raw or ""),
            max_tokens=max_tokens,
        )

    last_error: Exception | None = None
    for attempt in range(max(0, repair_attempts) + 1):
        try:
            data = _parse_json_text(raw)
            break
        except Exception as exc:
            last_error = exc
            # Do not "repair" heavily truncated resume JSON into a tiny valid stub.
            if metrics.get("truncated_output") and len(raw or "") > 2000:
                logger.error(
                    "llm_json_parse_failed_truncated",
                    raw=(raw or "")[:300],
                    error=str(exc),
                )
                raise ValueError(
                    f"LLM output truncated (likely max_tokens); refusing lossy repair: {(raw or '')[:200]}"
                ) from exc
            if attempt >= repair_attempts:
                logger.error("llm_json_parse_failed", raw=(raw or "")[:300], error=str(exc))
                raise ValueError(f"LLM returned non-JSON: {(raw or '')[:200]}") from exc

            metrics["json_repair_count"] += 1
            repair_system, repair_user = _repair_json_prompt(raw)
            metrics["input_chars"] += len(repair_system) + len(repair_user)
            raw = llm_call(
                repair_system, repair_user, max_tokens=max_tokens, model=model, provider=provider
            )
            metrics["output_chars"] += len(raw or "")
            if _looks_truncated_json(raw):
                metrics["truncated_output"] = True
    else:  # pragma: no cover - loop always breaks or raises
        raise ValueError(f"LLM returned non-JSON: {last_error}")

    if validate:
        validation_errors = validate(data)
        metrics["validation_errors"] = validation_errors

        for _ in range(max(0, validation_attempts)):
            if not validation_errors:
                break

            metrics["validation_retry_count"] += 1
            repair_system, repair_user = _repair_json_prompt(
                json.dumps(data, ensure_ascii=True),
                validation_errors=validation_errors,
            )
            metrics["input_chars"] += len(repair_system) + len(repair_user)
            raw = llm_call(
                repair_system, repair_user, max_tokens=max_tokens, model=model, provider=provider
            )
            metrics["output_chars"] += len(raw or "")
            data = _parse_json_text(raw)
            validation_errors = validate(data)
            metrics["validation_errors"] = validation_errors

    metrics["input_tokens_est"] = _estimate_tokens(metrics["input_chars"])
    metrics["output_tokens_est"] = _estimate_tokens(metrics["output_chars"])
    metrics["retry_count"] = metrics["json_repair_count"] + metrics["validation_retry_count"]
    return LLMJsonCallResult(data=data, metrics=metrics)


def llm_call_json(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str | None = None,
    provider: str | None = None,
) -> dict:
    """Make a Bedrock LLM call and parse/repair the response as JSON."""
    return llm_call_json_with_metrics(
        system_prompt, user_prompt, model=model, provider=provider
    ).data
