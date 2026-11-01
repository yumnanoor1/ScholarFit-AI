"""
Decides whether a student has finished their profile, from stored data only. Nothing the browser
sends can mark a profile complete: the only way through is for these columns to hold real values.
"""
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.user import StudentProfile, User

# The profile form sends this when it has no field to offer, so it never counts as an answer
PLACEHOLDER_FIELD = "general"
ACADEMIC_STATUSES = ("studying", "graduated")


def _filled(value) -> bool:
    return bool(str(value).strip()) if value is not None else False


def _valid_cgpa(profile: StudentProfile) -> bool:
    # 0 is what the profile form falls back to when no grade was entered
    return profile.cgpa is not None and profile.cgpa_scale is not None and 0 < profile.cgpa <= profile.cgpa_scale


def _has_country(profile: StudentProfile) -> bool:
    return any(country.strip() for country in (profile.preferred_countries or "").split(","))


REQUIRED_FIELDS: Tuple[Tuple[str, Callable[[StudentProfile], bool]], ...] = (
    ("Nationality", lambda profile: _filled(profile.nationality)),
    ("Current or highest degree", lambda profile: _filled(profile.degree_level)),
    ("Field of study", lambda profile: _filled(profile.field_of_study) and profile.field_of_study.strip().lower() != PLACEHOLDER_FIELD),
    ("University", lambda profile: _filled(profile.institution)),
    ("Study status", lambda profile: profile.academic_status in ACADEMIC_STATUSES),
    ("Graduation date", lambda profile: _filled(profile.graduation_date)),
    ("CGPA and grading scale", _valid_cgpa),
    ("Preferred study destination", _has_country),
)


@dataclass(frozen=True)
class ProfileCompletion:
    required: bool
    complete: bool
    percent: int
    missing: List[str]


def get_student_profile(db: Session, user: User) -> Optional[StudentProfile]:
    return db.query(StudentProfile).filter(StudentProfile.user_id == user.id).first()


def profile_completion(db: Session, user: User) -> ProfileCompletion:
    profile = get_student_profile(db, user)
    missing = [label for label, is_answered in REQUIRED_FIELDS if profile is None or not is_answered(profile)]
    if not _filled(user.full_name):
        missing.insert(0, "Full name")
    total = len(REQUIRED_FIELDS) + 1
    return ProfileCompletion(
        # Administrators run the catalogue, and don't need a student profile for that
        required=user.role != "admin",
        complete=not missing,
        percent=round((total - len(missing)) / total * 100),
        missing=missing,
    )
