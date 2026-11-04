from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.core.permissions import require_admin
from app.database import get_db
from app.models.opportunity import Scholarship, ScholarshipAuditLog
from app.schemas.admin import (
    AdminDetail, AdminRowPage, AdminSummary, ArchiveWrite, DuplicateComparison, DuplicatePair, DuplicateWrite,
    FlagWrite, VerificationWrite,
)
from app.schemas.opportunity import ScholarshipResponse
from app.services.scholarship_quality import (
    duplicate_pairs, field_changes, find_conflicts, find_issues, record_audit, reference_counts, set_archived,
    update_scholarship_if_current,
)
from app.services.source_check import check_url

# Every route needs an admin, whatever is added here later
router = APIRouter(prefix="/admin/scholarships", tags=["Admin Scholarships"], dependencies=[Depends(require_admin)])

SOURCE_FIELDS = ("official_info_url", "official_application_url")
INCOMPLETE_CODES = {"missing_deadline", "missing_funding", "missing_eligibility", "no_structured_data"}
ATTENTION_CODES = {"conflict", "needs_review", "broken_url", "missing_official_source", "stale_verification", "never_verified",
                   "outdated_source", "broken_source", "needs_reverification"}


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
    urls = list(dict.fromkeys(filter(None, [getattr(item, field) for field in SOURCE_FIELDS] + list(item.additional_source_urls or []))))
    item.source_checks = [check_url(url) for url in urls]
    record_audit(db, item.id, "source_check", admin, note=f"{len(urls)} link(s) checked")
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
