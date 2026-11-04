from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, StudentProfile
from app.schemas.user import ProfileCreate, ProfileStatus, ProfileUpdate, ProfileResponse
from app.routers.auth import get_current_user
from app.services.profile_completion import profile_completion

router = APIRouter(prefix="/profile", tags=["Student Profile"])


def _check_cgpa(cgpa, scale, require_scale=False):
    """CGPA cannot be higher than the scale"""
    if require_scale and cgpa is not None and scale is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CGPA scale is required when a CGPA is provided",
        )
    if cgpa is not None and scale is not None:
        if cgpa < 0 or cgpa > scale:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"CGPA must be between 0 and {scale}",
            )


def _merge_form_details(existing, updates):
    merged = dict(existing or {})
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_form_details(merged[key], value)
        else:
            merged[key] = value
    return merged


def _check_budget_fields(profile, changed_fields):
    budget_fields = {
        "budget_usd",
        "tuition_budget_amount",
        "tuition_budget_currency",
        "living_budget_amount",
        "living_budget_currency",
    }
    if not budget_fields.intersection(changed_fields):
        return
    for amount_name, currency_name in (
        ("tuition_budget_amount", "tuition_budget_currency"),
        ("living_budget_amount", "living_budget_currency"),
    ):
        amount = getattr(profile, amount_name)
        currency = getattr(profile, currency_name)
        if (amount is None) != (currency is None):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{amount_name} and {currency_name} must be provided together",
            )
    if profile.tuition_budget_currency not in (None, "USD") and profile.budget_usd is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="budget_usd can only be used for a USD tuition budget",
        )


def _sync_legacy_language_scores(profile):
    language_test = profile.language_test or {}
    test_type = language_test.get("test_type") if isinstance(language_test, dict) else None
    score = language_test.get("overall_score") if isinstance(language_test, dict) else None
    profile.ielts_score = score if test_type == "IELTS" else None
    profile.toefl_score = int(score) if test_type == "TOEFL iBT" and score is not None else None


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

    _check_cgpa(data.cgpa, data.cgpa_scale, require_scale=data.cgpa is not None)

    profile_data = data.model_dump()
    if data.language_test is not None:
        profile_data["language_test"] = data.language_test.model_dump(mode="json")
    profile = StudentProfile(user_id=current_user.id, **profile_data)
    if data.language_test is not None:
        _sync_legacy_language_scores(profile)
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


@router.get("/status", response_model=ProfileStatus)
def get_profile_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Whether your profile is finished, worked out from the stored data. Works before a profile exists."""
    return profile_completion(db, current_user)


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
    if data.language_test is not None:
        changes["language_test"] = data.language_test.model_dump(mode="json")
    for field, value in changes.items():
        if field == "form_details" and isinstance(value, dict):
            profile.form_details = _merge_form_details(profile.form_details, value)
        else:
            setattr(profile, field, value)

    if "language_test" in changes:
        _sync_legacy_language_scores(profile)
    _check_cgpa(
        profile.cgpa,
        profile.cgpa_scale,
        require_scale="cgpa" in changes and profile.cgpa is not None,
    )
    _check_budget_fields(profile, changes)

    db.commit()
    db.refresh(profile)
    return profile