"""
Checks whether a source URL answers. An administrator starts each check, and the result is only
advice: it never changes verification, and only a 404 or 410 counts as broken. Sites often refuse
automated requests, so a refusal or timeout is reported as inconclusive.

Each destination is resolved and validated before a direct connection to one of those addresses.
DNS lookups use the configured system resolver settings and share a bounded six-second lifetime.
"""
import hashlib
import http.client
import ipaddress
import re
import socket
import ssl
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

import dns.exception
import dns.rdatatype
import dns.resolver

from app.services.source_url_safety import UnsafeSourceURL, validate_source_url

TIMEOUT_SECONDS = 6
DNS_TIMEOUT_SECONDS = TIMEOUT_SECONDS
MAX_REDIRECTS = 3
MAX_CONTENT_HASH_BYTES = 10_000_000
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
BROKEN_CODES = {404, 410}
USER_AGENT = "FitScholars-source-check/1.0"

_AddressInfo = Tuple[int, int, int, str, tuple]
_Connector = Callable[[int, int, int, tuple, Optional[float]], socket.socket]


class _PeerAddressMismatch(OSError):
    pass


def _validated_url_parts(url: str) -> Tuple[urllib.parse.SplitResult, int]:
    validate_source_url(url)
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.casefold()
    default_port = 443 if scheme == "https" else 80
    explicit_port = parts.port
    if explicit_port is not None and explicit_port != default_port:
        raise UnsafeSourceURL("Source URL must use the standard HTTP or HTTPS port.")
    return parts, default_port


