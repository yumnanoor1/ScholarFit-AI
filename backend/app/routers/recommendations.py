from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.opportunity import Program, Scholarship
from app.models.user import StudentProfile, User
from app.core.permissions import require_complete_profile
from app.schemas.recommendation import RecommendationList, ScholarshipRecommendation
from app.services.scholarship_recommendations import recommend_for_student, recommend_one

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


def _context(db: Session, user: User, program_id: Optional[int]):
    """The signed-in student's own profile (None before one exists) and the selected program."""
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == user.id).first()
    program = None
    if program_id is not None:
        program = db.query(Program).filter(Program.id == program_id).first()
        if not program:
            raise HTTPException(status_code=404, detail="Program not found")
    return profile, program


@router.get("/scholarships", response_model=RecommendationList)
def scholarship_recommendations(
    program_id: Optional[int] = Query(None, gt=0, description="Rank for this program"),
    include_unverified: bool = Query(False, description="Also rank unverified records (always Needs Verification)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """Scholarships ranked for the signed-in student, with hard exclusions listed apart."""
    profile, program = _context(db, current_user, program_id)
    return recommend_for_student(db, profile, program, include_unverified=include_unverified)


@router.get("/scholarships/{scholarship_id}", response_model=ScholarshipRecommendation)
def scholarship_recommendation(
    scholarship_id: int = Path(..., gt=0),
    program_id: Optional[int] = Query(None, gt=0, description="Score for this program"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """The signed-in student's result for one scholarship, verified or not."""
    scholarship = db.query(Scholarship).filter(Scholarship.id == scholarship_id).first()
    if not scholarship:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    profile, program = _context(db, current_user, program_id)
    return recommend_one(db, scholarship, profile, program)
