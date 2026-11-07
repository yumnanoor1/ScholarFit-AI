from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_serializer, field_validator

from app.schemas.opportunity import ScholarshipResponse, is_web_url
from app.services.source_url_safety import safe_source_url, safe_source_urls_in_text

_SCHOLARSHIP_URL_FIELDS = {
    "official_url",
    "official_info_url",
    "official_application_url",
    "source_url",
}


def _sanitize_url_list(value):
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        return None
    if any(isinstance(item, (list, tuple)) for item in value):
        return [
            _sanitize_url_list(item) if isinstance(item, (list, tuple)) else item
            for item in value
        ]
    return [safe for item in value if (safe := safe_source_url(item)) is not None]


def _sanitize_audit_value(value):
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if key in _SCHOLARSHIP_URL_FIELDS:
                if isinstance(item, (list, tuple)):
                    sanitized[key] = [
                        safe_source_url(entry) if isinstance(entry, str) else entry
                        for entry in item
                    ]
                else:
                    sanitized[key] = safe_source_url(item)
            elif key == "additional_source_urls":
                sanitized[key] = _sanitize_url_list(item)
            else:
                sanitized[key] = _sanitize_audit_value(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_audit_value(item) for item in value]
    if isinstance(value, str):
        return safe_source_urls_in_text(value)
    return value


class QualityIssue(BaseModel):
    code: str
    label: str
    severity: Literal["high", "medium", "low"]
    detail: str


class AdminSummary(BaseModel):
    total: int
    verified: int
    unverified: int
    archived: int
    conflicting: int
    missing_official_source: int
    incomplete_structured: int
    needs_reverification: int
    broken_sources: int
    sources_checked: int
    duplicates: int


class AdminRow(BaseModel):
    id: int
    name: str
    provider: Optional[str]
    country: Optional[str]
    verification_status: Optional[str]
    verification_basis: Optional[str]
    last_verified_date: Optional[date]
    archived: bool
    duplicate_of_id: Optional[int]
    issues: List[QualityIssue]


class AdminRowPage(BaseModel):
    total: int
    items: List[AdminRow]


class AuditEntry(BaseModel):
    id: int
    action: str
    changes: Optional[dict]
    note: Optional[str]
    actor_email: Optional[str]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True

    @field_serializer("changes")
    def sanitize_metadata_urls_in_changes(self, changes):
        return _sanitize_audit_value(changes)

    @field_serializer("note")
    def sanitize_urls_in_note(self, note):
        return safe_source_urls_in_text(note) if note is not None else None


class ReferenceCounts(BaseModel):
    saved_by_students: int
    internal_links: int
    duplicates_pointing_here: int


class AdminScholarship(ScholarshipResponse):
    data_flags: Optional[List[str]] = None
    source_checks: Optional[List[dict]] = None
    archived_at: Optional[datetime] = None
    archive_reason: Optional[str] = None

    @field_serializer("source_checks")
    def redact_source_check_urls(self, source_checks):
        if source_checks is None:
            return None
        sanitized_checks = []
        for check in source_checks:
            if isinstance(check, dict):
                check = dict(check)
                check.pop("source_document_id", None)
                check.pop("content_hash", None)
                if "url" in check:
                    check["url"] = safe_source_url(check["url"]) or "[redacted invalid source URL]"
            sanitized_checks.append(check)
        return sanitized_checks


class AdminDetail(BaseModel):
    scholarship: AdminScholarship
    issues: List[QualityIssue]
    references: ReferenceCounts
    audit: List[AuditEntry]


class AdminDocumentVersionSummary(BaseModel):
    id: int
    content_hash: str
    retrieved_at: datetime
    mime_type: str
    extractor_version: str
    page_count: Optional[int]
    verification_status_snapshot: str
    verification_basis_snapshot: Optional[str]
    last_verified_date_snapshot: Optional[date]
    scholarship_record_version_snapshot: Optional[int]
    review_status: str
    indexing_status: str
    created_at: datetime


class AdminSourceDocumentSummary(BaseModel):
    id: int
    scholarship_name: str
    source_title: Optional[str] = None
    source_url: str
    source_role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    versions_total: int
    versions_skip: int
    versions_limit: int
    versions: List[AdminDocumentVersionSummary]


