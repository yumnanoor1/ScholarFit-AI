"""Deployment settings. In production a missing or unsafe setting stops the API from starting."""
import os
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

PRODUCTION_NAMES = ("production", "prod")
KNOWN_ENVIRONMENTS = PRODUCTION_NAMES + ("development", "dev", "test")
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "0.0.0.0")


def app_env() -> str:
    return os.getenv("APP_ENV", "development").strip().lower()


def is_production() -> bool:
    return app_env() in PRODUCTION_NAMES


def _production_problems() -> list:
    problems = []
    if len(os.getenv("SECRET_KEY", "").strip()) < 32:
        problems.append("SECRET_KEY must be at least 32 characters")

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        problems.append("DATABASE_URL must be set")
    elif "fitscholar_password" in database_url:
        problems.append("DATABASE_URL must not use the sample password")

    frontend = urlparse(os.getenv("FRONTEND_URL", "").strip())
    if frontend.scheme != "https" or not frontend.hostname or frontend.hostname in LOCAL_HOSTS:
        problems.append("FRONTEND_URL must be the site's public https address")

    if not (os.getenv("SMTP_HOST", "").strip() and os.getenv("SMTP_FROM", "").strip()):
        problems.append("SMTP_HOST and SMTP_FROM must be set so password reset emails can be sent")
    if os.getenv("SMTP_USE_TLS", "true").strip().lower() == "false":
        problems.append("SMTP_USE_TLS must stay on")
    return problems


def validate_settings() -> None:
    """Names the settings that are wrong, never their values."""
    if app_env() not in KNOWN_ENVIRONMENTS:
        # A typo such as "prodution" must not quietly run with development behaviour
        raise RuntimeError(f"APP_ENV must be one of: {', '.join(KNOWN_ENVIRONMENTS)}")
    if is_production():
        problems = _production_problems()
        if problems:
            raise RuntimeError("Unsafe production settings: " + "; ".join(problems))
