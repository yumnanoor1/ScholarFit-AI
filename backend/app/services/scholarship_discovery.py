"""Registry-based discovery of official European Master's scholarship opportunities."""
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import ScholarshipDiscoverySettings, scholarship_discovery_settings
from app.models.scholarship_discovery import ScholarshipDiscoveryRun
from app.models.scholarship_knowledge import ScholarshipDocumentVersion, ScholarshipSourceDocument
from app.models.opportunity import Scholarship
from app.services.scholarship_discovery_extraction import (
    EXTRACTOR_VERSION,
    GeminiScholarshipExtractor,
    ScholarshipExtractionError,
)
from app.services.scholarship_discovery_fetch import (
    DiscoveryFetchError,
    FetchedPage,
    OfficialSourceFetcher,
    is_registered_http_url,
)
from app.services.scholarship_discovery_sources import DiscoverySource, SOURCES
from app.services.scholarship_quality import (
    create_discovered_record,
    find_identity_record,
    flag_discovery_proposal,
)
from app.services.source_verification import is_currently_verified
from app.services.source_url_safety import validate_source_url

logger = logging.getLogger(__name__)
SUMMARY_KEYS = (
    "sources_attempted",
    "sources_successfully_fetched",
    "sources_skipped",
    "sources_failed",
    "scholarships_discovered",
    "new_records_created",
    "existing_records_flagged_for_review",
    "duplicates_skipped",
    "invalid_or_out_of_scope_rejected",
    "rag_source_versions_prepared_pending",
    "documents_awaiting_admin_review",
    "documents_approved",
    "documents_rejected",
    "sources_waiting_for_scholarship_verification",
)


class DiscoveryDisabled(RuntimeError):
    pass


def _initial_summary() -> dict:
    return {key: 0 for key in SUMMARY_KEYS}


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
        extracted_text=page.text,
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
    candidate_urls = [(page.url, "official_information")]
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
        if not resolved_url or not is_registered_http_url(resolved_url, source.official_domain):
            logger.warning(
                "Scholarship evidence URL rejected for %s: invalid_registered_domain",
                source.source_id,
            )
            continue
        source_urls.append((resolved_url, role))

    waiting_for_scholarship_verification = not is_currently_verified(scholarship)
    for url, role in dict.fromkeys(source_urls):
        document = _add_source_document(db, scholarship.id, url, role)
        if url == page.url and not waiting_for_scholarship_verification:
            prepared, pending = _prepare_pending_version(db, scholarship, document, page)
            prepared_count += int(prepared)
            awaiting_review += int(pending)
    return prepared_count, awaiting_review, int(waiting_for_scholarship_verification)


def _evidence_note(source: DiscoverySource, page: FetchedPage) -> str:
    return f"Official discovery source: {source.name} ({page.url}); evidence was machine-extracted and requires human review."


def _persist_candidate(db: Session, source: DiscoverySource, page: FetchedPage, candidate) -> tuple:
    values = candidate.values
    item = find_identity_record(db, values["name"], values["country"])
    evidence_note = _evidence_note(source, page)
    if item is None:
        try:
            item = create_discovered_record(db, values, evidence_note, candidate.evidence, commit=False)
            status = "created"
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            item = find_identity_record(db, values["name"], values["country"])
            if item is None:
                raise
            changed = flag_discovery_proposal(db, item, values, evidence_note, candidate.evidence, commit=False)
            status = "flagged" if changed else "duplicate"
    else:
        changed = flag_discovery_proposal(db, item, values, evidence_note, candidate.evidence, commit=False)
        status = "flagged" if changed else "duplicate"
    prepared_count, pending_count, verification_wait_count = _register_evidence(
        db,
        item,
        source,
        values,
        page,
    )
    db.commit()
    db.refresh(item)
    return status, prepared_count, pending_count, verification_wait_count


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
        "country_or_region": source.country_or_region,
        "source_url": source.source_url,
        "attempted_at": _now().isoformat(),
        "status": "pending",
        "pages_fetched": 0,
        "last_success_at": previous_success,
        "error": None,
    }


def _save_run(db: Session, run: ScholarshipDiscoveryRun, summary: dict, source_results: list, status: str):
    run.summary = dict(summary)
    run.source_results = list(source_results)
    run.status = status
    run.finished_at = None if status == "running" else _now()
    db.commit()


