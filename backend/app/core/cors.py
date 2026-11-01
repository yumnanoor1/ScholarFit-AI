import os

from app.core.config import is_production

LOCAL_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def allowed_origins() -> list:
    """The site's own address. Localhost is allowed only outside production."""
    configured = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
    if is_production():
        return [configured]
    return LOCAL_ORIGINS + [configured] if configured and configured not in LOCAL_ORIGINS else list(LOCAL_ORIGINS)
