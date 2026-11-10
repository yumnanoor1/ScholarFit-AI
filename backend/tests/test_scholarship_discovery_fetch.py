import io
import socket
import ssl
import unittest
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import format_datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.scholarship_discovery_fetch import (
    DiscoveryFetchError,
    OfficialSourceFetcher,
    _retry_delay_seconds,
)
from app.services.scholarship_discovery_sources import SOURCES_BY_ID


def _settings(**changes):
    values = {
        "request_timeout_seconds": 2,
        "max_response_bytes": 2048,
        "max_extracted_chars": 2000,
        "max_pages_per_source": 3,
        "max_retries": 1,
        "request_delay_seconds": 0,
        "user_agent": "FitScholarTest/1.0",
        "min_extracted_chars": 20,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _response(status=200, body=b"ok", headers=b"Content-Type: text/html\r\n"):
    reason = {
        200: b"OK",
        301: b"Moved Permanently",
        400: b"Bad Request",
        413: b"Content Too Large",
        429: b"Too Many Requests",
        504: b"Gateway Timeout",
    }[status]
    return (
        b"HTTP/1.1 " + str(status).encode("ascii") + b" " + reason + b"\r\n"
        + headers
        + b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
        + b"Connection: close\r\n\r\n"
        + body
    )


class _FakeSocket:
    def __init__(self, response):
        self.response = io.BytesIO(response)
        self.sent = bytearray()
        self.peer = None
        self.closed = False

    def makefile(self, mode, buffering=None):
        if mode != "rb" or buffering not in (None, -1):
            raise AssertionError("Unexpected HTTP response stream mode")
        return self.response

    def sendall(self, data):
        self.sent.extend(data)

    def getpeername(self):
        return self.peer

    def close(self):
        self.closed = True


class _FakeSSLContext:
    def wrap_socket(self, sock, server_hostname):
        self.server_hostname = server_hostname
        return sock


class ScholarshipDiscoveryFetchTests(unittest.TestCase):
    def setUp(self):
        self.source = SOURCES_BY_ID["daad-helmut-schmidt"]

    def test_registered_daad_url_matches_official_domain_and_metadata(self):
        expected_url = (
            "https://www2.daad.de/deutschland/stipendium/datenbank/en/"
            "21148-scholarship-database/?detail=50026397"
        )
        fetcher = OfficialSourceFetcher(_settings())

        self.assertEqual(self.source.source_url, expected_url)
        self.assertEqual(self.source.source_id, "daad-helmut-schmidt")
        self.assertEqual(self.source.official_domain, "daad.de")
        self.assertTrue(self.source.trust_reviewed)
        self.assertTrue(self.source.crawl_enabled)
        self.assertEqual(
            fetcher._safe_fetch_url(self.source, expected_url),
            expected_url,
        )

    def test_request_encodes_unicode_and_preserves_existing_escapes(self):
        url = (
            self.source.source_url.partition("?")[0]
            + "merit%2Fdetails?topic=étude&literal=%ZZ"
        )
        address = (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("93.184.216.34", 443),
        )
        fake_socket = _FakeSocket(_response(status=400, body=b"bad request"))

        def connector(family, socket_type, protocol, sockaddr, timeout):
            self.assertEqual(family, socket.AF_INET)
            self.assertEqual(socket_type, socket.SOCK_STREAM)
            self.assertEqual(protocol, socket.IPPROTO_TCP)
            self.assertEqual(timeout, 2)
            fake_socket.peer = sockaddr
            return fake_socket

        fetcher = OfficialSourceFetcher(_settings(), connector=connector)
        with patch.object(fetcher, "_resolve_public_addresses", return_value=[address]):
            with patch(
                "app.services.scholarship_discovery_fetch.ssl.create_default_context",
                return_value=_FakeSSLContext(),
            ):
                status, response_headers, response_body = fetcher._request(
                    self.source,
                    url,
                )

        self.assertEqual(status, 400)
        self.assertEqual(response_headers.get_content_type(), "text/html")
        self.assertEqual(response_body, b"")
        request, body = bytes(fake_socket.sent).split(b"\r\n\r\n", 1)
        self.assertIn(
            b"GET /deutschland/stipendium/datenbank/en/"
            b"21148-scholarship-database/merit%2Fdetails?"
            b"topic=%C3%A9tude&literal=%25ZZ HTTP/1.1",
            request,
        )
        self.assertIn(b"Host: www2.daad.de", request)
        self.assertIn(b"User-Agent: FitScholarTest/1.0", request)
        self.assertEqual(body, b"")
        self.assertTrue(fake_socket.closed)

    def test_registry_daad_301_uses_final_response_for_content_validation(self):
        final_url = (
            "https://www.daad.de/en/studying-in-germany/scholarships/epos/"
        )
        redirect_headers = Message()
        redirect_headers["Location"] = final_url
        final_headers = Message()
        final_headers["Content-Type"] = "text/html; charset=utf-8"
        fetcher = OfficialSourceFetcher(_settings())

        with patch.object(fetcher, "_robots_allowed", return_value=True):
            with patch.object(
                fetcher,
                "_request",
                side_effect=[
                    (301, redirect_headers, b""),
                    (
                        200,
                        final_headers,
                        b"<main><p>Official Master's scholarship information.</p></main>",
                    ),
                ],
            ) as request:
                page = fetcher.fetch(self.source, self.source.source_url)

        self.assertEqual(request.call_args_list[0].args[1], self.source.source_url)
        self.assertEqual(request.call_args_list[1].args[1], final_url)
        self.assertEqual(page.url, final_url)
        self.assertEqual(page.content_type, "text/html")
        self.assertIn("Official Master's scholarship information.", page.text)

    def test_remote_400_and_413_are_not_retried_and_local_size_rejection_is_distinct(self):
        for status in (400, 413):
            with self.subTest(status=status):
                sleep = Mock()
                fetcher = OfficialSourceFetcher(_settings(max_retries=2), sleep=sleep)
                with patch.object(
                    fetcher,
                    "_request",
                    return_value=(status, Message(), b""),
                ) as request:
                    with self.assertRaises(DiscoveryFetchError) as raised:
                        fetcher._fetch_bytes(self.source, self.source.source_url)

                self.assertEqual(request.call_count, 1)
                self.assertEqual(raised.exception.category, "http_status")
                self.assertEqual(raised.exception.status_code, status)
                self.assertEqual(raised.exception.attempt_count, 1)
                self.assertEqual(raised.exception.attempt_limit, 3)
                sleep.assert_not_called()

        address = (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("93.184.216.34", 443),
        )
        fake_socket = _FakeSocket(_response(body=b"oversized"))

        def connector(family, socket_type, protocol, sockaddr, timeout):
            self.assertEqual(family, socket.AF_INET)
            self.assertEqual(socket_type, socket.SOCK_STREAM)
            self.assertEqual(protocol, socket.IPPROTO_TCP)
            self.assertEqual(timeout, 2)
            fake_socket.peer = sockaddr
            return fake_socket

        fetcher = OfficialSourceFetcher(
            _settings(max_response_bytes=4),
            connector=connector,
        )
        with patch.object(fetcher, "_resolve_public_addresses", return_value=[address]):
            with patch(
                "app.services.scholarship_discovery_fetch.ssl.create_default_context",
                return_value=_FakeSSLContext(),
            ):
                with self.assertRaises(DiscoveryFetchError) as raised:
                    fetcher._request(self.source, self.source.source_url)

        self.assertEqual(raised.exception.category, "content_validation_failed")
        self.assertIsNone(raised.exception.status_code)

    def test_retry_after_is_honored_for_429_and_504(self):
        for status in (429, 504):
            with self.subTest(status=status):
                retry_headers = Message()
                retry_headers["Retry-After"] = "7"
                success_headers = Message()
                success_headers["Content-Type"] = "text/html"
                sleep = Mock()
                fetcher = OfficialSourceFetcher(_settings(), sleep=sleep)
                with patch.object(
                    fetcher,
                    "_request",
                    side_effect=[
                        (status, retry_headers, b""),
                        (200, success_headers, b"ok"),
                    ],
                ) as request:
                    fetcher._fetch_bytes(self.source, self.source.source_url)

                self.assertEqual(request.call_count, 2)
                sleep.assert_called_once_with(7)

    def test_retry_after_http_date_invalid_value_and_bounded_wait(self):
        now = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)
        retry_at = format_datetime(now + timedelta(seconds=7), usegmt=True)
        self.assertEqual(_retry_delay_seconds(1, retry_at, now=now), 7)
        self.assertEqual(_retry_delay_seconds(1, "invalid", now=now), 2)
        self.assertIsNone(_retry_delay_seconds(1, "61", now=now))

        retry_headers = Message()
        retry_headers["Retry-After"] = "61"
        sleep = Mock()
        fetcher = OfficialSourceFetcher(_settings(), sleep=sleep)
        with patch.object(
            fetcher,
            "_request",
            return_value=(429, retry_headers, b""),
        ) as request:
            with self.assertRaises(DiscoveryFetchError) as raised:
                fetcher._fetch_bytes(self.source, self.source.source_url)

        request.assert_called_once()
        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.attempt_count, 1)
        sleep.assert_not_called()

    def test_robots_failure_classification_fails_closed_except_for_404(self):
        cases = (
            (403, "http_status", "PermissionError", False),
            (404, "http_status", None, True),
            (503, "http_status", None, False),
            (None, "timeout", "TimeoutError", False),
            (None, "connection_error", "SSLError", False),
        )
        for status, category, cause_type, allowed in cases:
            with self.subTest(status=status, category=category):
                fetcher = OfficialSourceFetcher(_settings())
                failure = DiscoveryFetchError(
                    "sanitized robots failure",
                    status_code=status,
                    category=category,
                    cause_type=cause_type,
                )
                with patch.object(fetcher, "_fetch_bytes", side_effect=failure):
                    self.assertEqual(
                        fetcher._robots_allowed(self.source, self.source.source_url),
                        allowed,
                    )

                host = "www2.daad.de"
                if status == 404:
                    self.assertNotIn(host, fetcher._robots_failures)
                else:
                    details = fetcher._robots_failures[host]
                    self.assertEqual(details.status_code, status)
                    self.assertEqual(details.cause_category, category)
                    self.assertEqual(details.cause_type, cause_type)

    def test_timeout_and_ssl_transport_failures_keep_classification(self):
        cases = (
            (TimeoutError("timeout detail"), "timeout", "TimeoutError"),
            (ConnectionError("connection detail"), "connection_error", "ConnectionError"),
            (ssl.SSLError("TLS detail"), "connection_error", "SSLError"),
        )
        for error, category, cause_type in cases:
            with self.subTest(cause_type=cause_type):
                fetcher = OfficialSourceFetcher(_settings(max_retries=0))
                with patch.object(fetcher, "_request", side_effect=error):
                    with self.assertRaises(DiscoveryFetchError) as raised:
                        fetcher._fetch_bytes(self.source, self.source.source_url)

                self.assertEqual(raised.exception.category, category)
                self.assertEqual(raised.exception.immediate_cause_type, cause_type)
                self.assertNotIn("detail", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
