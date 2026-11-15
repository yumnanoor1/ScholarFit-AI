"""Bounded fetch and extraction primitives for discovery and Admin imports."""
import email.message
import email.utils
import hashlib
import http.client
import ipaddress
import json
import logging
import os
import re
import socket
import ssl
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Tuple

import dns.exception
import dns.rdatatype
import dns.resolver

if TYPE_CHECKING:
    from app.core.config import ScholarshipDiscoverySettings
else:
    ScholarshipDiscoverySettings = Any

from app.services.scholarship_discovery_budget import (
    DiscoveryRunBudget,
    DiscoveryRunLimitExceeded,
)
from app.services.scholarship_discovery_sources import DiscoverySource
from app.services.source_url_safety import safe_source_url

logger = logging.getLogger(__name__)
DNS_TIMEOUT_SECONDS = 6
MAX_REDIRECTS = 4
MAX_RETRY_AFTER_SECONDS = 60
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}
ALLOWED_PAGE_TYPES = {"text/html", "application/xhtml+xml", "application/pdf", "application/json"}
RELEVANT_LINK_TERMS = (
    "scholarship",
    "scholarship-details",
    "scholarship_details",
    "funding",
    "award",
    "grant",
    "master",
    "study",
    "student",
    "stipendium",
    "eligibility",
    "eligible",
    "deadline",
    "application",
    "benefits",
    "requirement",
    "postgraduate",
    "post-graduate",
)
DEFAULT_MAX_CRAWL_DEPTH = 1
MAX_CRAWL_DEPTH_LIMIT = 5
# Strong signals that a linked page is itself a scholarship entry rather than
# a hub. Only the first few pages of a source are fetched, so these go first.
_STRONG_LINK_TERMS = (
    "scholarship",
    "stipendium",
    "stipend",
    "datenbank",
    "detail=",
    "funding",
    "award",
    "grant",
)
# source_id -> pattern matched against "<path>?<query> <label>". Matching links
# are queued ahead of everything else and bypass the generic relevance filter,
# because a database detail URL need not spell out a relevant term in its path.
# An official page often names the scholarship but publishes the host country,
# deadlines and benefits only in a linked call document. These links rarely
# contain a generic relevant term, so they bypass the relevance filter.
_ANNOUNCEMENT_LINK_TERMS = (
    "announcement",
    "current announcement",
    "ausschreibung",
    "call for applications",
)
# The documents that carry the fields a record is useless without: who may
# apply, what is funded, which countries, how to apply. diag_run16 showed
# list_of_countries.pdf and information_about_the_master_s_courses.pdf losing
# the page budget to a checklist and an application form, which rank the same
# as any other PDF on the official domain.
# What a record is actually missing: who may apply, what is funded, where.
_DETAIL_LINK_TERMS = (
    "eligib",
    "requirement",
    "voraussetzung",
    "list_of_countries",
    "list of countries",
    "countries",
    "laenderliste",
    "funding",
    "foerderung",
    "benefit",
    "leistung",
    "stipend",
    "allowance",
    "deadline",
    "bewerbungsfrist",
    "master",
    "courses",
    "programme information",
)
# Useful, but a blank form or an FAQ answers fewer fields than the country
# list or the funding terms, and the page budget is small.
_SECONDARY_LINK_TERMS = (
    "application",
    "bewerbung",
    "apply",
    "faq",
    "frequently_asked",
    "frequently asked",
    "checklist",
    "checkliste",
)
# Pages that exist for the website rather than for the scholarship. Ranked
# last so they never take a page budget slot from a detail document.
_TECHNICAL_LINK_TERMS = (
    "technische",
    "technical",
    "sapportal",
    "voraussetzungen/pbf",
    "accessibility",
    "barrierefrei",
    "datenschutz",
    "privacy",
    "imprint",
    "impressum",
    "cookie",
    "sitemap",
    "login",
    "newsletter",
    "presse",
    "press",
)
SOURCE_PRIORITY_LINK_PATTERNS = {
    "daad": re.compile(r"stipendium/datenbank|[?&]detail=\d+", re.IGNORECASE),
}
_BOILERPLATE_TAGS = {
    "footer",
    "header",
    "iframe",
    "nav",
    "noscript",
    "script",
    "style",
    "svg",
    "template",
}
_VOID_HTML_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_CONSENT_MARKERS = re.compile(
    r"cookie|consent|gdpr|onetrust|cookiebot|usercentrics",
    re.IGNORECASE,
)
_UTILITY_FORM_MARKERS = re.compile(
    r"search|filter|newsletter|subscribe|consent|cookie|login|sign.?in",
    re.IGNORECASE,
)


# Host + path for at most this many link decisions. In-memory only: the
# single-source diagnostic prints them, the application never logs them.
MAX_RECORDED_LINK_DECISIONS = 200


def _empty_crawl_stats() -> dict:
    return {
        "linked_urls_discovered": 0,
        "linked_url_references": 0,
        "linked_pages_attempted": 0,
        "linked_pages_fetched": 0,
        "linked_pages_failed": 0,
        "linked_pages_skipped_safety": 0,
        "linked_pages_skipped_relevance": 0,
        # Every discovered link ends in exactly one of: skipped_relevance,
        # already_queued, fetched, failed, not_fetched_page_budget. Duplicates
        # and safety rejections are counted against linked_url_references,
        # because they never become a discovered link.
        "linked_pages_skipped_duplicate": 0,
        "linked_pages_skipped_already_queued": 0,
        "linked_pages_not_fetched_page_budget": 0,
        "pages_links_not_followed_depth": 0,
        "pages_links_not_followed_content_type": 0,
        "linked_pages_skipped": 0,
        "max_pages_per_source": 0,
        "max_crawl_depth": 0,
    }


def configured_max_crawl_depth() -> int:
    """How many link hops past the root page the crawl may follow.

    Fallback for settings objects that predate the max_crawl_depth field;
    ScholarshipDiscoverySettings resolves the variable at load time.
    """
    raw = os.getenv("SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH", "").strip()
    if not raw:
        return DEFAULT_MAX_CRAWL_DEPTH
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            "SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH must be an integer",
        ) from exc
    if not 0 <= value <= MAX_CRAWL_DEPTH_LIMIT:
        raise RuntimeError(
            "SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH must be between 0 and "
            f"{MAX_CRAWL_DEPTH_LIMIT}",
        )
    return value


def _is_source_domain_pdf(source: "DiscoverySource", parts) -> bool:
    """A .pdf on the source's own registered domain."""
    if not parts.path.casefold().endswith(".pdf"):
        return False
    return is_registered_domain(
        (parts.hostname or "").casefold(),
        source.official_domain,
    )


def _link_priority(source: "DiscoverySource", parts, label: str) -> int:
    """Lower sorts first.

    0 = source-specific pattern
    1 = announcement or call document
    2 = eligibility, funding, countries, deadlines or programme detail
    3 = application form, FAQ or checklist
    4 = any other own-domain PDF
    5 = strong scholarship term
    6 = generic relevant term
    7 = a page that exists for the website, not the scholarship

    Priorities 0 to 4 bypass the generic relevance filter, because a call
    document's URL and label need not contain a relevant term.
    """
    target = f"{parts.path}?{parts.query} {label}".casefold()
    pattern = SOURCE_PRIORITY_LINK_PATTERNS.get(source.source_id)
    if pattern is not None and pattern.search(target):
        return 0
    if any(term in target for term in _ANNOUNCEMENT_LINK_TERMS):
        return 1
    if any(term in target for term in _TECHNICAL_LINK_TERMS):
        return 7
    if any(term in target for term in _DETAIL_LINK_TERMS):
        return 2
    if any(term in target for term in _SECONDARY_LINK_TERMS):
        return 3
    if _is_source_domain_pdf(source, parts):
        return 4
    if any(term in target for term in _STRONG_LINK_TERMS):
        return 5
    return 6


class DiscoveryFetchError(RuntimeError):
    def __init__(
        self,
        message,
        status_code=None,
        *,
        category=None,
        stage=None,
        page_stage=None,
        attempt_count=None,
        attempt_limit=None,
        cause_type=None,
        cause_category=None,
        source_id=None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.category = category or ("http_status" if status_code is not None else "unknown")
        self.stage = stage
        self.page_stage = page_stage
        self.attempt_count = attempt_count
        self.attempt_limit = attempt_limit
        self.cause_type = cause_type
        self.cause_category = cause_category
        self.source_id = source_id

    @property
    def immediate_cause_type(self):
        if self.cause_type is not None:
            return self.cause_type
        return type(self.__cause__).__name__ if self.__cause__ is not None else None


@dataclass(frozen=True)
class _RobotsFailureDetails:
    status_code: Optional[int]
    attempt_count: Optional[int]
    attempt_limit: Optional[int]
    cause_type: Optional[str]
    cause_category: str


def _failure_category_for_exception(exc):
    if isinstance(exc, (dns.exception.DNSException, socket.gaierror)):
        return "dns_error"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, (ConnectionError, OSError)):
        return "connection_error"
    return "unknown"


def _request_target(parts: urllib.parse.SplitResult) -> str:
    path = urllib.parse.quote(
        parts.path or "/",
        safe="/%:@!$&'()*+,;=-._~",
    )
    query = urllib.parse.quote(
        parts.query,
        safe="/?%:@!$&'()*+,;=-._~",
    )
    target = path + ("?" + query if query else "")
    return re.sub(r"%(?![0-9A-Fa-f]{2})", "%25", target)


def _retry_delay_seconds(
    attempt: int,
    retry_after: Optional[str],
    *,
    now: Optional[datetime] = None,
) -> Optional[float]:
    delay = min(2 ** attempt, 8)
    if not isinstance(retry_after, str) or not retry_after.strip():
        return delay

    value = retry_after.strip()
    if re.fullmatch(r"[0-9]+", value):
        digits = value.lstrip("0") or "0"
        if len(digits) > len(str(MAX_RETRY_AFTER_SECONDS)):
            return None
        retry_after_seconds = int(digits)
    else:
        try:
            retry_at = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return delay
        if retry_at is None:
            return delay
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        retry_after_seconds = max(
            0.0,
            (retry_at.astimezone(timezone.utc) - current_time.astimezone(timezone.utc)).total_seconds(),
        )

    if retry_after_seconds > MAX_RETRY_AFTER_SECONDS:
        return None
    return max(delay, retry_after_seconds)


