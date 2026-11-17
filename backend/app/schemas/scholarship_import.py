from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ScholarshipImportSource(BaseModel):
    kind: Literal["webpage", "pdf_url", "pdf_upload", "pasted_text"]
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


class ScholarshipImportCandidate(BaseModel):
    """One award a page described, when it described more than one.

    A long page is read in sections, so sections can describe different
    awards. Each is offered for review rather than silently merged into one
    record, and the draft itself still carries the merged best-evidenced view.
    """
    label: str
    values: dict[str, Any] = Field(default_factory=dict)
    fields: dict[str, ScholarshipImportField]


class ScholarshipImportDraft(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    fields: dict[str, ScholarshipImportField]
    source: ScholarshipImportSource
    warnings: list[str] = Field(default_factory=list)
    # Empty when the page described a single award.
    candidates: list[ScholarshipImportCandidate] = Field(default_factory=list)
    # How the page was read, for the admin's information.
    chunk_count: int = 1


class ScholarshipImportTextWrite(BaseModel):
    """Page text an administrator pasted, with the URL it came from.

    The URL is provenance only: it is never requested. The text limit is
    generous because an admin pastes a whole page, and the extraction applies
    its own character limit on top.
    """
    model_config = {"extra": "forbid"}

    text: str = Field(..., min_length=1, max_length=200_000)
    url: Optional[str] = Field(None, max_length=2048)
