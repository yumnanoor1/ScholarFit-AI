"""Bounded fetch and extraction primitives for discovery and Admin imports."""
import email.message
import email.utils
import hashlib
import http.client
import ipaddress
import json
import logging
import re
import socket
import ssl
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Callable, List, Optional, Tuple

import dns.exception
import dns.rdatatype
import dns.resolver

from app.core.config import ScholarshipDiscoverySettings
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


def _empty_crawl_stats() -> dict:
    return {
        "linked_urls_discovered": 0,
        "linked_pages_attempted": 0,
        "linked_pages_fetched": 0,
        "linked_pages_failed": 0,
        "linked_pages_skipped_safety": 0,
        "linked_pages_skipped_relevance": 0,
        "linked_pages_skipped": 0,
    }


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
    ):
        self.settings = settings
        self.resolver = resolver
        self.connector = connector
        self.sleep = sleep
        self.clock = clock
        self.lock_check = lock_check
        self.run_budget = run_budget
        self._robots = {}
        self._robots_failures = {}
        self._last_request = {}
        self.last_crawl_stats = _empty_crawl_stats()

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

    def _safe_fetch_url(self, source: Optional[DiscoverySource], url: str) -> str:
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
            return normalized_url
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
            import fitz
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

    def fetch_import_url(self, url: str, source_type: str) -> FetchedPage:
        allowed_types = {
            "webpage": {"text/html", "application/xhtml+xml"},
            "pdf_url": {"application/pdf"},
        }
        if source_type not in allowed_types:
            raise DiscoveryFetchError("Unsupported import source type")
        final_url, headers, body = self._fetch_bytes(
            None,
            url,
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
                import fitz
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

    def crawl(self, source: DiscoverySource) -> List[FetchedPage]:
        self.last_crawl_stats = _empty_crawl_stats()
        root_url = self._safe_fetch_url(source, source.source_url)
        queue = [root_url]
        visited = set()
        pages = []
        while queue and len(visited) < self.settings.max_pages_per_source:
            url = queue.pop(0)
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
            if page.content_type not in {"text/html", "application/xhtml+xml"}:
                continue
            for href, label in page.links:
                self.last_crawl_stats["linked_urls_discovered"] += 1
                try:
                    absolute = urllib.parse.urljoin(page.url, href)
                    normalized_url = self._safe_fetch_url(source, absolute)
                    parts = urllib.parse.urlsplit(normalized_url)
                except (DiscoveryFetchError, TypeError, ValueError, UnicodeError) as exc:
                    self.last_crawl_stats["linked_pages_skipped_safety"] += 1
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
                relevance = f"{parts.path} {label}".casefold()
                if not any(term in relevance for term in RELEVANT_LINK_TERMS):
                    self.last_crawl_stats["linked_pages_skipped_relevance"] += 1
                    continue
                if normalized_url not in visited and normalized_url not in queue:
                    queue.append(normalized_url)
        self.last_crawl_stats["linked_pages_skipped"] = (
            self.last_crawl_stats["linked_pages_skipped_safety"]
            + self.last_crawl_stats["linked_pages_skipped_relevance"]
        )
        return pages