def _validate_address_info(address: _AddressInfo, port: int) -> None:
    try:
        family, socket_type, _protocol, _canonical_name, sockaddr = address
        ip_text = sockaddr[0]
        address_port = sockaddr[1]
        if (
            family not in (socket.AF_INET, socket.AF_INET6)
            or socket_type != socket.SOCK_STREAM
            or not isinstance(ip_text, str)
            or "%" in ip_text
            or address_port != port
        ):
            raise ValueError
        ip = ipaddress.ip_address(ip_text)
        if family == socket.AF_INET:
            if ip.version != 4:
                raise ValueError
        elif (
            ip.version != 6
            or len(sockaddr) < 4
            or sockaddr[3] != 0
            or ip.ipv4_mapped is not None
        ):
            raise ValueError
        if (
            not ip.is_global
            or ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError
    except (IndexError, TypeError, ValueError) as error:
        raise OSError("The host did not resolve exclusively to safe public addresses.") from error


def _resolve_public_addresses(
    host: str,
    port: int,
    resolver=None,
    clock: Optional[Callable[[], float]] = None,
) -> List[_AddressInfo]:
    """Resolve A and AAAA using one deadline, then validate every returned address."""
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if literal_ip.version == 4:
            family = socket.AF_INET
            sockaddr = (literal_ip.compressed, port)
        else:
            family = socket.AF_INET6
            sockaddr = (literal_ip.compressed, port, 0, 0)
        address = (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)
        _validate_address_info(address, port)
        return [address]

    monotonic = clock or time.monotonic
    deadline = monotonic() + DNS_TIMEOUT_SECONDS
    addresses = []

    try:
        if resolver is None:
            try:
                dns_resolver = dns.resolver.Resolver(configure=True)
            except NotImplementedError:
                raise OSError("System DNS resolver configuration is unsupported.") from None
        else:
            dns_resolver = resolver
        record_types = (
            (dns.rdatatype.A, socket.AF_INET, 4),
            (dns.rdatatype.AAAA, socket.AF_INET6, 6),
        )
        for record_type, family, ip_version in record_types:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise dns.exception.Timeout("DNS resolution deadline expired.")
            try:
                answer = dns_resolver.resolve(
                    host,
                    record_type,
                    lifetime=remaining,
                    search=True,
                )
            except dns.resolver.NoAnswer:
                continue

            for record in answer:
                ip = ipaddress.ip_address(record.address)
                if ip.version != ip_version:
                    raise ValueError("DNS record type returned an unexpected address family.")
                if family == socket.AF_INET:
                    sockaddr = (ip.compressed, port)
                else:
                    sockaddr = (ip.compressed, port, 0, 0)
                address = (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)
                _validate_address_info(address, port)
                addresses.append(address)
    except (dns.exception.DNSException, OSError, AttributeError, TypeError, ValueError):
        raise OSError("The host did not resolve to safe public addresses within the deadline.") from None

    if monotonic() >= deadline:
        raise OSError("The host did not resolve to safe public addresses within the deadline.")
    if not addresses:
        raise OSError("The host did not resolve to public addresses.")
    return addresses


def is_public_host(host: Optional[str], resolver=None) -> bool:
    if not host:
        return False
    try:
        _resolve_public_addresses(host, 443, resolver=resolver)
    except OSError:
        return False
    return True


def _connect_and_verify_peer(
    address: _AddressInfo,
    connector: _Connector,
    port: int,
) -> socket.socket:
    family, socket_type, protocol, _canonical_name, sockaddr = address
    connected = connector(family, socket_type, protocol, sockaddr, TIMEOUT_SECONDS)
    try:
        peer = connected.getpeername()
        peer_text = peer[0]
        if not isinstance(peer_text, str) or "%" in peer_text or peer[1] != port:
            raise _PeerAddressMismatch("Connected peer did not match a validated address.")
        peer_ip = ipaddress.ip_address(peer_text)
        expected_ip = ipaddress.ip_address(sockaddr[0])
        if (
            peer_ip != expected_ip
            or (peer_ip.version == 6 and peer_ip.ipv4_mapped is not None)
            or not peer_ip.is_global
            or (family == socket.AF_INET6 and (len(peer) < 4 or peer[3] != 0))
        ):
            raise _PeerAddressMismatch("Connected peer did not match a validated address.")
        return connected
    except BaseException:
        connected.close()
        raise


def _connect_validated_address(
    family: int,
    socket_type: int,
    protocol: int,
    sockaddr: tuple,
    timeout: Optional[float],
) -> socket.socket:
    connected = socket.socket(family, socket_type, protocol)
    try:
        connected.settimeout(timeout)
        connected.connect(sockaddr)
        return connected
    except BaseException:
        connected.close()
        raise


def _request(
    url: str,
    *,
    resolver=None,
    connector: Optional[_Connector] = None,
    clock: Optional[Callable[[], float]] = None,
):
    """Connect directly to a validated IP; environment proxy settings are not consulted."""
    parts, port = _validated_url_parts(url)
    host = parts.hostname
    if not host:
        raise ValueError("Source URL has no hostname.")
    addresses = _resolve_public_addresses(host, port, resolver=resolver, clock=clock)
    connect = connector or _connect_validated_address

    connected = None
    last_error = None
    for address in addresses:
        try:
            connected = _connect_and_verify_peer(address, connect, port)
            break
        except _PeerAddressMismatch:
            raise
        except OSError as error:
            last_error = error
    if connected is None:
        if last_error is not None:
            raise last_error
        raise OSError("Could not connect to a validated public address.")

    connection = None
    transport_socket = connected
    try:
        if parts.scheme.casefold() == "https":
            context = ssl.create_default_context()
            transport_socket = context.wrap_socket(connected, server_hostname=host)

        connection = http.client.HTTPConnection(host, port, timeout=TIMEOUT_SECONDS)
        connection.sock = transport_socket
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        connection.putrequest("GET", target, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", parts.netloc)
        connection.putheader("User-Agent", USER_AGENT)
        connection.putheader("Connection", "close")
        connection.endheaders()

        response = connection.getresponse()
        code = response.status
        redirect = response.getheader("Location") if 300 <= code < 400 else None
        if redirect:
            return code, redirect, None

        content_length = response.getheader("Content-Length")
        if content_length is not None and int(content_length) > MAX_CONTENT_HASH_BYTES:
            return code, None, None

        digest = hashlib.sha256()
        total_bytes = 0
        while total_bytes <= MAX_CONTENT_HASH_BYTES:
            body = response.read(min(64 * 1024, MAX_CONTENT_HASH_BYTES + 1 - total_bytes))
            if not body:
                return code, None, digest.hexdigest()
            total_bytes += len(body)
            if total_bytes > MAX_CONTENT_HASH_BYTES:
                return code, None, None
            digest.update(body)
        return code, None, None
    finally:
        if connection is not None:
            connection.close()
        else:
            transport_socket.close()


def check_url(url: str, fetch=None, host_allowed=None) -> dict:
    default_transport = fetch is None or fetch is _request
    if fetch is None:
        fetch = _request
    elif not default_transport and host_allowed is None:
        host_allowed = is_public_host

    result = {"url": url, "status": "inconclusive", "http_status": None, "detail": None,
              "checked_at": datetime.now(timezone.utc).isoformat(), "content_hash": None}
    current = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                parts, _port = _validated_url_parts(current)
            except (UnsafeSourceURL, TypeError, ValueError, UnicodeError):
                result.update(status="invalid", detail="Not a valid HTTP or HTTPS source URL.")
                return result
            if not default_transport and host_allowed is not None and not host_allowed(parts.hostname):
                result["detail"] = "The address couldn't be resolved to a public site, so it wasn't requested."
                return result
            fetched = fetch(current)
            if len(fetched) == 2:
                code, target = fetched
                content_hash = None
            else:
                code, target, content_hash = fetched
            result["http_status"] = code
            if not target:
                break
            current = urllib.parse.urljoin(current, target)
            content_hash = None
        else:
            result["detail"] = "Too many redirects."
            return result
    except (http.client.HTTPException, OSError, TimeoutError, ValueError) as error:
        result["detail"] = f"No answer: {type(error).__name__}"
        return result
    if code in BROKEN_CODES:
        result.update(status="broken", detail=f"The site answered {code}.")
    elif 200 <= code < 300:
        result.update(status="ok", detail="The page answered. That doesn't confirm what it says.")
        if isinstance(content_hash, str) and _SHA256_HEX.fullmatch(content_hash):
            result["content_hash"] = content_hash
    else:
        result["detail"] = f"The site answered {code}, which may just be refusing automated checks."
    return result
