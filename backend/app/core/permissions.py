from fastapi import Depends, HTTPException, status

from app.models.user import User
from app.routers.auth import get_current_user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Allow only users with the admin role"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin can perform this action",
        )
    return current_user