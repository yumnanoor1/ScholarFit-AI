"""
Checks whether a source URL answers. An administrator starts each check, and the result is only
advice: it never changes verification, and only a 404 or 410 counts as broken. Sites often refuse
automated requests, so a refusal or timeout is reported as inconclusive.

Addresses are checked before each request, including after redirects, so an admin-entered URL
can't reach the server's own network.
"""
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

TIMEOUT_SECONDS = 6
MAX_REDIRECTS = 3
BROKEN_CODES = {404, 410}
USER_AGENT = "FitScholars-source-check/1.0"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def is_public_host(host) -> bool:
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except (socket.gaierror, UnicodeError):
        return False
    return bool(addresses) and all(ipaddress.ip_address(item.split("%")[0]).is_global for item in addresses)


def _request(url):
    """(status code, redirect target or None). Raises URLError on network failure."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with _opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, None
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Location") if 300 <= error.code < 400 else None


def check_url(url: str, fetch=_request, host_allowed=is_public_host) -> dict:
    result = {"url": url, "status": "inconclusive", "http_status": None, "detail": None,
              "checked_at": datetime.now(timezone.utc).isoformat()}
    current = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            parts = urllib.parse.urlsplit(current)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                result.update(status="invalid", detail="Not a web address.")
                return result
            if not host_allowed(parts.hostname):
                result["detail"] = "The address couldn't be resolved to a public site, so it wasn't requested."
                return result
            code, target = fetch(current)
            result["http_status"] = code
            if not target:
                break
            current = urllib.parse.urljoin(current, target)
        else:
            result["detail"] = "Too many redirects."
            return result
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        result["detail"] = f"No answer: {type(error).__name__}"
        return result
    if code in BROKEN_CODES:
        result.update(status="broken", detail=f"The site answered {code}.")
    elif 200 <= code < 300:
        result.update(status="ok", detail="The page answered. That doesn't confirm what it says.")
    else:
        result["detail"] = f"The site answered {code}, which may just be refusing automated checks."
    return result
