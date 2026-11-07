"""Bounded fetch and extraction primitives for registry-approved official hosts."""
import email.message
import hashlib
import http.client
import ipaddress
import json
import logging
import socket
import ssl
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable, List, Optional, Tuple

import dns.exception
import dns.rdatatype
import dns.resolver

from app.core.config import ScholarshipDiscoverySettings
from app.services.scholarship_discovery_sources import DiscoverySource

logger = logging.getLogger(__name__)
DNS_TIMEOUT_SECONDS = 6
MAX_REDIRECTS = 4
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}
ALLOWED_PAGE_TYPES = {"text/html", "application/xhtml+xml", "application/pdf", "application/json"}
RELEVANT_LINK_TERMS = ("scholarship", "funding", "award", "grant", "master", "study", "student", "stipendium")


class DiscoveryFetchError(RuntimeError):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


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


@dataclass(frozen=True)
class FetchedPage:
    url: str
    content_type: str
    text: str
    links: Tuple[Tuple[str, str], ...]
    content_hash: str
    page_count: Optional[int] = None


class _HTMLContent(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text_parts = []
        self.links = []
        self._ignored = 0
        self._link_href = None
        self._link_text = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored += 1
        if tag == "a":
            self._link_href = attributes.get("href")
            self._link_text = []

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self._ignored:
            self._ignored -= 1
        if tag == "a" and self._link_href:
            label = " ".join(" ".join(self._link_text).split())
            self.links.append((self._link_href, label))
            self._link_href = None
            self._link_text = []

    def handle_data(self, data):
        if self._ignored:
            return
        text = " ".join(data.split())
        if text:
            self.text_parts.append(text)
            if self._link_href is not None:
                self._link_text.append(text)


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
    ):
        self.settings = settings
        self.resolver = resolver
        self.connector = connector
        self.sleep = sleep
        self.clock = clock
        self._robots = {}
        self._last_request = {}

    def _validate_url(self, source: DiscoverySource, url: str) -> urllib.parse.SplitResult:
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
            or not is_registered_domain(host, source.official_domain)
            or (port is not None and port != (443 if parts.scheme == "https" else 80))
        ):
            raise DiscoveryFetchError("URL is outside the registered official domain")
        return parts

    def _resolve_public_addresses(self, host: str, port: int) -> List[tuple]:
        deadline = self.clock() + DNS_TIMEOUT_SECONDS
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
        except (dns.exception.DNSException, OSError, AttributeError, IndexError, TypeError, ValueError) as exc:
            raise DiscoveryFetchError("Official host did not resolve to safe public addresses") from exc

        if self.clock() >= deadline:
            raise DiscoveryFetchError("Official host did not resolve to safe public addresses")
        if not addresses:
            raise DiscoveryFetchError("Official host did not resolve to public addresses")
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
                "Official host did not resolve exclusively to public addresses"
            ) from exc

    def _request(self, source: DiscoverySource, url: str) -> Tuple[int, email.message.Message, bytes]:
        parts = self._validate_url(source, url)
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "https" else 80)
        addresses = self._resolve_public_addresses(host, port)
        request_target = parts.path or "/"
        if parts.query:
            request_target += "?" + parts.query
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/pdf,application/json,text/plain",
            "Host": parts.netloc,
            "Connection": "close",
        }
        context = ssl.create_default_context() if parts.scheme == "https" else None
        last_error = None

        for address in addresses:
            if parts.scheme == "https":
                connection = _PinnedHTTPSConnection(
                    host,
                    port,
                    address,
                    self.connector,
                    self.settings.request_timeout_seconds,
                    context,
                )
            else:
                connection = _PinnedHTTPConnection(
                    host,
                    port,
                    address,
                    self.connector,
                    self.settings.request_timeout_seconds,
                )
            response = None
            try:
                connection.request("GET", request_target, headers=headers)
                response = connection.getresponse()
                response_headers = response.headers
                if not 200 <= response.status < 300:
                    return response.status, response_headers, b""
                length = response_headers.get("Content-Length")
                if length and int(length) > self.settings.max_response_bytes:
                    raise DiscoveryFetchError("Official response exceeded the configured size limit")
                body = response.read(self.settings.max_response_bytes + 1)
                if len(body) > self.settings.max_response_bytes:
                    raise DiscoveryFetchError("Official response exceeded the configured size limit")
                return response.status, response_headers, body
            except OSError as exc:
                last_error = exc
            finally:
                try:
                    if response is not None:
                        response.close()
                finally:
                    connection.close()

        if last_error is not None:
            raise last_error
        raise DiscoveryFetchError("Official host did not resolve to public addresses")

    def _throttle(self, host: str):
        now = self.clock()
        wait = self.settings.request_delay_seconds - (now - self._last_request.get(host, now))
        if wait > 0:
            self.sleep(wait)
        self._last_request[host] = self.clock()

    def _fetch_bytes(
        self,
        source: DiscoverySource,
        url: str,
        allowed_types=ALLOWED_PAGE_TYPES,
    ) -> Tuple[str, email.message.Message, bytes]:
        current = url
        for redirect_count in range(MAX_REDIRECTS + 1):
            parts = self._validate_url(source, current)
            host = parts.hostname.lower()
            last_error = None
            for attempt in range(self.settings.max_retries + 1):
                self._throttle(host)
                try:
                    status, headers, body = self._request(source, current)
                except (TimeoutError, OSError, ValueError) as exc:
                    last_error = exc
                    if attempt < self.settings.max_retries:
                        self.sleep(min(2 ** attempt, 8))
                        continue
                    raise DiscoveryFetchError(f"Fetch failed: {type(exc).__name__}") from exc
                if 300 <= status < 400:
                    target = headers.get("Location")
                    if not target:
                        raise DiscoveryFetchError(f"Redirect had no location (HTTP {status})")
                    current = urllib.parse.urljoin(current, target)
                    break
                if status in TRANSIENT_STATUSES and attempt < self.settings.max_retries:
                    self.sleep(min(2 ** attempt, 8))
                    continue
                if not 200 <= status < 300:
                    raise DiscoveryFetchError(f"Official host returned HTTP {status}", status_code=status)
                mime_type = headers.get_content_type().lower()
                if mime_type not in allowed_types:
                    raise DiscoveryFetchError(f"Unsupported content type: {mime_type}")
                return current, headers, body
            else:
                raise DiscoveryFetchError(f"Fetch failed: {type(last_error).__name__ if last_error else 'HTTP error'}")
            if redirect_count == MAX_REDIRECTS:
                raise DiscoveryFetchError("Too many redirects")
        raise DiscoveryFetchError("Too many redirects")

    def _robots_allowed(self, source: DiscoverySource, url: str) -> bool:
        parts = self._validate_url(source, url)
        host = parts.hostname.lower()
        if host not in self._robots:
            robots_url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
            try:
                final_url, headers, body = self._fetch_bytes(source, robots_url, allowed_types={"text/plain"})
            except DiscoveryFetchError as exc:
                if exc.status_code == 404:
                    self._robots[host] = None
                else:
                    logger.warning("Discovery robots check unavailable for %s: %s", source.source_id, type(exc).__name__)
                    self._robots[host] = False
            else:
                parser = urllib.robotparser.RobotFileParser(final_url)
                parser.parse(body.decode(headers.get_content_charset() or "utf-8", errors="replace").splitlines())
                self._robots[host] = parser
        policy = self._robots[host]
        return policy is None or policy is not False and policy.can_fetch(self.settings.user_agent, url)

    def fetch(self, source: DiscoverySource, url: str) -> FetchedPage:
        if not self._robots_allowed(source, url):
            raise DiscoveryFetchError("robots.txt disallows this URL or could not be checked")
        final_url, headers, body = self._fetch_bytes(source, url)
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
                raise DiscoveryFetchError(f"PDF extraction failed: {type(exc).__name__}") from exc
            if not text.strip():
                raise DiscoveryFetchError("PDF contained no extractable text")
            links = ()
        elif content_type == "application/json":
            try:
                text = json.dumps(json.loads(body), ensure_ascii=False)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DiscoveryFetchError("Official JSON response was invalid") from exc
            links = ()
            page_count = None
        else:
            charset = headers.get_content_charset() or "utf-8"
            try:
                html = body.decode(charset, errors="replace")
            except LookupError:
                html = body.decode("utf-8", errors="replace")
            parser = _HTMLContent()
            parser.feed(html)
            text = "\n".join(parser.text_parts)
            links = tuple(parser.links)
            page_count = None
            if not text.strip():
                raise DiscoveryFetchError("Official page contained no readable text")

        if len(text) > self.settings.max_extracted_chars:
            text = text[: self.settings.max_extracted_chars]
        return FetchedPage(
            url=final_url,
            content_type=content_type,
            text=text,
            links=links,
            content_hash=hashlib.sha256(body).hexdigest(),
            page_count=page_count,
        )

    def crawl(self, source: DiscoverySource) -> List[FetchedPage]:
        queue = [source.source_url]
        visited = set()
        pages = []
        while queue and len(visited) < self.settings.max_pages_per_source:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            try:
                page = self.fetch(source, url)
            except DiscoveryFetchError as exc:
                if url == source.source_url:
                    raise
                logger.warning(
                    "Discovery linked page fetch failed for %s: %s",
                    source.source_id,
                    type(exc).__name__,
                )
                continue
            pages.append(page)
            if page.content_type not in {"text/html", "application/xhtml+xml"}:
                continue
            for href, label in page.links:
                try:
                    absolute = urllib.parse.urljoin(page.url, href)
                    parts = urllib.parse.urlsplit(absolute)
                except (TypeError, ValueError):
                    continue
                if (
                    parts.scheme not in {"http", "https"}
                    or not is_registered_domain(parts.hostname, source.official_domain)
                ):
                    continue
                relevance = f"{parts.path} {label}".casefold()
                if any(term in relevance for term in RELEVANT_LINK_TERMS) and absolute not in visited and absolute not in queue:
                    queue.append(absolute)
        return pages
