from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.permissions import profile_incomplete_error, require_admin
from app.models.opportunity import Scholarship
from app.models.user import StudentProfile, User
from app.routers.auth import get_optional_user
from app.schemas.opportunity import (
    ScholarshipCreate,
    ScholarshipUpdate,
    StudentScholarshipResponse,
    ScholarshipWriteResult,
)
from app.schemas.search import (
    BenefitFilter, ConditionFilter, DeadlineFilter, EligibilityFilter, FundingFilter, ScholarshipFilterOptions,
    ScholarshipSearchResult, ScopeFilter, SortOption, VerificationFilter,
)
from app.services.profile_completion import profile_completion
from app.services.scholarship_quality import create_record, delete_record, update_record, write_result
from app.services.scholarship_search import filter_options, search_scholarships
from app.services.student_scholarship_visibility import (
    get_student_scholarship,
    get_student_scholarships,
    scholarship_response_payload,
)

router = APIRouter(prefix="/scholarships", tags=["Scholarships"])


@router.get("/", response_model=List[StudentScholarshipResponse])
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
    records = get_student_scholarships(db, include_unverified=include_unverified)
    if not records:
        return []
    query = db.query(Scholarship.id).filter(
        Scholarship.id.in_([record.scholarship.id for record in records])
    )
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

    ordered_ids = [
        row[0]
        for row in query.order_by(Scholarship.name, Scholarship.id)
        .offset(skip)
        .limit(limit)
        .all()
    ]
    records_by_id = {record.scholarship.id: record for record in records}
    return [
        scholarship_response_payload(records_by_id[scholarship_id])
        for scholarship_id in ordered_ids
    ]


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
    eligibility: List[EligibilityFilter] = Query([], description="Needs a signed-in student"),
    sort: Optional[SortOption] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Search and filter scholarships. Anyone can browse; personal results use the signed-in student only."""
    if current_user is None and (eligibility or sort == "recommendation"):
        raise HTTPException(status_code=401, detail="Log in to use your eligibility or recommendation score")
    personal = current_user is not None
    if personal:
        completion = profile_completion(db, current_user)
        if completion.required and not completion.complete:
            if eligibility or sort == "recommendation":
                raise profile_incomplete_error(completion)
            # Browsing stays open to everyone, so an unfinished profile sees what a visitor sees
            personal = False
    profile = None
    if personal:
        profile = db.query(StudentProfile).filter(StudentProfile.user_id == current_user.id).first()
    filters = dict(q=q, host_country=host_country, nationality=nationality, nationality_scope=nationality_scope, degree=degree,
                   discipline=discipline, academic_condition=academic_condition, funding=funding, benefit=benefit, deadline=deadline,
                   verification=verification, eligibility=eligibility)
    return search_scholarships(db, filters, profile, personal, sort=sort, skip=skip, limit=limit)


@router.get("/{scholarship_id}", response_model=StudentScholarshipResponse)
def get_scholarship(scholarship_id: int, db: Session = Depends(get_db)):
    """Get a single scholarship by id"""
    record = get_student_scholarship(db, scholarship_id)
    if not record:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    return scholarship_response_payload(record)


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
