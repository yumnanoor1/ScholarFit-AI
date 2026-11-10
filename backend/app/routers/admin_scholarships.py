from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import hashlib
import logging
import math
import threading
import uuid
from typing import Literal, Optional
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy import String, cast, func, or_, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.config import scholarship_discovery_settings
from app.core.permissions import require_admin
from app.database import get_db
from app.models.opportunity import Scholarship, ScholarshipAuditLog
from app.models.scholarship_discovery import (
    ScholarshipDiscoveryReviewItem,
    ScholarshipDiscoveryRun,
)
from app.models.scholarship_discovery_publication import (
    ScholarshipDiscoveryPublication,
    ScholarshipDiscoveryPublicationEvent,
)
from app.models.scholarship_knowledge import (
    EMBEDDING_DIMENSIONS,
    ScholarshipChunkEmbedding,
    ScholarshipDocumentChunk,
    ScholarshipDocumentVersion,
    ScholarshipDocumentVersionApproval,
    ScholarshipSourceDocument,
)
from app.schemas.admin import (
    AdminDetail, AdminDiscoveryHistoryPage, AdminDiscoveryMonitoring, AdminDiscoveryRunHistory,
    AdminDiscoveryRunStart,
    AdminDiscoverySourcePage,
    AdminDiscoveryPublication, AdminDiscoveryPublicationEventPage,
    AdminDiscoveryPublicationLifecycleWrite, AdminDiscoveryPublicationPage,
    AdminDocumentIndexResponse, AdminDocumentIndexWrite, AdminDocumentReviewResponse,
    AdminDiscoveryReviewItem, AdminDiscoveryReviewPage, AdminDiscoveryReviewWrite,
    AdminDocumentReviewWrite, AdminDocumentVersionDetail, AdminRowPage,
    AdminSourceDocumentPage, AdminSourceDocumentSummary, AdminSummary, ArchiveWrite, DuplicateComparison,
    DuplicatePair, DuplicateWrite, FlagWrite, VerificationWrite,
)
from app.schemas.opportunity import ScholarshipResponse
from app.schemas.scholarship_import import ScholarshipImportDraft
from app.services.scholarship_quality import (
    duplicate_pairs, field_changes, find_conflicts, find_issues,
    record_audit, reference_counts, set_archived,
    update_scholarship_if_current,
)
from app.services.scholarship_discovery_review import apply_review_action
from app.services.scholarship_discovery_scheduler import (
    calculate_next_run,
    discovery_advisory_lock_is_held,
)
from app.services.scholarship_discovery_publications import transition_publication
from app.services.scholarship_discovery_sources import SOURCES
from app.services.source_check import check_url
from app.services.source_verification import (
    document_source_issue,
    is_currently_verified,
    source_check_datetime,
)
from app.services.source_url_safety import safe_source_url, safe_source_urls_in_text
from app.services import rag_service
from app.services import scholarship_document_indexing as document_indexing
from app.services.scholarship_import import ScholarshipImportError, extract_scholarship_source

# Every route needs an admin, whatever is added here later
router = APIRouter(prefix="/admin/scholarships", tags=["Admin Scholarships"], dependencies=[Depends(require_admin)])
logger = logging.getLogger(__name__)
_manual_discovery_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="manual-discovery")
_manual_discovery_submission_lock = threading.Lock()
_manual_discovery_state_lock = threading.Lock()
_manual_discovery_state = {
    "status": "idle",
    "run_id": None,
    "trigger_type": None,
    "submitted_at": None,
    "started_at": None,
    "finished_at": None,
    "stage": None,
    "error": None,
}


def _update_manual_discovery_state(**changes) -> None:
    with _manual_discovery_state_lock:
        _manual_discovery_state.update(changes)


def _manual_discovery_state_snapshot() -> dict:
    with _manual_discovery_state_lock:
        return dict(_manual_discovery_state)


_GENERIC_DISCOVERY_ERROR_SUMMARY = (
    "Discovery run failed. See source-level diagnostics for details."
)
_SAFE_DISCOVERY_EXCEPTION_TYPES = {
    "AttributeError",
    "ConnectionError",
    "DBAPIError",
    "DiscoveryFetchError",
    "DiscoveryLockLost",
    "Exception",
    "FileNotFoundError",
    "HTTPException",
    "ImportError",
    "IndexError",
    "IntegrityError",
    "KeyError",
    "LookupError",
    "ModuleNotFoundError",
    "NotImplementedError",
    "OSError",
    "OperationalError",
    "PermissionError",
    "RuntimeError",
    "SQLAlchemyError",
    "ScholarshipExtractionError",
    "Timeout",
    "TimeoutError",
    "TypeError",
    "ValueError",
}
_SAFE_DISCOVERY_ERROR_MESSAGES = {
    "Interrupted run reconciled while holding the exclusive discovery advisory lock",
}


def _safe_discovery_error_summary(value: object) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str) and (
        value in _SAFE_DISCOVERY_EXCEPTION_TYPES
        or value in _SAFE_DISCOVERY_ERROR_MESSAGES
    ):
        return value
    return _GENERIC_DISCOVERY_ERROR_SUMMARY


SOURCE_FIELDS = ("official_info_url", "official_application_url")
INCOMPLETE_CODES = {"missing_deadline", "missing_funding", "missing_eligibility", "no_structured_data"}
ATTENTION_CODES = {"conflict", "needs_review", "broken_url", "missing_official_source", "stale_verification", "never_verified",
                   "outdated_source", "broken_source", "needs_reverification"}
MAX_EXTRACTED_TEXT_CHARS = 10000
MAX_SOURCE_CHECKS_PER_REQUEST = 20
MAX_DOCUMENT_SOURCE_CHECKS_PER_REQUEST = 10
MAX_DOCUMENT_OFFSET = 10000
MAX_TEXT_OFFSET = 1000000
SCHOLARSHIP_KNOWLEDGE_WRITE_LOCK_ID = 728341901270418
MAX_IMPORT_MULTIPART_OVERHEAD = 64 * 1024
MAX_IMPORT_FORM_FIELD_BYTES = 16 * 1024


def _limited_import_request(request: Request, maximum_bytes: int) -> Request:
    received_bytes = 0

    async def receive():
        nonlocal received_bytes
        message = await request.receive()
        if message["type"] == "http.request":
            received_bytes += len(message.get("body", b""))
            if received_bytes > maximum_bytes:
                raise HTTPException(status_code=413, detail="The import request exceeds the configured size limit.")
        return message

    return Request(request.scope, receive=receive)


@router.post("/import/extract", response_model=ScholarshipImportDraft)
async def extract_scholarship_import(request: Request):
    settings = scholarship_discovery_settings()
    content_length = request.headers.get("content-length")
    maximum_request_bytes = settings.max_response_bytes + MAX_IMPORT_MULTIPART_OVERHEAD
    if content_length is not None:
        try:
            request_size = int(content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="The import request size is invalid.") from exc
        if request_size < 0:
            raise HTTPException(status_code=400, detail="The import request size is invalid.")
        if request_size > maximum_request_bytes:
            raise HTTPException(status_code=413, detail="The import request exceeds the configured size limit.")
    bounded_request = _limited_import_request(request, maximum_request_bytes)

    try:
        async with bounded_request.form(
            max_files=1,
            max_fields=3,
            max_part_size=MAX_IMPORT_FORM_FIELD_BYTES,
        ) as form:
            allowed_keys = {"source_type", "url", "file"}
            if set(form.keys()) - allowed_keys:
                raise HTTPException(status_code=400, detail="The import request contains unsupported fields.")
            if any(len(form.getlist(key)) > 1 for key in allowed_keys):
                raise HTTPException(status_code=400, detail="The import request contains duplicate fields.")
            source_type = form.get("source_type")
            url = form.get("url")
            upload = form.get("file")
            if source_type not in {"webpage", "pdf_url", "pdf_upload"}:
                raise HTTPException(status_code=400, detail="Choose a supported import method.")
            if source_type == "pdf_upload":
                if url not in (None, "") or not isinstance(upload, StarletteUploadFile):
                    raise HTTPException(status_code=400, detail="Select one PDF document to import.")
                content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
                if content_type != "application/pdf":
                    raise HTTPException(status_code=415, detail="Upload a file identified as a PDF.")
                file_bytes = await upload.read(settings.max_response_bytes + 1)
                if len(file_bytes) > settings.max_response_bytes:
                    raise HTTPException(status_code=413, detail="The PDF exceeds the configured size limit.")
                result = await run_in_threadpool(
                    extract_scholarship_source,
                    source_type,
                    file_bytes=file_bytes,
                    filename=upload.filename,
                    settings=settings,
                )
            else:
                if upload is not None or not isinstance(url, str) or not url.strip():
                    raise HTTPException(status_code=400, detail="Enter one webpage or PDF URL.")
                if len(url) > 2048:
                    raise HTTPException(status_code=400, detail="The import URL is too long.")
                result = await run_in_threadpool(
                    extract_scholarship_source,
                    source_type,
                    url=url,
                    settings=settings,
                )
            return result
    except ScholarshipImportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _version_summary(version: ScholarshipDocumentVersion) -> dict:
    return {
        "id": version.id,
        "content_hash": version.content_hash,
        "retrieved_at": version.retrieved_at,
        "mime_type": version.mime_type,
        "extractor_version": version.extractor_version,
        "page_count": version.page_count,
        "verification_status_snapshot": version.verification_status_snapshot,
        "verification_basis_snapshot": version.verification_basis_snapshot,
        "last_verified_date_snapshot": version.last_verified_date_snapshot,
        "scholarship_record_version_snapshot": version.scholarship_record_version_snapshot,
        "review_status": version.review_status,
        "indexing_status": version.indexing_status,
        "created_at": version.created_at,
    }


