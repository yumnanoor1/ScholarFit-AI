"""Deployment settings. In production a missing or unsafe setting stops the API from starting."""
import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from pathlib import Path

from dotenv import load_dotenv

# backend/.env, resolved from this file rather than the working directory.
# load_dotenv() on its own searches upward from the CWD, so starting the
# server from the repository root loaded the root .env and silently ignored
# backend/.env, which is where the discovery settings live. Neither call
# overrides a variable the real environment already defines.
BACKEND_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(BACKEND_ENV_PATH)
load_dotenv()

logger = logging.getLogger(__name__)
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
REASONING_EFFORT_LEVELS = frozenset({"low", "medium", "high"})

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
    interval_hours: int = 24
    stale_run_timeout_hours: int = 12
    groq_model: str = DEFAULT_GROQ_MODEL
    groq_fallback_enabled: bool = True
    groq_organization_id: str | None = None
    groq_fallback_organization_id: str | None = None
    groq_rpm_limit: int | None = None
    groq_fallback_rpm_limit: int | None = None
    groq_tpm_limit: int | None = 8_000
    groq_fallback_tpm_limit: int | None = 8_000
    groq_max_concurrent_requests: int = 1
    groq_rate_limit_retries: int = 3
    # 2,048 could not hold a filled record: 25 priority fields plus their
    # quotes measure well over that, so the model economised and returned
    # about 10 fields with no quotes at all.
    groq_max_completion_tokens: int = 3_000
    # Estimated tokens for one Groq request (prompt + reserved completion).
    # None disables the local token preflight.
    groq_max_request_tokens: int | None = 6_000
    # Overrides the per-model default reasoning effort for extraction.
    # None means "use the model default" (see REASONING_EFFORT_BY_MODEL).
    groq_extraction_reasoning_effort: str | None = None
    max_crawl_depth: int = 1
    # Lowered with the completion budget so one request still fits
    # GROQ_MAX_REQUEST_TOKENS. See the note on groq_max_request_tokens.
    max_provider_chunk_chars: int = 3_000
    max_linked_urls: int = 100
    max_linked_url_chars: int = 2048
    max_linked_urls_bytes: int = 16_384
    max_provider_request_bytes: int = 512_000
    min_extracted_chars: int = 80


DEFAULT_DATABASE_URL = (
    "postgresql://fitscholar_user:fitscholar_password@localhost:5432/fitscholar_db"
)


def database_url() -> str:
    """The one DATABASE_URL for the whole process, from backend/.env.

    Everything that opens a connection goes through here, so the API, the
    discovery worker and the diagnostics can never disagree about which
    database they are using.
    """
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def database_identity(url) -> dict:
    """Host, port and database name for logs. Never the user or password."""
    try:
        from sqlalchemy.engine import make_url

        parsed = make_url(url) if isinstance(url, str) else url
        return {
            "database": parsed.database or "unknown",
            "host": parsed.host or "local",
            "port": parsed.port if parsed.port is not None else 0,
        }
    except Exception:
        return {"database": "unknown", "host": "unknown", "port": 0}


def groq_model() -> str:
    return os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL).strip() or DEFAULT_GROQ_MODEL


def is_groq_fallback_enabled() -> bool:
    return _discovery_bool("GROQ_FALLBACK_ENABLED", "true")


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


def _discovery_optional_limit(name: str, default: int | None) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value == 0:
        return None
    if not 1 <= value <= 1_000_000:
        raise RuntimeError(f"{name} must be between 1 and 1000000, or 0 to disable")
    return value


MANUAL_SOURCE_IDS_ENV = "SCHOLARSHIP_DISCOVERY_MANUAL_SOURCE_IDS"
_MANUAL_SOURCE_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def manual_discovery_source_ids() -> tuple[str, ...] | None:
    """Source ids a manual run is restricted to, in order, or None when unset.

    Only the shape of the value is checked here. Whether each id is a
    controlled manual source is checked where that list lives. Messages name
    the setting and never repeat the configured value.
    """
    raw = os.getenv(MANUAL_SOURCE_IDS_ENV)
    if raw is None:
        return None
    entries = tuple(part.strip() for part in raw.split(","))
    if not all(entries):
        raise RuntimeError(
            f"{MANUAL_SOURCE_IDS_ENV} must be a non-empty comma-separated list "
            "of discovery source ids"
        )
    if any(
        not _MANUAL_SOURCE_ID_PATTERN.fullmatch(entry) for entry in entries
    ):
        raise RuntimeError(
            f"{MANUAL_SOURCE_IDS_ENV} contains an entry that is not a "
            "discovery source id"
        )
    if len(set(entries)) != len(entries):
        raise RuntimeError(
            f"{MANUAL_SOURCE_IDS_ENV} must not list the same source id twice"
        )
    return entries


