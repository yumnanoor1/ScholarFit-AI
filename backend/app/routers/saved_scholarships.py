from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.opportunity import Scholarship
from app.models.user import SavedScholarship, User
from app.core.permissions import require_complete_profile
from app.schemas.opportunity import SavedScholarshipResponse
from app.services.student_scholarship_visibility import (
    get_student_scholarship,
    get_student_scholarships,
)

router = APIRouter(prefix="/saved-scholarships", tags=["Saved Scholarships"])


def _find_saved(db: Session, user: User, scholarship_id: int) -> Optional[SavedScholarship]:
    # Every lookup is limited to the signed-in student, so another student's record is never reachable
    return (
        db.query(SavedScholarship)
        .filter(SavedScholarship.user_id == user.id, SavedScholarship.scholarship_id == scholarship_id)
        .first()
    )


@router.get("/", response_model=List[SavedScholarshipResponse])
def list_saved_scholarships(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """Your saved scholarships, oldest first."""
    saved_records = (
        db.query(SavedScholarship)
        .options(joinedload(SavedScholarship.scholarship))
        .filter(SavedScholarship.user_id == current_user.id)
        .order_by(SavedScholarship.saved_at, SavedScholarship.id)
        .all()
    )
    if not saved_records:
        return []
    visible_ids = {
        record.scholarship.id
        for record in get_student_scholarships(db)
    }
    return [
        saved for saved in saved_records
        if saved.scholarship_id in visible_ids
    ]


@router.post("/{scholarship_id}", response_model=SavedScholarshipResponse, status_code=status.HTTP_201_CREATED)
def save_scholarship(
    response: Response,
    scholarship_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """Save a scholarship. Saving one you already saved returns the existing record (200)."""
    record = get_student_scholarship(db, scholarship_id)
    if record is None:
        scholarship = db.query(Scholarship).filter(Scholarship.id == scholarship_id).first()
        if scholarship is None:
            raise HTTPException(status_code=404, detail="Scholarship not found")
        if scholarship.archived:
            raise HTTPException(status_code=409, detail="This scholarship is no longer listed")
        raise HTTPException(status_code=404, detail="Scholarship not found")
    existing = _find_saved(db, current_user, scholarship_id)
    if existing:
        response.status_code = status.HTTP_200_OK
        return existing

    saved = SavedScholarship(user_id=current_user.id, scholarship_id=scholarship_id)
    db.add(saved)
    try:
        db.commit()
    except IntegrityError:
        # Two saves at once, such as a double click or a second tab
        db.rollback()
        existing = _find_saved(db, current_user, scholarship_id)
        if not existing or get_student_scholarship(db, scholarship_id) is None:
            raise HTTPException(status_code=404, detail="Scholarship not found")
        response.status_code = status.HTTP_200_OK
        return existing
    db.refresh(saved)
    return saved


@router.delete("/{scholarship_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_saved_scholarship(
    scholarship_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_complete_profile),
):
    """Remove a scholarship from your saved list. Nothing happens if it wasn't saved."""
    saved = _find_saved(db, current_user, scholarship_id)
    if saved:
        db.delete(saved)
        db.commit()
