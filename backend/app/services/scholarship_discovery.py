"""Registry-based discovery of official European Master's scholarship opportunities."""
import logging
import re
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.core.config import ScholarshipDiscoverySettings, scholarship_discovery_settings
from app.models.scholarship_discovery import ScholarshipDiscoveryRun
from app.models.scholarship_knowledge import ScholarshipDocumentVersion, ScholarshipSourceDocument
from app.models.opportunity import Scholarship
from app.services.scholarship_discovery_extraction import (
    EXTRACTOR_VERSION,
    GroqScholarshipExtractor,
    ScholarshipExtractionError,
)
from app.services.scholarship_discovery_budget import (
    ControlledManualSourceConfigurationError,
    DiscoveryRunBudget,
    DiscoveryRunLimitExceeded,
    controlled_manual_settings,
    controlled_manual_sources,
    diagnostic_single_source_budget,
    validate_controlled_manual_budget,
    validate_controlled_manual_run_sources,
    validate_diagnostic_single_source_budget,
)
from app.services.scholarship_discovery_database import (
    ManualDiscoveryDatabaseDeadline,
)
from app.services.scholarship_discovery_fetch import (
    DiscoveryFetchError,
    FetchedPage,
    OfficialSourceFetcher,
    resolve_trusted_source_url,
)
from app.services.scholarship_discovery_sources import DiscoverySource, SOURCES
from app.services.scholarship_quality import (
    find_possible_duplicate_records,
    find_identity_record,
)
from app.services.scholarship_discovery_review import (
    has_open_review_for_identity,
    persist_review_candidate,
)
from app.services.scholarship_discovery_publications import (
    record_publication_source_failure,
    record_publication_source_success,
)
from app.services.scholarship_discovery_scheduler import DiscoveryLockLost
from app.services.source_verification import is_currently_verified
from app.services.source_url_safety import safe_source_urls_in_text, validate_source_url

logger = logging.getLogger(__name__)
_DIAGNOSTIC_URL = re.compile(r"(?i)\b(?:https?|wss?)://[^\s<>\"']+")
_DIAGNOSTIC_SECRET = re.compile(
    r"(?i)\b(authorization|token|access[_-]?key|api[_-]?key|secret|password|"
    r"credential|signature|sig)\b\s*[:=]\s*(?:bearer\s+)?[^\s&,;]+"
)
SUMMARY_KEYS = (
    "sources_attempted",
    "sources_successfully_fetched",
    "sources_skipped",
    "sources_failed",
    "scholarships_discovered",
    "new_records_created",
    "review_candidates_queued",
    "ambiguous_duplicates_queued",
    "existing_records_flagged_for_review",
    "duplicates_skipped",
    "invalid_or_out_of_scope_rejected",
    "rag_source_versions_prepared_pending",
    "documents_awaiting_admin_review",
    "documents_approved",
    "documents_rejected",
    "sources_waiting_for_scholarship_verification",
    "linked_urls_discovered",
    "linked_url_references",
    "linked_pages_attempted",
    "linked_pages_fetched",
    "linked_pages_failed",
    "linked_pages_skipped",
    "linked_pages_skipped_safety",
    "linked_pages_skipped_relevance",
    "truncated_pages",
    "truncated_original_chars",
    "truncated_retained_chars",
    "valid_empty",
    "request_rejected",
    "candidates_accepted",
    "candidates_rejected",
    "insufficient_page_content",
    "provider_error",
    "malformed_response",
)
CRAWL_DIAGNOSTIC_KEYS = (
    "linked_urls_discovered",
    "linked_url_references",
    "linked_pages_attempted",
    "linked_pages_fetched",
    "linked_pages_failed",
    "linked_pages_skipped_safety",
    "linked_pages_skipped_relevance",
    "linked_pages_skipped",
)
EXTRACTION_DIAGNOSTIC_KEYS = (
    "valid_empty",
    "request_rejected",
    "candidates_accepted",
    "candidates_rejected",
    "insufficient_page_content",
    "provider_error",
    "malformed_response",
)


class DiscoveryDisabled(RuntimeError):
    pass


class DiagnosticSingleSourceError(ValueError):
    pass


_DIAGNOSTIC_TRIGGER_TYPE = "diagnostic_single_source"


def _initial_summary() -> dict:
    return {key: 0 for key in SUMMARY_KEYS}


def _persist_candidate(
    db,
    run_id,
    source,
    page,
    candidate,
    reason,
    conflicts=(),
    lock_check=None,
    run_budget=None,
):
    if run_budget is None:
        return persist_review_candidate(
            db,
            run_id,
            source,
            page,
            candidate,
            reason,
            conflicts,
            lock_check=lock_check,
        )

    run_budget.begin_candidate_persistence()
    persisted = False

    def mark_committed() -> None:
        nonlocal persisted
        persisted = True

    try:
        review_item, queued = persist_review_candidate(
            db,
            run_id,
            source,
            page,
            candidate,
            reason,
            conflicts,
            lock_check=lock_check,
            on_committed=mark_committed,
        )
        return review_item, queued
    finally:
        run_budget.finish_candidate_persistence(persisted)