def _discovery_reasoning_effort(name: str) -> str | None:
    """Validated reasoning effort, or None to use the per-model default."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    value = raw.strip().lower()
    if value not in REASONING_EFFORT_LEVELS:
        raise RuntimeError(
            f"{name} must be one of: {', '.join(sorted(REASONING_EFFORT_LEVELS))}",
        )
    return value


def _discovery_bool(name: str, default: str) -> bool:
    value = os.getenv(name, default).strip().lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise RuntimeError(f"{name} must be a boolean")
    return value in {"true", "1", "yes"}


def import_uses_browser() -> bool:
    """Whether admin URL import should read pages through headless Chromium.

    The plain HTTP path sends a bot User-Agent and a bare Accept header, which
    many official sites answer with 403. Chromium presents a real browser to
    the site and gets the page an administrator would see.

    Off by default: a browser costs memory and a process per import, and the
    plain path is enough for most sites. Set
    SCHOLARSHIP_IMPORT_USE_BROWSER=true to turn it on.
    """
    return os.getenv("SCHOLARSHIP_IMPORT_USE_BROWSER", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


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

    primary_rpm_limit = _discovery_optional_limit("GROQ_RPM_LIMIT", None)
    fallback_rpm_limit = _discovery_optional_limit(
        "GROQ_FALLBACK_RPM_LIMIT",
        primary_rpm_limit,
    )
    primary_tpm_limit = _discovery_optional_limit("GROQ_TPM_LIMIT", 8_000)
    fallback_tpm_limit = _discovery_optional_limit(
        "GROQ_FALLBACK_TPM_LIMIT",
        primary_tpm_limit,
    )

    return ScholarshipDiscoverySettings(
        enabled=enabled_value in {"true", "1", "yes"},
        request_timeout_seconds=_discovery_int("SCHOLARSHIP_DISCOVERY_REQUEST_TIMEOUT_SECONDS", 15, 1, 120),
        max_response_bytes=_discovery_int("SCHOLARSHIP_DISCOVERY_MAX_RESPONSE_BYTES", 10_000_000, 1024, 50_000_000),
        max_extracted_chars=_discovery_int("SCHOLARSHIP_DISCOVERY_MAX_EXTRACTED_CHARS", 30_000, 1000, 100_000),
        max_pages_per_source=_discovery_int("SCHOLARSHIP_DISCOVERY_MAX_PAGES_PER_SOURCE", 30, 1, 200),
        max_retries=_discovery_int("SCHOLARSHIP_DISCOVERY_MAX_RETRIES", 2, 0, 5),
        request_delay_seconds=request_delay,
        user_agent=os.getenv("SCHOLARSHIP_DISCOVERY_USER_AGENT", "FitScholarScholarshipDiscovery/1.0"),
        model=groq_model(),
        interval_hours=_discovery_int("SCHOLARSHIP_DISCOVERY_INTERVAL_HOURS", 24, 1, 8760),
        stale_run_timeout_hours=_discovery_int(
            "SCHOLARSHIP_DISCOVERY_STALE_RUN_TIMEOUT_HOURS", 12, 1, 720,
        ),
        groq_model=groq_model(),
        groq_fallback_enabled=is_groq_fallback_enabled(),
        # Key names do not prove organization ownership; distinct IDs are
        # required to separate organization-specific RPM accounting.
        groq_organization_id=os.getenv("GROQ_ORG_ID", "").strip() or None,
        groq_fallback_organization_id=(
            os.getenv("GROQ_FALLBACK_ORG_ID", "").strip() or None
        ),
        groq_rpm_limit=primary_rpm_limit,
        groq_fallback_rpm_limit=fallback_rpm_limit,
        groq_tpm_limit=primary_tpm_limit,
        groq_fallback_tpm_limit=fallback_tpm_limit,
        groq_max_concurrent_requests=_discovery_int(
            "GROQ_MAX_CONCURRENT_REQUESTS",
            1,
            1,
            32,
        ),
        groq_rate_limit_retries=_discovery_int(
            "GROQ_RATE_LIMIT_RETRIES",
            3,
            0,
            10,
        ),
        groq_max_completion_tokens=_discovery_int(
            "GROQ_MAX_COMPLETION_TOKENS",
            3_000,
            1,
            65_536,
        ),
        # The per-request ceiling. The org TPM limiter admits tpm * 0.9
        # (7,200 at the default 8,000), so raising this to 7,000 and
        # GROQ_MAX_INPUT_CHARS back to 5,000 keeps the same request count as
        # before the completion budget grew, at 6,609 worst-case tokens.
        groq_max_request_tokens=_discovery_optional_limit(
            "GROQ_MAX_REQUEST_TOKENS",
            6_000,
        ),
        groq_extraction_reasoning_effort=_discovery_reasoning_effort(
            "GROQ_EXTRACTION_REASONING_EFFORT",
        ),
        max_crawl_depth=_discovery_int(
            "SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH",
            1,
            0,
            5,
        ),
        max_provider_chunk_chars=_discovery_int(
            "GROQ_MAX_INPUT_CHARS",
            3_000,
            128,
            50_000,
        ),
        max_linked_urls=_discovery_int(
            "SCHOLARSHIP_DISCOVERY_MAX_LINKED_URLS", 100, 1, 1000,
        ),
        max_linked_url_chars=_discovery_int(
            "SCHOLARSHIP_DISCOVERY_MAX_LINKED_URL_CHARS", 2048, 64, 8192,
        ),
        max_linked_urls_bytes=_discovery_int(
            "SCHOLARSHIP_DISCOVERY_MAX_LINKED_URL_BYTES", 16_384, 256, 65_536,
        ),
        max_provider_request_bytes=_discovery_int(
            "SCHOLARSHIP_DISCOVERY_MAX_PROVIDER_REQUEST_BYTES", 512_000, 1024, 10_000_000,
        ),
        min_extracted_chars=_discovery_int(
            "SCHOLARSHIP_DISCOVERY_MIN_EXTRACTED_CHARS", 80, 1, 1_000,
        ),
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
