from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.auth import get_current_user
from app.services.profile_completion import ProfileCompletion, profile_completion

PROFILE_INCOMPLETE = "Complete your profile to use this feature."


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Allow only users with the admin role"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin can perform this action",
        )
    return current_user


def profile_incomplete_error(completion: ProfileCompletion) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "profile_incomplete", "message": PROFILE_INCOMPLETE, "missing": completion.missing},
    )


def require_complete_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    """Allow students with a finished profile. An expired sign-in stays a 401, from get_current_user."""
    completion = profile_completion(db, current_user)
    if completion.required and not completion.complete:
        raise profile_incomplete_error(completion)
    return current_user
