"""In-memory client format stand-in (no database)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID, uuid4


@dataclass
class ClientFormat:
    client_id: str
    format_metadata: Optional[dict[str, Any]] = None
    format_template_path: str = ""
    id: UUID = field(default_factory=uuid4)
    is_active: bool = True
