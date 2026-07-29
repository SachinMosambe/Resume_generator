"""In-memory candidate stand-in (no database)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID, uuid4


@dataclass
class Candidate:
    id: UUID = field(default_factory=uuid4)
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    job_applied: Optional[str] = None
    job_title: Optional[str] = None
    job_role: Optional[str] = None
    company_name: Optional[str] = None
    client_name: Optional[str] = None
    total_exp: Optional[str] = None
    us_exp: Optional[str] = None
    recruiter_id: UUID = field(default_factory=uuid4)
    resume_path: Optional[str] = None
    extracted_data: Optional[dict[str, Any]] = None
    skills_matched: Optional[list[str]] = None
    skills_not_matched: Optional[list[str]] = None
    primary_skills: Optional[str] = None
    secondary_skills: Optional[str] = None
    other_skills: Optional[str] = None
    main_summary: Optional[str] = None
    linkedin_summary: Optional[str] = None
    language: Optional[str] = None
    display_name: Optional[str] = None
    employment_history: list[Any] = field(default_factory=list)
    education_history: list[Any] = field(default_factory=list)
    generated_resume_path: Optional[str] = None
