from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import StudentFinancialPlan, StudentProfile, User
from app.models.opportunity import Scholarship
from app.core.permissions import require_complete_profile
from app.schemas.eligibility import ProfileImprovementResult, ScholarshipEligibilityResult
from app.services.profile_improvement import build_guidance, in_preferred_countries
from app.services.scholarship_eligibility import evaluate_scholarship

router = APIRouter(prefix="/eligibility", tags=["Eligibility"])

SCHOLARSHIP_STATUS_ORDER = {"eligible": 0, "missing_information": 1, "not_evaluated": 2, "not_eligible": 3}


def _get_profile(db: Session, user: User) -> StudentProfile:
    profile = (
        db.query(StudentProfile)
        .filter(StudentProfile.user_id == user.id)
        .first()
    )
    if not profile:
        raise HTTPException(
            status_code=404,
            detail="Profile not created yet. Create one first with POST /profile/",
        )
    return profile


@router.get("/scholarships", response_model=List[ScholarshipEligibilityResult])
def check_all_scholarships(
    eligible_only: bool = Query(False, description="Only scholarships whose stated requirements you meet"),
    include_unverified: bool = Query(False, description="Also evaluate unverified records (never marked eligible)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """Check your profile against every scholarship. Same visibility rule as GET /scholarships/:
    unverified records are left out unless include_unverified=true."""
    profile = _get_profile(db, current_user)
    query = db.query(Scholarship).filter(Scholarship.archived_at.is_(None))
    if not include_unverified:
        query = query.filter(Scholarship.verification_status == "verified")
    results = [evaluate_scholarship(scholarship, profile) for scholarship in query.all()]
    if eligible_only:
        results = [r for r in results if r["eligible"]]
    results.sort(key=lambda r: (SCHOLARSHIP_STATUS_ORDER[r["status"]], r["scholarship_name"]))
    return results


@router.get("/scholarships/{scholarship_id}", response_model=ScholarshipEligibilityResult)
def check_one_scholarship(
    scholarship_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """Check your profile against one scholarship (verified or not)."""
    profile = _get_profile(db, current_user)
    scholarship = db.query(Scholarship).filter(Scholarship.id == scholarship_id).first()
    if not scholarship:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    return evaluate_scholarship(scholarship, profile)


@router.get("/improvements", response_model=ProfileImprovementResult)
def profile_improvements(
    scholarship_id: Optional[int] = Query(None, gt=0, description="Only this scholarship"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """Scholarship-focused guidance from the signed-in student's profile and eligibility results."""
    profile = _get_profile(db, current_user)
    scholarships = []
    if scholarship_id is not None:
        scholarship = db.query(Scholarship).filter(Scholarship.id == scholarship_id).first()
        if not scholarship:
            raise HTTPException(status_code=404, detail="Scholarship not found")
        scholarships = [scholarship]
        scope = {"type": "selected", "description": "Your selected opportunity"}
    else:
        all_scholarships = (
            db.query(Scholarship)
            .filter(Scholarship.verification_status == "verified", Scholarship.archived_at.is_(None))
            .order_by(Scholarship.id)
            .all()
        )
        preferred = [c.strip().lower() for c in (profile.preferred_countries or "").split(",") if c.strip()]
        scholarships = [s for s in all_scholarships if in_preferred_countries(s.country, preferred)]
        if scholarships:
            scope = {"type": "preferred_countries", "description": f"Opportunities in {', '.join(c.strip() for c in profile.preferred_countries.split(','))}"}
        else:
            scholarships = all_scholarships
            scope = {"type": "all", "description": "All verified scholarships"}

    plan = db.query(StudentFinancialPlan).filter(StudentFinancialPlan.user_id == current_user.id).first()
    has_budget = profile.budget_usd is not None or (plan is not None and plan.budget_amount is not None)
    return {
        "scope": scope,
        **build_guidance(
            profile, scholarships, has_budget=has_budget,
            include_optional=scope["type"] != "selected",
        ),
    }
