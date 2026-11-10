from datetime import date, datetime
from typing import Dict, List, Literal, Optional

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
            if key == "_rag_page_snapshot":
                continue
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
    deadline: Optional[str]
    official_source_url: Optional[str]
    verification_status: Optional[str]
    verification_basis: Optional[str]
    last_verified_date: Optional[date]
    archived: bool
    duplicate_of_id: Optional[int]
    issues: List[QualityIssue]

    @field_serializer("official_source_url")
    def sanitize_official_source_url(self, source_url):
        return safe_source_url(source_url) if source_url is not None else None


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


class AdminDiscoverySourceDetails(BaseModel):
    source_id: Optional[str] = None
    source_name: Optional[str] = None
    pages_fetched: Optional[int] = None
    candidates_extracted: Optional[int] = None
    candidates_queued_for_review: Optional[int] = None
    crawl_diagnostics: Optional[Dict[str, int]] = None
    extraction_diagnostics: Optional[Dict[str, int]] = None
    candidate_rejection_reasons: Optional[Dict[str, int]] = None
    error: Optional[str] = None
    error_category: Optional[
        Literal[
            "http_status",
            "timeout",
            "connection_error",
            "dns_error",
            "robots_check_failed",
            "content_validation_failed",
            "invalid_candidate",
            "invalid_source_url",
            "malformed_response",
            "insufficient_page_content",
            "payload_too_large",
            "request_rejected",
            "provider_error",
            "unknown",
        ]
    ] = None
    failure_stage: Optional[Literal["robots", "root_fetch", "linked_page"]] = None
    page_stage: Optional[Literal["root_fetch", "linked_page"]] = None
    http_status: Optional[int] = None
    attempt_count: Optional[int] = None
    attempt_limit: Optional[int] = None
    cause_type: Optional[str] = None


class AdminDiscoverySourceFailure(AdminDiscoverySourceDetails):
    status: Optional[Literal["failed", "partial_failure"]] = None


class AdminDiscoverySourceSuccess(AdminDiscoverySourceDetails):
    status: Literal["succeeded"] = "succeeded"


class AdminDiscoverySourceUnknown(AdminDiscoverySourceDetails):
    status: Literal["unknown"] = "unknown"


class AdminDiscoveryTextTruncation(BaseModel):
    source_id: str
    page_index: int
    original_length: int
    retained_length: int


class AdminDiscoveryFetchDiagnostics(BaseModel):
    linked_urls_discovered: int = 0
    linked_pages_attempted: int = 0
    linked_pages_fetched: int = 0
    linked_pages_failed: int = 0
    linked_pages_skipped: int = 0
    linked_pages_skipped_safety: int = 0
    linked_pages_skipped_relevance: int = 0
    truncated_pages: int = 0
    truncated_original_chars: int = 0
    truncated_retained_chars: int = 0
    text_truncations: List[AdminDiscoveryTextTruncation] = Field(default_factory=list)


class AdminDiscoveryExtractionDiagnostics(BaseModel):
    valid_empty: int = 0
    request_rejected: int = 0
    candidates_accepted: int = 0
    candidates_rejected: int = 0
    insufficient_page_content: int = 0
    provider_error: int = 0
    malformed_response: int = 0


class AdminDiscoveryRunHistory(BaseModel):
    run_id: str
    trigger_type: Literal["scheduled", "catch_up", "manual"]
    scheduled_for: Optional[datetime]
    started_at: datetime
    completed_at: Optional[datetime]
    duration_seconds: float
    status: Literal["running", "completed", "failed"]
    display_status: Literal["running", "succeeded", "partial", "failed"]
    sources_attempted: int
    sources_succeeded: int
    sources_failed: int
    pages_fetched: int
    candidates_discovered: int
    scholarships_created: int
    candidates_queued_for_review: int
    duplicates_skipped: int
    error_summary: Optional[str]
    successful_sources: List[AdminDiscoverySourceSuccess] = Field(default_factory=list)
    failed_sources: List[AdminDiscoverySourceFailure]
    unknown_sources: List[AdminDiscoverySourceUnknown] = Field(default_factory=list)
    fetch_diagnostics: AdminDiscoveryFetchDiagnostics = Field(
        default_factory=AdminDiscoveryFetchDiagnostics,
    )
    extraction_diagnostics: AdminDiscoveryExtractionDiagnostics = Field(
        default_factory=AdminDiscoveryExtractionDiagnostics,
    )