class AdminSourceDocumentPage(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[AdminSourceDocumentSummary]


class AdminDocumentVersionDetail(BaseModel):
    scholarship_id: int
    scholarship_name: str
    source_document_id: int
    source_title: Optional[str] = None
    source_url: str
    source_role: str
    source_is_active: bool
    source_created_at: datetime
    source_updated_at: datetime
    document_version_id: int
    content_hash: str
    retrieved_at: datetime
    mime_type: str
    extractor_version: str
    page_count: Optional[int]
    verification_status_snapshot: str
    verification_basis_snapshot: Optional[str]
    last_verified_date_snapshot: Optional[date]
    scholarship_record_version_snapshot: Optional[int]
    review_status: str
    indexing_status: str
    created_at: datetime
    extracted_text: str
    text_offset: int
    text_limit: int
    text_total_chars: int
    has_more_text: bool


class AdminDocumentReviewWrite(BaseModel):
    model_config = {"extra": "forbid"}

    decision: Literal["approve", "reject"]
    reason: str = Field(..., min_length=1, max_length=2000)
    expected_content_hash: str = Field(..., pattern="^[0-9a-f]{64}$")
    expected_scholarship_record_version: int = Field(..., gt=0)

    @field_validator("reason")
    @classmethod
    def _non_empty_reason(cls, value):
        reason = value.strip()
        if not reason:
            raise ValueError("reason must not be blank")
        return reason


class AdminDocumentReviewResponse(BaseModel):
    scholarship_id: int
    document_version_id: int
    decision: Literal["approve", "reject"]
    content_hash: str
    scholarship_record_version: int
    review_status: Literal["pending", "approved", "rejected", "stale"]
    indexing_status: Literal["pending", "approved", "indexed", "failed", "stale"]
    approval_event_id: Optional[int] = None


class AdminDocumentIndexWrite(BaseModel):
    model_config = {"extra": "forbid"}

    expected_content_hash: str = Field(..., pattern="^[0-9a-f]{64}$")
    expected_scholarship_record_version: int = Field(..., gt=0)


class AdminDocumentIndexResponse(BaseModel):
    scholarship_id: int
    document_version_id: int
    status: Literal["indexed"]
    content_hash: str
    scholarship_record_version: int
    model_name: str
    model_revision: str
    chunk_count: int
    embedding_count: int
    chunks_created: int
    embeddings_created: int
    idempotent: bool


class VerificationWrite(BaseModel):
    model_config = {"extra": "forbid"}

    status: Literal["verified", "unverified"]
    basis: Literal["official_source", "mixed_sources", "secondary_only", "not_verified"]
    source_url: Optional[str] = Field(None, max_length=2000)
    verified_on: Optional[date] = None
    notes: str = Field(..., min_length=10, max_length=4000)
    evidence_reviewed: bool = False
    acknowledge_conflicts: bool = False

    @field_validator("source_url")
    @classmethod
    def _url(cls, value):
        if value is not None and not is_web_url(value):
            raise ValueError("must be a single http or https URL")
        return value


class FlagWrite(BaseModel):
    model_config = {"extra": "forbid"}

    flag: Literal["conflicting_information", "outdated_source", "broken_source", "needs_reverification"]
    active: bool
    note: Optional[str] = Field(None, max_length=1000)


class ArchiveWrite(BaseModel):
    model_config = {"extra": "forbid"}

    reason: str = Field(..., min_length=5, max_length=1000)


class DuplicateWrite(BaseModel):
    model_config = {"extra": "forbid"}

    duplicate_of_id: Optional[int] = Field(None, gt=0)      # None clears the flag
    note: str = Field(..., min_length=5, max_length=1000)


class DuplicatePair(BaseModel):
    first_id: int
    second_id: int
    first_name: str
    second_name: str
    kind: Literal["flagged", "suspected"]


class FieldDifference(BaseModel):
    field: str
    first: object = None
    second: object = None


class DuplicateComparison(BaseModel):
    first: AdminScholarship
    second: AdminScholarship
    differences: List[FieldDifference]
    first_references: ReferenceCounts
    second_references: ReferenceCounts
