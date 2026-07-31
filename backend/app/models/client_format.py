"""Client format stand-in (in-memory or loaded from a saved FormatProfile)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID, uuid4

from app.models.format_schema import normalize_format_metadata


@dataclass
class ClientFormat:
    client_id: str
    format_metadata: Optional[dict[str, Any]] = None
    format_template_path: str = ""
    id: UUID = field(default_factory=uuid4)
    is_active: bool = True
    # Optional path to original template bytes (pdf/doc/docx) for skeleton fill.
    template_bytes_path: str = ""
    format_profile_id: str = ""

    def __post_init__(self) -> None:
        if self.format_metadata:
            self.format_metadata = normalize_format_metadata(self.format_metadata)