def _close_run_resources(
    run_budget,
    extractor,
    database_deadline=None,
    fetcher=None,
) -> None:
    if database_deadline is not None:
        database_deadline.close()
    if run_budget is not None:
        run_budget.close()
    if isinstance(extractor, GroqScholarshipExtractor):
        try:
            extractor.close()
        except Exception as exc:
            logger.error(
                "Discovery provider client cleanup failed: %s",
                type(exc).__name__,
            )
    # The fetcher owns a Playwright process, a Chromium browser and its
    # context. Without this they outlive the run: on a long-lived API process
    # every run left a browser behind, and on Windows the accumulated sockets
    # and handles eventually fail with WinError 10055.
    if fetcher is not None:
        close_fetcher = getattr(fetcher, "close", None)
        if callable(close_fetcher):
            try:
                close_fetcher()
            except Exception as exc:
                logger.error(
                    "Discovery fetcher cleanup failed: %s",
                    type(exc).__name__,
                )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_url(url: str) -> str:
    validate_source_url(url)
    parts = urlsplit(url)
    host = parts.hostname.lower().rstrip(".")
    port = parts.port
    netloc = host if port is None or (parts.scheme == "https" and port == 443) or (
        parts.scheme == "http" and port == 80
    ) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(parse_qsl(parts.query, keep_blank_values=True))
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def _add_source_document(db: Session, scholarship_id: int, url: str, role: str) -> ScholarshipSourceDocument:
    normalized = _normalize_url(url)
    existing = (
        db.query(ScholarshipSourceDocument)
        .filter(
            ScholarshipSourceDocument.scholarship_id == scholarship_id,
            ScholarshipSourceDocument.normalized_url == normalized,
            ScholarshipSourceDocument.is_active.is_(True),
        )
        .first()
    )
    if existing:
        return existing
    document = ScholarshipSourceDocument(
        scholarship_id=scholarship_id,
        source_url=url,
        normalized_url=normalized,
        source_role=role,
    )
    db.add(document)
    db.flush()
    return document


def _prepare_pending_version(
    db: Session,
    scholarship: Scholarship,
    document: ScholarshipSourceDocument,
    page: FetchedPage,
) -> tuple:
    existing = (
        db.query(ScholarshipDocumentVersion)
        .filter(
            ScholarshipDocumentVersion.source_document_id == document.id,
            ScholarshipDocumentVersion.content_hash == page.content_hash,
        )
        .first()
    )
    if existing:
        return False, existing.review_status == "pending"
    if not is_currently_verified(scholarship):
        return False, False
    version = ScholarshipDocumentVersion(
        source_document_id=document.id,
        content_hash=page.content_hash,
        retrieved_at=_now(),
        mime_type=page.content_type,
        extractor_version=EXTRACTOR_VERSION,
        extracted_text=safe_source_urls_in_text(page.text),
        page_count=page.page_count,
        verification_status_snapshot=scholarship.verification_status,
        verification_basis_snapshot=scholarship.verification_basis,
        last_verified_date_snapshot=scholarship.last_verified_date,
        scholarship_record_version_snapshot=scholarship.record_version,
        review_status="pending",
        indexing_status="pending",
    )
    db.add(version)
    db.flush()
    return True, True


def _register_evidence(
    db: Session,
    scholarship: Scholarship,
    source: DiscoverySource,
    values: dict,
    page: FetchedPage,
) -> tuple:
    prepared_count = 0
    awaiting_review = 0
    safe_page_url = resolve_trusted_source_url(page.url, page.url, source)
    if safe_page_url is None:
        raise ScholarshipExtractionError("Scholarship source URL is invalid.", category="invalid_source_url")
    candidate_urls = [(safe_page_url, "official_information")]
    application_url = values.get("official_application_url")
    if application_url:
        candidate_urls.append((application_url, "official_application"))
    additional_urls = values.get("additional_source_urls") or []
    if not isinstance(additional_urls, (list, tuple)):
        additional_urls = [additional_urls]
    candidate_urls.extend((url, "additional_official") for url in additional_urls)

    source_urls = []
    for url, role in candidate_urls:
        try:
            resolved_url = (
                urljoin(page.url, url.strip())
                if isinstance(url, str) and url.strip()
                else None
            )
        except (TypeError, ValueError):
            resolved_url = None
        resolved_url = (
            resolve_trusted_source_url(page.url, resolved_url, source)
            if resolved_url
            else None
        )
        if not resolved_url:
            logger.warning(
                "Scholarship evidence URL rejected for %s: invalid_trusted_domain",
                source.source_id,
            )
            continue
        source_urls.append((resolved_url, role))

    waiting_for_scholarship_verification = not is_currently_verified(scholarship)
    for url, role in dict.fromkeys(source_urls):
        document = _add_source_document(db, scholarship.id, url, role)
        if url == safe_page_url and not waiting_for_scholarship_verification:
            prepared, pending = _prepare_pending_version(db, scholarship, document, page)
            prepared_count += int(prepared)
            awaiting_review += int(pending)
    return prepared_count, awaiting_review, int(waiting_for_scholarship_verification)


def prepare_review_evidence(db: Session, scholarship: Scholarship, item, values: dict) -> None:
    sources_by_id = {source.source_id: source for source in SOURCES}
    for entry in item.evidence_excerpts or []:
        if not isinstance(entry, dict):
            continue
        snapshot = entry.get("_rag_page_snapshot")
        source_id = entry.get("source_id")
        source = sources_by_id.get(source_id)
        if source is None:
            logger.warning(
                "Deferred discovery evidence skipped for review item %s: source is no longer registered",
                item.id,
            )
            continue
        if source.source_classification == "trusted_listing":
            continue
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("text"), str):
            logger.warning(
                "Deferred discovery evidence unavailable for review item %s: page snapshot is missing",
                item.id,
            )
            continue
        page = FetchedPage(
            url=entry.get("source_url") or item.source_url,
            content_type=snapshot.get("content_type") or "text/html",
            text=snapshot["text"],
            links=(),
            content_hash=entry.get("content_hash") or "",
            page_count=entry.get("page_count"),
        )
        _register_evidence(db, scholarship, source, values, page)


