from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.permissions import require_admin
from app.models.opportunity import Program, Scholarship, ScholarshipProgramLink
from app.models.user import StudentProfile, User
from app.routers.auth import get_optional_user
from app.schemas.matching import MatchOutcome, MatchResult, ScholarshipCoverageCounts, ScholarshipProgramLinkWrite
from app.schemas.opportunity import (
    ScholarshipCreate,
    ScholarshipUpdate,
    ScholarshipResponse,
    ScholarshipWriteResult,
)
from app.schemas.search import (
    BenefitFilter, ConditionFilter, DeadlineFilter, EligibilityFilter, FundingFilter, ScholarshipFilterOptions,
    ScholarshipSearchResult, ScopeFilter, SortOption, VerificationFilter,
)
from app.services.scholarship_matching import coverage_counts, evaluate_match, get_link, programs_for_scholarship
from app.services.scholarship_quality import create_record, delete_record, field_changes, record_audit, update_record, write_result
from app.services.scholarship_search import filter_options, search_scholarships

router = APIRouter(prefix="/scholarships", tags=["Scholarships"])


@router.get("/", response_model=List[ScholarshipResponse])
def list_scholarships(
    country: Optional[str] = Query(None, description="Country contains, e.g. Germany"),
    funding_type: Optional[str] = Query(None, description="e.g. Fully Funded or Partially Funded"),
    degree_level: Optional[str] = Query(None, description="e.g. Master"),
    pakistan_eligible_only: bool = Query(False, description="Only scholarships open to Pakistan"),
    include_unverified: bool = Query(False, description="Also show unverified records"),
    search: Optional[str] = Query(None, description="Search in the scholarship name"),
    skip: int = 0,
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db),
):
    """List scholarships with optional filters. Anyone can view.
    Unverified records are hidden unless include_unverified=true."""
    query = db.query(Scholarship).filter(Scholarship.archived_at.is_(None))

    if not include_unverified:
        query = query.filter(Scholarship.verification_status == "verified")
    if country:
        query = query.filter(Scholarship.country.ilike(f"%{country}%"))
    if funding_type:
        query = query.filter(Scholarship.funding_type.ilike(f"%{funding_type}%"))
    if degree_level:
        query = query.filter(Scholarship.degree_level.ilike(f"%{degree_level}%"))
    if pakistan_eligible_only:
        query = query.filter(Scholarship.pakistan_eligible.ilike("yes%"))
    if search:
        query = query.filter(Scholarship.name.ilike(f"%{search}%"))

    return query.order_by(Scholarship.name).offset(skip).limit(limit).all()


@router.get("/filter-options", response_model=ScholarshipFilterOptions)
def scholarship_filter_options(db: Session = Depends(get_db)):
    """The filter choices the data supports, with counts. Anyone can view."""
    return filter_options(db)