class AdminDiscoveryHistoryPage(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[AdminDiscoveryRunHistory]


class AdminDiscoveryRunStart(BaseModel):
    run_id: str
    status: Literal["running"]


class AdminDiscoveryMonitoring(BaseModel):
    enabled: bool
    interval_hours: int
    next_scheduled_run: Optional[datetime]
    current_run_status: Literal["idle", "running"]
    current_run: Optional[AdminDiscoveryRunHistory]
    current_manual_run: Optional[AdminDiscoveryRunHistory] = None
    last_scheduled_run: Optional[AdminDiscoveryRunHistory] = None
    last_attempted_run: Optional[AdminDiscoveryRunHistory]
    last_successful_run: Optional[AdminDiscoveryRunHistory]
    last_completed_run: Optional[AdminDiscoveryRunHistory] = None
    last_failed_run: Optional[AdminDiscoveryRunHistory] = None
    worker_status: Literal[
        "idle",
        "submitting",
        "starting",
        "running",
        "completed",
        "failed",
        "interrupted_unknown",
    ]
    worker_run_id: Optional[str] = None
    worker_trigger_type: Optional[Literal["scheduled", "catch_up", "manual"]] = None
    worker_started_at: Optional[datetime] = None
    worker_submitted_at: Optional[datetime] = None
    worker_duration_seconds: float = 0
    worker_recoverable: bool = False
    worker_stage: Optional[str] = None
    worker_error: Optional[str] = None
    recent_runs: List[AdminDiscoveryRunHistory]
    candidates_total: int
    review_queue_pending: int


class AdminDiscoverySource(BaseModel):
    source_id: str
    name: str
    official_domain: str
    category: str
    country_or_region: str
    source_url: str
    source_classification: Literal["official_provider", "government_authority", "trusted_listing"]
    active: bool
    status: Literal["not_checked", "pending", "fetched", "failed", "partial_failure", "skipped", "trust_review_required"]
    last_checked: Optional[str]
    pages_checked: int
    review_candidates: int

    @field_serializer("source_url")
    def sanitize_source_url(self, source_url):
        return safe_source_url(source_url) or "[redacted invalid source URL]"


class AdminDiscoverySourcePage(BaseModel):
    total: int
    items: List[AdminDiscoverySource]


class AdminDiscoveryReviewItem(BaseModel):
    id: int
    candidate_name: Optional[str]
    host_country: Optional[str]
    source_id: str
    source_name: str
    source_classification: Literal["official_provider", "government_authority", "trusted_listing"]
    source_trust_basis: Optional[str]
    source_url: str
    page_count: Optional[int]
    extracted_values: dict
    field_sources: dict
    evidence_excerpts: List[dict]
    missing_required_fields: List[str]
    conflicting_values: List[dict]
    review_reason: str
    discovery_run_id: str
    review_status: Literal["pending", "reviewed", "accepted", "rejected", "duplicate"]
    accepted_scholarship_id: Optional[int]
    duplicate_of_scholarship_id: Optional[int]
    reviewed_by_id: Optional[int]
    reviewed_at: Optional[datetime]
    review_note: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("source_url")
    def sanitize_source_url(self, source_url):
        return safe_source_url(source_url) or "[redacted invalid source URL]"

    @field_serializer("extracted_values", "field_sources", "evidence_excerpts", "conflicting_values")
    def sanitize_review_data(self, value):
        return _sanitize_audit_value(value)

    @field_serializer("review_reason", "review_note", "source_trust_basis")
    def sanitize_review_text(self, value):
        return safe_source_urls_in_text(value) if value is not None else None


class AdminDiscoveryReviewPage(BaseModel):
    total: int
    items: List[AdminDiscoveryReviewItem]


class AdminDiscoveryReviewWrite(BaseModel):
    model_config = {"extra": "forbid"}

    decision: Literal["reviewed", "accepted", "rejected", "duplicate", "link_and_publish"]
    values: Optional[dict] = None
    duplicate_of_scholarship_id: Optional[int] = Field(None, gt=0)
    link_to_scholarship_id: Optional[int] = Field(None, gt=0)
    note: Optional[str] = Field(None, max_length=1000)

    @field_validator("note")
    @classmethod
    def _trim_review_note(cls, value):
        if value is None:
            return None
        value = value.strip()
        return value or None


class AdminDiscoveryPublicationVersionSummary(BaseModel):
    id: int
    version_number: int
    review_item_id: int
    candidate_name_at_approval: Optional[str]
    host_country_at_approval: Optional[str]
    approved_values: dict
    source_evidence: List[dict]
    approval_decision: Literal["accepted", "link_and_publish"]
    approved_by_email: str
    approved_at: datetime

    @field_serializer("approved_values", "source_evidence")
    def sanitize_publication_version_data(self, value):
        return _sanitize_audit_value(value)


class AdminDiscoveryPublicationEvent(BaseModel):
    id: int
    publication_id: str
    publication_version_id: Optional[int]
    event_type: Literal[
        "published", "version_approved", "version_superseded", "revoked",
        "expired", "withdrawn", "superseded", "republished",
    ]
    previous_status: Optional[Literal["published", "expired", "withdrawn", "revoked", "superseded"]]
    new_status: Optional[Literal["published", "expired", "withdrawn", "revoked", "superseded"]]
    actor_id: Optional[int]
    actor_email: Optional[str]
    reason: Optional[str]
    event_data: dict
    created_at: datetime

    @field_serializer("reason", "event_data")
    def sanitize_publication_event(self, value):
        return _sanitize_audit_value(value)


class AdminDiscoveryPublicationEventPage(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[AdminDiscoveryPublicationEvent]


class AdminDiscoveryPublicationSource(BaseModel):
    id: int
    source_id: str
    source_name: str
    source_classification: Literal["official_provider", "government_authority", "trusted_listing"]
    source_trust_basis: Optional[str]
    source_url: str
    last_checked_at: Optional[datetime]
    last_successful_check_at: Optional[datetime]
    observed_content_hash: Optional[str]
    source_check_status: Literal["not_checked", "succeeded", "failed", "content_changed"]

    @field_serializer("source_url")
    def sanitize_publication_source_url(self, source_url):
        return safe_source_url(source_url) or "[redacted invalid source URL]"

    @field_serializer("source_trust_basis")
    def sanitize_publication_source_text(self, value):
        return safe_source_urls_in_text(value) if value is not None else None


class AdminDiscoveryPublication(BaseModel):
    id: str
    canonical_scholarship_id: int
    scholarship_name: Optional[str]
    status: Literal["published", "expired", "withdrawn", "revoked", "superseded"]
    current_version_id: Optional[int]
    current_version_number: Optional[int] = None
    published_at: datetime
    revoked_at: Optional[datetime]
    revoked_by_id: Optional[int]
    revoked_by_email: Optional[str]
    revocation_reason: Optional[str]
    superseded_by_publication_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    current_version: Optional[AdminDiscoveryPublicationVersionSummary]
    versions: List[AdminDiscoveryPublicationVersionSummary]
    sources: List[AdminDiscoveryPublicationSource]

    @field_serializer("revocation_reason")
    def sanitize_revocation_reason(self, value):
        return safe_source_urls_in_text(value) if value is not None else None


class AdminDiscoveryPublicationPage(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[AdminDiscoveryPublication]


class AdminDiscoveryPublicationLifecycleWrite(BaseModel):
    model_config = {"extra": "forbid"}

    decision: Literal["revoke", "expire", "withdraw", "supersede"]
    reason: str = Field(..., min_length=1, max_length=2000)
    superseded_by_publication_id: Optional[str] = Field(None, min_length=36, max_length=36)

    @field_validator("reason")
    @classmethod
    def _trim_lifecycle_reason(cls, value):
        reason = value.strip()
        if not reason:
            raise ValueError("reason must not be blank")
        return reason