def _existing_record_conflicts(item, candidate, source, page):
    source_classification = (
        "official_provider"
        if item.verification_status == "verified" and item.verification_basis == "official_source"
        else "existing_record"
    )
    existing_source = {
        "source_id": "existing-scholarship-record",
        "source_name": item.provider or "Existing scholarship record",
        "source_classification": source_classification,
        "source_url": item.official_info_url or item.official_url,
    }
    discovery_source = {
        "source_id": source.source_id,
        "source_name": source.name,
        "source_classification": source.source_classification,
        "source_url": resolve_trusted_source_url(page.url, page.url, source),
    }
    excluded = {"source_name", "official_info_url", "official_application_url", "additional_source_urls"}
    conflicts = []
    for field, incoming in candidate.values.items():
        if field in excluded or incoming in (None, ""):
            continue
        current = getattr(item, field, None)
        if current != incoming:
            conflicts.append({
                "field": field,
                "values": [
                    {"value": current, **existing_source},
                    {"value": incoming, **discovery_source},
                ],
                "preferred_source": None,
                "preferred_value": None,
            })
    return conflicts


def _possible_duplicate_conflict(item, name, country, source, page):
    existing_source = {
        "source_id": "existing-scholarship-record",
        "source_name": item.provider or "Existing scholarship record",
        "source_classification": (
            "official_provider"
            if item.verification_status == "verified" and item.verification_basis == "official_source"
            else "existing_record"
        ),
        "source_url": item.official_info_url or item.official_url,
    }
    return {
        "field": "possible_duplicate",
        "values": [
            {
                "value": {"id": item.id, "name": item.name, "country": item.country},
                **existing_source,
            },
            {
                "value": {"name": name, "country": country},
                "source_id": source.source_id,
                "source_name": source.name,
                "source_classification": source.source_classification,
                "source_url": resolve_trusted_source_url(page.url, page.url, source),
            },
        ],
        "preferred_source": None,
        "preferred_value": None,
    }


def _last_successful_fetch(db: Session, source_id: str) -> Optional[str]:
    previous_runs = (
        db.query(ScholarshipDiscoveryRun)
        .filter(ScholarshipDiscoveryRun.status.in_(("completed", "failed")))
        .order_by(ScholarshipDiscoveryRun.started_at.desc())
        .limit(365)
        .all()
    )
    for run in previous_runs:
        for result in run.source_results or []:
            if result.get("source_id") == source_id and result.get("last_success_at"):
                return result["last_success_at"]
    return None


def _source_result(source: DiscoverySource, previous_success: Optional[str]) -> dict:
    return {
        "source_id": source.source_id,
        "source_name": source.name,
        "official_domain": source.official_domain,
        "source_category": source.category,
        "source_classification": source.source_classification,
        "trust_basis": source.trust_basis,
        "trust_reviewed": source.trust_reviewed,
        "country_or_region": source.country_or_region,
        "source_url": source.source_url,
        "attempted_at": _now().isoformat(),
        "status": "pending",
        "pages_fetched": 0,
        "crawl_diagnostics": {key: 0 for key in CRAWL_DIAGNOSTIC_KEYS},
        "extraction_diagnostics": {key: 0 for key in EXTRACTION_DIAGNOSTIC_KEYS},
        "candidate_rejection_reasons": {},
        "text_truncations": [],
        "last_success_at": previous_success,
        "error": None,
    }


def _record_crawl_diagnostics(fetcher, result: dict, summary: dict) -> None:
    stats = getattr(fetcher, "last_crawl_stats", None)
    if not isinstance(stats, dict):
        return
    for key in CRAWL_DIAGNOSTIC_KEYS:
        value = stats.get(key, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            continue
        result["crawl_diagnostics"][key] = value
        summary[key] += value


def _record_page_text_diagnostics(
    source: DiscoverySource,
    result: dict,
    summary: dict,
    page_index: int,
    page: FetchedPage,
) -> None:
    original_length = page.original_text_length
    if not isinstance(original_length, int) or isinstance(original_length, bool) or original_length < 0:
        original_length = len(page.text)
    retained_length = page.retained_text_length
    if not isinstance(retained_length, int) or isinstance(retained_length, bool) or retained_length < 0:
        retained_length = len(page.text)
    if not page.text_truncated and original_length <= retained_length:
        return
    if retained_length >= original_length:
        return
    result["text_truncations"].append({
        "source_id": source.source_id,
        "page_index": page_index,
        "original_length": original_length,
        "retained_length": retained_length,
    })
    summary["truncated_pages"] += 1
    summary["truncated_original_chars"] += original_length
    summary["truncated_retained_chars"] += retained_length


def _record_extraction_outcome(
    result: dict,
    summary: dict,
    outcome: str,
    *,
    accepted: int = 0,
    rejected: int = 0,
) -> None:
    if outcome in {
        "valid_empty",
        "request_rejected",
        "insufficient_page_content",
        "provider_error",
        "malformed_response",
    }:
        result["extraction_diagnostics"][outcome] += 1
        summary[outcome] += 1
    if accepted:
        result["extraction_diagnostics"]["candidates_accepted"] += accepted
        summary["candidates_accepted"] += accepted
    if rejected:
        result["extraction_diagnostics"]["candidates_rejected"] += rejected
        summary["candidates_rejected"] += rejected


def _record_candidate_rejection_reasons(result: dict, extractor) -> None:
    reasons = getattr(extractor, "last_rejection_reasons", ())
    if not isinstance(reasons, (list, tuple)):
        return
    counts = result["candidate_rejection_reasons"]
    for reason in reasons:
        if isinstance(reason, str) and reason:
            counts[reason] = counts.get(reason, 0) + 1


def _record_candidate_rejection_details(result: dict, extractor) -> None:
    details = getattr(extractor, "last_rejection_detail_counts", None)
    if not isinstance(details, dict):
        return
    counts = result.setdefault("candidate_rejection_details", {})
    for code, count in details.items():
        if (
            isinstance(code, str)
            and re.fullmatch(r"[a-z_]{1,40}(?::[a-z_]{1,40})?", code)
            and isinstance(count, int)
            and not isinstance(count, bool)
            and count > 0
        ):
            counts[code] = counts.get(code, 0) + count


# An extraction failure in one of these categories will repeat on every later
# page of the source, so the source stops; any other page failure moves on.
_STOP_SOURCE_EXTRACTION_CATEGORIES = frozenset({
    "authentication_error",
    "invalid_source_url",
    "missing_api_key",
    "model_unavailable",
    "permission_error",
    "quota_error",
    "quota_exhausted",
})


def _record_provider_attempt_diagnostics(result: dict, extractor) -> None:
    diagnostics = getattr(extractor, "last_provider_diagnostics", None)
    if not isinstance(diagnostics, dict):
        return
    result["provider_attempt_diagnostics"] = diagnostics
    if diagnostics.get("processing_stopped_after_failed_page") is True:
        result["processing_stopped_after_failed_page"] = True


def _save_run(
    db: Session,
    run: ScholarshipDiscoveryRun,
    summary: dict,
    source_results: list,
    status: str,
    lock_check=None,
):
    if lock_check is not None:
        lock_check()
    run.summary = dict(summary)
    run.source_results = list(source_results)
    run.status = status
    run.finished_at = None if status == "running" else _now()
    db.commit()


def _sanitize_discovery_error(exc: Exception) -> str:
    message = _DIAGNOSTIC_URL.sub("<redacted URL>", str(exc))
    return _DIAGNOSTIC_SECRET.sub(r"\1=<redacted>", message)


def _safe_log_label(value) -> str:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value):
        return value
    return "unavailable"