def _log_fetch_failure(source_id, error, stage, page_stage=None):
    logger.warning(
        "Discovery fetch failed: source_id=%s stage=%s page_stage=%s category=%s "
        "cause_category=%s http_status=%s attempt_count=%s attempt_limit=%s cause_type=%s",
        source_id,
        stage,
        page_stage,
        error.category,
        error.cause_category,
        error.status_code,
        error.attempt_count,
        error.attempt_limit,
        error.immediate_cause_type,
    )


def _normalize_allowlisted_host(host) -> str:
    """One exact host name for a request allowlist, or ValueError.

    Wildcards are refused: an allowlist entry names a single host. This is the
    normalization the fetcher applies to `allowed_request_hosts`, named so the
    fetch diagnostic can apply the same rule to the hosts it reports.
    """
    normalized = _normalize_dns_name(host) if isinstance(host, str) else None
    if normalized is None or "*" in host:
        raise ValueError("allowed request hosts must be exact host names")
    return normalized


def _normalize_dns_name(name: str) -> Optional[str]:
    if not name:
        return None
    if name.endswith("."):
        name = name[:-1]
        if not name or name.endswith("."):
            return None
    try:
        normalized = name.encode("idna").decode("ascii").casefold()
    except UnicodeError:
        return None
    labels = normalized.split(".")
    if (
        len(normalized) > 253
        or any(
            not label
            or len(label) > 63
            or not label[0].isalnum()
            or not label[-1].isalnum()
            or any(not character.isalnum() and character != "-" for character in label)
            for label in labels
        )
    ):
        return None
    return normalized


def _address_tuple_for_public_ip(ip_text: str, port: int) -> tuple:
    try:
        ip = ipaddress.ip_address(ip_text)
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise DiscoveryFetchError(
            "Official host did not resolve to safe public addresses",
            category="dns_error",
            cause_type=type(exc).__name__,
        ) from exc
    family = socket.AF_INET if ip.version == 4 else socket.AF_INET6
    sockaddr = (
        (ip.compressed, port)
        if ip.version == 4
        else (ip.compressed, port, 0, 0)
    )
    return family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr


_DIAGNOSTIC_URL = re.compile(r"(?i)\b(?:https?|wss?)://[^\s<>\"']+")
_DIAGNOSTIC_SECRET = re.compile(
    r"(?i)\b(authorization|token|access[_-]?key|api[_-]?key|secret|password|"
    r"credential|signature|sig)\b\s*[:=]\s*(?:bearer\s+)?[^\s&,;]+"
)


def _sanitize_diagnostic_url(url: str) -> str:
    try:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname:
            return "<redacted URL>"
        host = parts.hostname.casefold()
        try:
            port = parts.port
        except ValueError:
            return "<redacted URL>"
        netloc = f"[{host}]" if ":" in host else host
        if port is not None:
            netloc = f"{netloc}:{port}"
        return urllib.parse.urlunsplit((parts.scheme.casefold(), netloc, parts.path, "", ""))
    except (TypeError, ValueError, UnicodeError):
        return "<redacted URL>"


def _sanitize_diagnostic_message(exc: BaseException) -> str:
    message = str(exc)
    message = _DIAGNOSTIC_URL.sub("<redacted URL>", message)
    return _DIAGNOSTIC_SECRET.sub(r"\1=<redacted>", message)


def is_registered_domain(host: Optional[str], registered_domain: str) -> bool:
    if not isinstance(host, str) or not host or not isinstance(registered_domain, str):
        return False

    normalized_host = _normalize_dns_name(host)
    normalized_domain = _normalize_dns_name(registered_domain)
    return bool(normalized_host and normalized_domain) and (
        normalized_host == normalized_domain or normalized_host.endswith("." + normalized_domain)
    )


def is_registered_http_url(url: str, registered_domain: str) -> bool:
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except (TypeError, ValueError):
        return False
    host = parts.hostname
    return bool(
        parts.scheme in {"http", "https"}
        and host
        and parts.username is None
        and parts.password is None
        and is_registered_domain(host, registered_domain)
        and (port is None or port == (443 if parts.scheme == "https" else 80))
    )


def is_trusted_source_http_url(url: str, source: DiscoverySource) -> bool:
    return any(
        is_registered_http_url(url, domain)
        for domain in (source.official_domain, *source.trusted_external_domains)
    )


def resolve_trusted_source_url(
    base_url: str,
    url: str,
    source: DiscoverySource,
) -> Optional[str]:
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        absolute_url = urllib.parse.urljoin(base_url, url.strip())
        safe_url = safe_source_url(absolute_url)
        if safe_url is None or not is_trusted_source_http_url(safe_url, source):
            return None
        parts = urllib.parse.urlsplit(safe_url)
        port = parts.port
    except (TypeError, ValueError, UnicodeError):
        return None

    host = parts.hostname.casefold().rstrip(".")
    default_port = 443 if parts.scheme.casefold() == "https" else 80
    netloc = host if port in (None, default_port) else f"{host}:{port}"
    return urllib.parse.urlunsplit((
        parts.scheme.casefold(),
        netloc,
        parts.path or "/",
        parts.query,
        "",
    ))


@dataclass(frozen=True)
class FetchedPage:
    url: str
    content_type: str
    text: str
    links: Tuple[Tuple[str, str], ...]
    content_hash: str
    page_count: Optional[int] = None
    page_texts: Tuple[str, ...] = ()
    original_text_length: Optional[int] = None
    retained_text_length: Optional[int] = None
    text_truncated: bool = False
    insufficient_content: bool = False