def run_discovery(
    db: Session,
    *,
    settings: Optional[ScholarshipDiscoverySettings] = None,
    sources: Iterable[DiscoverySource] = SOURCES,
    fetcher: Optional[OfficialSourceFetcher] = None,
    extractor: Optional[GeminiScholarshipExtractor] = None,
) -> dict:
    settings = settings or scholarship_discovery_settings()
    if not settings.enabled:
        raise DiscoveryDisabled("Set SCHOLARSHIP_DISCOVERY_ENABLED=true to run discovery")
    fetcher = fetcher or OfficialSourceFetcher(settings)
    extractor = extractor or GeminiScholarshipExtractor(settings)

    run = ScholarshipDiscoveryRun(
        id=str(uuid.uuid4()),
        started_at=_now(),
        status="running",
        summary=_initial_summary(),
        source_results=[],
    )
    db.add(run)
    db.commit()
    summary = _initial_summary()
    source_results = []

    try:
        for source in sources:
            summary["sources_attempted"] += 1
            result = _source_result(source, _last_successful_fetch(db, source.source_id))
            if source.discovery_only:
                summary["sources_skipped"] += 1
                result["status"] = "skipped"
                source_results.append(result)
                _save_run(db, run, summary, source_results, "running")
                continue

            source_waiting_for_scholarship_verification = False
            try:
                pages = fetcher.crawl(source)
            except DiscoveryFetchError as exc:
                summary["sources_failed"] += 1
                result.update(status="failed", error=type(exc).__name__)
                logger.warning("Scholarship source fetch failed for %s: %s", source.source_id, type(exc).__name__)
                source_results.append(result)
                _save_run(db, run, summary, source_results, "running")
                continue

            result["pages_fetched"] = len(pages)
            result["status"] = "fetched"
            if pages:
                result["last_success_at"] = _now().isoformat()
            summary["sources_successfully_fetched"] += 1
            for page in pages:
                try:
                    candidates = extractor.extract(page, source)
                except ScholarshipExtractionError as exc:
                    summary["sources_failed"] += 1
                    result["status"] = "partial_failure"
                    result["error"] = type(exc).__name__
                    logger.warning("Scholarship page extraction failed for %s: %s", source.source_id, type(exc).__name__)
                    break
                summary["invalid_or_out_of_scope_rejected"] += extractor.last_rejected_count
                for candidate in candidates:
                    summary["scholarships_discovered"] += 1
                    try:
                        status, prepared_count, pending_count, waiting_count = _persist_candidate(
                            db, source, page, candidate,
                        )
                    except Exception:
                        db.rollback()
                        raise
                    if status == "created":
                        summary["new_records_created"] += 1
                    elif status == "flagged":
                        summary["existing_records_flagged_for_review"] += 1
                    else:
                        summary["duplicates_skipped"] += 1
                    summary["rag_source_versions_prepared_pending"] += prepared_count
                    summary["documents_awaiting_admin_review"] += pending_count
                    source_waiting_for_scholarship_verification |= bool(waiting_count)

            summary["sources_waiting_for_scholarship_verification"] += int(
                source_waiting_for_scholarship_verification,
            )
            source_results.append(result)
            _save_run(db, run, summary, source_results, "running")

    except Exception as exc:
        try:
            db.rollback()
        except Exception as rollback_exc:
            logger.error("Scholarship discovery rollback failed: %s", type(rollback_exc).__name__)
        try:
            failed_run = db.get(ScholarshipDiscoveryRun, run.id)
            if failed_run is not None:
                summary["sources_failed"] += 1
                failed_run.summary = dict(summary)
                failed_run.source_results = list(source_results)
                failed_run.status = "failed"
                failed_run.finished_at = _now()
                db.commit()
        except Exception as history_exc:
            try:
                db.rollback()
            except Exception as rollback_exc:
                logger.error("Scholarship discovery history rollback failed: %s", type(rollback_exc).__name__)
            logger.error("Scholarship discovery failure status could not be saved: %s", type(history_exc).__name__)
        logger.error("Scholarship discovery run failed: %s", type(exc).__name__)
        raise

    status = "failed" if summary["sources_failed"] else "completed"
    _save_run(db, run, summary, source_results, status)
    return {
        "run_id": run.id,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat(),
        "status": status,
        "summary": summary,
        "sources": source_results,
    }
