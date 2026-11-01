from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import StudentFinancialPlan, StudentProfile, User
from app.models.opportunity import Program, Scholarship
from app.routers.auth import get_current_user
from app.schemas.eligibility import EligibilityResult, ProfileImprovementResult, ScholarshipEligibilityResult
from app.services.eligibility_engine import check_program_eligibility
from app.services.profile_improvement import build_guidance, in_preferred_countries
from app.services.scholarship_eligibility import evaluate_scholarship

router = APIRouter(prefix="/eligibility", tags=["Eligibility"])

# Sort order: eligible first, then fixable (missing info), then unchecked, then not met
STATUS_ORDER = {"eligible": 0, "missing-information": 1, "not-evaluated": 2, "not-eligible": 3}
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


@router.get("/programs", response_model=List[EligibilityResult])
def check_all_programs(
    eligible_only: bool = Query(False, description="Show only programs you are eligible for"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check your profile against every program. Eligible programs come first."""
    profile = _get_profile(db, current_user)
    results = [
        check_program_eligibility(profile, program)
        for program in db.query(Program).all()
    ]
    if eligible_only:
        results = [r for r in results if r["eligible"]]
    results.sort(key=lambda r: (STATUS_ORDER[r["status"]], len(r["missing_requirements"]), r["program_id"]))
    return results


@router.get("/programs/{program_id}", response_model=EligibilityResult)
def check_one_program(
    program_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check your profile against one program."""
    profile = _get_profile(db, current_user)
    program = db.query(Program).filter(Program.id == program_id).first()
    if not program:
        raise HTTPException(status_code=404, detail="Program not found")
    return check_program_eligibility(profile, program)


@router.get("/scholarships", response_model=List[ScholarshipEligibilityResult])
def check_all_scholarships(
    eligible_only: bool = Query(False, description="Only scholarships whose stated requirements you meet"),
    include_unverified: bool = Query(False, description="Also evaluate unverified records (never marked eligible)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
):
    """Check your profile against one scholarship (verified or not)."""
    profile = _get_profile(db, current_user)
    scholarship = db.query(Scholarship).filter(Scholarship.id == scholarship_id).first()
    if not scholarship:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    return evaluate_scholarship(scholarship, profile)


@router.get("/improvements", response_model=ProfileImprovementResult)
def profile_improvements(
    program_id: Optional[int] = Query(None, gt=0, description="Only this program"),
    scholarship_id: Optional[int] = Query(None, gt=0, description="Only this scholarship"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Personal guidance from your own profile and eligibility results. Covers the selected opportunity,
    or else verified opportunities in your preferred countries, or else all of them."""
    profile = _get_profile(db, current_user)
    programs = []
    scholarships = []
    if program_id is not None or scholarship_id is not None:
        if program_id is not None:
            program = db.query(Program).filter(Program.id == program_id).first()
            if not program:
                raise HTTPException(status_code=404, detail="Program not found")
            programs = [program]
        if scholarship_id is not None:
            scholarship = db.query(Scholarship).filter(Scholarship.id == scholarship_id).first()
            if not scholarship:
                raise HTTPException(status_code=404, detail="Scholarship not found")
            scholarships = [scholarship]
        scope = {"type": "selected", "description": "Your selected opportunity"}
    else:
        all_programs = db.query(Program).order_by(Program.id).all()
        all_scholarships = (
            db.query(Scholarship)
            .filter(Scholarship.verification_status == "verified", Scholarship.archived_at.is_(None))
            .order_by(Scholarship.id)
            .all()
        )
        preferred = [c.strip().lower() for c in (profile.preferred_countries or "").split(",") if c.strip()]
        programs = [p for p in all_programs if in_preferred_countries(p.university.country, preferred)]
        scholarships = [s for s in all_scholarships if in_preferred_countries(s.country, preferred)]
        if programs or scholarships:
            scope = {"type": "preferred_countries", "description": f"Opportunities in {', '.join(c.strip() for c in profile.preferred_countries.split(','))}"}
        else:
            programs, scholarships = all_programs, all_scholarships
            scope = {"type": "all", "description": "All programs and verified scholarships"}

    plan = db.query(StudentFinancialPlan).filter(StudentFinancialPlan.user_id == current_user.id).first()
    has_budget = profile.budget_usd is not None or (plan is not None and plan.budget_amount is not None)
    return {"scope": scope, **build_guidance(profile, programs, scholarships, has_budget=has_budget)}