class _HTMLContent(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._text_segments = []
        self.links = []
        self._frames = []
        self._active_links = []

    @property
    def text_parts(self):
        focused = [text for in_content, text in self._text_segments if in_content]
        if focused:
            return focused + [text for in_content, text in self._text_segments if not in_content]
        return [text for _, text in self._text_segments]

    def _is_suppressed(self):
        return any(frame["suppressed"] for frame in self._frames)

    @staticmethod
    def _is_consent_banner(attributes):
        identity = " ".join(
            str(attributes.get(name, ""))
            for name in ("id", "class", "role", "aria-label", "data-testid")
        )
        return bool(_CONSENT_MARKERS.search(identity))

    @staticmethod
    def _is_utility_form(attributes):
        identity = " ".join(
            str(attributes.get(name, ""))
            for name in ("id", "class", "role", "aria-label", "data-testid", "name", "action")
        )
        return bool(_UTILITY_FORM_MARKERS.search(identity))

    def _recover_malformed_boilerplate(self, tag):
        if tag not in {"main", "article"}:
            return
        for index, frame in enumerate(self._frames):
            if frame["suppressed"] and (
                frame["tag"] in _BOILERPLATE_TAGS
                or frame["consent_banner"]
                or frame["utility_form"]
            ):
                del self._frames[index:]
                return

    def _finish_link(self):
        if not self._active_links:
            return
        href, label_parts = self._active_links.pop()
        label = " ".join(" ".join(label_parts).split())
        if href:
            self.links.append((href, label))

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self._recover_malformed_boilerplate(tag)
        consent_banner = self._is_consent_banner(attributes)
        utility_form = tag == "form" and self._is_utility_form(attributes)
        own_suppression = (
            tag in _BOILERPLATE_TAGS
            or consent_banner
            or utility_form
            or tag in {"input", "option", "select", "textarea"}
        )
        suppressed = self._is_suppressed() or own_suppression
        if tag == "a":
            if self._active_links:
                self._finish_link()
            if not suppressed:
                self._active_links.append((attributes.get("href"), []))
        if tag not in _VOID_HTML_TAGS:
            self._frames.append({
                "tag": tag,
                "suppressed": suppressed,
                "focus": tag in {"main", "article"},
                "consent_banner": consent_banner,
                "utility_form": utility_form,
            })

    def handle_endtag(self, tag):
        if tag == "a":
            self._finish_link()
        for index in range(len(self._frames) - 1, -1, -1):
            if self._frames[index]["tag"] == tag:
                del self._frames[index:]
                break

    def handle_data(self, data):
        if self._is_suppressed():
            return
        text = " ".join(data.split())
        if text:
            in_content = any(frame["focus"] for frame in self._frames)
            self._text_segments.append((in_content, text))
            if self._active_links:
                self._active_links[-1][1].append(text)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def close(self):
        super().close()
        while self._active_links:
            self._finish_link()


def _connect_validated_address(
    family: int,
    socket_type: int,
    protocol: int,
    sockaddr: tuple,
    timeout: Optional[float],
) -> socket.socket:
    sock = socket.socket(family, socket_type, protocol)
    try:
        sock.settimeout(timeout)
        sock.connect(sockaddr)
        if family in (socket.AF_INET, socket.AF_INET6):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return sock
    except BaseException:
        sock.close()
        raise


class _PinnedConnectionMixin:
    def _open_validated_socket(self):
        family, socket_type, protocol, _canonical_name, sockaddr = self._address_info
        connected = self._connector(family, socket_type, protocol, sockaddr, self.timeout)
        try:
            peer = connected.getpeername()
            peer_ip_text, peer_port = peer[0], peer[1]
            if (
                not isinstance(peer, tuple)
                or len(peer) < 2
                or not isinstance(peer_ip_text, str)
                or "%" in peer_ip_text
                or isinstance(peer_port, bool)
                or not isinstance(peer_port, int)
            ):
                raise ValueError
            peer_ip = ipaddress.ip_address(peer_ip_text)
            expected_ip = ipaddress.ip_address(sockaddr[0])
            if peer_ip != expected_ip or peer_port != sockaddr[1]:
                raise ValueError
            if family == socket.AF_INET6 and (
                len(peer) < 4
                or peer[3] != sockaddr[3]
                or peer_ip.ipv4_mapped is not None
            ):
                raise ValueError
            if family == socket.AF_INET and peer_ip.version != 4:
                raise ValueError
        except (AttributeError, IndexError, OSError, TypeError, ValueError) as exc:
            connected.close()
            raise OSError("Connected peer did not match a validated address.") from exc
        return connected


class _PinnedHTTPConnection(_PinnedConnectionMixin, http.client.HTTPConnection):
    def __init__(self, host, port, address_info, connector, timeout):
        self._address_info = address_info
        self._connector = connector
        super().__init__(host, port, timeout=timeout)

    def connect(self):
        self.sock = self._open_validated_socket()


class _PinnedHTTPSConnection(_PinnedConnectionMixin, http.client.HTTPSConnection):
    def __init__(self, host, port, address_info, connector, timeout, context):
        self._address_info = address_info
        self._connector = connector
        super().__init__(host, port, timeout=timeout, context=context)

    def connect(self):
        sock = self._open_validated_socket()
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class OfficialSourceFetcher:
    def __init__(
        self,
        settings: ScholarshipDiscoverySettings,
        *,
        resolver: Optional[Callable[..., object]] = None,
        connector: Callable[[int, int, int, tuple, Optional[float]], socket.socket] = _connect_validated_address,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        lock_check: Optional[Callable[[], None]] = None,
        run_budget: Optional[DiscoveryRunBudget] = None,
        playwright_factory: Optional[Callable[[], object]] = None,
        browser_launcher: Optional[Callable[..., object]] = None,
        browser_launch_args: Optional[List[str]] = None,
        allowed_request_hosts: Optional[set] = None,
        max_crawl_depth: Optional[int] = None,
    ):
        self.settings = settings
        if max_crawl_depth is not None:
            self.max_crawl_depth = max_crawl_depth
        elif hasattr(settings, "max_crawl_depth"):
            self.max_crawl_depth = settings.max_crawl_depth
        else:
            self.max_crawl_depth = configured_max_crawl_depth()
        self.resolver = resolver
        self.connector = connector
        self.sleep = sleep
        self.clock = clock
        self.lock_check = lock_check
        self.run_budget = run_budget
        self.playwright_factory = playwright_factory
        self.browser_launcher = browser_launcher
        self.chromium_enabled = (
            playwright_factory is not None or browser_launcher is not None
        )
        self._browser_launch_args = tuple(browser_launch_args or ())
        if any(not isinstance(argument, str) for argument in self._browser_launch_args):
            raise ValueError("browser launch arguments must be strings")
        self._validate_browser_launch_args()
        if allowed_request_hosts is None:
            self._allowed_request_hosts = None
        else:
            normalized_hosts = {
                _normalize_allowlisted_host(host)
                for host in allowed_request_hosts
            }
            self._allowed_request_hosts = frozenset(normalized_hosts)
        self._pinned_host_ips = {}
        self._host_resolver_rules = "MAP * ~NOTFOUND"
        self._playwright = None
        self._browser = None
        self._context = None
        self._browser_launched = False
        self.cleanup_errors = []
        self.last_navigation_diagnostics = []
        self.last_policy_rejection = None
        self._policy_failures = []
        self._navigation_source = None
        self._current_page = None
        self._max_rendered_content_bytes = settings.max_response_bytes
        self._robots = {}
        self._robots_failures = {}
        self._last_request = {}
        self.last_crawl_stats = _empty_crawl_stats()
        self.last_link_decisions = []

    def _check_lock(self):
        if self.lock_check is not None:
            self.lock_check()

    def _validate_url(self, source: Optional[DiscoverySource], url: str) -> urllib.parse.SplitResult:
        try:
            parts = urllib.parse.urlsplit(url)
            port = parts.port
        except ValueError as exc:
            raise DiscoveryFetchError("URL is invalid") from exc
        host = (parts.hostname or "").lower()
        if (
            parts.scheme not in {"http", "https"}
            or not host
            or parts.username is not None
            or parts.password is not None
            or source is not None and not is_registered_domain(host, source.official_domain)
            or (port is not None and port != (443 if parts.scheme == "https" else 80))
        ):
            if source is not None:
                raise DiscoveryFetchError("URL is outside the registered official domain")
            raise DiscoveryFetchError("URL is outside the permitted HTTP/HTTPS destinations")
        return parts

    def _safe_fetch_url(
        self,
        source: Optional[DiscoverySource],
        url: str,
        *,
        request_type: Optional[str] = None,
    ) -> str:
        parts = self._validate_url(source, url)
        safe_url = safe_source_url(url)
        if safe_url is None:
            raise DiscoveryFetchError("URL is invalid")
        safe_parts = urllib.parse.urlsplit(safe_url)
        if parts.query != safe_parts.query:
            raise DiscoveryFetchError(
                "URL contains sensitive query parameters",
                category="sensitive_query_rejected",
            )
        if source is not None:
            normalized_url = resolve_trusted_source_url(url, safe_url, source)
            if normalized_url is None:
                raise DiscoveryFetchError("URL is outside the registered official domain")
            safe_url = normalized_url
        if request_type is not None:
            parts = urllib.parse.urlsplit(safe_url)
            host = parts.hostname
            port = parts.port or (443 if parts.scheme.casefold() == "https" else 80)
            self._ensure_host_resolves_public(host, port)
        return safe_url

    def _resolve_public_addresses(self, host: str, port: int) -> List[tuple]:
        dns_timeout = DNS_TIMEOUT_SECONDS
        if self.run_budget is not None:
            dns_timeout = min(dns_timeout, self.run_budget.remaining_seconds())
        deadline = self.clock() + dns_timeout
        try:
            try:
                dns_resolver = dns.resolver.Resolver(configure=True) if self.resolver is None else None
            except NotImplementedError as exc:
                raise DiscoveryFetchError(
                    "System DNS resolver configuration is unsupported"
                ) from exc
            resolve = (
                self.resolver
                if self.resolver is not None
                else dns_resolver.resolve
            )
            addresses = []
            for record_type, family, ip_version in (
                (dns.rdatatype.A, socket.AF_INET, 4),
                (dns.rdatatype.AAAA, socket.AF_INET6, 6),
            ):
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise dns.exception.Timeout("DNS resolution deadline expired")
                try:
                    answer = resolve(host, record_type, lifetime=remaining, search=False)
                except dns.resolver.NoAnswer:
                    continue
                for record in answer:
                    ip_text = record.address
                    if not isinstance(ip_text, str):
                        raise ValueError("DNS returned a malformed address")
                    ip = ipaddress.ip_address(ip_text)
                    if ip.version != ip_version:
                        raise ValueError("DNS returned an unexpected address family")
                    if family == socket.AF_INET:
                        sockaddr = (ip.compressed, port)
                    else:
                        sockaddr = (ip.compressed, port, 0, 0)
                    address = (
                        family,
                        socket.SOCK_STREAM,
                        socket.IPPROTO_TCP,
                        "",
                        sockaddr,
                    )
                    self._validate_public_address(address, port)
                    addresses.append(address)
        except DiscoveryFetchError:
            raise
        except (dns.exception.DNSException, OSError) as exc:
            raise DiscoveryFetchError(
                "Official host did not resolve to safe public addresses",
                category="dns_error",
                cause_type=type(exc).__name__,
            ) from exc
        except (AttributeError, IndexError, TypeError, ValueError) as exc:
            raise DiscoveryFetchError(
                "Official host did not resolve to safe public addresses",
                category="unknown",
                cause_type=type(exc).__name__,
            ) from exc

        if self.clock() >= deadline:
            raise DiscoveryFetchError(
                "Official host did not resolve to safe public addresses",
                category="dns_error",
            )
        if not addresses:
            raise DiscoveryFetchError(
                "Official host did not resolve to public addresses",
                category="dns_error",
            )
        return addresses

    @staticmethod
    def _host_resolver_rule_ip(ip_text: str) -> str:
        try:
            ip = ipaddress.ip_address(ip_text)
        except (TypeError, ValueError) as exc:
            raise DiscoveryFetchError(
                "Official host did not resolve to safe public addresses",
                category="dns_error",
                cause_type=type(exc).__name__,
            ) from exc
        return f"[{ip.compressed}]" if ip.version == 6 else ip.compressed

    def _refresh_host_resolver_rules(self) -> None:
        rules = []
        for host in sorted(self._pinned_host_ips):
            for ip_text in self._pinned_host_ips[host]:
                rules.append(f"MAP {host} {self._host_resolver_rule_ip(ip_text)}")
        rules.append("MAP * ~NOTFOUND")
        self._host_resolver_rules = ", ".join(rules)

    def _ensure_host_resolves_public(self, host: str, port: int = 443) -> List[tuple]:
        normalized_host = _normalize_dns_name(host) if isinstance(host, str) else None
        if normalized_host is None:
            raise DiscoveryFetchError(
                "Official host did not resolve to safe public addresses",
                category="dns_error",
            )
        pinned = self._pinned_host_ips.get(normalized_host)
        if pinned is not None:
            addresses = [
                _address_tuple_for_public_ip(ip_text, port)
                for ip_text in pinned
            ]
            for address in addresses:
                self._validate_public_address(address, port)
            return addresses
        if self._browser_launched or self._browser is not None:
            raise DiscoveryFetchError(
                "Hostname was not pinned before Chromium launch",
                category="browser_pinning_unavailable",
            )

        try:
            literal_ip = ipaddress.ip_address(normalized_host)
        except ValueError:
            resolved_addresses = self._resolve_public_addresses(normalized_host, port)
            addresses = [
                _address_tuple_for_public_ip(address[4][0], port)
                for address in resolved_addresses
            ]
        else:
            addresses = [_address_tuple_for_public_ip(literal_ip.compressed, port)]
        for address in addresses:
            self._validate_public_address(address, port)
        self._pinned_host_ips[normalized_host] = list(dict.fromkeys(
            address[4][0] for address in addresses
        ))
        self._refresh_host_resolver_rules()
        return addresses

    def prepin_hostnames(self, hostnames) -> None:
        normalized_hosts = set()
        for hostname in hostnames:
            normalized = _normalize_dns_name(hostname) if isinstance(hostname, str) else None
            if normalized is None:
                raise DiscoveryFetchError(
                    "Official host did not resolve to safe public addresses",
                    category="dns_error",
                )
            normalized_hosts.add(normalized)
        for hostname in sorted(normalized_hosts):
            self._ensure_host_resolves_public(hostname)

    def _validate_browser_launch_args(self) -> None:
        for argument in self._browser_launch_args:
            lowered = argument.strip().casefold()
            if lowered.startswith(("--proxy-", "--proxy", "--no-proxy")):
                raise DiscoveryFetchError(
                    "Proxy-related Chromium arguments are not permitted",
                    category="unsafe_browser_launch_config",
                )
            if lowered.startswith("--host-resolver-rules"):
                raise DiscoveryFetchError(
                    "Caller-supplied host resolver rules are not permitted",
                    category="unsafe_browser_launch_config",
                )

    def _browser_launch_arguments(self) -> List[str]:
        self._validate_browser_launch_args()
        return [
            *self._browser_launch_args,
            f"--host-resolver-rules={self._host_resolver_rules}",
        ]

    def _ensure_browser(self):
        if self._context is not None:
            return self._context

        self._validate_browser_launch_args()
        for host in sorted(self._allowed_request_hosts or ()):
            self._ensure_host_resolves_public(host)

        try:
            if self.playwright_factory is None:
                from playwright.sync_api import sync_playwright

                playwright = sync_playwright().start()
            else:
                playwright = self.playwright_factory()
                start = getattr(playwright, "start", None)
                if callable(start):
                    playwright = start()
            self._playwright = playwright
            launcher = self.browser_launcher or playwright.chromium.launch
            self._browser_launched = True
            self._browser = launcher(
                headless=True,
                args=self._browser_launch_arguments(),
            )
            self._context = self._browser.new_context(
                service_workers="block",
                java_script_enabled=True,
                ignore_https_errors=False,
            )
            self._context.route("**/*", self._context_route_handler)
            route_web_socket = getattr(self._context, "route_web_socket", None)
            if self._allowed_request_hosts is not None and callable(route_web_socket):
                route_web_socket("**/*", self._websocket_route_handler)
            return self._context
        except DiscoveryFetchError:
            self._stop_playwright()
            raise
        except Exception as exc:
            self._stop_playwright()
            raise DiscoveryFetchError(
                f"Chromium initialization failed: {type(exc).__name__}",
                category="browser_error",
                cause_type=type(exc).__name__,
            ) from exc

    def _stop_playwright(self) -> None:
        playwright = self._playwright
        self._playwright = None
        if playwright is not None:
            try:
                playwright.stop()
            except Exception as exc:
                self.cleanup_errors.append(f"playwright:{type(exc).__name__}")

    def _record_navigation_attempt(self, **diagnostic) -> None:
        self.last_navigation_diagnostics.append(diagnostic)

    def _account_browser_request(self) -> None:
        if self.run_budget is None:
            return
        self.run_budget.ensure_active()
        consume_attempt = getattr(self.run_budget, "consume_http_attempt", None)
        if callable(consume_attempt):
            consume_attempt()
            return
        begin_attempt = getattr(self.run_budget, "begin_http_attempt", None)
        if callable(begin_attempt):
            token, _remaining = begin_attempt(lambda: None)
            invoke_attempt = getattr(self.run_budget, "invoke_http_attempt", None)
            if callable(invoke_attempt):
                invoke_attempt(token, lambda _remaining: None)
            unregister = getattr(self.run_budget, "unregister_cancellation", None)
            if callable(unregister):
                unregister(token)
            return
        self.run_budget.consume_http_attempt()

    @staticmethod
    def _abort_route(route) -> None:
        route.abort()

    def _route_failure(self, route, failures, category, hostname=None, request_type=None, reason=None):
        failure = DiscoveryFetchError(
            "Browser request was rejected by the fetch policy",
            category=category,
        )
        failures.append(failure)
        if hostname is not None:
            self.last_policy_rejection = {
                "hostname": hostname,
                "request_type": request_type,
                "reason": reason or category,
            }
        try:
            self._abort_route(route)
        except Exception:
            logger.warning(
                "Browser route abort failed: category=%s",
                category,
            )

    def _validate_browser_route(self, route, source, expected_page, failures):
        request = route.request
        try:
            frame = request.frame
            page = frame.page
            is_main_frame = frame is page.main_frame
        except Exception:
            try:
                self._account_browser_request()
            except DiscoveryRunLimitExceeded as exc:
                failures.append(exc)
            self._route_failure(route, failures, "frame_identification_failed")
            return

        request_type = (
            "main_frame_redirect"
            if is_main_frame and request.redirected_from is not None
            else "main_frame_navigation"
            if is_main_frame and request.is_navigation_request()
            else "subresource_redirect"
            if request.redirected_from is not None
            else "subresource"
        )
        try:
            self._account_browser_request()
        except DiscoveryRunLimitExceeded as exc:
            failures.append(exc)
            self._route_failure(
                route,
                failures,
                "request_budget_exhausted",
                request_type=request_type,
            )
            return

        if expected_page is not None and page is not expected_page:
            self._route_failure(
                route,
                failures,
                "additional_page_rejected",
                request_type=request_type,
            )
            return

        try:
            parts = urllib.parse.urlsplit(request.url)
            port = parts.port
        except (TypeError, ValueError):
            self._route_failure(route, failures, "external_scheme_rejected", request_type=request_type)
            return
        scheme = parts.scheme.casefold()
        hostname = (parts.hostname or "").casefold().rstrip(".")
        if (
            scheme not in {"http", "https"}
            or not hostname
            or parts.username is not None
            or parts.password is not None
        ):
            self._route_failure(
                route,
                failures,
                "external_scheme_rejected",
                hostname=hostname or None,
                request_type=request_type,
            )
            return

        previous_url = getattr(request.redirected_from, "url", None)
        if previous_url:
            try:
                if urllib.parse.urlsplit(previous_url).scheme.casefold() == "https" and scheme == "http":
                    self._route_failure(
                        route,
                        failures,
                        "https_downgrade_rejected",
                        hostname=hostname,
                        request_type=request_type,
                    )
                    return
            except (TypeError, ValueError):
                self._route_failure(route, failures, "external_scheme_rejected", request_type=request_type)
                return

        if self._allowed_request_hosts is not None:
            allowed = hostname in self._allowed_request_hosts
        elif is_main_frame and source is not None:
            allowed = is_trusted_source_http_url(request.url, source)
        else:
            allowed = True
        if not allowed:
            self._route_failure(
                route,
                failures,
                "request_host_not_allowed",
                hostname=hostname,
                request_type=request_type,
                reason="host_not_in_exact_allowlist",
            )
            return

        try:
            self._ensure_host_resolves_public(
                hostname,
                port or (443 if scheme == "https" else 80),
            )
        except DiscoveryFetchError as exc:
            if is_main_frame or exc.category != "browser_pinning_unavailable":
                failures.append(exc)
            if not is_main_frame and exc.category == "browser_pinning_unavailable":
                try:
                    route.abort()
                except Exception:
                    logger.warning(
                        "Browser route abort failed: category=%s",
                        exc.category,
                    )
                return
            if is_main_frame:
                logger.warning(
                    "Browser request blocked: host=%s request_type=%s category=%s",
                    hostname,
                    request_type,
                    exc.category,
                )
            self._route_failure(
                route,
                failures,
                exc.category,
                hostname=hostname,
                request_type=request_type,
                reason="hostname_not_pinned",
            )
            return
        try:
            route.continue_()
        except Exception as exc:
            failures.append(
                DiscoveryFetchError(
                    "Browser request could not be continued",
                    category="request_handler_failed",
                    cause_type=type(exc).__name__,
                )
            )
            self._route_failure(route, failures, "request_handler_failed", hostname, request_type)

    def _context_route_handler(self, route) -> None:
        self._validate_browser_route(
            route,
            self._navigation_source,
            self._current_page,
            self._policy_failures,
        )

    def _websocket_route_handler(self, websocket) -> None:
        try:
            websocket.close(code=1008, reason="WebSockets disabled by fetch policy")
        finally:
            self._policy_failures.append(
                DiscoveryFetchError(
                    "Browser WebSocket request was rejected",
                    category="websocket_rejected",
                )
            )

    def _install_request_controls(self, page, source: Optional[DiscoverySource]):
        self._navigation_source = source
        self._current_page = page
        failures = []
        self._policy_failures = failures
        if self._context is not None:
            self._context.route(
                "**/*",
                lambda route: self._validate_browser_route(
                    route,
                    source,
                    page,
                    failures,
                ),
            )
            context_route_web_socket = getattr(self._context, "route_web_socket", None)
            if (
                self._allowed_request_hosts is not None
                and callable(context_route_web_socket)
            ):
                context_route_web_socket("**/*", self._websocket_route_handler)
        page.route(
            "**/*",
            lambda route: self._validate_browser_route(route, source, page, failures),
        )
        route_web_socket = getattr(page, "route_web_socket", None)
        if self._allowed_request_hosts is not None and callable(route_web_socket):
            route_web_socket("**/*", self._websocket_route_handler)
        return failures

    @staticmethod
    def _browser_error_category(exc: BaseException) -> str:
        message = str(exc).casefold()
        if "err_name_not_resolved" in message or "name_not_resolved" in message:
            return "dns_error"
        if "err_cert_" in message or "certificate" in message or "tls" in message:
            return "tls_error"
        if "timeout" in message or "timed out" in message:
            return "timeout"
        if "connection" in message or "err_" in message:
            return "connection_error"
        return "unknown"

    def _record_navigation_safely(self, **diagnostic) -> None:
        try:
            self._record_navigation_attempt(**diagnostic)
        except Exception as exc:
            logger.warning(
                "Browser navigation diagnostic failed: cause_type=%s",
                type(exc).__name__,
            )

    @staticmethod
    def _response_headers(response) -> email.message.Message:
        headers = email.message.Message()
        raw_headers = getattr(response, "headers", {}) or {}
        if hasattr(raw_headers, "items"):
            for name, value in raw_headers.items():
                headers[str(name).title()] = str(value)
        return headers

    def _close_page(self, page) -> None:
        try:
            page.close()
        except Exception as exc:
            self.cleanup_errors.append(f"page:{type(exc).__name__}")

    def _navigate_html(
        self,
        source: DiscoverySource,
        url: str,
        *,
        request_type: str = "main_frame_navigation",
        allowed_types=ALLOWED_PAGE_TYPES,
        record_diagnostics: bool = True,
    ) -> FetchedPage:
        safe_url = self._safe_fetch_url(source, url, request_type=request_type)
        parts = urllib.parse.urlsplit(safe_url)
        host = (parts.hostname or "").casefold().rstrip(".")
        port = parts.port or (443 if parts.scheme.casefold() == "https" else 80)
        self._ensure_host_resolves_public(host, port)
        context = self._ensure_browser()
        page = context.new_page()
        self._install_request_controls(page, source)
        timeout_ms = max(1, int(self.settings.request_timeout_seconds * 1000))
        page.set_default_navigation_timeout(timeout_ms)
        page.set_default_timeout(timeout_ms)

        diagnostic = {
            "url": _sanitize_diagnostic_url(safe_url),
            "outcome": None,
            "response_present": False,
            "http_status": None,
            "content_length_present": False,
            "content_length": None,
            "response_size": None,
            "response_size_source": None,
            "retry_decision": "none",
            "retry_delay": None,
        }
        try:
            response = page.goto(
                safe_url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            if response is None:
                raise DiscoveryFetchError(
                    "Chromium navigation returned no response",
                    category="unknown",
                )
            diagnostic["response_present"] = True
            status = getattr(response, "status", None)
            diagnostic["http_status"] = status
            headers = self._response_headers(response)
            raw_length = headers.get("Content-Length")
            try:
                content_length = int(raw_length) if raw_length is not None else None
                if content_length is not None and content_length < 0:
                    content_length = None
            except (TypeError, ValueError):
                content_length = None
            diagnostic["content_length_present"] = raw_length is not None
            diagnostic["content_length"] = content_length
            diagnostic["retry_after"] = headers.get("Retry-After")
            if content_length is not None:
                diagnostic["response_size"] = content_length
                diagnostic["response_size_source"] = "content_length"
                if content_length > self.settings.max_response_bytes:
                    raise DiscoveryFetchError(
                        "Official response exceeded the configured size limit",
                        status_code=status,
                        category="content_validation_failed",
                    )
            if status is None:
                raise DiscoveryFetchError(
                    "Chromium response metadata was unavailable",
                    category="unknown",
                )
            if not 200 <= status < 300:
                raise DiscoveryFetchError(
                    f"Official host returned HTTP {status}",
                    status_code=status,
                    category="http_status",
                )

            final_url = getattr(response, "url", safe_url) or safe_url
            final_url = self._safe_fetch_url(source, final_url, request_type=request_type)
            final_parts = urllib.parse.urlsplit(final_url)
            if parts.scheme.casefold() == "https" and final_parts.scheme.casefold() == "http":
                raise DiscoveryFetchError(
                    "HTTPS redirect to HTTP was rejected",
                    status_code=status,
                    category="https_downgrade_rejected",
                )
            content_type = headers.get_content_type().casefold()
            if content_type not in allowed_types:
                raise DiscoveryFetchError(
                    f"Unsupported content type: {content_type}",
                    status_code=status,
                    category="content_validation_failed",
                )

            body = response.body()
            diagnostic["response_size"] = len(body)
            diagnostic["response_size_source"] = "body"
            if len(body) > self.settings.max_response_bytes:
                raise DiscoveryFetchError(
                    "Official response exceeded the configured size limit",
                    status_code=status,
                    category="content_validation_failed",
                )
            if content_type == "application/pdf":
                page_texts = self._pdf_page_texts(body)
                text = "\n".join(page_texts)
                links = ()
                page_count = len(page_texts)
            elif content_type == "application/json":
                try:
                    text = json.dumps(json.loads(body), ensure_ascii=False)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise DiscoveryFetchError(
                        "Official JSON response was invalid",
                        category="content_validation_failed",
                        cause_type=type(exc).__name__,
                    ) from exc
                links = ()
                page_texts = (text,)
                page_count = None
            elif content_type == "text/plain":
                text = body.decode(headers.get_content_charset() or "utf-8", errors="replace")
                links = ()
                page_texts = (text,)
                page_count = None
            else:
                html = page.content()
                rendered_size = len(html.encode("utf-8"))
                if rendered_size > self._max_rendered_content_bytes:
                    raise DiscoveryFetchError(
                        "Rendered page exceeded the configured size limit",
                        status_code=status,
                        category="content_validation_failed",
                    )
                parser = _HTMLContent()
                parser.feed(html)
                parser.close()
                text = "\n".join(parser.text_parts)
                links = tuple(parser.links)
                page_texts = (text,)
                page_count = None

            original_text_length = len(text)
            text = text[: self.settings.max_extracted_chars]
            page_texts = tuple(
                page_text[: self.settings.max_extracted_chars]
                for page_text in page_texts
            )
            retained_text_length = len(text)
            diagnostic["retry_decision"] = "none"
            diagnostic["outcome"] = "navigation_succeeded"
            if record_diagnostics:
                self._record_navigation_safely(**diagnostic)
            return FetchedPage(
                url=final_url,
                content_type=content_type,
                text=text,
                links=links,
                content_hash=hashlib.sha256(body).hexdigest(),
                page_count=page_count,
                page_texts=page_texts,
                original_text_length=original_text_length,
                retained_text_length=retained_text_length,
                text_truncated=retained_text_length < original_text_length,
                insufficient_content=(
                    len(text.strip()) < self.settings.min_extracted_chars
                ),
            )
        except DiscoveryFetchError as exc:
            diagnostic["retry_decision"] = "none"
            diagnostic["outcome"] = (
                "http_error" if exc.status_code is not None else "navigation_failed"
            )
            if record_diagnostics:
                self._record_navigation_safely(**diagnostic)
            raise
        except Exception as exc:
            for failure in self._policy_failures:
                if isinstance(failure, DiscoveryRunLimitExceeded):
                    raise failure
                if (
                    isinstance(failure, DiscoveryFetchError)
                    and failure.category == "browser_pinning_unavailable"
                ):
                    raise failure
            if (
                self.last_policy_rejection is not None
                and self.last_policy_rejection.get("request_type", "").startswith("main_frame")
            ):
                for failure in reversed(self._policy_failures):
                    if isinstance(failure, DiscoveryFetchError):
                        raise failure
            diagnostic["retry_decision"] = "none"
            diagnostic["outcome"] = "navigation_failed"
            if record_diagnostics:
                self._record_navigation_safely(**diagnostic)
            raise DiscoveryFetchError(
                f"Chromium navigation failed: {type(exc).__name__}",
                status_code=diagnostic["http_status"],
                category=self._browser_error_category(exc),
                cause_type=type(exc).__name__,
            ) from exc
        finally:
            self._close_page(page)

    def _fetch_playwright_page(
        self,
        source: DiscoverySource,
        url: str,
        *,
        allowed_types=ALLOWED_PAGE_TYPES,
        record_diagnostics: bool = True,
    ) -> FetchedPage:
        attempt_limit = self.settings.max_retries + 1
        for attempt in range(attempt_limit):
            self._check_lock()
            try:
                return self._navigate_html(
                    source,
                    url,
                    allowed_types=allowed_types,
                    record_diagnostics=record_diagnostics,
                )
            except DiscoveryRunLimitExceeded:
                raise
            except DiscoveryFetchError as exc:
                exc.attempt_count = attempt + 1
                exc.attempt_limit = attempt_limit
                retryable = (
                    exc.status_code in TRANSIENT_STATUSES
                    and attempt + 1 < attempt_limit
                )
                if not retryable:
                    if self.last_navigation_diagnostics:
                        diagnostic = self.last_navigation_diagnostics[-1]
                        diagnostic["retry_decision"] = (
                            "exhausted"
                            if exc.status_code in TRANSIENT_STATUSES
                            else "none"
                        )
                        if diagnostic["retry_decision"] == "exhausted":
                            diagnostic["retry_reason"] = (
                                f"http_{exc.status_code}_retry_limit"
                            )
                    raise
                retry_after = None
                if self.last_navigation_diagnostics:
                    retry_after = self.last_navigation_diagnostics[-1].get("retry_after")
                delay = _retry_delay_seconds(attempt, retry_after)
                if self.last_navigation_diagnostics:
                    self.last_navigation_diagnostics[-1]["retry_delay"] = delay
                if delay is None:
                    self.last_navigation_diagnostics[-1]["retry_decision"] = "exhausted"
                    self.last_navigation_diagnostics[-1]["retry_reason"] = (
                        "retry_after_exceeds_limit"
                    )
                    raise
                self.last_navigation_diagnostics[-1]["retry_decision"] = "retry"
                if self.run_budget is None:
                    self.sleep(delay)
                else:
                    self.run_budget.wait(delay)
        raise DiscoveryFetchError(
            "Chromium navigation retry limit was exhausted",
            category="unknown",
            attempt_count=attempt_limit,
            attempt_limit=attempt_limit,
        )

    def _fetch_playwright(self, source: DiscoverySource, url: str) -> FetchedPage:
        safe_url = self._safe_fetch_url(source, url)
        root_url = self._safe_fetch_url(source, source.source_url)
        is_root_page = safe_url == root_url
        if not self._robots_allowed(source, safe_url):
            host = urllib.parse.urlsplit(safe_url).hostname.casefold()
            page_stage = "root_fetch" if is_root_page else "linked_page"
            details = self._robots_failures.get(host)
            raise DiscoveryFetchError(
                "robots.txt disallows this URL or could not be checked",
                status_code=details.status_code if details else None,
                category="robots_check_failed",
                stage="robots",
                page_stage=page_stage,
                attempt_count=details.attempt_count if details else None,
                attempt_limit=details.attempt_limit if details else None,
                cause_type=details.cause_type if details else None,
                cause_category=details.cause_category if details else None,
                source_id=source.source_id,
            )
        return self._fetch_playwright_page(source, safe_url)

    def close(self) -> None:
        for name, resource in (
            ("context", self._context),
            ("browser", self._browser),
        ):
            if resource is None:
                continue
            try:
                resource.close()
            except Exception as exc:
                self.cleanup_errors.append(f"{name}:{type(exc).__name__}")
        self._context = None
        self._browser = None
        self._stop_playwright()
        self._browser_launched = False

    @staticmethod
    def _validate_public_address(address: tuple, port: int) -> None:
        try:
            family, socket_type, protocol, _canonical_name, sockaddr = address
            ip_text = sockaddr[0]
            if not isinstance(ip_text, str) or "%" in ip_text:
                raise ValueError
            ip = ipaddress.ip_address(ip_text)
            if (
                family not in (socket.AF_INET, socket.AF_INET6)
                or socket_type != socket.SOCK_STREAM
                or protocol != socket.IPPROTO_TCP
                or sockaddr[1] != port
                or family == socket.AF_INET and ip.version != 4
                or family == socket.AF_INET6 and (
                    ip.version != 6
                    or len(sockaddr) < 4
                    or sockaddr[3] != 0
                    or ip.ipv4_mapped is not None
                )
                or not ip.is_global
                or ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                raise ValueError
        except (IndexError, TypeError, ValueError) as exc:
            raise DiscoveryFetchError(
                "Official host did not resolve exclusively to public addresses",
                category="dns_error",
                cause_type=type(exc).__name__,
            ) from exc

    def _request(
        self,
        source: Optional[DiscoverySource],
        url: str,
        *,
        on_request_attempt: Optional[Callable[[], None]] = None,
    ) -> Tuple[int, email.message.Message, bytes]:
        url = self._safe_fetch_url(source, url)
        parts = self._validate_url(source, url)
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "https" else 80)
        addresses = self._resolve_public_addresses(host, port)
        request_target = _request_target(parts)
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/pdf,application/json,text/plain",
            "Host": parts.netloc,
            "Connection": "close",
        }
        context = ssl.create_default_context() if parts.scheme == "https" else None
        last_error = None

        for address in addresses:
            if self.run_budget is not None:
                timeout = min(
                    self.settings.request_timeout_seconds,
                    self.run_budget.remaining_seconds(),
                )
            else:
                timeout = self.settings.request_timeout_seconds
            if parts.scheme == "https":
                connection = _PinnedHTTPSConnection(
                    host,
                    port,
                    address,
                    self.connector,
                    timeout,
                    context,
                )
            else:
                connection = _PinnedHTTPConnection(
                    host,
                    port,
                    address,
                    self.connector,
                    timeout,
                )
            response = None
            cancellation_token = None
            try:
                if self.run_budget is not None:
                    cancellation_token, _remaining = self.run_budget.begin_http_attempt(
                        connection.close,
                    )
                    def invoke_request(remaining):
                        connection.timeout = min(
                            self.settings.request_timeout_seconds,
                            remaining,
                        )
                        if on_request_attempt is not None:
                            on_request_attempt()
                        connection.request("GET", request_target, headers=headers)

                    self.run_budget.invoke_http_attempt(
                        cancellation_token,
                        invoke_request,
                    )
                else:
                    if on_request_attempt is not None:
                        on_request_attempt()
                    connection.request("GET", request_target, headers=headers)
                response = connection.getresponse()
                response_headers = response.headers
                if not 200 <= response.status < 300:
                    return response.status, response_headers, b""
                length = response_headers.get("Content-Length")
                if length and int(length) > self.settings.max_response_bytes:
                    raise DiscoveryFetchError(
                        "Official response exceeded the configured size limit",
                        category="content_validation_failed",
                    )
                body = response.read(self.settings.max_response_bytes + 1)
                if len(body) > self.settings.max_response_bytes:
                    raise DiscoveryFetchError(
                        "Official response exceeded the configured size limit",
                        category="content_validation_failed",
                    )
                return response.status, response_headers, body
            except OSError as exc:
                last_error = exc
            finally:
                try:
                    if response is not None:
                        response.close()
                finally:
                    try:
                        connection.close()
                    finally:
                        if self.run_budget is not None and cancellation_token is not None:
                            self.run_budget.unregister_cancellation(cancellation_token)

        if last_error is not None:
            raise last_error
        raise DiscoveryFetchError(
            "Official host did not resolve to public addresses",
            category="dns_error",
        )

    def _throttle(self, host: str):
        now = self.clock()
        wait = self.settings.request_delay_seconds - (now - self._last_request.get(host, now))
        if self.run_budget is not None:
            self.run_budget.ensure_active()
            wait = min(wait, self.run_budget.remaining_seconds())
        if wait > 0:
            if self.run_budget is None:
                self.sleep(wait)
            else:
                self.run_budget.wait(wait)
        self._last_request[host] = self.clock()

    def _fetch_bytes(
        self,
        source: Optional[DiscoverySource],
        url: str,
        allowed_types=ALLOWED_PAGE_TYPES,
        *,
        on_request_attempt: Optional[Callable[[], None]] = None,
    ) -> Tuple[str, email.message.Message, bytes]:
        current = self._safe_fetch_url(source, url)
        for redirect_count in range(MAX_REDIRECTS + 1):
            current = self._safe_fetch_url(source, current)
            self._check_lock()
            parts = self._validate_url(source, current)
            host = parts.hostname.lower()
            last_error = None
            attempt_limit = self.settings.max_retries + 1
            for attempt in range(attempt_limit):
                self._check_lock()
                self._throttle(host)
                try:
                    if on_request_attempt is None:
                        status, headers, body = self._request(source, current)
                    else:
                        status, headers, body = self._request(
                            source,
                            current,
                            on_request_attempt=on_request_attempt,
                        )
                    if self.run_budget is not None:
                        self.run_budget.ensure_active()
                except DiscoveryFetchError as exc:
                    if exc.attempt_count is None:
                        exc.attempt_count = attempt + 1
                    if exc.attempt_limit is None:
                        exc.attempt_limit = attempt_limit
                    raise
                except DiscoveryRunLimitExceeded:
                    raise
                except (TimeoutError, OSError, ValueError) as exc:
                    if self.run_budget is not None:
                        self.run_budget.ensure_active()
                    last_error = exc
                    if attempt < self.settings.max_retries:
                        if self.run_budget is None:
                            self.sleep(min(2 ** attempt, 8))
                        else:
                            self.run_budget.wait(min(2 ** attempt, 8))
                        continue
                    raise DiscoveryFetchError(
                        f"Fetch failed: {type(exc).__name__}",
                        category=_failure_category_for_exception(exc),
                        attempt_count=attempt + 1,
                        attempt_limit=attempt_limit,
                        cause_type=type(exc).__name__,
                    ) from exc
                if 300 <= status < 400:
                    target = headers.get("Location")
                    if not target:
                        raise DiscoveryFetchError(
                            f"Redirect had no location (HTTP {status})",
                            status_code=status,
                            category="content_validation_failed",
                            attempt_count=attempt + 1,
                            attempt_limit=attempt_limit,
                        )
                    if self.run_budget is not None:
                        self.run_budget.ensure_active()
                    redirected_url = self._safe_fetch_url(
                        source,
                        urllib.parse.urljoin(current, target),
                    )
                    current_parts = urllib.parse.urlsplit(current)
                    redirected_parts = urllib.parse.urlsplit(redirected_url)
                    if (
                        current_parts.scheme == "https"
                        and redirected_parts.scheme == "http"
                    ):
                        raise DiscoveryFetchError(
                            "HTTPS redirect to HTTP was rejected",
                            status_code=status,
                            category="https_downgrade_rejected",
                            attempt_count=attempt + 1,
                            attempt_limit=attempt_limit,
                        )
                    current = redirected_url
                    break
                if status in TRANSIENT_STATUSES and attempt < self.settings.max_retries:
                    retry_delay = _retry_delay_seconds(
                        attempt,
                        headers.get("Retry-After"),
                    )
                    if retry_delay is None:
                        logger.info(
                            "Discovery fetch retry skipped: source_id=%s http_status=%s "
                            "reason=retry_after_exceeds_limit",
                            source.source_id if source is not None else None,
                            status,
                        )
                    else:
                        if self.run_budget is None:
                            self.sleep(retry_delay)
                        else:
                            self.run_budget.wait(retry_delay)
                        continue
                if not 200 <= status < 300:
                    raise DiscoveryFetchError(
                        f"Official host returned HTTP {status}",
                        status_code=status,
                        attempt_count=attempt + 1,
                        attempt_limit=attempt_limit,
                    )
                mime_type = headers.get_content_type().lower()
                if mime_type not in allowed_types:
                    raise DiscoveryFetchError(
                        f"Unsupported content type: {mime_type}",
                        status_code=status,
                        category="content_validation_failed",
                        attempt_count=attempt + 1,
                        attempt_limit=attempt_limit,
                    )
                return current, headers, body
            else:
                raise DiscoveryFetchError(
                    f"Fetch failed: {type(last_error).__name__ if last_error else 'HTTP error'}",
                    category=_failure_category_for_exception(last_error) if last_error else "unknown",
                    attempt_count=attempt_limit,
                    attempt_limit=attempt_limit,
                    cause_type=type(last_error).__name__ if last_error else None,
                )
            if redirect_count == MAX_REDIRECTS:
                raise DiscoveryFetchError(
                    "Too many redirects",
                    status_code=status,
                    category="content_validation_failed",
                    attempt_count=attempt + 1,
                    attempt_limit=attempt_limit,
                )
        raise DiscoveryFetchError("Too many redirects", category="content_validation_failed")

    def _pdf_page_texts(self, body: bytes, *, enforce_page_limit: bool = True) -> Tuple[str, ...]:
        if b"%PDF-" not in body[:1024]:
            raise DiscoveryFetchError(
                "The response did not contain a valid PDF signature",
                category="content_validation_failed",
            )
        try:
            import pymupdf as fitz
        except ImportError as exc:
            raise DiscoveryFetchError(
                "PDF extraction dependency PyMuPDF is unavailable",
                category="unknown",
                cause_type=type(exc).__name__,
            ) from exc
        try:
            with fitz.open(stream=body, filetype="pdf") as document:
                if document.needs_pass:
                    raise DiscoveryFetchError(
                        "Encrypted PDFs are not supported",
                        category="content_validation_failed",
                    )
                page_count = len(document)
                if page_count == 0:
                    raise DiscoveryFetchError(
                        "PDF contained no pages",
                        category="content_validation_failed",
                    )
                if enforce_page_limit and page_count > self.settings.max_pages_per_source:
                    raise DiscoveryFetchError(
                        "PDF exceeded the configured page limit",
                        category="content_validation_failed",
                    )
                remaining = self.settings.max_extracted_chars
                page_texts = []
                for page in document:
                    page_text = page.get_text()
                    page_texts.append(page_text[:remaining])
                    remaining = max(0, remaining - len(page_text))
        except DiscoveryFetchError:
            raise
        except Exception as exc:
            logger.warning("PDF extraction failed: %s", type(exc).__name__)
            raise DiscoveryFetchError(
                "PDF extraction failed",
                category="content_validation_failed",
                cause_type=type(exc).__name__,
            ) from exc
        if not any(text.strip() for text in page_texts):
            raise DiscoveryFetchError(
                "PDF contained no extractable text",
                category="content_validation_failed",
            )
        return tuple(page_texts)

    def extract_uploaded_pdf(self, body: bytes) -> FetchedPage:
        if len(body) > self.settings.max_response_bytes:
            raise DiscoveryFetchError(
                "PDF exceeded the configured size limit",
                category="content_validation_failed",
            )
        page_texts = self._pdf_page_texts(body)
        text = "\n".join(page_texts)
        return FetchedPage(
            url="",
            content_type="application/pdf",
            text=text,
            links=(),
            content_hash=hashlib.sha256(body).hexdigest(),
            page_count=len(page_texts),
            page_texts=page_texts,
        )

    @staticmethod
    def _reject_private_literal_host(url: str) -> None:
        """Refuse a URL whose host is a literal non-public IP address.

        For URLs that are stored rather than fetched. The fetch path checks
        resolved addresses instead, which is stronger but needs DNS.
        """
        host = (urllib.parse.urlsplit(url).hostname or "").strip("[]")
        if not host:
            raise DiscoveryFetchError("URL is invalid")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return  # A hostname, not a literal address.
        if (
            not ip.is_global
            or ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise DiscoveryFetchError("URL does not name a public host")

    def page_from_pasted_text(self, text: str, source_url: str | None = None) -> FetchedPage:
        """A page built from text an administrator pasted in.

        Nothing is fetched, so there is no robots rule and no HTTP status to
        map. The source URL is kept as provenance only, after the same safety
        check every other URL gets, and the same character limit applies.
        """
        if not isinstance(text, str) or not text.strip():
            raise DiscoveryFetchError(
                "Pasted text was empty",
                category="content_validation_failed",
            )
        encoded = text.encode("utf-8", errors="replace")
        if len(encoded) > self.settings.max_response_bytes:
            raise DiscoveryFetchError(
                "Pasted text exceeded the configured size limit",
                category="content_validation_failed",
            )
        safe_url = ""
        if source_url:
            # Recorded, never requested: the same validation as a fetch so a
            # provenance URL can never be unsafe or carry a secret query.
            safe_url = self._safe_fetch_url(None, source_url)
            # A URL we never connect to skips address resolution, so a literal
            # private or loopback host would otherwise be stored and shown as
            # the source. No DNS here: a name is left alone, an IP is checked.
            self._reject_private_literal_host(safe_url)
        trimmed = text
        if len(trimmed) > self.settings.max_extracted_chars:
            trimmed = trimmed[: self.settings.max_extracted_chars]
        return FetchedPage(
            url=safe_url,
            content_type="text/plain",
            text=trimmed,
            links=(),
            content_hash=hashlib.sha256(encoded).hexdigest(),
            page_count=None,
            page_texts=(trimmed,),
        )

    def fetch_import_url(self, url: str, source_type: str) -> FetchedPage:
        """Read one page or PDF for admin import.

        Same class, same URL safety checks, same size limits and the same
        robots.txt rule as discovery. When this fetcher was built with a
        browser (see config.import_uses_browser) an HTML page is read through
        Chromium, because the plain HTTP path sends a bot User-Agent that many
        official sites answer with 403. A PDF always takes the HTTP path:
        there is nothing for a browser to render.
        """
        allowed_types = {
            "webpage": {"text/html", "application/xhtml+xml"},
            "pdf_url": {"application/pdf"},
        }
        if source_type not in allowed_types:
            raise DiscoveryFetchError("Unsupported import source type")

        # robots.txt applies to import exactly as it does to discovery. This
        # was missing: import fetched whatever it was pointed at.
        safe_url = self._safe_fetch_url(None, url)
        if not self._robots_allowed(None, safe_url):
            host = urllib.parse.urlsplit(safe_url).hostname
            details = self._robots_failures.get((host or "").lower())
            raise DiscoveryFetchError(
                "robots.txt disallows this URL or could not be checked",
                status_code=details.status_code if details else None,
                category="robots_check_failed",
                stage="robots",
                page_stage="root_fetch",
                attempt_count=details.attempt_count if details else None,
                attempt_limit=details.attempt_limit if details else None,
                cause_type=details.cause_type if details else None,
                cause_category=details.cause_category if details else None,
            )

        if self.chromium_enabled and source_type == "webpage":
            page = self._fetch_playwright_page(
                None,
                safe_url,
                allowed_types=allowed_types[source_type],
                record_diagnostics=False,
            )
            text = page.text
            if len(text) > self.settings.max_extracted_chars:
                text = text[: self.settings.max_extracted_chars]
            return FetchedPage(
                url=page.url,
                content_type=page.content_type,
                text=text,
                links=page.links,
                content_hash=page.content_hash,
                page_count=page.page_count,
                page_texts=(text,),
            )

        final_url, headers, body = self._fetch_bytes(
            None,
            safe_url,
            allowed_types=allowed_types[source_type],
        )
        content_type = headers.get_content_type().lower()
        if content_type == "application/pdf":
            page_texts = self._pdf_page_texts(body)
            text = "\n".join(page_texts)
            links = ()
            page_count = len(page_texts)
        else:
            charset = headers.get_content_charset() or "utf-8"
            try:
                html = body.decode(charset, errors="replace")
            except LookupError:
                html = body.decode("utf-8", errors="replace")
            parser = _HTMLContent()
            parser.feed(html)
            parser.close()
            text = "\n".join(parser.text_parts)
            if not text.strip():
                raise DiscoveryFetchError(
                    "Webpage contained no readable text",
                    category="content_validation_failed",
                )
            links = tuple(parser.links)
            page_count = None
            page_texts = (text,)

        if len(text) > self.settings.max_extracted_chars:
            text = text[: self.settings.max_extracted_chars]
            remaining = self.settings.max_extracted_chars
            limited_page_texts = []
            for page_text in page_texts:
                limited_page_texts.append(page_text[:remaining])
                remaining = max(0, remaining - len(page_text))
            page_texts = tuple(limited_page_texts)
        return FetchedPage(
            url=final_url,
            content_type=content_type,
            text=text,
            links=links,
            content_hash=hashlib.sha256(body).hexdigest(),
            page_count=page_count,
            page_texts=page_texts,
        )

    def _robots_allowed(self, source: DiscoverySource, url: str) -> bool:
        url = self._safe_fetch_url(source, url)
        parts = self._validate_url(source, url)
        host = parts.hostname.lower()
        if host not in self._robots:
            robots_url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
            try:
                if self.playwright_factory is not None or self.browser_launcher is not None:
                    robots_page = None
                    robots_failure: DiscoveryFetchError | None = None
                    for _attempt_allowed_types in (
                        {'text/plain'},
                        {'text/plain', 'text/html', 'application/xhtml+xml'},
                    ):
                        try:
                            robots_page = self._fetch_playwright_page(
                                source,
                                robots_url,
                                allowed_types=_attempt_allowed_types,
                                record_diagnostics=False,
                            )
                            break
                        except DiscoveryFetchError as exc:
                            robots_failure = exc
                            if exc.status_code is not None:
                                # The server answered. Widening the accepted
                                # content types cannot change that answer, and
                                # retrying costs another page; the handler
                                # below decides what the status means (404 =
                                # no robots.txt = nothing disallowed).
                                break
                            continue
                    if robots_page is None:
                        # Re-raise the real failure. Replacing it with a
                        # synthetic status-less error made every missing
                        # robots.txt look unverifiable, which skipped the
                        # whole source.
                        raise robots_failure if robots_failure is not None else (
                            DiscoveryFetchError(
                                'robots.txt could not be fetched',
                                status_code=None,
                                category='robots_check_failed',
                            )
                        )
                    parser = urllib.robotparser.RobotFileParser(robots_page.url)
                    parser.parse(robots_page.text.splitlines())
                    self._robots[host] = parser
                    self._robots_failures.pop(host, None)
                    return parser.can_fetch(self.settings.user_agent, url)
                final_url, headers, body = self._fetch_bytes(source, robots_url, allowed_types={"text/plain"})
            except DiscoveryFetchError as exc:
                if exc.status_code == 404:
                    self._robots[host] = None
                    self._robots_failures.pop(host, None)
                else:
                    self._robots_failures[host] = _RobotsFailureDetails(
                        status_code=exc.status_code,
                        attempt_count=exc.attempt_count,
                        attempt_limit=exc.attempt_limit,
                        cause_type=exc.immediate_cause_type,
                        cause_category=exc.category,
                    )
                    self._robots[host] = False
            else:
                parser = urllib.robotparser.RobotFileParser(final_url)
                parser.parse(body.decode(headers.get_content_charset() or "utf-8", errors="replace").splitlines())
                self._robots_failures.pop(host, None)
                self._robots[host] = parser
        policy = self._robots[host]
        return policy is None or policy is not False and policy.can_fetch(self.settings.user_agent, url)

    def fetch(self, source: DiscoverySource, url: str) -> FetchedPage:
        if self.playwright_factory is not None or self.browser_launcher is not None:
            # The Playwright path does not go through _fetch_bytes, so the
            # linked-page attempt counter has to be recorded here or it stays
            # at zero however many linked pages are tried.
            try:
                is_root_page = url == self._safe_fetch_url(source, source.source_url)
            except (DiscoveryFetchError, TypeError, ValueError, UnicodeError):
                is_root_page = False
            if not is_root_page:
                self.last_crawl_stats["linked_pages_attempted"] += 1
            return self._fetch_playwright(source, url)
        url = self._safe_fetch_url(source, url)
        root_url = self._safe_fetch_url(source, source.source_url)
        is_root_page = url == root_url
        if not self._robots_allowed(source, url):
            host = urllib.parse.urlsplit(url).hostname.lower()
            page_stage = "root_fetch" if is_root_page else "linked_page"
            details = self._robots_failures.get(host)
            failure = DiscoveryFetchError(
                "robots.txt disallows this URL or could not be checked",
                status_code=details.status_code if details else None,
                category="robots_check_failed",
                stage="robots",
                page_stage=page_stage,
                attempt_count=details.attempt_count if details else None,
                attempt_limit=details.attempt_limit if details else None,
                cause_type=details.cause_type if details else None,
                cause_category=details.cause_category if details else None,
                source_id=source.source_id,
            )
            if details is not None:
                _log_fetch_failure(source.source_id, failure, "robots", page_stage)
            raise failure
        if is_root_page:
            final_url, headers, body = self._fetch_bytes(source, url)
        else:
            attempt_recorded = False

            def record_linked_page_attempt():
                nonlocal attempt_recorded
                if not attempt_recorded:
                    self.last_crawl_stats["linked_pages_attempted"] += 1
                    attempt_recorded = True

            final_url, headers, body = self._fetch_bytes(
                source,
                url,
                on_request_attempt=record_linked_page_attempt,
            )
        content_type = headers.get_content_type().lower()
        if content_type == "application/pdf":
            try:
                import pymupdf as fitz
            except ImportError as exc:
                raise DiscoveryFetchError("PDF extraction dependency PyMuPDF is unavailable") from exc
            try:
                with fitz.open(stream=body, filetype="pdf") as document:
                    text = "\n".join(page.get_text() for page in document)
                    page_count = len(document)
            except Exception as exc:
                raise DiscoveryFetchError(
                    f"PDF extraction failed: {type(exc).__name__}",
                    category="content_validation_failed",
                    cause_type=type(exc).__name__,
                ) from exc
            if not text.strip():
                raise DiscoveryFetchError(
                    "PDF contained no extractable text",
                    category="content_validation_failed",
                )
            links = ()
            page_texts = ()
        elif content_type == "application/json":
            try:
                text = json.dumps(json.loads(body), ensure_ascii=False)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DiscoveryFetchError(
                    "Official JSON response was invalid",
                    category="content_validation_failed",
                    cause_type=type(exc).__name__,
                ) from exc
            links = ()
            page_count = None
            page_texts = (text,)
        else:
            charset = headers.get_content_charset() or "utf-8"
            try:
                html = body.decode(charset, errors="replace")
            except LookupError:
                html = body.decode("utf-8", errors="replace")
            parser = _HTMLContent()
            parser.feed(html)
            parser.close()
            text = "\n".join(parser.text_parts)
            links = tuple(parser.links)
            page_count = None
            page_texts = (text,)

        original_text_length = len(text)
        if len(text) > self.settings.max_extracted_chars:
            text = text[: self.settings.max_extracted_chars]
        retained_text_length = len(text)
        if content_type in {"text/html", "application/xhtml+xml", "application/json"}:
            page_texts = (text,)
        return FetchedPage(
            url=final_url,
            content_type=content_type,
            text=text,
            links=links,
            content_hash=hashlib.sha256(body).hexdigest(),
            page_count=page_count,
            page_texts=page_texts,
            original_text_length=original_text_length,
            retained_text_length=retained_text_length,
            text_truncated=retained_text_length < original_text_length,
            insufficient_content=(
                len(text.strip()) < self.settings.min_extracted_chars
            ),
        )

    def _record_link_decision(self, url: str, decision: str) -> dict | None:
        """Remember one link decision: host, path and why, nothing else.

        Kept in memory for the single-source diagnostic to print. The
        application never logs these, and no query string, fragment or page
        text is recorded.
        """
        if len(self.last_link_decisions) >= MAX_RECORDED_LINK_DECISIONS:
            return None
        try:
            parts = urllib.parse.urlsplit(url)
            host = (parts.hostname or "").lower()
            path = parts.path or "/"
        except (TypeError, ValueError, UnicodeError):
            host, path = "", ""
        entry = {"host": host, "path": path, "decision": decision}
        self.last_link_decisions.append(entry)
        return entry

    def crawl(self, source: DiscoverySource) -> List[FetchedPage]:
        self.last_crawl_stats = _empty_crawl_stats()
        self.last_link_decisions = []
        decision_by_url = {}
        max_depth = self.max_crawl_depth
        self.last_crawl_stats["max_crawl_depth"] = max_depth
        self.last_crawl_stats["max_pages_per_source"] = (
            self.settings.max_pages_per_source
        )
        root_url = self._safe_fetch_url(source, source.source_url)
        # (priority, discovery order, url, depth); the root page always first.
        queue = [(-1, 0, root_url, 0)]
        queued = {root_url}
        discovered = set()
        order = 0
        visited = set()
        pages = []
        while queue and len(visited) < self.settings.max_pages_per_source:
            queue.sort(key=lambda item: (item[0], item[1]))
            _priority, _order, url, depth = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            if self.run_budget is not None:
                self.run_budget.start_page(source.source_id)
            try:
                page = self.fetch(source, url)
            except DiscoveryFetchError as exc:
                page_stage = "root_fetch" if url == root_url else "linked_page"
                if exc.stage is None:
                    exc.stage = page_stage
                if exc.page_stage is None:
                    exc.page_stage = page_stage
                if url == root_url:
                    raise
                self.last_crawl_stats["linked_pages_failed"] += 1
                entry = decision_by_url.get(url)
                if entry is not None:
                    entry["decision"] = "failed"
                _log_fetch_failure(
                    source.source_id,
                    exc,
                    exc.stage,
                    exc.page_stage,
                )
                continue
            if self.run_budget is not None:
                self.run_budget.record_page_fetched()
            pages.append(page)
            if url != root_url:
                self.last_crawl_stats["linked_pages_fetched"] += 1
                entry = decision_by_url.get(url)
                if entry is not None:
                    entry["decision"] = "fetched"
            if page.content_type not in {"text/html", "application/xhtml+xml"}:
                self.last_crawl_stats["pages_links_not_followed_content_type"] += 1
                continue
            if depth >= max_depth:
                # Depth limit reached: this page's links are not followed.
                self.last_crawl_stats["pages_links_not_followed_depth"] += 1
                continue
            for href, label in page.links:
                self.last_crawl_stats["linked_url_references"] += 1
                try:
                    absolute = urllib.parse.urljoin(page.url, href)
                    normalized_url = self._safe_fetch_url(source, absolute)
                    parts = urllib.parse.urlsplit(normalized_url)
                except (DiscoveryFetchError, TypeError, ValueError, UnicodeError) as exc:
                    self.last_crawl_stats["linked_pages_skipped_safety"] += 1
                    self._record_link_decision(
                        urllib.parse.urljoin(page.url, href)
                        if isinstance(href, str)
                        else "",
                        "skipped_safety",
                    )
                    if (
                        isinstance(exc, DiscoveryFetchError)
                        and exc.category == "sensitive_query_rejected"
                    ):
                        logger.info(
                            "Scholarship linked page skipped: source_id=%s "
                            "category=sensitive_query_rejected",
                            source.source_id,
                        )
                    continue
                if normalized_url in discovered:
                    self.last_crawl_stats["linked_pages_skipped_duplicate"] += 1
                    continue
                discovered.add(normalized_url)
                self.last_crawl_stats["linked_urls_discovered"] += 1
                relevance = f"{parts.path} {label}".casefold()
                priority = _link_priority(source, parts, label)
                # Priorities 0-4 are call documents, detail documents and
                # own-domain PDFs: their URL and label need not spell out a
                # relevant term, so the generic filter does not apply.
                if priority > 4 and not any(
                    term in relevance for term in RELEVANT_LINK_TERMS
                ):
                    self.last_crawl_stats["linked_pages_skipped_relevance"] += 1
                    self._record_link_decision(
                        normalized_url, "skipped_relevance",
                    )
                    continue
                if normalized_url not in visited and normalized_url not in queued:
                    order += 1
                    queue.append((priority, order, normalized_url, depth + 1))
                    queued.add(normalized_url)
                    entry = self._record_link_decision(normalized_url, "queued")
                    if entry is not None:
                        decision_by_url[normalized_url] = entry
                else:
                    # Already fetched or already waiting: previously dropped
                    # without a trace. A link back to the root page lands here.
                    self.last_crawl_stats[
                        "linked_pages_skipped_already_queued"
                    ] += 1
                    self._record_link_decision(
                        normalized_url, "already_queued",
                    )
        unfetched = {
            item[2] for item in queue if item[2] not in visited
        }
        self.last_crawl_stats["linked_pages_not_fetched_page_budget"] = len(
            unfetched
        )
        for url in unfetched:
            entry = decision_by_url.get(url)
            if entry is not None:
                entry["decision"] = "not_fetched_page_budget"
        self.last_crawl_stats["linked_pages_skipped"] = (
            self.last_crawl_stats["linked_pages_skipped_safety"]
            + self.last_crawl_stats["linked_pages_skipped_relevance"]
        )
        logger.info(
            "Scholarship crawl finished: source_id=%s max_depth=%s pages_fetched=%d "
            "unique_links=%d link_references=%d",
            source.source_id,
            max_depth,
            len(pages),
            self.last_crawl_stats["linked_urls_discovered"],
            self.last_crawl_stats["linked_url_references"],
        )
        return pages