def _safe_log_status(value):
    if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
        return value
    return None


def _prepin_discovery_source_hostnames(fetcher, sources) -> None:
    prepin = getattr(fetcher, "prepin_hostnames", None)
    if not callable(prepin) or getattr(fetcher, "chromium_enabled", True) is False:
        return
    hostnames = set()
    for source in sources:
        trust_basis = getattr(source, "trust_basis", None)
        if (
            getattr(source, "crawl_enabled", False) is not True
            or getattr(source, "trust_reviewed", False) is not True
            or not isinstance(trust_basis, str)
            or not trust_basis.strip()
            or getattr(source, "discovery_only", False) is not False
        ):
            continue
        source_url = getattr(source, "source_url", None)
        if not isinstance(source_url, str) or not source_url.strip():
            continue
        try:
            hostname = urlsplit(source_url).hostname
        except (TypeError, ValueError, UnicodeError):
            continue
        if hostname:
            hostnames.add(hostname)
    if hostnames:
        prepin(sorted(hostnames))


# A source needs time to fetch its pages and run extraction. Starting one with
# less than this left guarantees being cut off mid-source, which is how a run
# ends as a crash instead of a partial success.
MIN_SECONDS_TO_START_A_SOURCE = 60.0


def _time_for_another_source(run_budget, sources_started: int) -> bool:
    """Is there time to start another source, or should the run stop cleanly?

    The first source always runs. A budget shorter than the threshold would
    otherwise finish without attempting anything, which is worse than being
    cut off: the run would do no work at all.
    """
    if sources_started == 0:
        return True
    remaining = getattr(run_budget, "remaining_seconds", None)
    if not callable(remaining):
        return True
    try:
        seconds = remaining()
    except Exception:
        return False
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        return True
    return seconds >= MIN_SECONDS_TO_START_A_SOURCE


def _connection_pool_counts(db) -> dict:
    """Checked-out and idle pool connections, if the pool reports them.

    Cheap: both are counters the pool already keeps. A NullPool (the manual
    run's own engine) reports nothing, hence the empty dict. To check from
    outside the process on Windows:

        netstat -ano | findstr :5432
        netstat -ano | find /c "ESTABLISHED"
    """
    try:
        pool = db.get_bind().engine.pool
        return {
            "checked_out": int(pool.checkedout()),
            "idle": int(pool.checkedin()),
        }
    except Exception:
        return {}


def _database_identity(db) -> dict:
    """Host, port and database name of the session's own connection.

    Logged at run start so a run writing to an unexpected database is obvious
    instead of looking like lost data. Never the user or password.
    """
    from app.core.config import database_identity

    try:
        return database_identity(db.get_bind().url)
    except Exception:
        return {"database": "unknown", "host": "unknown", "port": 0}


def _save_failure_status(db, run_id, summary, source_results, status) -> bool:
    """Write the run's final status through a session of its own.

    The run's session has just been rolled back, so its ORM objects are
    expired and some refer to rows the rollback discarded. Touching them
    raises ObjectDeletedError and the status is lost, which is how a run ends
    with no record of why. A fresh session reloads the row by id instead.
    """
    try:
        bind = db.get_bind()
    except Exception:
        return False
    if bind is None:
        return False
    session = Session(bind=bind)
    try:
        row = session.get(ScholarshipDiscoveryRun, run_id)
        if row is None:
            return False
        row.summary = dict(summary)
        row.source_results = list(source_results)
        row.status = status
        row.finished_at = _now()
        session.commit()
        return True
    except Exception as exc:
        logger.error(
            "Scholarship discovery failure status could not be saved in a "
            "fresh session: %s",
            type(exc).__name__,
        )
        try:
            session.rollback()
        except Exception:
            pass
        return False
    finally:
        try:
            session.close()
        except Exception:
            pass


