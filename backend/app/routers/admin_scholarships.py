from datetime import date, datetime, timezone
import hashlib
import logging
import math
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.permissions import require_admin
from app.database import get_db
from app.models.opportunity import Scholarship, ScholarshipAuditLog
from app.models.scholarship_knowledge import (
    EMBEDDING_DIMENSIONS,
    ScholarshipChunkEmbedding,
    ScholarshipDocumentChunk,
    ScholarshipDocumentVersion,
    ScholarshipDocumentVersionApproval,
    ScholarshipSourceDocument,
)
from app.schemas.admin import (
    AdminDetail, AdminDocumentIndexResponse, AdminDocumentIndexWrite, AdminDocumentReviewResponse,
    AdminDocumentReviewWrite, AdminDocumentVersionDetail, AdminRowPage,
    AdminSourceDocumentPage, AdminSourceDocumentSummary, AdminSummary, ArchiveWrite, DuplicateComparison,
    DuplicatePair, DuplicateWrite, FlagWrite, VerificationWrite,
)
from app.schemas.opportunity import ScholarshipResponse
from app.services.scholarship_quality import (
    duplicate_pairs, field_changes, find_conflicts, find_issues, record_audit, reference_counts, set_archived,
    update_scholarship_if_current,
)
from app.services.source_check import check_url
from app.services.source_verification import (
    document_source_issue,
    is_currently_verified,
    source_check_datetime,
)
from app.services.source_url_safety import safe_source_url, safe_source_urls_in_text
from app.services import rag_service
from app.services import scholarship_document_indexing as document_indexing

# Every route needs an admin, whatever is added here later
router = APIRouter(prefix="/admin/scholarships", tags=["Admin Scholarships"], dependencies=[Depends(require_admin)])
logger = logging.getLogger(__name__)

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
    issue: Optional[str] = Query(None, max_length=40, description="An issue code, or attention for what needs work"),
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
        if issue and not (codes & ATTENTION_CODES if issue == "attention" else issue in codes):
            continue
        rows.append({"id": row.id, "name": row.name, "provider": row.provider, "country": row.country,
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
