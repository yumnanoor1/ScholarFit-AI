from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import StudentProfile, User
from app.core.permissions import require_complete_profile
from app.schemas.recommendation import RecommendationList, ScholarshipRecommendation
from app.services.scholarship_recommendations import recommend_for_student, recommend_one
from app.services.student_scholarship_visibility import get_student_scholarship

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


def _profile(db: Session, user: User):
    return db.query(StudentProfile).filter(StudentProfile.user_id == user.id).first()


@router.get("/scholarships", response_model=RecommendationList)
def scholarship_recommendations(
    include_unverified: bool = Query(False, description="Also rank unverified records (always Needs Verification)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """Scholarships ranked for the signed-in student, with hard exclusions listed apart."""
    return recommend_for_student(db, _profile(db, current_user), include_unverified=include_unverified)


@router.get("/scholarships/{scholarship_id}", response_model=ScholarshipRecommendation)
def scholarship_recommendation(
    scholarship_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """The signed-in student's result for one scholarship, verified or not."""
    record = get_student_scholarship(db, scholarship_id)
    if not record:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    return recommend_one(
        db,
        record.scholarship,
        _profile(db, current_user),
        source_provenance=record.source_provenance(),
    )
