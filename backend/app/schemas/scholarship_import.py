from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ScholarshipImportSource(BaseModel):
    kind: Literal["webpage", "pdf_url", "pdf_upload"]
    label: str
    url: Optional[str] = None
    content_type: str
    page_count: Optional[int] = None


class ScholarshipImportField(BaseModel):
    status: Literal["extracted", "uncertain", "not_found"]
    value: Any = None
    suggestion_valid: bool = False
    source_label: Optional[str] = None
    source_url: Optional[str] = None
    evidence_excerpt: Optional[str] = None
    page_number: Optional[int] = None
    confidence: Optional[Literal["high", "medium", "low"]] = None
    note: Optional[str] = None


class ScholarshipImportDraft(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    fields: dict[str, ScholarshipImportField]
    source: ScholarshipImportSource
    warnings: list[str] = Field(default_factory=list)