def run_discovery(
    db: Session,
    *,
    settings: Optional[ScholarshipDiscoverySettings] = None,
    sources: Optional[Iterable[DiscoverySource]] = None,
    fetcher: Optional[OfficialSourceFetcher] = None,
    extractor: Optional[GroqScholarshipExtractor] = None,
    trigger_type: str = "manual",
    scheduled_for: Optional[datetime] = None,
    lock_guard=None,
    run_id: Optional[str] = None,
    on_run_started: Optional[Callable[[str], None]] = None,
    on_stage: Optional[Callable[[str], None]] = None,
    run_budget: Optional[DiscoveryRunBudget] = None,
    database_deadline: Optional[ManualDiscoveryDatabaseDeadline] = None,
    diagnostic_only: bool = False,
) -> dict:
    settings = settings or scholarship_discovery_settings()
    owns_database_deadline = False
    if diagnostic_only:
        if trigger_type != _DIAGNOSTIC_TRIGGER_TYPE:
            raise DiagnosticSingleSourceError(
                "Diagnostic-only runs require the diagnostic trigger type"
            )
        selected_sources = tuple(sources) if sources is not None else ()
        if (
            len(selected_sources) != 1
            or selected_sources[0] not in SOURCES
            or selected_sources[0].crawl_enabled is not True
            or selected_sources[0].trust_reviewed is not True
            or not isinstance(selected_sources[0].trust_basis, str)
            or not selected_sources[0].trust_basis.strip()
            or selected_sources[0].discovery_only is not False
        ):
            raise DiagnosticSingleSourceError(
                "Diagnostic-only runs require exactly one registered, trusted crawl source"
            )
        sources = selected_sources
        if not isinstance(settings, ScholarshipDiscoverySettings):
            raise DiagnosticSingleSourceError(
                "Diagnostic discovery settings are invalid"
            )
        try:
            settings = controlled_manual_settings(settings)
        except (AttributeError, TypeError, ValueError) as exc:
            raise DiagnosticSingleSourceError(
                "Diagnostic discovery settings are invalid"
            ) from exc
        if run_budget is None:
            run_budget = diagnostic_single_source_budget()
        try:
            validate_diagnostic_single_source_budget(run_budget)
        except ControlledManualSourceConfigurationError as exc:
            if isinstance(run_budget, DiscoveryRunBudget):
                _close_run_resources(run_budget, None)
            raise DiagnosticSingleSourceError(
                "Diagnostic run budget is invalid"
            ) from exc
        try:
            run_budget.start()
        except RuntimeError as exc:
            _close_run_resources(run_budget, None)
            raise DiagnosticSingleSourceError(
                "Diagnostic run budget is invalid"
            ) from exc
        if database_deadline is not None:
            try:
                database_deadline.attach_session(db)
            except Exception:
                _close_run_resources(run_budget, None)
                raise
    elif trigger_type == _DIAGNOSTIC_TRIGGER_TYPE:
        raise DiagnosticSingleSourceError(
            "The diagnostic trigger requires diagnostic_only=True"
        )
    elif trigger_type == "manual":
        sources = validate_controlled_manual_run_sources(
            controlled_manual_sources() if sources is None else sources,
        )
        settings = controlled_manual_settings(settings)
        if run_budget is None:
            run_budget = DiscoveryRunBudget()
        try:
            validate_controlled_manual_budget(run_budget)
            run_budget.start()
            if database_deadline is None:
                database_deadline = ManualDiscoveryDatabaseDeadline.for_session(
                    db,
                    run_budget,
                )
                owns_database_deadline = True
            database_deadline.attach_session(db)
        except Exception:
            _close_run_resources(
                run_budget,
                None,
                database_deadline if owns_database_deadline else None,
            )
            raise
    else:
        if run_budget is not None or database_deadline is not None:
            raise ControlledManualSourceConfigurationError
        if sources is None:
            sources = SOURCES
    sources = tuple(sources)
    if not settings.enabled and trigger_type != "manual" and not diagnostic_only:
        raise DiscoveryDisabled("Set SCHOLARSHIP_DISCOVERY_ENABLED=true to run discovery")
    lock_check = None
    if lock_guard is not None:
        def verify_lock_ownership():
            try:
                owns_lock = lock_guard.check(db)
            except DiscoveryLockLost:
                raise
            except Exception as exc:
                raise DiscoveryLockLost(
                    "Could not confirm discovery advisory-lock ownership"
                ) from exc
            if owns_lock is not True:
                raise DiscoveryLockLost("Discovery advisory-lock ownership was lost")

        lock_check = verify_lock_ownership
    owns_fetcher = fetcher is None
    fetcher = fetcher or OfficialSourceFetcher(
        settings,
        lock_check=lock_check,
        run_budget=run_budget,
        max_crawl_depth=getattr(settings, "max_crawl_depth", None),
    )
    if lock_check is not None and isinstance(fetcher, OfficialSourceFetcher):
        fetcher.lock_check = lock_check
    if isinstance(fetcher, OfficialSourceFetcher):
        fetcher.run_budget = run_budget
    if extractor is None:
        extractor = GroqScholarshipExtractor(settings, run_budget=run_budget)
    elif isinstance(extractor, GroqScholarshipExtractor):
        extractor.run_budget = run_budget
    if lock_check is not None:
        lock_check()

    run = ScholarshipDiscoveryRun(
        id=run_id or str(uuid.uuid4()),
        started_at=_now(),
        trigger_type="manual" if diagnostic_only else trigger_type,
        scheduled_for=scheduled_for,
        status="running",
        summary={
            **_initial_summary(),
            **(
                {
                    "diagnostic_only": True,
                    "diagnostic_trigger_type": trigger_type,
                    "diagnostic_source_id": sources[0].source_id,
                }
                if diagnostic_only
                else {}
            ),
            **(
                {"resource_budget": run_budget.snapshot()}
                if run_budget is not None
                else {}
            ),
        },
        source_results=[],
    )
    try:
        db.add(run)
        if lock_check is not None:
            lock_check()
        db.commit()
    except Exception:
        _close_run_resources(
            run_budget,
            extractor,
            database_deadline if owns_database_deadline else None,
            fetcher if owns_fetcher else None,
        )
        raise
    if on_run_started is not None:
        try:
            on_run_started(run.id)
        except Exception as exc:
            logger.error("Discovery run-start notification failed: %s", type(exc).__name__)
    summary = _initial_summary()
    if diagnostic_only:
        summary.update(
            diagnostic_only=True,
            diagnostic_trigger_type=trigger_type,
            diagnostic_source_id=sources[0].source_id,
        )
    source_results = []
    current_source_result = None
    diagnostic_candidates_seen = 0

    stopped_early_reason = None
    sources_not_reached = []
    try:
        identity = _database_identity(db)
        logger.info(
            "Scholarship discovery writing to: database=%s host=%s port=%s",
            identity["database"],
            identity["host"],
            identity["port"],
        )
        logger.info(
            "Scholarship discovery sources selected: trigger_type=%s count=%d "
            "source_ids=%s",
            _safe_log_label(trigger_type),
            len(sources),
            ",".join(_safe_log_label(item.source_id) for item in sources),
        )
        _prepin_discovery_source_hostnames(fetcher, sources)
        for source_index, source in enumerate(sources):
            current_source_result = None
            if run_budget is not None and not _time_for_another_source(
                run_budget, source_index,
            ):
                # Stop between sources instead of being cut off inside one.
                # Everything already committed stays; the rest is reported.
                stopped_early_reason = "duration_seconds"
                sources_not_reached = [
                    item.source_id for item in sources[source_index:]
                ]
                logger.info(
                    "Scholarship discovery stopping before a new source: "
                    "reason=time_limit sources_not_reached=%d",
                    len(sources_not_reached),
                )
                break
            if run_budget is not None:
                run_budget.start_source(source.source_id)
            if on_stage is not None:
                try:
                    on_stage(f"source:{source.source_id}")
                except Exception as exc:
                    logger.error("Discovery stage notification failed: %s", type(exc).__name__)
            if lock_check is not None:
                lock_check()
            summary["sources_attempted"] += 1
            result = _source_result(source, _last_successful_fetch(db, source.source_id))
            current_source_result = result
            if not (source.trust_reviewed and source.trust_basis):
                summary["sources_skipped"] += 1
                result["status"] = "trust_review_required"
                source_results.append(result)
                _save_run(db, run, summary, source_results, "running", lock_check)
                continue
            if not source.crawl_enabled:
                summary["sources_skipped"] += 1
                result["status"] = "skipped"
                source_results.append(result)
                _save_run(db, run, summary, source_results, "running", lock_check)
                continue
            if source.discovery_only:
                summary["sources_skipped"] += 1
                result["status"] = "skipped"
                source_results.append(result)
                _save_run(db, run, summary, source_results, "running", lock_check)
                continue

            try:
                pages = fetcher.crawl(source)
                if lock_check is not None:
                    lock_check()
            except DiscoveryFetchError as exc:
                _record_crawl_diagnostics(fetcher, result, summary)
                if lock_check is not None:
                    lock_check()
                if exc.stage is None:
                    exc.stage = "root_fetch"
                if exc.page_stage is None:
                    exc.page_stage = "root_fetch"
                if not diagnostic_only:
                    record_publication_source_failure(db, source.source_id)
                summary["sources_failed"] += 1
                result.update(
                    status="failed",
                    error=type(exc).__name__,
                    error_category=exc.category,
                    failure_stage=exc.stage,
                    page_stage=exc.page_stage,
                )
                if exc.status_code is not None:
                    result["http_status"] = exc.status_code
                if exc.attempt_count is not None:
                    result["attempt_count"] = exc.attempt_count
                if exc.attempt_limit is not None:
                    result["attempt_limit"] = exc.attempt_limit
                if exc.immediate_cause_type is not None:
                    result["cause_type"] = exc.immediate_cause_type
                if exc.cause_category is not None:
                    result["cause_category"] = exc.cause_category
                logger.warning(
                    "Scholarship source fetch failed: source_id=%s stage=%s page_stage=%s "
                    "category=%s cause_category=%s http_status=%s attempt_count=%s "
                    "attempt_limit=%s cause_type=%s",
                    source.source_id,
                    exc.stage,
                    exc.page_stage,
                    exc.category,
                    exc.cause_category,
                    exc.status_code,
                    exc.attempt_count,
                    exc.attempt_limit,
                    exc.immediate_cause_type,
                )
                source_results.append(result)
                current_source_result = None
                _save_run(db, run, summary, source_results, "running", lock_check)
                continue

            _record_crawl_diagnostics(fetcher, result, summary)
            result["pages_fetched"] = len(pages)
            result["status"] = "fetched"
            if pages:
                result["last_success_at"] = _now().isoformat()
            summary["sources_successfully_fetched"] += 1
            source_waiting_for_scholarship_verification = False
            source_extraction_failed = False
            pages_extracted = 0
            pages_failed = 0
            for page_index, page in enumerate(pages, start=1):
                if lock_check is not None:
                    lock_check()
                _record_page_text_diagnostics(
                    source,
                    result,
                    summary,
                    page_index,
                    page,
                )
                safe_page_url = resolve_trusted_source_url(page.url, page.url, source)
                if safe_page_url is None:
                    raise ScholarshipExtractionError(
                        "Scholarship source URL is invalid.",
                        category="invalid_source_url",
                    )
                if getattr(page, "insufficient_content", False) or not page.text.strip():
                    # Nothing was sent to the provider, so the fetch itself is
                    # the success being recorded, as before.
                    if not diagnostic_only:
                        record_publication_source_success(
                            db,
                            source.source_id,
                            safe_page_url,
                            page.content_hash,
                        )
                    _record_extraction_outcome(
                        result,
                        summary,
                        "insufficient_page_content",
                    )
                    logger.info(
                        "Scholarship page extraction skipped: source_id=%s "
                        "category=insufficient_page_content text_chars=%s minimum_chars=%s",
                        source.source_id,
                        len(page.text),
                        settings.min_extracted_chars,
                    )
                    continue
                try:
                    candidates = extractor.extract(page, source)
                    _record_provider_attempt_diagnostics(result, extractor)
                    if lock_check is not None:
                        lock_check()
                    _record_candidate_rejection_reasons(result, extractor)
                    _record_candidate_rejection_details(result, extractor)
                except ScholarshipExtractionError as exc:
                    _record_provider_attempt_diagnostics(result, extractor)
                    outcome = (
                        "request_rejected"
                        if exc.is_request_preflight_rejection
                        else "malformed_response"
                        if exc.category == "malformed_response"
                        else "insufficient_page_content"
                        if exc.category == "insufficient_page_content"
                        else "provider_error"
                    )
                    _record_extraction_outcome(result, summary, outcome)
                    _record_candidate_rejection_details(result, extractor)
                    pages_failed += 1
                    if not source_extraction_failed:
                        # Count the source once, however many of its pages fail.
                        summary["sources_failed"] += 1
                        source_extraction_failed = True
                        result["error"] = exc.category
                        if exc.http_status is not None:
                            result["http_status"] = exc.http_status
                    result["status"] = "partial_failure"
                    result.setdefault("page_failures", []).append({
                        "page_index": page_index,
                        "category": exc.category,
                        "http_status": exc.http_status,
                    })
                    logger.warning(
                        "Scholarship page extraction failed for %s: page_index=%s "
                        "category=%s http_status=%s",
                        source.source_id,
                        page_index,
                        exc.category,
                        exc.http_status,
                    )
                    if exc.category in _STOP_SOURCE_EXTRACTION_CATEGORIES:
                        result["processing_stopped_after_failed_page"] = True
                        break
                    continue
                pages_extracted += 1
                # Recorded only once the page was actually extracted, so a
                # failed extraction is never reported as a fresh success.
                if not diagnostic_only:
                    record_publication_source_success(
                        db,
                        source.source_id,
                        safe_page_url,
                        page.content_hash,
                    )
                rejected_count = getattr(extractor, "last_rejected_count", 0)
                if not isinstance(rejected_count, int) or isinstance(rejected_count, bool) or rejected_count < 0:
                    rejected_count = 0
                accepted_count = len(candidates)
                if accepted_count:
                    outcome = "candidates_accepted"
                elif rejected_count:
                    outcome = "candidates_rejected"
                else:
                    outcome = "valid_empty"
                _record_extraction_outcome(
                    result,
                    summary,
                    outcome,
                    accepted=accepted_count,
                    rejected=rejected_count,
                )
                summary["invalid_or_out_of_scope_rejected"] += rejected_count
                if diagnostic_only:
                    diagnostic_candidates_seen += accepted_count
                    if diagnostic_candidates_seen > run_budget.max_candidates:
                        raise DiscoveryRunLimitExceeded(
                            "candidates",
                            run_budget.max_candidates,
                        )
                    summary["scholarships_discovered"] += accepted_count
                    continue
                for candidate in candidates:
                    if run_budget is not None:
                        run_budget.ensure_candidate_capacity()
                    if lock_check is not None:
                        lock_check()
                    summary["scholarships_discovered"] += 1
                    try:
                        values = candidate.values
                        name = values.get("name")
                        country = values.get("country")
                        existing = (
                            find_identity_record(db, name, country)
                            if isinstance(name, str) and name.strip()
                            and isinstance(country, str) and country.strip()
                            else None
                        )
                        open_review = has_open_review_for_identity(db, name, country)
                        if existing is not None:
                            source_waiting_for_scholarship_verification |= not is_currently_verified(existing)
                            field_conflicts = _existing_record_conflicts(
                                existing,
                                candidate,
                                source,
                                page,
                            )
                            conflicts = [
                                *field_conflicts,
                                _possible_duplicate_conflict(
                                    existing,
                                    name,
                                    country,
                                    source,
                                    page,
                                ),
                            ]
                            reason = (
                                "conflicting_existing_scholarship"
                                if field_conflicts
                                else "existing_scholarship_match"
                            )
                            _, queued = _persist_candidate(
                                db,
                                run.id,
                                source,
                                page,
                                candidate,
                                reason,
                                conflicts,
                                lock_check=lock_check,
                                run_budget=run_budget,
                            )
                            summary["review_candidates_queued"] += int(queued)
                        else:
                            possible_duplicates = (
                                find_possible_duplicate_records(db, name, country)
                                if isinstance(name, str) and name.strip()
                                and isinstance(country, str) and country.strip()
                                else []
                            )
                            if possible_duplicates:
                                conflicts = [
                                    _possible_duplicate_conflict(
                                        match,
                                        name,
                                        country,
                                        source,
                                        page,
                                    )
                                    for match in possible_duplicates
                                ]
                                _, queued = _persist_candidate(
                                    db,
                                    run.id,
                                    source,
                                    page,
                                    candidate,
                                    "ambiguous_duplicate",
                                    conflicts,
                                    lock_check=lock_check,
                                    run_budget=run_budget,
                                )
                                summary["review_candidates_queued"] += int(queued)
                                summary["ambiguous_duplicates_queued"] += int(queued)
                            else:
                                if source.source_classification == "trusted_listing":
                                    reason = "trusted_listing_requires_official_confirmation"
                                elif candidate.requires_review:
                                    reason = "incomplete_or_conflicting_candidate"
                                elif open_review:
                                    reason = "existing_review_candidate"
                                else:
                                    reason = "admin_review_required"
                                _, queued = _persist_candidate(
                                    db,
                                    run.id,
                                    source,
                                    page,
                                    candidate,
                                    reason,
                                    lock_check=lock_check,
                                    run_budget=run_budget,
                                )
                                summary["review_candidates_queued"] += int(queued)
                    except Exception:
                        db.rollback()
                        raise
            result["pages_extracted"] = pages_extracted
            result["pages_failed"] = pages_failed
            if pages_failed:
                result["extraction_status"] = (
                    "all_pages_failed" if not pages_extracted else "some_pages_failed"
                )
            summary["sources_waiting_for_scholarship_verification"] += int(
                source_waiting_for_scholarship_verification,
            )
            source_results.append(result)
            pool_counts = _connection_pool_counts(db)
            logger.info(
                "Scholarship discovery source finished: source_id=%s status=%s "
                "pages_extracted=%s db_connections_checked_out=%s "
                "db_connections_idle=%s",
                _safe_log_label(source.source_id),
                _safe_log_label(result.get("status")),
                result.get("pages_extracted", 0),
                pool_counts.get("checked_out", "unavailable"),
                pool_counts.get("idle", "unavailable"),
            )
            if run_budget is not None:
                run_budget.ensure_active()
            _save_run(db, run, summary, source_results, "running", lock_check)
            current_source_result = None

        if run_budget is not None and stopped_early_reason is None:
            run_budget.ensure_active()

    except Exception as exc:
        if lock_check is not None:
            try:
                with (
                    database_deadline.finalization()
                    if database_deadline is not None
                    else nullcontext()
                ):
                    lock_check()
            except DiscoveryLockLost:
                try:
                    db.rollback()
                except Exception as rollback_exc:
                    logger.error("Scholarship discovery rollback failed: %s", type(rollback_exc).__name__)
                _close_run_resources(
                    run_budget,
                    extractor,
                    database_deadline if owns_database_deadline else None,
                    fetcher if owns_fetcher else None,
                )
                raise DiscoveryLockLost(
                    "Discovery stopped because advisory-lock ownership was lost"
                ) from exc
        with (
            database_deadline.finalization()
            if database_deadline is not None
            else nullcontext()
        ):
            try:
                db.rollback()
            except Exception as rollback_exc:
                logger.error("Scholarship discovery rollback failed: %s", type(rollback_exc).__name__)
            try:
                budget_exhausted = isinstance(exc, DiscoveryRunLimitExceeded)
                if budget_exhausted:
                    summary["stop_reason"] = exc.as_dict()
                    if current_source_result is not None and current_source_result not in source_results:
                        current_source_result.update(
                            status="stopped",
                            stop_reason=exc.as_dict(),
                        )
                        source_results.append(current_source_result)
                    reached = {item.get("source_id") for item in source_results}
                    summary["sources_not_reached"] = [
                        item.source_id
                        for item in sources
                        if item.source_id not in reached
                    ]
                else:
                    summary["sources_failed"] += 1
                if run_budget is not None:
                    summary["resource_budget"] = run_budget.snapshot()
                summary["error_summary"] = (
                    "run_budget_exhausted"
                    if budget_exhausted
                    else type(exc).__name__
                )
                # A run cut off mid-source is partial, not broken. The status
                # column only allows running/completed/failed, so the outcome
                # is recorded in the summary and everything already committed
                # stays committed.
                if (
                    budget_exhausted
                    and getattr(exc, "resource", None) == "duration_seconds"
                ):
                    summary["run_outcome"] = "stopped_time_limit"
                failure_status = "failed"
                if not _save_failure_status(
                    db, run.id, summary, source_results, failure_status,
                ):
                    failed_run = db.get(ScholarshipDiscoveryRun, run.id)
                    if failed_run is not None:
                        failed_run.summary = dict(summary)
                        failed_run.source_results = list(source_results)
                        failed_run.status = failure_status
                        failed_run.finished_at = _now()
                        db.commit()
            except Exception as history_exc:
                try:
                    db.rollback()
                except Exception as rollback_exc:
                    logger.error("Scholarship discovery history rollback failed: %s", type(rollback_exc).__name__)
                logger.error("Scholarship discovery failure status could not be saved: %s", type(history_exc).__name__)
        logger.error(
            "Scholarship discovery run failed: type=%s category=%s cause_type=%s http_status=%s",
            _safe_log_label(type(exc).__name__),
            _safe_log_label(getattr(exc, "category", None)),
            _safe_log_label(getattr(exc, "cause_type", None)),
            _safe_log_status(getattr(exc, "status_code", None)),
        )
        _close_run_resources(
            run_budget,
            extractor,
            database_deadline if owns_database_deadline else None,
            fetcher if owns_fetcher else None,
        )
        raise

    if run_budget is not None:
        summary["resource_budget"] = run_budget.snapshot()
    if stopped_early_reason is not None:
        summary["stop_reason"] = {
            "code": "DISCOVERY_RUN_STOPPED_EARLY",
            "resource": stopped_early_reason,
        }
        summary["sources_not_reached"] = list(sources_not_reached)
        # The run row's status column is constrained to running/completed/
        # failed, so the partial outcome is reported in the summary. Nothing
        # failed here: the sources that ran are finished and committed.
        summary["run_outcome"] = (
            "stopped_time_limit"
            if stopped_early_reason == "duration_seconds"
            else "completed_partial"
        )
    status = "failed" if summary["sources_failed"] else "completed"
    try:
        _save_run(db, run, summary, source_results, status, lock_check)
    finally:
        _close_run_resources(
            run_budget,
            extractor,
            database_deadline if owns_database_deadline else None,
            fetcher if owns_fetcher else None,
        )
    return {
        "run_id": run.id,
        "trigger_type": trigger_type,
        "scheduled_for": run.scheduled_for.isoformat() if run.scheduled_for else None,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat(),
        "status": status,
        "summary": summary,
        "sources": source_results,
    }