def _source_summary(
    source: ScholarshipSourceDocument,
    scholarship_name: str,
    version_skip: int,
    version_limit: int,
) -> dict:
    versions = sorted(source.versions, key=lambda version: (version.retrieved_at, version.id), reverse=True)
    return {
        "id": source.id,
        "scholarship_name": scholarship_name,
        "source_title": None,
        "source_url": safe_source_url(source.source_url) or "[redacted invalid source URL]",
        "source_role": source.source_role,
        "is_active": source.is_active,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
        "versions_total": len(versions),
        "versions_skip": version_skip,
        "versions_limit": version_limit,
        "versions": [_version_summary(version) for version in versions[version_skip:version_skip + version_limit]],
    }


def _record(db: Session, scholarship_id: int) -> Scholarship:
    item = db.query(Scholarship).filter(Scholarship.id == scholarship_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    return item


def _rows_with_issues(db: Session, include_archived=True):
    rows = db.query(Scholarship).order_by(Scholarship.id).all()
    suspected = {value for pair in duplicate_pairs(rows) for value in (pair["first_id"], pair["second_id"])}
    return [(row, find_issues(row, duplicate_ids=suspected)) for row in rows if include_archived or not row.archived]


@router.get("/summary", response_model=AdminSummary)
def summary(db: Session = Depends(get_db)):
    """Counts for the admin dashboard. Archived records count only under archived."""
    everything = _rows_with_issues(db)
    active = [(row, issues) for row, issues in everything if not row.archived]

    def has(codes):
        return sum(any(issue["code"] in codes for issue in issues) for _, issues in active)

    checked = [check for row, _ in active for check in row.source_checks or []]
    return {
        "total": len(active),
        "verified": sum(row.verification_status == "verified" for row, _ in active),
        "unverified": sum(row.verification_status != "verified" for row, _ in active),
        "archived": len(everything) - len(active),
        "conflicting": has({"conflict"}),
        "missing_official_source": has({"missing_official_source"}),
        "incomplete_structured": has(INCOMPLETE_CODES),
        "needs_reverification": has({"stale_verification", "needs_reverification", "never_verified"}),
        "broken_sources": sum(check.get("status") == "broken" for check in checked),
        "sources_checked": len(checked),
        "duplicates": has({"duplicate"}),
    }


@router.get("/discovery-reviews", response_model=AdminDiscoveryReviewPage)
def list_discovery_reviews(
    status: Optional[Literal["pending", "reviewed", "accepted", "rejected", "duplicate"]] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    q: Optional[str] = Query(None, max_length=200),
    db: Session = Depends(get_db),
):
    query = db.query(ScholarshipDiscoveryReviewItem)
    if status is not None:
        query = query.filter(ScholarshipDiscoveryReviewItem.review_status == status)
    if q and q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.filter(or_(
            ScholarshipDiscoveryReviewItem.candidate_name.ilike(pattern, escape="\\"),
            ScholarshipDiscoveryReviewItem.source_name.ilike(pattern, escape="\\"),
            ScholarshipDiscoveryReviewItem.source_id.ilike(pattern, escape="\\"),
            ScholarshipDiscoveryReviewItem.host_country.ilike(pattern, escape="\\"),
        ))
    total = query.count()
    items = query.order_by(
        ScholarshipDiscoveryReviewItem.created_at.desc(),
        ScholarshipDiscoveryReviewItem.id.desc(),
    ).offset(skip).limit(limit).all()
    return {"total": total, "items": items}


def _discovery_run_history(
    run: ScholarshipDiscoveryRun,
    now: datetime,
    review_counts_by_source: Optional[dict[str, int]] = None,
) -> AdminDiscoveryRunHistory:
    summary = run.summary or {}
    source_results = run.source_results if isinstance(run.source_results, list) else []
    failure_categories = {
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
    }

    def safe_choice(value, choices):
        return value if isinstance(value, str) and value in choices else None

    def safe_exception_type(value):
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 80
            or not value.isascii()
            or not value[0].isalpha()
            or not all(character.isalnum() or character == "_" for character in value)
        ):
            return None
        return value

    def safe_integer(value, minimum, maximum=None):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            return None
        if maximum is not None and value > maximum:
            return None
        return value

    def safe_count_map(value):
        if not isinstance(value, dict):
            return None
        return {
            key: count
            for key, raw_count in value.items()
            if (
                isinstance(key, str)
                and key
                and len(key) <= 100
                and key.isascii()
                and all(character.isalnum() or character in "._-" for character in key)
                and (count := safe_integer(raw_count, 0, 1_000_000_000)) is not None
            )
        }

    successful_sources = []
    failed_sources = []
    unknown_sources = []
    for source in source_results:
        if not isinstance(source, dict):
            continue
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id or len(source_id) > 100:
            source_id = None
        source_name = source.get("source_name")
        if not isinstance(source_name, str) or not source_name or len(source_name) > 255:
            source_name = None
        crawl_diagnostics = safe_count_map(source.get("crawl_diagnostics"))
        extraction_diagnostics = safe_count_map(source.get("extraction_diagnostics"))
        candidates_extracted = safe_integer(source.get("candidates_extracted"), 0, 1_000_000_000)
        if candidates_extracted is None and extraction_diagnostics is not None:
            candidates_extracted = safe_integer(
                extraction_diagnostics.get("candidates_accepted"),
                0,
                1_000_000_000,
            )
        candidates_queued = safe_integer(
            source.get("candidates_queued_for_review"),
            0,
            1_000_000_000,
        )
        if candidates_queued is None and review_counts_by_source is not None and source_id is not None:
            candidates_queued = review_counts_by_source.get(source_id, 0)

        details = {
            "source_id": source_id,
            "source_name": source_name,
            "pages_fetched": safe_integer(source.get("pages_fetched"), 0, 1_000_000_000),
            "candidates_extracted": candidates_extracted,
            "candidates_queued_for_review": candidates_queued,
            "crawl_diagnostics": crawl_diagnostics,
            "extraction_diagnostics": extraction_diagnostics,
            "candidate_rejection_reasons": safe_count_map(
                source.get("candidate_rejection_reasons"),
            ),
            "error": safe_exception_type(source.get("error")),
            "error_category": safe_choice(source.get("error_category"), failure_categories),
            "failure_stage": safe_choice(
                source.get("failure_stage"),
                {"robots", "root_fetch", "linked_page"},
            ),
            "page_stage": safe_choice(source.get("page_stage"), {"root_fetch", "linked_page"}),
            "http_status": safe_integer(source.get("http_status"), 100, 599),
            "attempt_count": safe_integer(source.get("attempt_count"), 1),
            "attempt_limit": safe_integer(source.get("attempt_limit"), 1),
            "cause_type": safe_exception_type(source.get("cause_type")),
        }
        source_status = source.get("status")
        if source_status in ("failed", "partial_failure"):
            failed_sources.append({**details, "status": source_status})
        elif source_status in ("fetched", "succeeded"):
            successful_sources.append({**details, "status": "succeeded"})
        else:
            unknown_sources.append({**details, "status": "unknown"})

    source_failures = summary.get("sources_failed", 0)
    if not isinstance(source_failures, int) or isinstance(source_failures, bool):
        source_failures = 0
    source_failures = max(source_failures, len(failed_sources))
    if run.status == "failed":
        display_status = "failed"
    elif run.status == "running":
        display_status = "running"
    else:
        display_status = "partial" if source_failures else "succeeded"
    pages_fetched = sum(
        source.get("pages_fetched", 0)
        for source in source_results
        if isinstance(source.get("pages_fetched"), int)
        and not isinstance(source.get("pages_fetched"), bool)
    )

    def diagnostic_count(key):
        return safe_integer(summary.get(key, 0), 0, 1_000_000_000) or 0

    text_truncations = []
    for source in source_results:
        source_id = source.get("source_id")
        if (
            not isinstance(source_id, str)
            or not source_id
            or len(source_id) > 100
            or not source_id.isascii()
            or not all(character.isalnum() or character in "._-" for character in source_id)
        ):
            continue
        source_truncations = source.get("text_truncations", [])
        if not isinstance(source_truncations, list):
            continue
        for truncation in source_truncations:
            if not isinstance(truncation, dict):
                continue
            page_index = safe_integer(truncation.get("page_index"), 1, 200)
            original_length = safe_integer(truncation.get("original_length"), 1, 10_000_000)
            retained_length = safe_integer(truncation.get("retained_length"), 0, 10_000_000)
            if (
                page_index is None
                or original_length is None
                or retained_length is None
                or retained_length >= original_length
            ):
                continue
            text_truncations.append({
                "source_id": source_id,
                "page_index": page_index,
                "original_length": original_length,
                "retained_length": retained_length,
            })
            if len(text_truncations) >= 2_000:
                break
        if len(text_truncations) >= 2_000:
            break

    started_at = run.started_at
    ended_at = run.finished_at or now
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=timezone.utc)
    duration_seconds = max(0.0, (ended_at - started_at).total_seconds())
    return AdminDiscoveryRunHistory(
        run_id=run.id,
        trigger_type=run.trigger_type,
        scheduled_for=run.scheduled_for,
        started_at=run.started_at,
        completed_at=run.finished_at,
        duration_seconds=round(duration_seconds, 2),
        status=run.status,
        display_status=display_status,
        sources_attempted=summary.get("sources_attempted", 0),
        sources_succeeded=summary.get("sources_successfully_fetched", 0),
        sources_failed=source_failures,
        pages_fetched=pages_fetched,
        candidates_discovered=summary.get("scholarships_discovered", 0),
        scholarships_created=summary.get("new_records_created", 0),
        candidates_queued_for_review=summary.get("review_candidates_queued", 0),
        duplicates_skipped=summary.get("duplicates_skipped", 0),
        error_summary=_safe_discovery_error_summary(summary.get("error_summary")),
        successful_sources=successful_sources,
        failed_sources=failed_sources,
        unknown_sources=unknown_sources,
        fetch_diagnostics={
            "linked_urls_discovered": diagnostic_count("linked_urls_discovered"),
            "linked_pages_attempted": diagnostic_count("linked_pages_attempted"),
            "linked_pages_fetched": diagnostic_count("linked_pages_fetched"),
            "linked_pages_failed": diagnostic_count("linked_pages_failed"),
            "linked_pages_skipped": diagnostic_count("linked_pages_skipped"),
            "linked_pages_skipped_safety": diagnostic_count("linked_pages_skipped_safety"),
            "linked_pages_skipped_relevance": diagnostic_count("linked_pages_skipped_relevance"),
            "truncated_pages": diagnostic_count("truncated_pages"),
            "truncated_original_chars": diagnostic_count("truncated_original_chars"),
            "truncated_retained_chars": diagnostic_count("truncated_retained_chars"),
            "text_truncations": text_truncations,
        },
        extraction_diagnostics={
            "valid_empty": diagnostic_count("valid_empty"),
            "request_rejected": diagnostic_count("request_rejected"),
            "candidates_accepted": diagnostic_count("candidates_accepted"),
            "candidates_rejected": diagnostic_count("candidates_rejected"),
            "insufficient_page_content": diagnostic_count("insufficient_page_content"),
            "provider_error": diagnostic_count("provider_error"),
            "malformed_response": diagnostic_count("malformed_response"),
        },
    )