@router.get("/search", response_model=ScholarshipSearchResult)
def search(
    q: Optional[str] = Query(None, max_length=100, description="Words to find; all must match"),
    host_country: List[str] = Query([], description="Where the award is held"),
    nationality: Optional[str] = Query(None, max_length=80, description="Citizenship to check; separate from host country"),
    nationality_scope: List[ScopeFilter] = Query([]),
    degree: List[str] = Query([]),
    discipline: List[str] = Query([], description="A listed discipline, or all_fields"),
    academic_condition: List[ConditionFilter] = Query([]),
    funding: List[FundingFilter] = Query([]),
    benefit: List[BenefitFilter] = Query([], description="All chosen benefits must be offered"),
    deadline: List[DeadlineFilter] = Query([]),
    verification: List[VerificationFilter] = Query([], description="Verified only unless unverified is asked for"),
    program_id: Optional[int] = Query(None, gt=0),
    match: List[MatchOutcome] = Query([], description="Needs program_id"),
    eligibility: List[EligibilityFilter] = Query([], description="Needs a signed-in student"),
    sort: Optional[SortOption] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Search and filter scholarships. Anyone can browse; personal results use the signed-in student only."""
    if match and program_id is None:
        raise HTTPException(status_code=422, detail="Choose a program to filter by relationship")
    if current_user is None and (eligibility or sort == "recommendation"):
        raise HTTPException(status_code=401, detail="Log in to use your eligibility or recommendation score")
    program = None
    if program_id is not None:
        program = db.query(Program).filter(Program.id == program_id).first()
        if not program:
            raise HTTPException(status_code=404, detail="Program not found")
    profile = None
    if current_user is not None:
        profile = db.query(StudentProfile).filter(StudentProfile.user_id == current_user.id).first()
    filters = dict(q=q, host_country=host_country, nationality=nationality, nationality_scope=nationality_scope, degree=degree,
                   discipline=discipline, academic_condition=academic_condition, funding=funding, benefit=benefit, deadline=deadline,
                   verification=verification, match=match, eligibility=eligibility)
    return search_scholarships(db, filters, profile, current_user is not None, program, sort, skip, limit)


@router.get("/program-coverage", response_model=List[ScholarshipCoverageCounts])
def program_coverage(
    include_unverified: bool = Query(False, description="Also count unverified records"),
    db: Session = Depends(get_db),
):
    """How many catalog programs each scholarship may support. Anyone can view."""
    return coverage_counts(db, include_unverified=include_unverified)


@router.get("/{scholarship_id}", response_model=ScholarshipResponse)
def get_scholarship(scholarship_id: int, db: Session = Depends(get_db)):
    """Get a single scholarship by id"""
    item = db.query(Scholarship).filter(Scholarship.id == scholarship_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    return item


@router.post("/", response_model=ScholarshipWriteResult, status_code=201)
def create_scholarship(
    data: ScholarshipCreate,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Add a new scholarship (admin only). It starts unverified, whatever was sent."""
    return write_result(create_record(db, data.model_dump(), admin), [])


@router.put("/{scholarship_id}", response_model=ScholarshipWriteResult)
def update_scholarship(
    scholarship_id: int,
    data: ScholarshipUpdate,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Update only the fields that are sent (admin only). Verification has its own endpoint.
    Changing a requirement's wording without its structured values (or the reverse) flags it for review."""
    item = db.query(Scholarship).filter(Scholarship.id == scholarship_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    return write_result(item, update_record(db, item, data, admin))


@router.delete("/{scholarship_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scholarship(
    scholarship_id: int,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Permanently delete an unreferenced scholarship (admin only). Anything in use must be archived instead."""
    item = db.query(Scholarship).filter(Scholarship.id == scholarship_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    delete_record(db, item, admin)


def _pair(db: Session, scholarship_id: int, program_id: int):
    scholarship = db.query(Scholarship).filter(Scholarship.id == scholarship_id).first()
    if not scholarship:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    program = db.query(Program).filter(Program.id == program_id).first()
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")
    return scholarship, program


@router.get("/{scholarship_id}/programs", response_model=List[MatchResult])
def scholarship_programs(
    scholarship_id: int = Path(..., gt=0),
    include_not_matches: bool = Query(False, description="Also return programs that are ruled out"),
    db: Session = Depends(get_db),
):
    """Programs this scholarship may support, best evidence first. Anyone can view."""
    scholarship = db.query(Scholarship).filter(Scholarship.id == scholarship_id).first()
    if not scholarship:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    return programs_for_scholarship(db, scholarship, include_not_matches=include_not_matches)


@router.get("/{scholarship_id}/programs/{program_id}", response_model=MatchResult)
def scholarship_program_match(
    scholarship_id: int = Path(..., gt=0),
    program_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
):
    """The matching outcome for one scholarship and program, with its explanation and evidence."""
    scholarship, program = _pair(db, scholarship_id, program_id)
    return evaluate_match(scholarship, program, get_link(db, scholarship_id, program_id))


@router.put("/{scholarship_id}/programs/{program_id}", response_model=MatchResult)
def set_scholarship_program_link(
    data: ScholarshipProgramLinkWrite,
    scholarship_id: int = Path(..., gt=0),
    program_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Add or replace the relationship for this pair (admin only). A pair has at most one."""
    scholarship, program = _pair(db, scholarship_id, program_id)
    link = get_link(db, scholarship_id, program_id)
    if link is None:
        link = ScholarshipProgramLink(scholarship_id=scholarship_id, program_id=program_id)
        db.add(link)
    before = {field: getattr(link, field, None) for field in data.model_dump()}
    for field, value in data.model_dump().items():
        setattr(link, field, value)
    record_audit(db, scholarship_id, "relationship", admin, field_changes(before, data.model_dump()), f"Program {program_id}")
    db.commit()
    db.refresh(link)
    return evaluate_match(scholarship, program, link)


@router.delete("/{scholarship_id}/programs/{program_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scholarship_program_link(
    scholarship_id: int = Path(..., gt=0),
    program_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Remove the relationship for this pair (admin only). The scholarship and program stay."""
    _pair(db, scholarship_id, program_id)
    link = get_link(db, scholarship_id, program_id)
    if not link:
        raise HTTPException(status_code=404, detail="Relationship not found")
    record_audit(db, scholarship_id, "relationship_removed", admin, {"outcome": [link.outcome, None]}, f"Program {program_id}")
    db.delete(link)
    db.commit()