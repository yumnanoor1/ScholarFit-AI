from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, StudentProfile
from app.models.opportunity import Program
from app.routers.auth import get_current_user
from app.schemas.eligibility import EligibilityResult
from app.services.eligibility_engine import check_program_eligibility

router = APIRouter(prefix="/eligibility", tags=["Eligibility"])


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
    results.sort(key=lambda r: (not r["eligible"], len(r["missing_requirements"])))
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