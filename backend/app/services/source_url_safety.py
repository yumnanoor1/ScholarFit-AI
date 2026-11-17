"""Validation and redaction for scholarship document source URLs."""
import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class UnsafeSourceURL(ValueError):
    """A source URL is malformed, credential-bearing, or uses an unsupported scheme."""


_SENSITIVE_QUERY_NAMES = {
    "accesskey",
    "apikey",
    "awsaccesskeyid",
    "authorization",
    "authorizationcode",
    "auth",
    "bearer",
    "clientsecret",
    "code",
    "codeverifier",
    "credential",
    "credentials",
    "jwt",
    "hmac",
    "hash",
    "mac",
    "key",
    "password",
    "passwd",
    "privatekey",
    "secret",
    "session",
    "sessionid",
    "sig",
    "sign",
    "signature",
    "oauthcode",
}
_SENSITIVE_QUERY_COMPONENTS = {
    "auth",
    "credential",
    "credentials",
    "hash",
    "hmac",
    "key",
    "mac",
    "oauth",
    "passwd",
    "password",
    "secret",
    "session",
    "sessionid",
    "sig",
    "signing",
    "signature",
    "signed",
    "token",
}
_SENSITIVE_QUERY_SUFFIXES = (
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "credentials",
    "signature",
    "sig",
    "hmac",
    "hash",
    "mac",
)
# Bare hostnames are ambiguous with filenames, so require a common suffix, www, or a URL component.
_URL_IN_TEXT = re.compile(
    r"(?<![A-Z0-9._%+-])(?:[A-Z][A-Z0-9+.-]*://|//|"
    r"(?:javascript|data|mailto|file|tel):)[^\s<>\"'()]+"
    r"|(?<![A-Z0-9._%+@:/-])(?P<bare>"
    r"(?=www\.|(?:[A-Z0-9-]+\.)+"
    r"(?:com|org|net|edu|gov|mil|int|info|biz|io|co|uk|de|fr|eu|au|ca|nz|pk|in)"
    r"(?![A-Z0-9_-]|\.[A-Z0-9_-])|"
    r"(?:[A-Z0-9-]+\.)+(?:[A-Z]{2,63}|XN--[A-Z0-9-]{2,59})(?=[:/?#]))"
    r"(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+"
    r"(?:[A-Z]{2,63}|XN--[A-Z0-9-]{2,59})"
    r"(?![A-Z0-9_-]|\.[A-Z0-9_-])"
    r"(?::[0-9]{1,5})?(?:[/?#](?:[^\s<>\"'()]|\([^()\s<>\"']*\))*)?)",
    re.IGNORECASE,
)
_TRAILING_URL_PUNCTUATION = ".,;!"


def _normalized_query_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def _is_sensitive_query_name(name: str) -> bool:
    normalized = _normalized_query_name(name)
    components = re.findall(r"[a-z0-9]+", name.casefold())
    if (
        normalized in _SENSITIVE_QUERY_NAMES
        or any(component in _SENSITIVE_QUERY_COMPONENTS for component in components)
        or normalized.startswith(("hmac", "signed", "signature"))
        or normalized.endswith(_SENSITIVE_QUERY_SUFFIXES)
    ):
        return True

    for prefix in ("auth", "oauth", "x", "aws", "amz", "xamz", "xgoog"):
        if not normalized.startswith(prefix):
            continue
        suffix = normalized[len(prefix):]
        if (
            suffix == "sign"
            or suffix.startswith(("hmac", "signed", "signature", "key"))
            or suffix.endswith(_SENSITIVE_QUERY_SUFFIXES)
        ):
            return True
    return False


def validate_source_url(value: str) -> str:
    """Validate a stored document URL without returning or logging its contents in errors."""
    if not isinstance(value, str) or not value or any(char.isspace() or ord(char) < 32 for char in value):
        raise UnsafeSourceURL("Source URL must be a valid HTTP or HTTPS URL.")
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
        parts.port
    except (TypeError, ValueError, UnicodeError):
        raise UnsafeSourceURL("Source URL must be a valid HTTP or HTTPS URL.") from None
    if (
        parts.scheme.casefold() not in {"http", "https"}
        or not parts.netloc
        or not hostname
        or parts.username is not None
        or parts.password is not None
    ):
        raise UnsafeSourceURL("Source URL must be a valid HTTP or HTTPS URL without credentials.")
    return value


def safe_source_url(value: str) -> Optional[str]:
    """Return a displayable URL, omitting credentials, sensitive query fields, or malformed URLs."""
    try:
        validate_source_url(value)
        parts = urlsplit(value)
        query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    except (UnsafeSourceURL, TypeError, ValueError, UnicodeError):
        return None

    safe_pairs = [(key, item) for key, item in query_pairs if not _is_sensitive_query_name(key)]
    query = parts.query if len(safe_pairs) == len(query_pairs) else urlencode(safe_pairs, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def safe_source_urls_in_text(value: str) -> str:
    """Redact unsafe or sensitive URLs embedded in free text."""
    if not isinstance(value, str):
        return value

    def replace(match):
        candidate = match.group(0)
        trailing_punctuation = _TRAILING_URL_PUNCTUATION + ("?]}" if match.group("bare") else "")
        url = candidate.rstrip(trailing_punctuation)
        punctuation = candidate[len(url):]
        if match.group("bare"):
            return "[redacted URL]" + punctuation
        return (safe_source_url(url) or "[redacted invalid source URL]") + punctuation

    return _URL_IN_TEXT.sub(replace, value)
