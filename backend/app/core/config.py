"""Deployment settings. In production a missing or unsafe setting stops the API from starting."""
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

PRODUCTION_NAMES = ("production",)
KNOWN_ENVIRONMENTS = PRODUCTION_NAMES + ("development", "dev", "test")
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "0.0.0.0")
MINILM_MODEL_REVISION_ENV = "MINILM_MODEL_REVISION"
_MINILM_COMMIT_SHA = re.compile(r"[0-9a-fA-F]{40}")


def is_valid_minilm_model_revision(value: str) -> bool:
    return bool(_MINILM_COMMIT_SHA.fullmatch(value))


@dataclass(frozen=True)
class ScholarshipDiscoverySettings:
    enabled: bool
    request_timeout_seconds: int
    max_response_bytes: int
    max_extracted_chars: int
    max_pages_per_source: int
    max_retries: int
    request_delay_seconds: float
    user_agent: str
    model: str


def _discovery_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def scholarship_discovery_settings() -> ScholarshipDiscoverySettings:
    enabled_value = os.getenv("SCHOLARSHIP_DISCOVERY_ENABLED", "false").strip().lower()
    if enabled_value not in {"true", "false", "1", "0", "yes", "no"}:
        raise RuntimeError("SCHOLARSHIP_DISCOVERY_ENABLED must be a boolean")
    try:
        request_delay = float(os.getenv("SCHOLARSHIP_DISCOVERY_REQUEST_DELAY_SECONDS", "1"))
    except ValueError as exc:
        raise RuntimeError("SCHOLARSHIP_DISCOVERY_REQUEST_DELAY_SECONDS must be numeric") from exc
    if not 0 <= request_delay <= 60:
        raise RuntimeError("SCHOLARSHIP_DISCOVERY_REQUEST_DELAY_SECONDS must be between 0 and 60")

    return ScholarshipDiscoverySettings(
        enabled=enabled_value in {"true", "1", "yes"},
        request_timeout_seconds=_discovery_int("SCHOLARSHIP_DISCOVERY_REQUEST_TIMEOUT_SECONDS", 15, 1, 120),
        max_response_bytes=_discovery_int("SCHOLARSHIP_DISCOVERY_MAX_RESPONSE_BYTES", 10_000_000, 1024, 50_000_000),
        max_extracted_chars=_discovery_int("SCHOLARSHIP_DISCOVERY_MAX_EXTRACTED_CHARS", 30_000, 1000, 100_000),
        max_pages_per_source=_discovery_int("SCHOLARSHIP_DISCOVERY_MAX_PAGES_PER_SOURCE", 30, 1, 200),
        max_retries=_discovery_int("SCHOLARSHIP_DISCOVERY_MAX_RETRIES", 2, 0, 5),
        request_delay_seconds=request_delay,
        user_agent=os.getenv("SCHOLARSHIP_DISCOVERY_USER_AGENT", "FitScholarScholarshipDiscovery/1.0"),
        model=os.getenv("SCHOLARSHIP_DISCOVERY_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-2.5-flash",
    )


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

    if not os.getenv("GOOGLE_CLIENT_ID", "").strip():
        problems.append("GOOGLE_CLIENT_ID must be set so Google sign-in tokens can be verified")
    if not is_valid_minilm_model_revision(os.getenv(MINILM_MODEL_REVISION_ENV, "")):
        problems.append(
            "MINILM_MODEL_REVISION must be a pinned 40-character hexadecimal commit SHA"
        )
    return problems


def validate_settings() -> None:
    """Names the settings that are wrong, never their values."""
    configured_environment = os.getenv("APP_ENV", "").strip()
    if not configured_environment:
        raise RuntimeError("APP_ENV must be explicitly set")
    if app_env() not in KNOWN_ENVIRONMENTS:
        # A typo such as "prodution" must not quietly run with development behaviour
        raise RuntimeError(f"APP_ENV must be one of: {', '.join(KNOWN_ENVIRONMENTS)}")
    if is_production():
        problems = _production_problems()
        if problems:
            raise RuntimeError("Unsafe production settings: " + "; ".join(problems))