def _execute_manual_discovery(run_id: str, on_run_started, on_stage):
    from discover_scholarships import main

    return main(
        trigger_type="manual",
        run_id=run_id,
        on_run_started=on_run_started,
        on_stage=on_stage,
    )


def _monitoring_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _discovery_worker_snapshot(db, latest_attempt, latest_running, now: datetime) -> dict:
    local_state = _manual_discovery_state_snapshot()
    advisory_lock_held = discovery_advisory_lock_is_held(db)
    local_status = local_state["status"]
    run = None

    if advisory_lock_held is True:
        run = latest_running
        worker_status = "running" if run else (
            local_status if local_status in {"submitting", "starting"} else "starting"
        )
    elif advisory_lock_held is False:
        if latest_running is not None:
            worker_status = "interrupted_unknown"
            run = latest_running
        elif local_status in {"submitting", "starting"}:
            worker_status = local_status
        elif local_status == "running":
            worker_status = "interrupted_unknown"
        else:
            worker_status = local_status
    elif latest_running is not None:
        if local_status == "running" and local_state["run_id"] == latest_running.id:
            worker_status = "running"
            run = latest_running
        else:
            worker_status = "interrupted_unknown"
            run = latest_running
    elif local_status in {"submitting", "starting"}:
        worker_status = local_status
    elif local_status == "running":
        worker_status = "interrupted_unknown"
    else:
        worker_status = local_status

    local_terminal = local_status in {"completed", "failed"}
    local_result_is_newer = local_terminal and (
        latest_attempt is None
        or local_state["submitted_at"] is None
        or _monitoring_utc(local_state["submitted_at"])
        >= _monitoring_utc(latest_attempt.started_at)
    )
    if local_result_is_newer:
        worker_status = local_status
    elif worker_status in {"idle", "completed", "failed"} and latest_attempt is not None:
        if latest_attempt.status == "completed":
            worker_status = "completed"
            run = latest_attempt
        elif latest_attempt.status == "failed":
            worker_status = "failed"
            run = latest_attempt

    if run is not None:
        started_at = run.started_at
        finished_at = run.finished_at
        worker_run_id = run.id
        trigger_type = run.trigger_type
        summary = run.summary or {}
        worker_error = _safe_discovery_error_summary(summary.get("error_summary"))
        worker_stage = "interrupted" if worker_status == "interrupted_unknown" else (
            local_state["stage"]
            if local_state["run_id"] == run.id and local_state["stage"]
            else "discovery"
        )
    else:
        started_at = local_state["started_at"]
        finished_at = local_state["finished_at"]
        worker_run_id = local_state["run_id"]
        trigger_type = local_state["trigger_type"]
        worker_error = local_state["error"]
        worker_stage = local_state["stage"]
    submitted_at = (
        local_state["submitted_at"]
        if local_state["run_id"] == worker_run_id
        else None
    )

    if started_at is not None and started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if finished_at is not None and finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)
    duration_start = started_at or submitted_at
    if duration_start is not None and duration_start.tzinfo is None:
        duration_start = duration_start.replace(tzinfo=timezone.utc)
    duration_end = finished_at or now
    duration = (
        max(0.0, (duration_end - duration_start).total_seconds())
        if duration_start is not None
        else 0.0
    )
    if worker_status in {"completed", "failed"}:
        worker_stage = worker_status
    if worker_status == "interrupted_unknown" and worker_error is None:
        worker_error = (
            "A running record exists without an active PostgreSQL discovery advisory lock."
            if advisory_lock_held is False
            else "A running record exists, but advisory-lock ownership cannot be verified."
        )

    return {
        "status": worker_status,
        "run": run if worker_status == "running" else None,
        "run_id": worker_run_id,
        "trigger_type": trigger_type,
        "started_at": started_at,
        "submitted_at": submitted_at,
        "duration_seconds": round(duration, 2),
        "recoverable": worker_status == "interrupted_unknown" and advisory_lock_held is False,
        "stage": worker_stage,
        "error": worker_error,
    }


@router.post(
    "/discovery-runs/manual",
    response_model=AdminDiscoveryRunStart,
    status_code=202,
)
def start_manual_discovery(db: Session = Depends(get_db)):
    if not _manual_discovery_submission_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "MANUAL_SUBMISSION_IN_PROGRESS",
                "message": "A manual discovery submission is already in progress.",
            },
        )

    submitted = False
    previous_state = _manual_discovery_state_snapshot()
    try:
        run_id = str(uuid.uuid4())
        _update_manual_discovery_state(
            status="submitting",
            run_id=run_id,
            trigger_type="manual",
            submitted_at=datetime.now(timezone.utc),
            started_at=None,
            finished_at=None,
            stage="checking_active_run",
            error=None,
        )
        settings = scholarship_discovery_settings()
        active_since = datetime.now(timezone.utc) - timedelta(
            hours=settings.stale_run_timeout_hours
        )
        active_run = (
            db.query(ScholarshipDiscoveryRun)
            .filter(
                ScholarshipDiscoveryRun.status == "running",
                ScholarshipDiscoveryRun.started_at >= active_since,
            )
            .first()
        )
        advisory_lock_held = discovery_advisory_lock_is_held(db)
        if active_run and advisory_lock_held is not False:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "DISCOVERY_DATABASE_RUN_ACTIVE",
                    "message": "A recent discovery run is recorded as running and its advisory-lock state is active or unknown.",
                },
            )

        started = Future()
        signal_lock = threading.Lock()

        def mark_started(started_run_id: str) -> None:
            _update_manual_discovery_state(
                status="running",
                run_id=started_run_id,
                trigger_type="manual",
                started_at=datetime.now(timezone.utc),
                stage="discovery",
                error=None,
            )
            with signal_lock:
                if not started.done():
                    started.set_result(started_run_id)

        def mark_stage(stage: str) -> None:
            _update_manual_discovery_state(stage=stage)

        _update_manual_discovery_state(status="starting", stage="waiting_for_worker_start")
        worker = _manual_discovery_executor.submit(
            _execute_manual_discovery,
            run_id,
            mark_started,
            mark_stage,
        )
        submitted = True

        def release_submission_lock(completed_worker) -> None:
            try:
                error = completed_worker.exception()
                if error is not None:
                    logger.error(
                        "Manual scholarship discovery worker failed: %s",
                        type(error).__name__,
                    )
                    _update_manual_discovery_state(
                        status="failed",
                        finished_at=datetime.now(timezone.utc),
                        stage="failed",
                        error=type(error).__name__,
                    )
                else:
                    exit_code = completed_worker.result()
                    if exit_code == 0:
                        status = "completed"
                        error_summary = None
                    elif exit_code == 3:
                        status = "failed"
                        error_summary = "DISCOVERY_ADVISORY_LOCK_ACTIVE"
                    else:
                        status = "failed"
                        error_summary = f"Discovery worker exited with status {exit_code}."
                    _update_manual_discovery_state(
                        status=status,
                        finished_at=datetime.now(timezone.utc),
                        stage=status,
                        error=error_summary,
                    )
            except Exception as exc:
                logger.error(
                    "Manual scholarship discovery worker completion failed: %s",
                    type(exc).__name__,
                )
                _update_manual_discovery_state(
                    status="failed",
                    finished_at=datetime.now(timezone.utc),
                    stage="failed",
                    error=type(exc).__name__,
                )
            finally:
                with signal_lock:
                    if not started.done():
                        started.set_result(None)
                _manual_discovery_submission_lock.release()

        worker.add_done_callback(release_submission_lock)
        started_run_id = started.result()
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("Manual discovery could not check active runs: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="Unable to verify whether discovery is already running.",
        ) from exc
    except RuntimeError as exc:
        logger.error("Manual discovery could not be submitted: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="Unable to start scholarship discovery.",
        ) from exc
    finally:
        if not submitted:
            _update_manual_discovery_state(**previous_state)
            _manual_discovery_submission_lock.release()

    if started_run_id is None:
        try:
            exit_code = worker.result()
        except Exception as exc:
            logger.error("Manual discovery failed before run creation: %s", type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail="Scholarship discovery could not be started.",
            ) from exc
        if exit_code == 3:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "DISCOVERY_ADVISORY_LOCK_ACTIVE",
                    "message": "Another discovery worker currently holds the PostgreSQL advisory lock.",
                },
            )
        raise HTTPException(
            status_code=503,
            detail="Scholarship discovery could not be started.",
        )
    return AdminDiscoveryRunStart(run_id=started_run_id, status="running")


