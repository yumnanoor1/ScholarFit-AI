from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, StudentProfile
from app.schemas.user import ProfileCreate, ProfileUpdate, ProfileResponse
from app.routers.auth import get_current_user

router = APIRouter(prefix="/profile", tags=["Student Profile"])


def _check_cgpa(cgpa, scale):
    """CGPA cannot be higher than the scale"""
    if cgpa is not None and scale is not None:
        if cgpa < 0 or cgpa > scale:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"CGPA must be between 0 and {scale}",
            )


@router.post("/", response_model=ProfileResponse, status_code=201)
def create_profile(
    data: ProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create your profile (each user can have only one profile)"""
    existing = (
        db.query(StudentProfile)
        .filter(StudentProfile.user_id == current_user.id)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile already exists. Use PUT to update it",
        )

    _check_cgpa(data.cgpa, data.cgpa_scale)

    profile = StudentProfile(user_id=current_user.id, **data.model_dump())
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/", response_model=ProfileResponse)
def get_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """View your profile"""
    profile = (
        db.query(StudentProfile)
        .filter(StudentProfile.user_id == current_user.id)
        .first()
    )
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not created yet. Create one first with POST /profile/",
        )
    return profile


@router.put("/", response_model=ProfileResponse)
def update_profile(
    data: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update only the fields that are sent"""
    profile = (
        db.query(StudentProfile)
        .filter(StudentProfile.user_id == current_user.id)
        .first()
    )
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not created yet. Create one first with POST /profile/",
        )

    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(profile, field, value)

    _check_cgpa(profile.cgpa, profile.cgpa_scale)

    db.commit()
    db.refresh(profile)
    return profile