@router.get("/discovery-monitoring", response_model=AdminDiscoveryMonitoring)
def discovery_monitoring(db: Session = Depends(get_db)):
    settings = scholarship_discovery_settings()
    now = datetime.now(timezone.utc)
    recent_records = (
        db.query(ScholarshipDiscoveryRun)
        .order_by(ScholarshipDiscoveryRun.started_at.desc())
        .limit(25)
        .all()
    )
    latest_attempt = (
        db.query(ScholarshipDiscoveryRun)
        .order_by(ScholarshipDiscoveryRun.started_at.desc())
        .first()
    )
    latest_success = (
        db.query(ScholarshipDiscoveryRun)
        .filter(ScholarshipDiscoveryRun.status == "completed")
        .order_by(ScholarshipDiscoveryRun.started_at.desc())
        .first()
    )
    latest_failure = (
        db.query(ScholarshipDiscoveryRun)
        .filter(ScholarshipDiscoveryRun.status == "failed")
        .order_by(ScholarshipDiscoveryRun.finished_at.desc())
        .first()
    )
    latest_running = (
        db.query(ScholarshipDiscoveryRun)
        .filter(ScholarshipDiscoveryRun.status == "running")
        .order_by(ScholarshipDiscoveryRun.started_at.desc())
        .first()
    )
    worker = _discovery_worker_snapshot(db, latest_attempt, latest_running, now)
    current = worker["run"]
    current_manual = current if current and current.trigger_type == "manual" else None
    latest_scheduled = (
        db.query(ScholarshipDiscoveryRun)
        .filter(ScholarshipDiscoveryRun.scheduled_for.is_not(None))
        .order_by(ScholarshipDiscoveryRun.scheduled_for.desc())
        .first()
    )
    next_scheduled = None
    if settings.enabled:
        next_scheduled, _trigger = calculate_next_run(
            latest_scheduled.scheduled_for if latest_scheduled else None,
            now,
            settings.interval_hours,
        )

    return AdminDiscoveryMonitoring(
        enabled=settings.enabled,
        interval_hours=settings.interval_hours,
        next_scheduled_run=next_scheduled,
        current_run_status="running" if worker["status"] == "running" else "idle",
        current_run=_discovery_run_history(current, now) if current else None,
        current_manual_run=_discovery_run_history(current_manual, now) if current_manual else None,
        last_scheduled_run=(
            _discovery_run_history(latest_scheduled, now) if latest_scheduled else None
        ),
        last_attempted_run=_discovery_run_history(latest_attempt, now) if latest_attempt else None,
        last_successful_run=_discovery_run_history(latest_success, now) if latest_success else None,
        last_completed_run=_discovery_run_history(latest_success, now) if latest_success else None,
        last_failed_run=_discovery_run_history(latest_failure, now) if latest_failure else None,
        worker_status=worker["status"],
        worker_run_id=worker["run_id"],
        worker_trigger_type=worker["trigger_type"],
        worker_started_at=worker["started_at"],
        worker_submitted_at=worker["submitted_at"],
        worker_duration_seconds=worker["duration_seconds"],
        worker_recoverable=worker["recoverable"],
        worker_stage=worker["stage"],
        worker_error=worker["error"],
        recent_runs=[_discovery_run_history(run, now) for run in recent_records],
        candidates_total=db.query(func.count(ScholarshipDiscoveryReviewItem.id)).scalar() or 0,
        review_queue_pending=(
            db.query(func.count(ScholarshipDiscoveryReviewItem.id))
            .filter(ScholarshipDiscoveryReviewItem.review_status == "pending")
            .scalar()
            or 0
        ),
    )


@router.get("/discovery-history", response_model=AdminDiscoveryHistoryPage)
def discovery_history(
    status: Optional[Literal["succeeded", "partial", "failed"]] = Query(None),
    days: int = Query(30, ge=0, le=3650),
    q: Optional[str] = Query(None, max_length=200),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    query = db.query(ScholarshipDiscoveryRun)
    if days:
        query = query.filter(ScholarshipDiscoveryRun.started_at >= now - timedelta(days=days))
    if q and q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.filter(or_(
            ScholarshipDiscoveryRun.id.ilike(pattern, escape="\\"),
            ScholarshipDiscoveryRun.trigger_type.ilike(pattern, escape="\\"),
            cast(ScholarshipDiscoveryRun.summary, String).ilike(pattern, escape="\\"),
            cast(ScholarshipDiscoveryRun.source_results, String).ilike(pattern, escape="\\"),
        ))

    runs = [
        (run, _discovery_run_history(run, now))
        for run in query.order_by(ScholarshipDiscoveryRun.started_at.desc()).all()
    ]
    if status:
        runs = [(run, history) for run, history in runs if history.display_status == status]
    selected_runs = runs[skip:skip + limit]
    review_counts = {}
    if selected_runs:
        run_ids = [run.id for run, _history in selected_runs]
        review_rows = (
            db.query(
                ScholarshipDiscoveryReviewItem.discovery_run_id,
                ScholarshipDiscoveryReviewItem.source_id,
                func.count(ScholarshipDiscoveryReviewItem.id),
            )
            .filter(ScholarshipDiscoveryReviewItem.discovery_run_id.in_(run_ids))
            .group_by(
                ScholarshipDiscoveryReviewItem.discovery_run_id,
                ScholarshipDiscoveryReviewItem.source_id,
            )
            .all()
        )
        for run_id, source_id, count in review_rows:
            review_counts.setdefault(run_id, {})[source_id] = count
    return {
        "total": len(runs),
        "skip": skip,
        "limit": limit,
        "items": [
            _discovery_run_history(run, now, review_counts.get(run.id, {}))
            for run, _history in selected_runs
        ],
    }


def _discovery_publication_response(publication, scholarship_name):
    version = publication.current_version

    def version_summary(entry):
        return {
            "id": entry.id,
            "version_number": entry.version_number,
            "review_item_id": entry.review_item_id,
            "candidate_name_at_approval": entry.candidate_name_at_approval,
            "host_country_at_approval": entry.host_country_at_approval,
            "approved_values": entry.approved_values,
            "source_evidence": entry.source_evidence,
            "approval_decision": entry.approval_decision,
            "approved_by_email": entry.approved_by_email,
            "approved_at": entry.approved_at,
        }

    return {
        "id": publication.id,
        "canonical_scholarship_id": publication.canonical_scholarship_id,
        "scholarship_name": scholarship_name,
        "status": publication.status,
        "current_version_id": publication.current_version_id,
        "current_version_number": version.version_number if version else None,
        "current_version": version_summary(version) if version else None,
        "versions": [version_summary(entry) for entry in publication.versions],
        "published_at": publication.published_at,
        "revoked_at": publication.revoked_at,
        "revoked_by_id": publication.revoked_by_id,
        "revoked_by_email": publication.revoked_by_email,
        "revocation_reason": publication.revocation_reason,
        "superseded_by_publication_id": publication.superseded_by_publication_id,
        "created_at": publication.created_at,
        "updated_at": publication.updated_at,
        "sources": [
            {
                "id": source.id,
                "source_id": source.source_id,
                "source_name": source.source_name,
                "source_classification": source.source_classification,
                "source_trust_basis": source.source_trust_basis,
                "source_url": source.source_url,
                "last_checked_at": source.last_checked_at,
                "last_successful_check_at": source.last_successful_check_at,
                "observed_content_hash": source.observed_content_hash,
                "source_check_status": source.source_check_status,
            }
            for source in publication.sources
        ],
    }


@router.get("/discovery-publications", response_model=AdminDiscoveryPublicationPage)
def discovery_publications(
    status: Optional[Literal["published", "expired", "withdrawn", "revoked", "superseded"]] = Query(None),
    scholarship_id: Optional[int] = Query(None, gt=0),
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(ScholarshipDiscoveryPublication).options(
        selectinload(ScholarshipDiscoveryPublication.current_version),
        selectinload(ScholarshipDiscoveryPublication.versions),
        selectinload(ScholarshipDiscoveryPublication.sources),
    )
    if status:
        query = query.filter(ScholarshipDiscoveryPublication.status == status)
    if scholarship_id:
        query = query.filter(
            ScholarshipDiscoveryPublication.canonical_scholarship_id == scholarship_id,
        )
    total = query.count()
    publications = (
        query.order_by(ScholarshipDiscoveryPublication.updated_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    scholarship_names = dict(
        db.query(Scholarship.id, Scholarship.name)
        .filter(Scholarship.id.in_([item.canonical_scholarship_id for item in publications]))
        .all()
    ) if publications else {}
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [
            _discovery_publication_response(item, scholarship_names.get(item.canonical_scholarship_id))
            for item in publications
        ],
    }


@router.post(
    "/discovery-publications/{publication_id}/lifecycle",
    response_model=AdminDiscoveryPublication,
)
def change_discovery_publication_lifecycle(
    data: AdminDiscoveryPublicationLifecycleWrite,
    publication_id: str = Path(..., min_length=36, max_length=36),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    try:
        publication = transition_publication(
            db,
            publication_id,
            admin,
            decision=data.decision,
            reason=data.reason,
            superseded_by_publication_id=data.superseded_by_publication_id,
        )
        publication = (
            db.query(ScholarshipDiscoveryPublication)
            .options(
                selectinload(ScholarshipDiscoveryPublication.current_version),
                selectinload(ScholarshipDiscoveryPublication.versions),
                selectinload(ScholarshipDiscoveryPublication.sources),
            )
            .filter(ScholarshipDiscoveryPublication.id == publication.id)
            .first()
        )
        scholarship_name = db.query(Scholarship.name).filter(
            Scholarship.id == publication.canonical_scholarship_id,
        ).scalar()
        return _discovery_publication_response(publication, scholarship_name)
    except Exception:
        db.rollback()
        raise


@router.get(
    "/discovery-publications/{publication_id}/events",
    response_model=AdminDiscoveryPublicationEventPage,
)
def discovery_publication_events(
    publication_id: str = Path(..., min_length=36, max_length=36),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    exists = (
        db.query(ScholarshipDiscoveryPublication.id)
        .filter(ScholarshipDiscoveryPublication.id == publication_id)
        .first()
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="Discovery publication not found")
    query = db.query(ScholarshipDiscoveryPublicationEvent).filter(
        ScholarshipDiscoveryPublicationEvent.publication_id == publication_id,
    )
    total = query.count()
    events = (
        query.order_by(
            ScholarshipDiscoveryPublicationEvent.created_at.desc(),
            ScholarshipDiscoveryPublicationEvent.id.desc(),
        )
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {"total": total, "skip": skip, "limit": limit, "items": events}


@router.get("/discovery-sources", response_model=AdminDiscoverySourcePage)
def discovery_sources(db: Session = Depends(get_db)):
    review_counts = dict(
        db.query(
            ScholarshipDiscoveryReviewItem.source_id,
            func.count(ScholarshipDiscoveryReviewItem.id),
        )
        .group_by(ScholarshipDiscoveryReviewItem.source_id)
        .all()
    )
    recent_source_runs = (
        db.query(ScholarshipDiscoveryRun.source_results)
        .order_by(ScholarshipDiscoveryRun.started_at.desc())
        .all()
    )
    latest_results = {}
    for (source_results,) in recent_source_runs:
        for result in source_results or []:
            if not isinstance(result, dict):
                continue
            source_id = result.get("source_id")
            if source_id and source_id not in latest_results:
                latest_results[source_id] = result

    valid_statuses = {
        "pending",
        "fetched",
        "failed",
        "partial_failure",
        "skipped",
        "trust_review_required",
    }
    items = []
    for source in SOURCES:
        latest = latest_results.get(source.source_id, {})
        status = latest.get("status")
        if status not in valid_statuses:
            status = "not_checked"
        active = (
            source.crawl_enabled
            and not source.discovery_only
            and source.trust_reviewed
            and bool(source.trust_basis)
        )
        pages_checked = latest.get("pages_fetched", 0)
        items.append({
            "source_id": source.source_id,
            "name": source.name,
            "official_domain": source.official_domain,
            "category": source.category,
            "country_or_region": source.country_or_region,
            "source_url": source.source_url,
            "source_classification": source.source_classification,
            "active": active,
            "status": status,
            "last_checked": latest.get("attempted_at") if isinstance(latest.get("attempted_at"), str) else None,
            "pages_checked": pages_checked if isinstance(pages_checked, int) and not isinstance(pages_checked, bool) else 0,
            "review_candidates": review_counts.get(source.source_id, 0),
        })
    return {"total": len(items), "items": items}


@router.post(
    "/discovery-reviews/{review_id}/review",
    response_model=AdminDiscoveryReviewItem,
)
def review_discovery_item(
    data: AdminDiscoveryReviewWrite,
    review_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    item = (
        db.query(ScholarshipDiscoveryReviewItem)
        .filter(ScholarshipDiscoveryReviewItem.id == review_id)
        .with_for_update()
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Discovery review item not found")
    if data.decision not in {"accepted", "link_and_publish"} and data.values is not None:
        raise HTTPException(status_code=422, detail="Edited scholarship values are only valid when publishing")
    if data.decision != "duplicate" and data.duplicate_of_scholarship_id is not None:
        raise HTTPException(status_code=422, detail="A duplicate scholarship is only valid for duplicate decisions")
    if data.decision != "link_and_publish" and data.link_to_scholarship_id is not None:
        raise HTTPException(status_code=422, detail="A link target is only valid for link-and-publish")
    try:
        return apply_review_action(
            db,
            item,
            decision=data.decision,
            admin=admin,
            values=data.values,
            duplicate_of_scholarship_id=data.duplicate_of_scholarship_id,
            link_to_scholarship_id=data.link_to_scholarship_id,
            note=data.note,
        )
    except Exception:
        db.rollback()
        raise


@router.get("/duplicates", response_model=List[DuplicatePair])
def duplicates(db: Session = Depends(get_db)):
    """Flagged and suspected duplicate pairs. Nothing is merged."""
    return duplicate_pairs(db.query(Scholarship).order_by(Scholarship.id).all())


@router.get("/duplicates/compare", response_model=DuplicateComparison)
def compare_duplicates(first: int = Query(..., gt=0), second: int = Query(..., gt=0), db: Session = Depends(get_db)):
    """Two records side by side, with every field that differs."""
    if first == second:
        raise HTTPException(status_code=422, detail="Choose two different records")
    one, two = _record(db, first), _record(db, second)
    one_data, two_data = ScholarshipResponse.model_validate(one).model_dump(), ScholarshipResponse.model_validate(two).model_dump()
    skip = {"id", "record_version", "duplicate_of_id"}
    differences = [{"field": field, "first": _plain(one_data[field]), "second": _plain(two_data[field])}
                   for field in one_data if field not in skip and one_data[field] != two_data[field]]
    return {"first": one, "second": two, "differences": differences,
            "first_references": reference_counts(db, first), "second_references": reference_counts(db, second)}


def _plain(value):
    return value.isoformat() if isinstance(value, date) else value


@router.get("", response_model=AdminRowPage)
def list_records(
    q: Optional[str] = Query(None, max_length=100, description="Name, provider or country"),
    verification: Optional[str] = Query(None, pattern="^(verified|unverified)$"),
    issue: Optional[str] = Query(None, max_length=40, description="An issue code, verification_recheck, or attention for what needs work"),
    archived: bool = Query(False, description="Show archived records instead"),
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Scholarship records with their data quality issues, most issues first."""
    text = " ".join((q or "").lower().split())
    rows = []
    for row, issues in _rows_with_issues(db):
        codes = {item["code"] for item in issues}
        if row.archived != archived or (verification and row.verification_status != verification):
            continue
        if text and text not in " ".join(filter(None, [row.name, row.provider, row.country])).lower():
            continue
        if issue:
            if issue == "attention":
                if not codes & ATTENTION_CODES:
                    continue
            elif issue == "verification_recheck":
                if not codes & {"needs_reverification", "stale_verification"}:
                    continue
            elif issue not in codes:
                continue
        rows.append({"id": row.id, "name": row.name, "provider": row.provider, "country": row.country,
                     "deadline": row.deadline,
                     "official_source_url": row.official_info_url or row.official_url,
                     "verification_status": row.verification_status, "verification_basis": row.verification_basis,
                     "last_verified_date": row.last_verified_date, "archived": row.archived, "duplicate_of_id": row.duplicate_of_id,
                     "issues": issues})
    rows.sort(key=lambda item: (-sum(entry["severity"] == "high" for entry in item["issues"]), -len(item["issues"]), item["id"]))
    return {"total": len(rows), "items": rows[skip:skip + limit]}


def _detail(db: Session, item: Scholarship) -> dict:
    audit = (db.query(ScholarshipAuditLog).filter(ScholarshipAuditLog.scholarship_id == item.id)
             .order_by(ScholarshipAuditLog.id.desc()).limit(50).all())
    return {"scholarship": item, "issues": find_issues(item), "references": reference_counts(db, item.id), "audit": audit}


@router.get("/{scholarship_id}/documents", response_model=AdminSourceDocumentPage)
def list_documents(
    scholarship_id: int = Path(..., gt=0),
    skip: int = Query(0, ge=0, le=MAX_DOCUMENT_OFFSET),
    limit: int = Query(25, ge=1, le=100),
    version_skip: int = Query(0, ge=0, le=MAX_DOCUMENT_OFFSET),
    version_limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List a scholarship's source documents and their stored versions."""
    scholarship = _record(db, scholarship_id)
    query = db.query(ScholarshipSourceDocument).filter(
        ScholarshipSourceDocument.scholarship_id == scholarship_id
    )
    total = query.count()
    sources = (
        query.options(selectinload(ScholarshipSourceDocument.versions))
        .order_by(ScholarshipSourceDocument.id)
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [
            _source_summary(source, scholarship.name, version_skip, version_limit)
            for source in sources
        ],
    }


@router.get("/{scholarship_id}/documents/{version_id}", response_model=AdminDocumentVersionDetail)
def inspect_document_version(
    scholarship_id: int = Path(..., gt=0),
    version_id: int = Path(..., gt=0),
    text_offset: int = Query(0, ge=0, le=MAX_TEXT_OFFSET),
    text_limit: int = Query(4000, ge=1, le=MAX_EXTRACTED_TEXT_CHARS),
    db: Session = Depends(get_db),
):
    """Return stored version metadata and one bounded slice of its extracted text."""
    scholarship = _record(db, scholarship_id)
    row = (
        db.query(ScholarshipSourceDocument, ScholarshipDocumentVersion)
        .join(
            ScholarshipDocumentVersion,
            ScholarshipDocumentVersion.source_document_id == ScholarshipSourceDocument.id,
        )
        .filter(
            ScholarshipSourceDocument.scholarship_id == scholarship_id,
            ScholarshipDocumentVersion.id == version_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Document version not found")

    source, version = row
    display_text = safe_source_urls_in_text(version.extracted_text)
    text_total_chars = len(display_text)
    extracted_text = display_text[text_offset:text_offset + text_limit]
    return {
        "scholarship_id": scholarship_id,
        "scholarship_name": scholarship.name,
        "source_document_id": source.id,
        "source_title": None,
        "source_url": safe_source_url(source.source_url) or "[redacted invalid source URL]",
        "source_role": source.source_role,
        "source_is_active": source.is_active,
        "source_created_at": source.created_at,
        "source_updated_at": source.updated_at,
        "document_version_id": version.id,
        **_version_summary(version),
        "extracted_text": extracted_text,
        "text_offset": text_offset,
        "text_limit": text_limit,
        "text_total_chars": text_total_chars,
        "has_more_text": text_offset + len(extracted_text) < text_total_chars,
    }


def _load_document_index_context(db, scholarship_id, version_id, *, lock_rows=False):
    scholarship_query = db.query(Scholarship).filter(Scholarship.id == scholarship_id)
    if lock_rows:
        scholarship_query = scholarship_query.with_for_update()
    scholarship = scholarship_query.first()
    if scholarship is None:
        raise HTTPException(status_code=404, detail="Scholarship not found")

    version_scope = (
        db.query(ScholarshipDocumentVersion.source_document_id)
        .join(
            ScholarshipSourceDocument,
            ScholarshipSourceDocument.id == ScholarshipDocumentVersion.source_document_id,
        )
        .filter(
            ScholarshipSourceDocument.scholarship_id == scholarship_id,
            ScholarshipDocumentVersion.id == version_id,
        )
        .first()
    )
    if version_scope is None:
        raise HTTPException(status_code=404, detail="Document version not found")

    source_query = db.query(ScholarshipSourceDocument).filter(
        ScholarshipSourceDocument.id == version_scope.source_document_id,
        ScholarshipSourceDocument.scholarship_id == scholarship_id,
    )
    if lock_rows:
        source_query = source_query.with_for_update()
    source = source_query.first()
    if source is None:
        raise HTTPException(status_code=404, detail="Document version not found")

    version_query = db.query(ScholarshipDocumentVersion).filter(
        ScholarshipDocumentVersion.id == version_id,
        ScholarshipDocumentVersion.source_document_id == source.id,
    )
    if lock_rows:
        version_query = version_query.with_for_update()
    version = version_query.first()
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found")

    latest_version_query = (
        db.query(ScholarshipDocumentVersion)
        .filter(ScholarshipDocumentVersion.source_document_id == source.id)
        .order_by(ScholarshipDocumentVersion.id.desc())
    )
    if lock_rows:
        latest_version_query = latest_version_query.with_for_update()
    latest_version = latest_version_query.first()

    latest_approval_query = (
        db.query(ScholarshipDocumentVersionApproval)
        .filter(ScholarshipDocumentVersionApproval.document_version_id == version.id)
        .order_by(ScholarshipDocumentVersionApproval.id.desc())
    )
    if lock_rows:
        latest_approval_query = latest_approval_query.with_for_update()
    latest_approval = latest_approval_query.first()

    return scholarship, source, version, latest_version, latest_approval


def _validate_document_index_eligibility(
    scholarship,
    source,
    version,
    latest_version,
    latest_approval,
    expected_content_hash,
    expected_record_version,
):
    if latest_version is None or latest_version.id != version.id:
        raise HTTPException(status_code=409, detail="Document version has been superseded")
    if version.content_hash != expected_content_hash:
        raise HTTPException(status_code=409, detail="Document content changed; reload before indexing")
    if scholarship.record_version != expected_record_version:
        raise HTTPException(status_code=409, detail="Scholarship record changed; reload before indexing")
    if scholarship.archived_at is not None:
        raise HTTPException(status_code=409, detail="Archived scholarships cannot be indexed")
    if not source.is_active:
        raise HTTPException(status_code=409, detail="Inactive source documents cannot be indexed")
    if (
        scholarship.verification_status != "verified"
        or scholarship.verification_basis != "official_source"
        or not is_currently_verified(scholarship)
    ):
        raise HTTPException(
            status_code=409,
            detail="Scholarship is not currently verified against a healthy official source",
        )
    if document_source_issue(
        source.source_url,
        scholarship.source_checks,
        source_document_id=source.id,
        expected_content_hash=version.content_hash,
    ):
        raise HTTPException(
            status_code=409,
            detail="Document source URL has no current successful source check",
        )
    if (
        version.scholarship_record_version_snapshot != scholarship.record_version
        or version.verification_status_snapshot != scholarship.verification_status
        or version.verification_basis_snapshot != scholarship.verification_basis
        or version.last_verified_date_snapshot != scholarship.last_verified_date
    ):
        raise HTTPException(status_code=409, detail="Scholarship or document verification snapshot is stale")
    if (
        version.verification_status_snapshot != "verified"
        or version.verification_basis_snapshot != "official_source"
    ):
        raise HTTPException(status_code=409, detail="Document version lacks an official verification snapshot")
    if version.review_status != "approved":
        raise HTTPException(status_code=409, detail="Only approved document versions can be indexed")
    if version.indexing_status not in {"approved", "indexed"}:
        raise HTTPException(status_code=409, detail="Document version is not approved for indexing")
    if latest_approval is None or latest_approval.decision != "approved":
        raise HTTPException(status_code=409, detail="The latest document approval is not active")
    if (
        latest_approval.verification_status_snapshot != version.verification_status_snapshot
        or latest_approval.verification_basis_snapshot != version.verification_basis_snapshot
        or latest_approval.review_status_snapshot != "approved"
        or latest_approval.indexing_status_snapshot != "approved"
        or latest_approval.document_record_version_snapshot != version.scholarship_record_version_snapshot
        or not latest_approval.source_active_at_decision
        or latest_approval.scholarship_record_version_at_decision != scholarship.record_version
        or latest_approval.scholarship_verification_status_at_decision != scholarship.verification_status
        or latest_approval.scholarship_verification_basis_at_decision != scholarship.verification_basis
        or latest_approval.scholarship_archived_at_decision is not None
    ):
        raise HTTPException(status_code=409, detail="The latest document approval is stale or inconsistent")


def _validated_index_vector(values):
    try:
        components = list(values)
    except TypeError as exc:
        raise ValueError("embedding vector is not iterable") from exc
    if len(components) != EMBEDDING_DIMENSIONS:
        raise ValueError("embedding vector has an unexpected number of dimensions")
    vector = []
    for component in components:
        if isinstance(component, (bool, str, bytes)):
            raise ValueError("embedding vector contains a non-numeric value")
        try:
            value = float(component)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("embedding vector contains a non-numeric value") from exc
        if not math.isfinite(value):
            raise ValueError("embedding vector contains a non-finite value")
        vector.append(value)
    if not math.isclose(math.hypot(*vector), 1.0, rel_tol=1e-4, abs_tol=1e-4):
        raise ValueError("embedding vector is not normalized")
    return vector


def _validated_expected_chunks(extracted_text, chunks):
    if not chunks:
        raise HTTPException(status_code=409, detail="Document text has no indexable content")
    expected = {}
    for ordinal, chunk in enumerate(chunks):
        if (
            chunk.ordinal != ordinal
            or not isinstance(chunk.chunk_text, str)
            or not isinstance(chunk.start_offset, int)
            or isinstance(chunk.start_offset, bool)
            or not isinstance(chunk.end_offset, int)
            or isinstance(chunk.end_offset, bool)
            or chunk.start_offset < 0
            or chunk.end_offset <= chunk.start_offset
            or chunk.end_offset > len(extracted_text)
            or extracted_text[chunk.start_offset:chunk.end_offset] != chunk.chunk_text
            or chunk.chunk_hash != hashlib.sha256(chunk.chunk_text.encode("utf-8")).hexdigest()
        ):
            raise HTTPException(status_code=503, detail="Document chunking returned inconsistent source offsets")
        expected[ordinal] = chunk
    return expected


def _validate_stored_chunk(row, expected):
    if (
        row.chunk_ordinal != expected.ordinal
        or row.chunk_text != expected.chunk_text
        or row.chunk_hash != expected.chunk_hash
        or row.start_offset != expected.start_offset
        or row.end_offset != expected.end_offset
    ):
        raise HTTPException(
            status_code=409,
            detail="Existing document chunks conflict with the current deterministic chunking",
        )


def _validate_stored_embedding(
    row,
    allowed_chunk_ids,
    approval_id,
    model_name,
    expected_vector=None,
):
    if row.chunk_id not in allowed_chunk_ids:
        raise HTTPException(status_code=409, detail="An existing embedding references an unexpected document chunk")
    if row.approval_id != approval_id:
        raise HTTPException(status_code=409, detail="An existing embedding references an obsolete approval")
    if row.model_name != model_name:
        raise HTTPException(status_code=409, detail="An existing embedding uses an unsupported model")
    if row.dimensions != EMBEDDING_DIMENSIONS:
        raise HTTPException(status_code=409, detail="An existing embedding has incompatible dimensions")
    try:
        stored_vector = _validated_index_vector(row.embedding)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="An existing embedding vector is invalid") from exc
    # pgvector stores float32 components, so allow only a tight storage-rounding tolerance.
    if expected_vector is not None and any(
        not math.isclose(stored, expected, rel_tol=1e-6, abs_tol=1e-12)
        for stored, expected in zip(stored_vector, expected_vector)
    ):
        raise HTTPException(
            status_code=409,
            detail="An existing embedding conflicts with the generated vector",
        )


@router.post(
    "/{scholarship_id}/documents/{version_id}/index",
    response_model=AdminDocumentIndexResponse,
)
def index_document_version(
    data: AdminDocumentIndexWrite,
    scholarship_id: int = Path(..., gt=0),
    version_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Index the latest approved version without mutating its approval history."""
    committed = False
    try:
        scholarship, source, version, latest_version, latest_approval = _load_document_index_context(
            db, scholarship_id, version_id
        )
        _validate_document_index_eligibility(
            scholarship,
            source,
            version,
            latest_version,
            latest_approval,
            data.expected_content_hash,
            data.expected_scholarship_record_version,
        )
        extracted_text = version.extracted_text
        version_content_hash = version.content_hash
        version_record_version = scholarship.record_version
        source_document_id = source.id

        try:
            document_indexing.validate_document_input_size(extracted_text)
        except document_indexing.DocumentInputTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        if not extracted_text.strip():
            raise HTTPException(status_code=409, detail="Document text has no indexable content")
        db.rollback()

        try:
            model_revision = rag_service.get_model_revision()
            chunks = document_indexing.chunk_document_text(
                extracted_text,
                model_revision=model_revision,
            )
            expected_chunks = _validated_expected_chunks(extracted_text, chunks)
            vectors = document_indexing.generate_document_embeddings(
                chunks,
                model_revision=model_revision,
            )
            if rag_service.get_model_revision() != model_revision:
                raise rag_service.RagUnavailable("embedding model revision changed during indexing")
            if len(vectors) != len(chunks):
                raise ValueError("embedding count does not match the document chunk count")
            vectors = [_validated_index_vector(vector) for vector in vectors]
        except rag_service.RagUnavailable as exc:
            logger.warning("Scholarship indexing model unavailable: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="The configured document embedding model is unavailable") from exc
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            logger.warning("Scholarship indexing preprocessing failed: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="Document chunking or embedding generation failed") from exc

        db.rollback()
        db.begin()
        if db.get_bind().dialect.name == "postgresql":
            db.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": SCHOLARSHIP_KNOWLEDGE_WRITE_LOCK_ID},
            )

        (
            scholarship,
            source,
            version,
            latest_version,
            latest_approval,
        ) = _load_document_index_context(db, scholarship_id, version_id, lock_rows=True)
        _validate_document_index_eligibility(
            scholarship,
            source,
            version,
            latest_version,
            latest_approval,
            data.expected_content_hash,
            data.expected_scholarship_record_version,
        )
        if (
            source.id != source_document_id
            or version.content_hash != version_content_hash
            or scholarship.record_version != version_record_version
            or version.extracted_text != extracted_text
        ):
            raise HTTPException(status_code=409, detail="Document changed during indexing; reload and retry")

        existing_chunks = (
            db.query(ScholarshipDocumentChunk)
            .filter(ScholarshipDocumentChunk.document_version_id == version.id)
            .order_by(ScholarshipDocumentChunk.chunk_ordinal)
            .all()
        )
        chunks_by_ordinal = {}
        for row in existing_chunks:
            expected = expected_chunks.get(row.chunk_ordinal)
            if expected is None:
                raise HTTPException(status_code=409, detail="Unexpected immutable chunks already exist")
            _validate_stored_chunk(row, expected)
            chunks_by_ordinal[row.chunk_ordinal] = row

        chunks_created = 0
        for ordinal, chunk in expected_chunks.items():
            if ordinal in chunks_by_ordinal:
                continue
            row = ScholarshipDocumentChunk(
                document_version_id=version.id,
                chunk_ordinal=ordinal,
                chunk_text=chunk.chunk_text,
                chunk_hash=chunk.chunk_hash,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
            )
            db.add(row)
            chunks_by_ordinal[ordinal] = row
            chunks_created += 1
        db.flush()

        persisted_chunks = (
            db.query(ScholarshipDocumentChunk)
            .filter(ScholarshipDocumentChunk.document_version_id == version.id)
            .order_by(ScholarshipDocumentChunk.chunk_ordinal)
            .all()
        )
        if len(persisted_chunks) != len(expected_chunks):
            raise HTTPException(status_code=409, detail="Persisted chunk count does not match the extracted document")
        chunks_by_ordinal = {}
        for row in persisted_chunks:
            expected = expected_chunks.get(row.chunk_ordinal)
            if expected is None:
                raise HTTPException(status_code=409, detail="Unexpected immutable chunks already exist")
            _validate_stored_chunk(row, expected)
            chunks_by_ordinal[row.chunk_ordinal] = row
        if set(chunks_by_ordinal) != set(expected_chunks):
            raise HTTPException(status_code=409, detail="Persisted chunks are incomplete")

        allowed_chunk_ids = {row.id for row in persisted_chunks}
        expected_vectors_by_chunk_id = {
            chunks_by_ordinal[ordinal].id: vectors[ordinal]
            for ordinal in expected_chunks
        }
        existing_embeddings = (
            db.query(ScholarshipChunkEmbedding)
            .join(
                ScholarshipDocumentChunk,
                ScholarshipDocumentChunk.id == ScholarshipChunkEmbedding.chunk_id,
            )
            .filter(ScholarshipDocumentChunk.document_version_id == version.id)
            .all()
        )
        target_embeddings = {}
        for row in existing_embeddings:
            is_target_embedding = (
                row.model_name == document_indexing.rag_service.QUERY_MODEL_NAME
                and row.model_revision == model_revision
            )
            _validate_stored_embedding(
                row,
                allowed_chunk_ids,
                latest_approval.id,
                document_indexing.rag_service.QUERY_MODEL_NAME,
                expected_vectors_by_chunk_id.get(row.chunk_id) if is_target_embedding else None,
            )
            if is_target_embedding:
                if row.chunk_id in target_embeddings:
                    raise HTTPException(status_code=409, detail="Duplicate embeddings exist for the configured model")
                target_embeddings[row.chunk_id] = row

        embeddings_created = 0
        for ordinal, chunk in expected_chunks.items():
            stored_chunk = chunks_by_ordinal[ordinal]
            if stored_chunk.id in target_embeddings:
                continue
            db.add(ScholarshipChunkEmbedding(
                chunk_id=stored_chunk.id,
                document_version_id=version.id,
                approval_id=latest_approval.id,
                embedding=vectors[ordinal],
                model_name=document_indexing.rag_service.QUERY_MODEL_NAME,
                model_revision=model_revision,
                dimensions=EMBEDDING_DIMENSIONS,
            ))
            embeddings_created += 1
        db.flush()

        persisted_embeddings = (
            db.query(ScholarshipChunkEmbedding)
            .join(
                ScholarshipDocumentChunk,
                ScholarshipDocumentChunk.id == ScholarshipChunkEmbedding.chunk_id,
            )
            .filter(
                ScholarshipDocumentChunk.document_version_id == version.id,
                ScholarshipChunkEmbedding.model_name == document_indexing.rag_service.QUERY_MODEL_NAME,
                ScholarshipChunkEmbedding.model_revision == model_revision,
            )
            .all()
        )
        target_embeddings = {}
        for row in persisted_embeddings:
            _validate_stored_embedding(
                row,
                allowed_chunk_ids,
                latest_approval.id,
                document_indexing.rag_service.QUERY_MODEL_NAME,
                expected_vectors_by_chunk_id.get(row.chunk_id),
            )
            target_embeddings[row.chunk_id] = row
        if set(target_embeddings) != allowed_chunk_ids:
            raise HTTPException(status_code=409, detail="Persisted embeddings are incomplete")

        old_indexing_status = version.indexing_status
        if version.indexing_status != "indexed":
            version.indexing_status = "indexed"
            db.flush()
        if old_indexing_status != "indexed" or chunks_created or embeddings_created:
            record_audit(
                db,
                scholarship.id,
                "document_indexed",
                admin,
                {
                    "document_version_id": [None, version.id],
                    "indexing_status": [old_indexing_status, "indexed"],
                    "model_name": [None, document_indexing.rag_service.QUERY_MODEL_NAME],
                    "model_revision": [None, model_revision],
                    "chunk_count": [None, len(expected_chunks)],
                    "embedding_count": [None, len(expected_chunks)],
                },
                "Indexed approved scholarship document.",
            )

        response = {
            "scholarship_id": scholarship.id,
            "document_version_id": version.id,
            "status": "indexed",
            "content_hash": version.content_hash,
            "scholarship_record_version": scholarship.record_version,
            "model_name": document_indexing.rag_service.QUERY_MODEL_NAME,
            "model_revision": model_revision,
            "chunk_count": len(expected_chunks),
            "embedding_count": len(expected_chunks),
            "chunks_created": chunks_created,
            "embeddings_created": embeddings_created,
            "idempotent": old_indexing_status == "indexed" and not chunks_created and not embeddings_created,
        }
        db.commit()
        committed = True
        return response
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="Indexing conflicted with immutable data or a database eligibility constraint",
        ) from exc
    finally:
        if not committed:
            db.rollback()


@router.post(
    "/{scholarship_id}/documents/{version_id}/review",
    response_model=AdminDocumentReviewResponse,
)
def review_document_version(
    data: AdminDocumentReviewWrite,
    scholarship_id: int = Path(..., gt=0),
    version_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Approve or reject the latest document version using the database's snapshot contract."""
    committed = False
    try:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": SCHOLARSHIP_KNOWLEDGE_WRITE_LOCK_ID},
            )

        scholarship = (
            db.query(Scholarship)
            .filter(Scholarship.id == scholarship_id)
            .with_for_update()
            .first()
        )
        if scholarship is None:
            raise HTTPException(status_code=404, detail="Scholarship not found")

        version_scope = (
            db.query(ScholarshipDocumentVersion.source_document_id)
            .join(
                ScholarshipSourceDocument,
                ScholarshipSourceDocument.id == ScholarshipDocumentVersion.source_document_id,
            )
            .filter(
                ScholarshipSourceDocument.scholarship_id == scholarship_id,
                ScholarshipDocumentVersion.id == version_id,
            )
            .first()
        )
        if version_scope is None:
            raise HTTPException(status_code=404, detail="Document version not found")

        source = (
            db.query(ScholarshipSourceDocument)
            .filter(
                ScholarshipSourceDocument.id == version_scope.source_document_id,
                ScholarshipSourceDocument.scholarship_id == scholarship_id,
            )
            .with_for_update()
            .first()
        )
        if source is None:
            raise HTTPException(status_code=404, detail="Document version not found")

        version = (
            db.query(ScholarshipDocumentVersion)
            .filter(
                ScholarshipDocumentVersion.id == version_id,
                ScholarshipDocumentVersion.source_document_id == source.id,
            )
            .with_for_update()
            .first()
        )
        if version is None:
            raise HTTPException(status_code=404, detail="Document version not found")

        latest_version = (
            db.query(ScholarshipDocumentVersion)
            .filter(ScholarshipDocumentVersion.source_document_id == source.id)
            .order_by(ScholarshipDocumentVersion.id.desc())
            .with_for_update()
            .first()
        )
        if latest_version is None or latest_version.id != version.id:
            raise HTTPException(status_code=409, detail="Document version has been superseded")
        if version.content_hash != data.expected_content_hash:
            raise HTTPException(status_code=409, detail="Document content changed; reload before reviewing")
        if (
            scholarship.record_version != data.expected_scholarship_record_version
            or version.scholarship_record_version_snapshot != scholarship.record_version
            or version.verification_status_snapshot != scholarship.verification_status
            or version.verification_basis_snapshot != scholarship.verification_basis
            or version.last_verified_date_snapshot != scholarship.last_verified_date
        ):
            raise HTTPException(status_code=409, detail="Scholarship or document verification snapshot is stale")
        if version.review_status == "rejected":
            raise HTTPException(status_code=409, detail="A rejected document version cannot be reviewed again")
        if version.review_status == "stale":
            raise HTTPException(status_code=409, detail="A stale document version cannot be reviewed")

        old_review_status = version.review_status
        old_indexing_status = version.indexing_status
        approval_event_id = None

        if data.decision == "approve":
            if old_review_status != "pending" or old_indexing_status != "pending":
                raise HTTPException(status_code=409, detail="Document version is not pending review")
            if scholarship.archived_at is not None:
                raise HTTPException(status_code=409, detail="Archived scholarships cannot be approved")
            if not source.is_active:
                raise HTTPException(status_code=409, detail="Inactive source documents cannot be approved")
            if (
                scholarship.verification_status != "verified"
                or scholarship.verification_basis != "official_source"
                or not is_currently_verified(scholarship)
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Scholarship is not currently verified against a healthy official source",
                )
            if document_source_issue(
                source.source_url,
                scholarship.source_checks,
                source_document_id=source.id,
                expected_content_hash=version.content_hash,
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Document source URL has no current successful source check",
                )
            if (
                version.verification_status_snapshot != "verified"
                or version.verification_basis_snapshot != "official_source"
            ):
                raise HTTPException(status_code=409, detail="Document version lacks an official verification snapshot")

            version.review_status = "approved"
            version.indexing_status = "approved"
            db.flush()

            approval = ScholarshipDocumentVersionApproval(
                document_version_id=version.id,
                decision="approved",
                verification_status_snapshot=version.verification_status_snapshot,
                verification_basis_snapshot=version.verification_basis_snapshot,
                review_status_snapshot=version.review_status,
                indexing_status_snapshot=version.indexing_status,
                document_record_version_snapshot=version.scholarship_record_version_snapshot,
                source_active_at_decision=source.is_active,
                scholarship_record_version_at_decision=scholarship.record_version,
                scholarship_verification_status_at_decision=scholarship.verification_status,
                scholarship_verification_basis_at_decision=scholarship.verification_basis,
                scholarship_archived_at_decision=scholarship.archived_at,
                actor=admin.email,
                reason=data.reason,
            )
            db.add(approval)
            db.flush()
            approval_event_id = approval.id
        else:
            if old_review_status not in {"pending", "approved"}:
                raise HTTPException(status_code=409, detail="Document version cannot be rejected from its current state")
            version.review_status = "rejected"
            db.flush()

        changes = {
            "decision": [None, data.decision],
            "document_version_id": [None, version.id],
            "content_hash": [None, version.content_hash],
            "review_status": [old_review_status, version.review_status],
            "indexing_status": [old_indexing_status, version.indexing_status],
            "scholarship_record_version": [
                version.scholarship_record_version_snapshot,
                scholarship.record_version,
            ],
        }
        record_audit(
            db,
            scholarship.id,
            f"document_{'approved' if data.decision == 'approve' else 'rejected'}",
            admin,
            changes,
            data.reason,
        )
        response = {
            "scholarship_id": scholarship.id,
            "document_version_id": version.id,
            "decision": data.decision,
            "content_hash": version.content_hash,
            "scholarship_record_version": scholarship.record_version,
            "review_status": version.review_status,
            "indexing_status": version.indexing_status,
            "approval_event_id": approval_event_id,
        }
        db.commit()
        committed = True
        return response
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="Document eligibility changed or the database rejected the review",
        ) from exc
    finally:
        if not committed:
            db.rollback()


@router.get("/{scholarship_id}", response_model=AdminDetail)
def record_detail(scholarship_id: int = Path(..., gt=0), db: Session = Depends(get_db)):
    """One record with its issues, what depends on it, and its change history."""
    return _detail(db, _record(db, scholarship_id))


@router.post("/{scholarship_id}/verification", response_model=AdminDetail)
def set_verification(
    data: VerificationWrite,
    scholarship_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Records a person's verification decision. A URL alone never verifies a record."""
    item = _record(db, scholarship_id)
    if data.status == "verified":
        if not data.evidence_reviewed:
            raise HTTPException(status_code=422, detail="Confirm that you reviewed the evidence yourself")
        if data.basis != "official_source":
            raise HTTPException(status_code=422, detail="A mixed, secondary, or missing source can't verify a record")
        if not data.source_url or not data.verified_on:
            raise HTTPException(status_code=422, detail="Verifying needs the source URL and the date you checked it")
        if data.verified_on > date.today():
            raise HTTPException(status_code=422, detail="The verification date can't be in the future")
        conflicts = find_conflicts(item)
        if conflicts and not data.acknowledge_conflicts:
            raise HTTPException(status_code=409, detail=f"This record has conflicts: {'; '.join(conflicts)}")
    before = {field: getattr(item, field) for field in (
        "verification_status", "verification_basis", "official_info_url", "last_verified_date",
        "verification_notes", "last_verified",
    )}
    after = {"verification_status": data.status, "verification_basis": data.basis, "verification_notes": data.notes}
    if data.status == "verified":
        after.update(
            official_info_url=data.source_url,
            last_verified_date=data.verified_on,
            last_verified=data.verified_on.isoformat(),
        )
    changes = field_changes(before, after)
    if not changes:
        return _detail(db, item)
    update_scholarship_if_current(db, item, after)
    record_audit(db, item.id, "verification", admin, changes, data.notes)
    db.commit()
    db.refresh(item)
    return _detail(db, item)


@router.post("/{scholarship_id}/flags", response_model=AdminDetail)
def set_flag(data: FlagWrite, scholarship_id: int = Path(..., gt=0), db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Raises or clears a review flag. Verification status doesn't change."""
    item = _record(db, scholarship_id)
    flags = set(item.data_flags or [])
    was_active = data.flag in flags
    if was_active == data.active:
        return _detail(db, item)
    flags = flags | {data.flag} if data.active else flags - {data.flag}
    update_scholarship_if_current(db, item, {"data_flags": sorted(flags)})
    record_audit(db, item.id, "flag", admin, {data.flag: [was_active, data.active]}, data.note)
    db.commit()
    db.refresh(item)
    return _detail(db, item)


@router.post("/{scholarship_id}/source-check", response_model=AdminDetail)
def check_sources(scholarship_id: int = Path(..., gt=0), db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Requests this record's source links now. The result is advice and verification doesn't change."""
    item = _record(db, scholarship_id)
    additional_urls = item.additional_source_urls or []
    if not isinstance(additional_urls, (list, tuple)):
        additional_urls = [additional_urls]
    configured_urls = list(dict.fromkeys(
        url for url in (
            [getattr(item, field) for field in SOURCE_FIELDS] + list(additional_urls)
        )
        if isinstance(url, str) and url
    ))
    existing_checks = [
        check for check in (item.source_checks or [])
        if isinstance(check, dict)
    ]
    checks_by_key = {}
    checked_document_ids = []
    for check in existing_checks:
        source_document_id = check.get("source_document_id")
        if isinstance(source_document_id, int) and not isinstance(source_document_id, bool):
            checks_by_key[("document", source_document_id)] = check
            checked_document_ids.append(source_document_id)
        elif isinstance(check.get("url"), str):
            checks_by_key[("url", check["url"])] = check

    def checked_at_order(url):
        check = checks_by_key.get(("url", url))
        checked_at = source_check_datetime(check)
        return checked_at or datetime.min.replace(tzinfo=timezone.utc)

    selected_urls = sorted(configured_urls, key=checked_at_order)[
        :MAX_SOURCE_CHECKS_PER_REQUEST - MAX_DOCUMENT_SOURCE_CHECKS_PER_REQUEST
    ]
    base_document_query = (
        db.query(ScholarshipSourceDocument)
        .filter(
            ScholarshipSourceDocument.scholarship_id == item.id,
            ScholarshipSourceDocument.is_active.is_(True),
        )
    )
    document_cursor = max(checked_document_ids, default=0)
    document_sources = (
        base_document_query
        .filter(ScholarshipSourceDocument.id > document_cursor)
        .order_by(ScholarshipSourceDocument.id)
        .limit(MAX_DOCUMENT_SOURCE_CHECKS_PER_REQUEST)
        .all()
    )
    if not document_sources:
        document_sources = (
            base_document_query
            .order_by(ScholarshipSourceDocument.id)
            .limit(MAX_DOCUMENT_SOURCE_CHECKS_PER_REQUEST)
            .all()
        )

    for url in selected_urls:
        checks_by_key[("url", url)] = check_url(url)
    for source in document_sources:
        check = check_url(source.source_url)
        check["source_document_id"] = source.id
        checks_by_key[("document", source.id)] = check

    item.source_checks = list(checks_by_key.values())
    checked_count = len(selected_urls) + len(document_sources)
    record_audit(
        db,
        item.id,
        "source_check",
        admin,
        note=f"{checked_count} link(s) checked",
    )
    db.commit()
    db.refresh(item)
    return _detail(db, item)


@router.post("/{scholarship_id}/archive", response_model=AdminDetail)
def archive(data: ArchiveWrite, scholarship_id: int = Path(..., gt=0), db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Takes a record out of every listing. Its ID, saved rows and internal links stay."""
    item = _record(db, scholarship_id)
    if item.archived:
        raise HTTPException(status_code=409, detail="This record is already archived")
    set_archived(db, item, admin, data.reason)
    return _detail(db, item)


@router.post("/{scholarship_id}/restore", response_model=AdminDetail)
def restore(scholarship_id: int = Path(..., gt=0), db: Session = Depends(get_db), admin=Depends(require_admin)):
    item = _record(db, scholarship_id)
    if not item.archived:
        raise HTTPException(status_code=409, detail="This record isn't archived")
    set_archived(db, item, admin, None)
    return _detail(db, item)


@router.post("/{scholarship_id}/duplicate", response_model=AdminDetail)
def set_duplicate(data: DuplicateWrite, scholarship_id: int = Path(..., gt=0), db: Session = Depends(get_db), admin=Depends(require_admin)):
    """Flags or clears a duplicate. Both records and everything linked to them stay as they are."""
    item = _record(db, scholarship_id)
    target = data.duplicate_of_id
    if target is not None:
        if target == scholarship_id:
            raise HTTPException(status_code=422, detail="A record can't be a duplicate of itself")
        if _record(db, target).duplicate_of_id is not None:
            raise HTTPException(status_code=422, detail="Point to the main record, not to another duplicate")
    old = item.duplicate_of_id
    if old == target:
        return _detail(db, item)
    update_scholarship_if_current(db, item, {"duplicate_of_id": target})
    record_audit(db, item.id, "duplicate", admin, {"duplicate_of_id": [old, target]}, data.note)
    db.commit()
    db.refresh(item)
    return _detail(db, item)
