import os
import subprocess
import sys
import unittest
import urllib.parse
from email.message import Message
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from app.services.scholarship_discovery_budget import (
    DiscoveryRunBudget,
    DiscoveryRunLimitExceeded,
)
from app.services.scholarship_discovery_fetch import (
    DiscoveryFetchError,
    FetchedPage,
    OfficialSourceFetcher,
    _sanitize_diagnostic_message,
    _sanitize_diagnostic_url,
)
from app.services.scholarship_discovery_sources import SOURCES_BY_ID


def _settings(**changes):
    values = {
        "request_timeout_seconds": 2,
        "max_response_bytes": 4096,
        "max_extracted_chars": 5000,
        "max_pages_per_source": 5,
        "max_retries": 1,
        "request_delay_seconds": 0,
        "user_agent": "FitScholarPlaywrightTest/1.0",
        "min_extracted_chars": 20,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _offline_public_resolver(host, record_type, lifetime=None, search=False):
    import dns.rdatatype
    import dns.resolver as _dns_resolver

    if int(record_type) == int(dns.rdatatype.A):
        return [SimpleNamespace(address="93.184.216.34")]
    raise _dns_resolver.NoAnswer()


class _FakeResponse:
    def __init__(self, *, url, status=200, headers=None, body=b""):
        self.url = url
        self.status = status
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}
        self._body = body
        self.body_calls = 0

    def body(self):
        self.body_calls += 1
        return self._body


class _FakeFrame:
    def __init__(self, page, *, is_main_frame):
        self.page = page


class _FakeRequest:
    def __init__(
        self,
        url,
        page,
        redirected_from=None,
        *,
        navigation=True,
        frame_error=None,
    ):
        self.url = url
        self._frame = page.main_frame if navigation else _FakeFrame(page, is_main_frame=False)
        self._frame_error = frame_error
        self.redirected_from = redirected_from
        self._navigation = navigation

    @property
    def frame(self):
        if self._frame_error is not None:
            raise self._frame_error
        return self._frame

    def is_navigation_request(self):
        return self._navigation


class _FakeRoute:
    def __init__(self, request):
        self.request = request
        self.aborted = False
        self.continued = False

    def continue_(self):
        self.continued = True

    def abort(self):
        self.aborted = True


class _FakeWebSocketRoute:
    def __init__(self):
        self.closed = False
        self.close_args = None

    def close(self, *, code=None, reason=None):
        self.closed = True
        self.close_args = (code, reason)


class _FakePage:
    def __init__(self, *, response=None, response_sequence=None, html="", title="Mock scholarship title", content_error=None, goto_error=None, close_error=None, by_url=None):
        self._response = response
        self._response_sequence = list(response_sequence or [])
        self._html = html
        self._title = title
        self._content_error = content_error
        self._goto_error = goto_error
        self._close_error = close_error
        self._by_url = by_url or {}
        self.closed = False
        self.goto_calls = []
        self.timeouts = []
        self.main_frame = _FakeFrame(self, is_main_frame=True)
        self._route_handler = None
        self._websocket_handler = None

    def route(self, _pattern, handler):
        self._route_handler = handler

    def route_web_socket(self, _pattern, handler):
        self._websocket_handler = handler

    def set_default_navigation_timeout(self, ms):
        self.timeouts.append(("nav", ms))

    def set_default_timeout(self, ms):
        self.timeouts.append(("default", ms))

    def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls.append((url, wait_until, timeout))
        route = _FakeRoute(_FakeRequest(url, self))
        self._route_handler(route)
        if route.aborted:
            raise RuntimeError("request aborted")
        spec = self._by_url.get(url)
        if spec is None and url.endswith("/robots.txt"):
            spec = self._by_url.get("__robots__")
        if spec is not None:
            if "goto_error" in spec and spec["goto_error"] is not None:
                raise spec["goto_error"]
            self._html = spec.get("html", self._html)
            self._content_error = spec.get("content_error", self._content_error)
            response = spec.get("response", self._response)
            return self._follow_fake_redirect(url, response)
        if self._goto_error is not None:
            raise self._goto_error
        if self._response_sequence:
            response = self._response_sequence.pop(0)
        else:
            response = self._response
        return self._follow_fake_redirect(url, response)

    def _follow_fake_redirect(self, initial_url, response):
        final_url = getattr(response, "url", initial_url)
        if final_url != initial_url:
            route = _FakeRoute(
                _FakeRequest(
                    final_url,
                    self,
                    redirected_from=_FakeRequest(initial_url, self),
                )
            )
            self._route_handler(route)
            if route.aborted:
                raise RuntimeError("redirect request aborted")
        return response

    def content(self):
        if self._content_error is not None:
            raise self._content_error
        return self._html

    def title(self):
        return self._title

    def close(self):
        self.closed = True
        if self._close_error is not None:
            raise self._close_error


class _FakeContext:
    def __init__(self, pages):
        self._pages = list(pages)
        self._opened_pages = []
        self.new_page_calls = 0
        self.closed = False
        self.default_nav_timeouts = []
        self.default_timeouts = []
        self._route_handler = None
        self._websocket_handler = None

    def new_page(self):
        self.new_page_calls += 1
        if not self._pages:
            raise RuntimeError("no fake pages left")
        page = self._pages.pop(0)
        self._opened_pages.append(page)
        if self._route_handler is not None:
            page._route_handler = self._route_handler
        if self._websocket_handler is not None:
            page._websocket_handler = self._websocket_handler
        return page

    def route(self, _pattern, handler):
        self._route_handler = handler
        for page in self._opened_pages:
            page._route_handler = handler

    def unroute(self, _pattern, handler):
        if self._route_handler is handler:
            self._route_handler = None
            for page in self._opened_pages:
                page._route_handler = None

    def route_web_socket(self, _pattern, handler):
        self._websocket_handler = handler
        for page in self._opened_pages:
            page._websocket_handler = handler

    def set_default_navigation_timeout(self, ms):
        self.default_nav_timeouts.append(ms)

    def set_default_timeout(self, ms):
        self.default_timeouts.append(ms)

    def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, context):
        self._context = context
        self.closed = False
        self.new_context_calls = []

    def new_context(self, **kwargs):
        self.new_context_calls.append(kwargs)
        return self._context

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, browser):
        self._browser = browser
        self.launch_calls = []

    def launch(self, **kwargs):
        self.launch_calls.append(kwargs)
        return self._browser


class _FakePlaywright:
    def __init__(self, browser):
        self.chromium = _FakeChromium(browser)
        self.stopped = False

    def stop(self):
        self.stopped = True


class PlaywrightFetcherTests(unittest.TestCase):
    def setUp(self):
        self.source = SOURCES_BY_ID["daad-helmut-schmidt"]
        self.robots_url = "https://www2.daad.de/robots.txt"

    def _robots_page(self):
        return _FakePage(
            by_url={
                "__robots__": {
                    "response": _FakeResponse(url=self.robots_url, status=404, headers={"content-type": "text/plain"}, body=b""),
                    "html": "",
                }
            }
        )

    def _fetcher(
        self,
        page,
        *,
        robots=True,
        run_budget=None,
        allowed_request_hosts=None,
        resolver=None,
        **kwargs,
    ):
        pages = ([self._robots_page()] if robots else []) + ([page] if page is not None else [])
        context = _FakeContext(pages)
        browser = _FakeBrowser(context)
        pw = _FakePlaywright(browser)
        fetcher = OfficialSourceFetcher(
            _settings(**kwargs),
            run_budget=run_budget,
            allowed_request_hosts=allowed_request_hosts,
            resolver=resolver or _offline_public_resolver,
            playwright_factory=lambda: pw,
        )
        fetcher._test_pw = pw
        fetcher._test_browser = browser
        fetcher._test_context = context
        return fetcher

    def _install_route_policy(self, fetcher, page):
        if fetcher.resolver is None:
            fetcher.resolver = _offline_public_resolver
        if fetcher._allowed_request_hosts is None:
            return fetcher._install_request_controls(page, self.source)
        context = _FakeContext([])
        fetcher._context = context
        failures = fetcher._install_request_controls(page, self.source)
        page._route_handler = context._route_handler
        page._websocket_handler = context._websocket_handler
        return failures

    def test_http_503_then_success_retries_with_fresh_page(self):
        budget = DiscoveryRunBudget(
            max_sources=1,
            max_pages=1,
            max_pages_per_source=1,
            max_http_attempts=5,
            max_candidates=0,
            max_provider_attempts=0,
            duration_seconds=10,
            start_deadline_timer=False,
        )
        budget.start()
        first = _FakeResponse(url=self.source.source_url, status=503, headers={"content-type": "text/html"}, body=b"unavailable")
        second = _FakeResponse(url=self.source.source_url, status=200, headers={"content-type": "text/html"}, body=b"<html>raw</html>")
        first_page = _FakePage(response=first, html="")
        second_page = _FakePage(
            response=second,
            html="<html><body><main><h1>Master Scholarship</h1><p>Apply now</p></main></body></html>",
        )
        context = _FakeContext([self._robots_page(), first_page, second_page])
        fetcher = self._fetcher_with_context(context, run_budget=budget)
        result = fetcher.fetch(self.source, self.source.source_url)
        self.assertIn("Master Scholarship", result.text)
        self.assertTrue(first_page.closed)
        self.assertTrue(second_page.closed)
        self.assertEqual(context.new_page_calls, 3)
        self.assertEqual(fetcher.last_navigation_diagnostics[0]["http_status"], 503)
        self.assertEqual(fetcher.last_navigation_diagnostics[0]["retry_decision"], "retry")
        self.assertEqual(fetcher.last_navigation_diagnostics[1]["http_status"], 200)
        self.assertEqual(fetcher.last_navigation_diagnostics[1]["outcome"], "navigation_succeeded")
        fetcher.close()

    def test_http_503_retry_exhaustion_preserves_last_status(self):
        budget = DiscoveryRunBudget(
            max_sources=1,
            max_pages=1,
            max_pages_per_source=1,
            max_http_attempts=10,
            max_candidates=0,
            max_provider_attempts=0,
            duration_seconds=10,
            start_deadline_timer=False,
        )
        budget.start()
        resp = _FakeResponse(url=self.source.source_url, status=503, body=b"unavailable")
        first_page = _FakePage(response=resp, html="")
        second_page = _FakePage(response=resp, html="")
        context = _FakeContext([self._robots_page(), first_page, second_page])
        fetcher = self._fetcher_with_context(context, run_budget=budget)
        with self.assertRaises(DiscoveryFetchError) as raised:
            fetcher.fetch(self.source, self.source.source_url)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.attempt_count, 2)
        self.assertEqual(raised.exception.attempt_limit, 2)
        self.assertEqual(len(fetcher.last_navigation_diagnostics), 2)
        self.assertTrue(all(item["retry_decision"] in {"retry", "exhausted"} for item in fetcher.last_navigation_diagnostics))
        self.assertEqual(fetcher.last_navigation_diagnostics[-1]["retry_reason"], "http_503_retry_limit")
        self.assertTrue(first_page.closed)
        self.assertTrue(second_page.closed)
        self.assertEqual(context.new_page_calls, 3)
        fetcher.close()

    def test_navigation_timeout_is_not_retried(self):
        budget = DiscoveryRunBudget(
            max_sources=1,
            max_pages=1,
            max_pages_per_source=1,
            max_http_attempts=5,
            max_candidates=0,
            max_provider_attempts=0,
            duration_seconds=10,
            start_deadline_timer=False,
        )
        budget.start()
        page = _FakePage(goto_error=type("TimeoutError", (Exception,), {})("Timeout 2000ms exceeded"))
        fetcher = self._fetcher(page, robots=True, run_budget=budget)
        with self.assertRaises(DiscoveryFetchError) as raised:
            fetcher.fetch(self.source, self.source.source_url)
        self.assertEqual(raised.exception.category, "timeout")
        self.assertEqual(len(fetcher.last_navigation_diagnostics), 1)
        self.assertEqual(fetcher.last_navigation_diagnostics[0]["retry_decision"], "none")
        fetcher.close()

    def test_http_429_valid_retry_after_is_respected(self):
        sleep = Mock()
        first = _FakeResponse(
            url=self.source.source_url,
            status=429,
            headers={"content-type": "text/html", "retry-after": "2"},
            body=b"",
        )
        second = _FakeResponse(
            url=self.source.source_url,
            status=200,
            headers={"content-type": "text/html"},
            body=b"<html>raw</html>",
        )
        first_page = _FakePage(response=first, html="")
        second_page = _FakePage(
            response=second,
            html="<html><body><main><h1>Master Scholarship</h1><p>Apply now</p></main></body></html>",
        )
        context = _FakeContext([self._robots_page(), first_page, second_page])
        fetcher = self._fetcher_with_context(context, sleep=sleep)
        result = fetcher.fetch(self.source, self.source.source_url)
        self.assertIn("Master Scholarship", result.text)
        sleep.assert_called_once_with(2.0)
        self.assertEqual(fetcher.last_navigation_diagnostics[0]["retry_delay"], 2.0)
        self.assertEqual(fetcher.last_navigation_diagnostics[0]["retry_decision"], "retry")
        fetcher.close()

    def test_http_429_missing_or_malformed_retry_after_uses_backoff(self):
        cases = [
            ("missing", {"content-type": "text/html"}, 1.0),
            ("malformed", {"content-type": "text/html", "retry-after": "not-a-date"}, 1.0),
        ]
        for name, headers, expected_delay in cases:
            with self.subTest(name=name):
                sleep = Mock()
                first = _FakeResponse(url=self.source.source_url, status=429, headers=headers, body=b"")
                second = _FakeResponse(
                    url=self.source.source_url,
                    status=200,
                    headers={"content-type": "text/html"},
                    body=b"<html>raw</html>",
                )
                first_page = _FakePage(response=first, html="")
                second_page = _FakePage(
                    response=second,
                    html="<html><body><main><h1>Master Scholarship</h1><p>Apply now</p></main></body></html>",
                )
                context = _FakeContext([self._robots_page(), first_page, second_page])
                fetcher = self._fetcher_with_context(context, sleep=sleep)
                result = fetcher.fetch(self.source, self.source.source_url)
                self.assertIn("Master Scholarship", result.text)
                sleep.assert_called_once_with(expected_delay)
                self.assertEqual(fetcher.last_navigation_diagnostics[0]["retry_delay"], expected_delay)
                fetcher.close()

    def test_non_retryable_http_statuses_do_not_retry(self):
        for status in (400, 401, 403, 404, 413):
            with self.subTest(status=status):
                resp = _FakeResponse(url=self.source.source_url, status=status, body=b"")
                page = _FakePage(response=resp, html="")
                fetcher = self._fetcher(page, robots=True)
                with self.assertRaises(DiscoveryFetchError) as raised:
                    fetcher.fetch(self.source, self.source.source_url)
                self.assertEqual(raised.exception.status_code, status)
                self.assertEqual(fetcher._test_context.new_page_calls, 2)
                self.assertEqual(fetcher.last_navigation_diagnostics[0]["retry_decision"], "none")
                fetcher.close()

    def test_missing_response_metadata_is_recorded(self):
        resp = _FakeResponse(url=self.source.source_url, status=None, headers={}, body=b"<html>raw</html>")
        page = _FakePage(response=resp, html="")
        fetcher = self._fetcher(page, robots=True)
        with self.assertRaises(DiscoveryFetchError) as raised:
            fetcher.fetch(self.source, self.source.source_url)
        self.assertIsNone(raised.exception.status_code)
        self.assertEqual(raised.exception.category, "unknown")
        attempt = fetcher.last_navigation_diagnostics[0]
        self.assertTrue(attempt["response_present"])
        self.assertIsNone(attempt["http_status"])
        self.assertFalse(attempt["content_length_present"])
        fetcher.close()

    def test_content_length_precheck_rejects_before_body(self):
        resp = _FakeResponse(
            url=self.source.source_url,
            status=200,
            headers={"content-type": "text/html", "content-length": "99999"},
            body=b"small",
        )
        page = _FakePage(response=resp, html="")
        fetcher = self._fetcher(page, robots=True)
        with self.assertRaises(DiscoveryFetchError) as raised:
            fetcher.fetch(self.source, self.source.source_url)
        self.assertEqual(raised.exception.category, "content_validation_failed")
        self.assertEqual(resp.body_calls, 0)
        attempt = fetcher.last_navigation_diagnostics[0]
        self.assertEqual(attempt["content_length"], 99999)
        self.assertEqual(attempt["response_size"], 99999)
        self.assertEqual(attempt["response_size_source"], "content_length")
        fetcher.close()

    def test_dns_connection_and_tls_errors_are_classified(self):
        cases = [
            ("net::ERR_NAME_NOT_RESOLVED", "dns_error"),
            ("net::ERR_CONNECTION_REFUSED", "connection_error"),
            ("net::ERR_CERT_AUTHORITY_INVALID", "tls_error"),
        ]
        for message, category in cases:
            with self.subTest(category=category):
                page = _FakePage(goto_error=RuntimeError(message))
                fetcher = self._fetcher(page, robots=True)
                with self.assertRaises(DiscoveryFetchError) as raised:
                    fetcher.fetch(self.source, self.source.source_url)
                self.assertEqual(raised.exception.category, category)
                self.assertEqual(fetcher.last_navigation_diagnostics[0]["retry_decision"], "none")
                fetcher.close()

    def test_sensitive_url_and_message_are_sanitized_in_navigation_diagnostics(self):
        self.assertEqual(
            _sanitize_diagnostic_url("https://user:secret@www2.daad.de/path?token=SECRET_TOKEN_123#frag"),
            "https://www2.daad.de/path",
        )
        sanitized = _sanitize_diagnostic_message(
            RuntimeError("token=SECRET_TOKEN_123 Authorization: Bearer SECRET https://secret.example/path")
        )
        self.assertNotIn("SECRET_TOKEN_123", sanitized)
        self.assertNotIn("secret.example", sanitized)
        self.assertIn("<redacted>", sanitized)

    def test_diagnostic_failure_does_not_mask_original_fetch_error(self):
        page = _FakePage(goto_error=RuntimeError("net::ERR_NAME_NOT_RESOLVED"))
        fetcher = self._fetcher(page, robots=True)
        with patch.object(fetcher, "_record_navigation_attempt", side_effect=RuntimeError("diagnostic failure")):
            with self.assertRaises(DiscoveryFetchError) as raised:
                fetcher.fetch(self.source, self.source.source_url)
        self.assertEqual(raised.exception.category, "dns_error")
        fetcher.close()

    def test_retry_attempts_close_failed_pages(self):
        budget = DiscoveryRunBudget(
            max_sources=1,
            max_pages=1,
            max_pages_per_source=1,
            max_http_attempts=10,
            max_candidates=0,
            max_provider_attempts=0,
            duration_seconds=10,
            start_deadline_timer=False,
        )
        budget.start()
        first = _FakeResponse(url=self.source.source_url, status=503, body=b"unavailable")
        second = _FakeResponse(url=self.source.source_url, status=200, body=b"<html>raw</html>")
        first_page = _FakePage(response=first, html="")
        second_page = _FakePage(response=second, html="<html><body><main><h1>Master Scholarship</h1><p>Apply now</p></main></body></html>")
        context = _FakeContext([self._robots_page(), first_page, second_page])
        fetcher = self._fetcher_with_context(context, run_budget=budget)
        result = fetcher.fetch(self.source, self.source.source_url)
        self.assertIn("Master Scholarship", result.text)
        self.assertTrue(first_page.closed)
        self.assertTrue(second_page.closed)
        fetcher.close()

    def test_page_cleanup_after_retry_and_failure(self):
        budget = DiscoveryRunBudget(
            max_sources=1,
            max_pages=1,
            max_pages_per_source=1,
            max_http_attempts=10,
            max_candidates=0,
            max_provider_attempts=0,
            duration_seconds=10,
            start_deadline_timer=False,
        )
        budget.start()
        resp = _FakeResponse(url=self.source.source_url, status=503, body=b"unavailable")
        first_page = _FakePage(response=resp, html="")
        second_page = _FakePage(response=resp, html="")
        context = _FakeContext([self._robots_page(), first_page, second_page])
        fetcher = self._fetcher_with_context(context, run_budget=budget)
        with self.assertRaises(DiscoveryFetchError):
            fetcher.fetch(self.source, self.source.source_url)
        self.assertTrue(first_page.closed)
        self.assertTrue(second_page.closed)
        fetcher.close()

    def _fetcher_with_context(self, context, *, run_budget=None, sleep=None, **kwargs):
        browser = _FakeBrowser(context)
        pw = _FakePlaywright(browser)
        fetcher = OfficialSourceFetcher(
            _settings(**kwargs),
            run_budget=run_budget,
            sleep=sleep,
            resolver=_offline_public_resolver,
            playwright_factory=lambda: pw,
        )
        fetcher._test_pw = pw
        fetcher._test_browser = browser
        fetcher._test_context = context
        return fetcher

    def test_successful_navigation_extracts_rendered_html_text_and_links(self):
        html = """
        <html><body>
          <main><h1>Master Scholarship</h1><p>Apply for a Master's degree scholarship.</p>
          <a href="/details">Details</a></main>
        </body></html>
        """
        resp = _FakeResponse(url=self.source.source_url, body=b"<html>raw</html>")
        page = _FakePage(response=resp, html=html)
        fetcher = self._fetcher(page)

        result = fetcher.fetch(self.source, self.source.source_url)

        self.assertIsInstance(result, FetchedPage)
        self.assertEqual(result.url, self.source.source_url)
        self.assertIn("Master Scholarship", result.text)
        self.assertIn("Apply for a Master's degree scholarship.", result.text)
        self.assertTrue(any("/details" in href for href, _ in result.links))
        self.assertTrue(page.closed)
        self.assertEqual(fetcher._test_browser.new_context_calls[0]["java_script_enabled"], True)
        self.assertEqual(fetcher._test_browser.new_context_calls[0]["ignore_https_errors"], False)
        fetcher.close()

    def test_javascript_rendered_html_uses_page_content(self):
        # Body is minimal but rendered DOM has content (simulates JS-rendered page)
        resp = _FakeResponse(url=self.source.source_url, body=b"<html><body><div id='app'></div></body></html>")
        page = _FakePage(
            response=resp,
            html="<html><body><div id='app'>Rendered scholarship details for Master's applicants</div></body></html>",
        )
        fetcher = self._fetcher(page)
        result = fetcher.fetch(self.source, self.source.source_url)
        self.assertIn("Rendered scholarship details", result.text)
        fetcher.close()

    def test_navigation_timeout_raises_discovery_fetch_error(self):
        class PlaywrightTimeoutError(Exception):
            pass

        budget = DiscoveryRunBudget(
            max_sources=1,
            max_pages=1,
            max_pages_per_source=1,
            max_http_attempts=5,
            max_candidates=0,
            max_provider_attempts=0,
            duration_seconds=10,
            start_deadline_timer=False,
        )
        budget.start()
        page = _FakePage(
            goto_error=PlaywrightTimeoutError("Timeout 2000ms exceeded"),
            close_error=RuntimeError("page close failed"),
        )
        fetcher = self._fetcher(page, robots=True, run_budget=budget)
        with self.assertRaises(DiscoveryFetchError) as raised:
            fetcher.fetch(self.source, self.source.source_url)
        self.assertEqual(raised.exception.category, "timeout")
        self.assertEqual(budget.snapshot()["http_attempts"], 2)
        self.assertTrue(page.closed)
        self.assertIn("page:RuntimeError", fetcher.cleanup_errors)
        fetcher.close()
        self.assertTrue(fetcher._test_context.closed)
        self.assertTrue(fetcher._test_browser.closed)
        self.assertTrue(fetcher._test_pw.stopped)
        budget.close()

    def test_http_error_status_raises_discovery_fetch_error(self):
        resp = _FakeResponse(url=self.source.source_url, status=400, body=b"bad request")
        page = _FakePage(response=resp, html="")
        fetcher = self._fetcher(page, robots=True)
        with self.assertRaises(DiscoveryFetchError) as raised:
            fetcher.fetch(self.source, self.source.source_url)
        self.assertEqual(raised.exception.status_code, 400)
        self.assertTrue(page.closed)
        fetcher.close()

    def test_redirect_final_url_is_validated_and_preserved(self):
        redirected = "https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=50026397"
        resp = _FakeResponse(url=redirected, status=200, body=b"<html>ok</html>")
        page = _FakePage(response=resp, html="<html><body>Redirected Master's scholarship page content</body></html>")
        fetcher = self._fetcher(page)
        result = fetcher.fetch(self.source, self.source.source_url)
        self.assertEqual(result.url, redirected)
        fetcher.close()

    def test_redirect_outside_registered_source_is_blocked(self):
        response = _FakeResponse(
            url="https://outside.example/scholarship",
            body=b"<html>not allowed</html>",
        )
        page = _FakePage(response=response, html="<p>not allowed</p>")
        fetcher = self._fetcher(page)
        with self.assertRaises(DiscoveryFetchError):
            fetcher.fetch(self.source, self.source.source_url)
        self.assertTrue(page.closed)
        fetcher.close()

    def test_https_redirect_to_http_is_blocked(self):
        response = _FakeResponse(
            url="http://www2.daad.de/deutschland/scholarship",
            body=b"<html>not allowed</html>",
        )
        page = _FakePage(response=response, html="<p>not allowed</p>")
        fetcher = self._fetcher(page)
        with self.assertRaises(DiscoveryFetchError) as raised:
            fetcher.fetch(self.source, self.source.source_url)
        self.assertEqual(raised.exception.category, "https_downgrade_rejected")
        fetcher.close()

    def test_browser_cleanup_closes_page_context_browser(self):
        html = "<html><body><p>Enough scholarship content for extraction pipeline text.</p></body></html>"
        resp = _FakeResponse(url=self.source.source_url, body=b"ok")
        page = _FakePage(response=resp, html=html)
        fetcher = self._fetcher(page)
        fetcher.fetch(self.source, self.source.source_url)
        fetcher.close()
        self.assertTrue(page.closed)
        self.assertTrue(fetcher._test_context.closed)
        self.assertTrue(fetcher._test_browser.closed)
        self.assertTrue(fetcher._test_pw.stopped)

    def test_cleanup_is_attempted_even_when_page_close_raises(self):
        html = "<html><body><p>Enough scholarship content for extraction pipeline text.</p></body></html>"
        resp = _FakeResponse(url=self.source.source_url, body=b"ok")
        page = _FakePage(response=resp, html=html, close_error=RuntimeError("close failed"))
        fetcher = self._fetcher(page)
        fetcher.fetch(self.source, self.source.source_url)
        fetcher.close()
        self.assertTrue(fetcher._test_context.closed)
        self.assertTrue(fetcher._test_browser.closed)
        self.assertIn("page:RuntimeError", fetcher.cleanup_errors)
        self.assertTrue(fetcher._test_pw.stopped)

    def test_cleanup_continues_after_context_close_failure(self):
        response = _FakeResponse(url=self.source.source_url, body=b"ok")
        page = _FakePage(
            response=response,
            html="<html><body><p>Scholarship details with sufficient content.</p></body></html>",
        )
        fetcher = self._fetcher(page)
        fetcher.fetch(self.source, self.source.source_url)
        fetcher._test_context.close = Mock(side_effect=RuntimeError("context close failed"))

        fetcher.close()

        self.assertEqual(fetcher.cleanup_errors, ["context:RuntimeError"])
        self.assertTrue(fetcher._test_browser.closed)
        self.assertTrue(fetcher._test_pw.stopped)

    def test_main_frame_is_identified_by_frame_identity(self):
        fetcher = OfficialSourceFetcher(
            _settings(),
            allowed_request_hosts={"www2.daad.de"},
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        page = _FakePage()
        failures = self._install_route_policy(fetcher, page)
        route = _FakeRoute(_FakeRequest(self.source.source_url, page))

        page._route_handler(route)

        self.assertFalse(hasattr(page.main_frame, "is_main_frame"))
        self.assertTrue(route.continued)
        self.assertEqual(failures, [])
        fetcher.close()

    def test_fetch_response_size_limit_is_enforced(self):
        response = _FakeResponse(
            url=self.source.source_url,
            headers={"content-type": "text/html", "content-length": "32"},
            body=b"small",
        )
        page = _FakePage(response=response, html="<p>Scholarship information</p>")
        fetcher = self._fetcher(page, max_response_bytes=8)

        with self.assertRaises(DiscoveryFetchError) as raised:
            fetcher.fetch(self.source, self.source.source_url)

        self.assertEqual(raised.exception.category, "content_validation_failed")
        self.assertEqual(response.body_calls, 0)
        self.assertTrue(page.closed)
        fetcher.close()

    def test_rendered_dom_size_limit_is_enforced(self):
        response = _FakeResponse(url=self.source.source_url, body=b"<html/>")
        page = _FakePage(
            response=response,
            html="<html><body>Rendered scholarship information</body></html>",
        )
        fetcher = self._fetcher(page)
        fetcher._max_rendered_content_bytes = 16

        with self.assertRaises(DiscoveryFetchError) as raised:
            fetcher.fetch(self.source, self.source.source_url)

        self.assertEqual(raised.exception.category, "content_validation_failed")
        self.assertTrue(page.closed)
        fetcher.close()

    def test_invalid_json_processing_still_closes_page(self):
        response = _FakeResponse(
            url=self.source.source_url,
            headers={"content-type": "application/json"},
            body=b"{invalid",
        )
        page = _FakePage(response=response)
        fetcher = self._fetcher(page)

        with self.assertRaises(DiscoveryFetchError) as raised:
            fetcher.fetch(self.source, self.source.source_url)

        self.assertEqual(raised.exception.category, "content_validation_failed")
        self.assertTrue(page.closed)
        fetcher.close()

    def test_browser_initialization_failure_stops_playwright(self):
        context = _FakeContext([])
        pw = _FakePlaywright(_FakeBrowser(context))
        pw.chromium.launch = Mock(side_effect=RuntimeError("browser launch failed"))
        fetcher = OfficialSourceFetcher(
            _settings(),
            playwright_factory=lambda: pw,
        )

        with self.assertRaises(DiscoveryFetchError):
            fetcher._ensure_browser()

        self.assertTrue(pw.stopped)
        fetcher.close()

    def test_shared_browser_lifecycle_reused_across_pages_in_crawl(self):
        root = self.source.source_url
        html_root = "<html><body><p>Master scholarship root content long enough for crawl extraction.</p></body></html>"
        # robots (404, cached) + root page
        robots = self._robots_page()
        root_page = _FakePage(response=_FakeResponse(url=root, body=b"r"), html=html_root)
        context = _FakeContext([robots, root_page])
        browser = _FakeBrowser(context)
        pw = _FakePlaywright(browser)
        # Every other test in this file injects the offline resolver; without
        # it this one resolves the real host over DNS and fails whenever the
        # network is slow or unavailable.
        fetcher = OfficialSourceFetcher(
            _settings(max_pages_per_source=1),
            playwright_factory=lambda: pw,
            resolver=_offline_public_resolver,
        )
        fetcher._test_pw = pw
        fetcher._test_browser = browser
        fetcher._test_context = context
        result = fetcher.crawl(self.source)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(pw.chromium.launch_calls), 1)
        self.assertGreaterEqual(len(browser.new_context_calls), 1)
        fetcher.close()
        self.assertTrue(pw.stopped)

    def test_browser_error_raises_discovery_fetch_error(self):
        page = _FakePage(goto_error=RuntimeError("net::ERR_CERT_AUTHORITY_INVALID"))
        fetcher = self._fetcher(page, robots=True)
        with self.assertRaises(DiscoveryFetchError) as raised:
            fetcher.fetch(self.source, self.source.source_url)
        self.assertEqual(raised.exception.category, "tls_error")
        fetcher.close()

    def test_browser_requests_obey_run_http_attempt_budget(self):
        page = self._robots_page()
        fetcher = self._fetcher(page, robots=False)
        fetcher.run_budget = SimpleNamespace(
            remaining_seconds=lambda: 10,
            ensure_active=lambda: None,
            begin_http_attempt=Mock(
                side_effect=DiscoveryRunLimitExceeded("http_attempts", 1),
            ),
        )
        with self.assertRaises(DiscoveryRunLimitExceeded):
            fetcher.fetch(self.source, self.source.source_url)
        self.assertTrue(page.closed)
        fetcher.close()

    def test_robots_and_content_navigation_are_each_budgeted(self):
        budget = DiscoveryRunBudget(
            max_sources=1,
            max_pages=1,
            max_pages_per_source=1,
            max_http_attempts=5,
            max_candidates=0,
            max_provider_attempts=0,
            duration_seconds=10,
            start_deadline_timer=False,
        )
        budget.start()
        content_page = _FakePage(
            response=_FakeResponse(url=self.source.source_url, body=b"content"),
            html="<html><body><p>Scholarship content for a registered source.</p></body></html>",
        )
        fetcher = self._fetcher(
            content_page,
            run_budget=budget,
            allowed_request_hosts={"www2.daad.de"},
        )

        result = fetcher.fetch(self.source, self.source.source_url)

        self.assertIn("Scholarship content", result.text)
        self.assertEqual(budget.snapshot()["http_attempts"], 2)
        self.assertEqual(
            [page.closed for page in fetcher._test_context._opened_pages],
            [True, True],
        )
        self.assertEqual(fetcher.cleanup_errors, [])
        budget.close()
        fetcher.close()

    def test_request_handler_failure_is_accounted_and_aborted(self):
        budget = DiscoveryRunBudget(
            max_sources=1,
            max_pages=1,
            max_pages_per_source=1,
            max_http_attempts=3,
            max_candidates=0,
            max_provider_attempts=0,
            duration_seconds=10,
            start_deadline_timer=False,
        )
        budget.start()
        fetcher = OfficialSourceFetcher(
            _settings(),
            run_budget=budget,
            allowed_request_hosts={"www2.daad.de"},
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        page = _FakePage()
        failures = self._install_route_policy(fetcher, page)
        route = _FakeRoute(
            _FakeRequest(
                "https://www2.daad.de/assets/app.js",
                page,
                navigation=False,
                frame_error=RuntimeError("frame detached"),
            )
        )

        page._route_handler(route)

        self.assertTrue(route.aborted)
        self.assertEqual(failures[0].category, "frame_identification_failed")
        self.assertEqual(budget.snapshot()["http_attempts"], 1)
        budget.close()
        fetcher.close()

    def test_redirect_hops_are_counted_once_per_http_request(self):
        budget = DiscoveryRunBudget(
            max_sources=1,
            max_pages=1,
            max_pages_per_source=1,
            max_http_attempts=5,
            max_candidates=0,
            max_provider_attempts=0,
            duration_seconds=10,
            start_deadline_timer=False,
        )
        budget.start()
        fetcher = OfficialSourceFetcher(
            _settings(),
            run_budget=budget,
            allowed_request_hosts={"www2.daad.de"},
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        page = _FakePage()
        failures = self._install_route_policy(fetcher, page)
        first_request = _FakeRequest(self.source.source_url, page)
        first_route = _FakeRoute(first_request)
        redirect_route = _FakeRoute(
            _FakeRequest(
                "https://www2.daad.de/scholarships/redirected",
                page,
                redirected_from=first_request,
            )
        )

        page._route_handler(first_route)
        page._route_handler(redirect_route)

        self.assertTrue(first_route.continued)
        self.assertTrue(redirect_route.continued)
        self.assertEqual(failures, [])
        self.assertEqual(budget.snapshot()["http_attempts"], 2)
        budget.close()
        fetcher.close()

    def test_explicitly_approved_external_subresource_is_allowed_and_budgeted(self):
        budget = DiscoveryRunBudget(
            max_sources=1,
            max_pages=1,
            max_pages_per_source=1,
            max_http_attempts=1,
            max_candidates=0,
            max_provider_attempts=0,
            duration_seconds=10,
            start_deadline_timer=False,
        )
        budget.start()
        fetcher = OfficialSourceFetcher(
            _settings(),
            run_budget=budget,
            allowed_request_hosts={"www2.daad.de", "assets.example.test"},
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        page = _FakePage()
        failures = self._install_route_policy(fetcher, page)
        route = _FakeRoute(
            _FakeRequest(
                "https://assets.example.test/app.js",
                page,
                navigation=False,
            )
        )

        page._route_handler(route)

        self.assertTrue(route.continued)
        self.assertFalse(route.aborted)
        self.assertEqual(failures, [])
        self.assertEqual(budget.snapshot()["http_attempts"], 1)
        budget.close()
        fetcher.close()

    def test_unapproved_third_party_subresource_is_blocked(self):
        budget = DiscoveryRunBudget(
            max_sources=1,
            max_pages=1,
            max_pages_per_source=1,
            max_http_attempts=3,
            max_candidates=0,
            max_provider_attempts=0,
            duration_seconds=10,
            start_deadline_timer=False,
        )
        budget.start()
        fetcher = OfficialSourceFetcher(
            _settings(),
            run_budget=budget,
            allowed_request_hosts={"www2.daad.de"},
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        page = _FakePage()
        failures = self._install_route_policy(fetcher, page)
        route = _FakeRoute(
            _FakeRequest(
                "https://unapproved.example.test/tracker.js",
                page,
                navigation=False,
            )
        )

        page._route_handler(route)

        self.assertTrue(route.aborted)
        self.assertFalse(route.continued)
        self.assertEqual(failures[0].category, "request_host_not_allowed")
        self.assertEqual(
            fetcher.last_policy_rejection,
            {
                "hostname": "unapproved.example.test",
                "request_type": "subresource",
                "reason": "host_not_in_exact_allowlist",
            },
        )
        self.assertEqual(budget.snapshot()["http_attempts"], 1)
        budget.close()
        fetcher.close()

    def test_subresource_redirect_to_unapproved_host_is_blocked(self):
        fetcher = OfficialSourceFetcher(
            _settings(),
            allowed_request_hosts={"www2.daad.de", "assets.example.test"},
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        page = _FakePage()
        failures = self._install_route_policy(fetcher, page)
        original = _FakeRequest(
            "https://assets.example.test/app.js",
            page,
            navigation=False,
        )
        route = _FakeRoute(
            _FakeRequest(
                "https://redirector.example.test/app.js",
                page,
                redirected_from=original,
                navigation=False,
            )
        )

        page._route_handler(route)

        self.assertTrue(route.aborted)
        self.assertEqual(failures[0].category, "request_host_not_allowed")
        self.assertEqual(
            fetcher.last_policy_rejection,
            {
                "hostname": "redirector.example.test",
                "request_type": "subresource_redirect",
                "reason": "host_not_in_exact_allowlist",
            },
        )
        fetcher.close()

    def test_https_to_http_subresource_redirect_is_blocked(self):
        fetcher = OfficialSourceFetcher(
            _settings(),
            allowed_request_hosts={"www2.daad.de", "assets.example.test"},
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        page = _FakePage()
        failures = self._install_route_policy(fetcher, page)
        original = _FakeRequest(
            "https://assets.example.test/app.js",
            page,
            navigation=False,
        )
        route = _FakeRoute(
            _FakeRequest(
                "http://assets.example.test/app.js",
                page,
                redirected_from=original,
                navigation=False,
            )
        )

        page._route_handler(route)

        self.assertTrue(route.aborted)
        self.assertEqual(failures[0].category, "https_downgrade_rejected")
        fetcher.close()

    def test_main_frame_redirect_must_match_exact_host_allowlist(self):
        fetcher = OfficialSourceFetcher(
            _settings(),
            allowed_request_hosts={"www2.daad.de"},
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        page = _FakePage()
        failures = self._install_route_policy(fetcher, page)
        original = _FakeRequest(self.source.source_url, page)
        route = _FakeRoute(
            _FakeRequest(
                "https://www.daad.de/scholarship",
                page,
                redirected_from=original,
            )
        )

        page._route_handler(route)

        self.assertTrue(route.aborted)
        self.assertEqual(failures[0].category, "request_host_not_allowed")
        self.assertEqual(
            fetcher.last_policy_rejection,
            {
                "hostname": "www.daad.de",
                "request_type": "main_frame_redirect",
                "reason": "host_not_in_exact_allowlist",
            },
        )
        fetcher.close()

    def test_request_from_additional_page_is_blocked_by_context_policy(self):
        fetcher = OfficialSourceFetcher(
            _settings(),
            allowed_request_hosts={"www2.daad.de"},
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        page = _FakePage()
        failures = self._install_route_policy(fetcher, page)
        popup = _FakePage()
        route = _FakeRoute(
            _FakeRequest("https://www2.daad.de/popup", popup)
        )

        page._route_handler(route)

        self.assertTrue(route.aborted)
        self.assertEqual(failures[0].category, "additional_page_rejected")
        fetcher.close()

    def test_request_budget_exhaustion_aborts_permitted_subresource(self):
        budget = DiscoveryRunBudget(
            max_sources=1,
            max_pages=1,
            max_pages_per_source=1,
            max_http_attempts=1,
            max_candidates=0,
            max_provider_attempts=0,
            duration_seconds=10,
            start_deadline_timer=False,
        )
        budget.start()
        budget.consume_http_attempt()
        fetcher = OfficialSourceFetcher(
            _settings(),
            run_budget=budget,
            allowed_request_hosts={"www2.daad.de", "assets.example.test"},
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        page = _FakePage()
        failures = self._install_route_policy(fetcher, page)
        route = _FakeRoute(
            _FakeRequest(
                "https://assets.example.test/app.js",
                page,
                navigation=False,
            )
        )

        page._route_handler(route)

        self.assertTrue(route.aborted)
        self.assertIsInstance(failures[0], DiscoveryRunLimitExceeded)
        self.assertFalse(route.continued)
        budget.close()
        fetcher.close()

    def test_non_http_external_scheme_and_websocket_are_blocked(self):
        fetcher = OfficialSourceFetcher(
            _settings(),
            allowed_request_hosts={"www2.daad.de"},
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        page = _FakePage()
        failures = self._install_route_policy(fetcher, page)
        file_route = _FakeRoute(
            _FakeRequest("file:///C:/sensitive.txt", page, navigation=False)
        )
        page._route_handler(file_route)
        websocket_route = _FakeWebSocketRoute()
        page._websocket_handler(websocket_route)

        self.assertTrue(file_route.aborted)
        self.assertEqual(failures[0].category, "external_scheme_rejected")
        self.assertTrue(websocket_route.closed)
        self.assertEqual(websocket_route.close_args, (1008, "WebSockets disabled by fetch policy"))
        self.assertEqual(failures[1].category, "websocket_rejected")
        fetcher.close()

    def test_unconfigured_policy_preserves_third_party_subresource_behavior(self):
        # Safe default: third-party host is DNS-validated and pinned before browser
        # contact (deterministic offline-safe resolver here), preserving behavior
        # while preventing independent/unsafe Chromium resolution.
        fetcher = OfficialSourceFetcher(
            _settings(),
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        page = _FakePage()
        failures = self._install_route_policy(fetcher, page)
        route = _FakeRoute(
            _FakeRequest(
                "https://third-party.example.test/asset.js",
                page,
                navigation=False,
            )
        )

        page._route_handler(route)

        self.assertTrue(route.continued)
        self.assertFalse(route.aborted)
        self.assertEqual(failures, [])
        self.assertIn("third-party.example.test", fetcher._pinned_host_ips)
        self.assertIsNone(page._websocket_handler)
        fetcher.close()

    def test_unpinnable_third_party_subresource_is_blocked_without_failing_page(self):
        def resolver(_host, record_type, lifetime=None, search=False):
            return [SimpleNamespace(address="8.8.8.8")] if int(record_type) == 1 else []

        fetcher = OfficialSourceFetcher(_settings(), resolver=resolver)
        fetcher._browser = Mock()
        page = _FakePage()
        failures = self._install_route_policy(fetcher, page)
        route = _FakeRoute(
            _FakeRequest(
                "https://third-party.example.test/asset.js",
                page,
                navigation=False,
            )
        )

        page._route_handler(route)

        self.assertTrue(route.aborted)
        self.assertEqual(failures, [])
        self.assertNotIn("third-party.example.test", fetcher._pinned_host_ips)
        fetcher.close()

    def test_unpinnable_main_frame_request_still_fails_closed(self):
        def resolver(_host, record_type, lifetime=None, search=False):
            return [SimpleNamespace(address="8.8.8.8")] if int(record_type) == 1 else []

        fetcher = OfficialSourceFetcher(_settings(), resolver=resolver)
        fetcher._browser = Mock()
        page = _FakePage()
        failures = self._install_route_policy(fetcher, page)
        route = _FakeRoute(_FakeRequest(self.source.source_url, page))

        with self.assertLogs(
            "app.services.scholarship_discovery_fetch",
            level="WARNING",
        ) as logs:
            page._route_handler(route)

        self.assertTrue(route.aborted)
        self.assertEqual(failures[0].category, "browser_pinning_unavailable")
        self.assertIn("host=www2.daad.de request_type=main_frame_navigation", logs.output[0])
        fetcher.close()

    def test_allowed_host_policy_rejects_wildcards(self):
        with self.assertRaises(ValueError):
            OfficialSourceFetcher(
                _settings(),
                allowed_request_hosts={"*.daad.de"},
                playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
            )

    def test_allowed_host_policy_blocks_service_workers(self):
        context = _FakeContext([])
        browser = _FakeBrowser(context)
        pw = _FakePlaywright(browser)
        import dns.rdatatype, dns.resolver as _dns
        def _resolver(host, record_type, lifetime=None, search=False):
            if int(record_type) == int(dns.rdatatype.A):
                return [type("R", (), {"address": "93.184.216.34"})()]
            raise _dns.NoAnswer()
        fetcher = OfficialSourceFetcher(
            _settings(),
            allowed_request_hosts={"www2.daad.de"},
            resolver=_resolver,
            playwright_factory=lambda: pw,
        )
        fetcher._test_browser = browser

        fetcher._ensure_browser()

        self.assertEqual(browser.new_context_calls[0]["service_workers"], "block")
        # Resolver rules are required for safe browser DNS pinning; launch args
        # must not be empty.
        launch_args = pw.chromium.launch_calls[0]["args"]
        self.assertTrue(any(a.startswith("--host-resolver-rules=") for a in launch_args))
        resolver_arg = [a for a in launch_args if a.startswith("--host-resolver-rules=")][0]
        self.assertIn("MAP www2.daad.de 93.184.216.34", resolver_arg)
        self.assertIn("MAP * ~NOTFOUND", resolver_arg)
        fetcher.close()

    def test_unconfigured_policy_blocks_service_workers(self):
        # Service workers can initiate requests outside normal page-route control;
        # block them consistently regardless of allowlist policy.
        context = _FakeContext([])
        browser = _FakeBrowser(context)
        pw = _FakePlaywright(browser)
        import dns.rdatatype, dns.resolver as _dns
        def _resolver(host, record_type, lifetime=None, search=False):
            if int(record_type) == int(dns.rdatatype.A):
                return [type("R", (), {"address": "93.184.216.34"})()]
            raise _dns.NoAnswer()
        fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=_resolver,
            playwright_factory=lambda: pw,
        )
        fetcher._ensure_browser()
        self.assertEqual(browser.new_context_calls[0]["service_workers"], "block")
        fetcher.close()

    def test_proxy_related_browser_launch_args_are_rejected(self):
        for arg in [
            "--proxy-server=http://127.0.0.1:8080",
            "--proxy-pac-url=http://example.test/proxy.pac",
            "--proxy-bypass-list=localhost",
            "--proxy-auto-detect",
            "--no-proxy-server",
            "--proxy-server",
        ]:
            with self.subTest(arg=arg):
                with self.assertRaises(DiscoveryFetchError) as raised:
                    OfficialSourceFetcher(_settings(), browser_launch_args=[arg])
                self.assertEqual(raised.exception.category, "unsafe_browser_launch_config")

    def test_conflicting_host_resolver_rules_are_rejected(self):
        with self.assertRaises(DiscoveryFetchError) as raised:
            OfficialSourceFetcher(
                _settings(),
                browser_launch_args=["--host-resolver-rules=MAP evil.test 1.2.3.4"],
            )
        self.assertEqual(raised.exception.category, "unsafe_browser_launch_config")

    def test_safe_non_security_launch_args_are_supported(self):
        context = _FakeContext([])
        browser = _FakeBrowser(context)
        pw = _FakePlaywright(browser)
        import dns.rdatatype, dns.resolver as _dns
        def _resolver(host, record_type, lifetime=None, search=False):
            if int(record_type) == int(dns.rdatatype.A):
                return [type("R", (), {"address": "93.184.216.34"})()]
            raise _dns.NoAnswer()
        fetcher = OfficialSourceFetcher(
            _settings(),
            allowed_request_hosts={"www2.daad.de"},
            resolver=_resolver,
            browser_launch_args=["--disable-gpu", "--disable-dev-shm-usage"],
            playwright_factory=lambda: pw,
        )
        fetcher._ensure_browser()
        launch_args = pw.chromium.launch_calls[0]["args"]
        self.assertIn("--disable-gpu", launch_args)
        self.assertIn("--disable-dev-shm-usage", launch_args)
        self.assertTrue(any(a.startswith("--host-resolver-rules=") for a in launch_args))
        self.assertEqual(sum(1 for a in launch_args if a.startswith("--host-resolver-rules=")), 1)
        self.assertIn("MAP * ~NOTFOUND", [a for a in launch_args if a.startswith("--host-resolver-rules=")][0])
        fetcher.close()

    def test_host_resolver_rule_ip_formats_ipv4_unbracketed_and_ipv6_bracketed(self):
        self.assertEqual(
            OfficialSourceFetcher._host_resolver_rule_ip("93.184.216.34"),
            "93.184.216.34",
        )
        self.assertEqual(
            OfficialSourceFetcher._host_resolver_rule_ip("2001:db8::1"),
            "[2001:db8::1]",
        )
        self.assertEqual(
            OfficialSourceFetcher._host_resolver_rule_ip(
                "2001:0db8:0000:0000:0000:0000:0000:0001"
            ),
            "[2001:db8::1]",
        )
        self.assertEqual(
            OfficialSourceFetcher._host_resolver_rule_ip("::1"),
            "[::1]",
        )

    def test_host_resolver_rule_ip_rejects_invalid_address(self):
        with self.assertRaises(DiscoveryFetchError) as raised:
            OfficialSourceFetcher._host_resolver_rule_ip("not-an-ip")
        self.assertEqual(raised.exception.category, "dns_error")

    def test_pinned_ipv6_host_emits_bracketed_resolver_rule(self):
        context = _FakeContext([])
        browser = _FakeBrowser(context)
        pw = _FakePlaywright(browser)
        import dns.rdatatype
        import dns.resolver as _dns

        def _resolver(host, record_type, lifetime=None, search=False):
            if int(record_type) == int(dns.rdatatype.AAAA):
                return [type("R", (), {"address": "2001:4860:4860::8888"})()]
            raise _dns.NoAnswer()

        fetcher = OfficialSourceFetcher(
            _settings(),
            allowed_request_hosts={"www2.daad.de"},
            resolver=_resolver,
            playwright_factory=lambda: pw,
        )
        fetcher._ensure_browser()

        resolver_arg = [
            a
            for a in pw.chromium.launch_calls[0]["args"]
            if a.startswith("--host-resolver-rules=")
        ][0]
        self.assertIn("MAP www2.daad.de [2001:4860:4860::8888]", resolver_arg)
        self.assertIn("MAP * ~NOTFOUND", resolver_arg)
        fetcher.close()

    def test_browser_initialization_fails_closed_when_launch_config_is_unsafe(self):
        fetcher = OfficialSourceFetcher(
            _settings(),
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        # Defense-in-depth path: mutate internal args to simulate unsafe config
        # reaching launch validation.
        fetcher._browser_launch_args = ("--proxy-server=http://127.0.0.1:8080",)
        with self.assertRaises(DiscoveryFetchError) as raised:
            fetcher._ensure_browser()
        self.assertEqual(raised.exception.category, "unsafe_browser_launch_config")
        self.assertEqual(fetcher.cleanup_errors, [])

    def test_fetcher_import_does_not_load_application_config(self):
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = (
            "import sys; from typing import get_type_hints; "
            "from app.services.scholarship_discovery_fetch import OfficialSourceFetcher; "
            "from app.services.scholarship_discovery_budget import controlled_manual_settings; "
            "from app.services.scholarship_discovery_fetch_legacy import OfficialSourceFetcher as LegacyFetcher; "
            "assert 'app.core.config' not in sys.modules; "
            "assert get_type_hints(OfficialSourceFetcher.__init__)['settings'] is not None; "
            "assert get_type_hints(controlled_manual_settings)['settings'] is not None; "
            "assert get_type_hints(LegacyFetcher.__init__)['settings'] is not None"
        )
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=backend_dir,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()



class PlaywrightFetcherSSRFProtectionTests(unittest.TestCase):
    def setUp(self):
        self.source = SOURCES_BY_ID["daad-helmut-schmidt"]
        self.source_host = urllib.parse.urlsplit(self.source.source_url).hostname.lower()

    @staticmethod
    def _resolver(mapping):
        import dns.resolver as _dns_resolver

        def resolve(host, record_type, lifetime=None, search=False):
            host_key = (host or "").strip(".").lower()
            records = mapping.get(host_key, mapping.get("*", {}))
            ips = records.get(int(record_type), [])
            if not ips:
                raise _dns_resolver.NoAnswer()
            return [type("R", (), {"address": ip})() for ip in ips]

        return resolve

    @staticmethod
    def _page_for(url, html="<html><body><p>Safe scholarship content long enough for extraction.</p></body></html>"):
        return _FakePage(response=_FakeResponse(url=url, body=b"ok"), html=html)

    @staticmethod
    def _helper():
        helper = PlaywrightFetcherTests()
        helper.setUp()
        return helper

    def _base_fetcher(self, **kwargs):
        return OfficialSourceFetcher(_settings(), **kwargs)

    def _prime_robots_allowed(self, fetcher):
        # Focus these tests on target navigation/request validation, not robots I/O.
        fetcher._robots[self.source_host] = None

    def test_ipv4_loopback_rejected_before_browser_navigation(self):
        resolver = self._resolver({"www2.daad.de": {1: ["127.0.0.1"], 28: []}})
        page = self._page_for(self.source.source_url)
        fetcher = self._helper()._fetcher(page, robots=False, resolver=resolver)
        self._prime_robots_allowed(fetcher)
        try:
            with self.assertRaises(DiscoveryFetchError) as raised:
                fetcher.fetch(self.source, self.source.source_url)
            self.assertEqual(raised.exception.category, "dns_error")
            self.assertEqual(page.goto_calls, [])
            self.assertEqual(fetcher._test_context.new_page_calls, 0)
        finally:
            fetcher.close()

    def test_ipv4_private_address_rejected(self):
        resolver = self._resolver({"www2.daad.de": {1: ["10.0.0.5"], 28: []}})
        page = self._page_for(self.source.source_url)
        fetcher = self._helper()._fetcher(page, robots=False, resolver=resolver)
        self._prime_robots_allowed(fetcher)
        try:
            with self.assertRaises(DiscoveryFetchError):
                fetcher.fetch(self.source, self.source.source_url)
            self.assertEqual(page.goto_calls, [])
        finally:
            fetcher.close()

    def test_ipv6_loopback_rejected(self):
        resolver = self._resolver({"www2.daad.de": {1: [], 28: ["::1"]}})
        page = self._page_for(self.source.source_url)
        fetcher = self._helper()._fetcher(page, robots=False, resolver=resolver)
        self._prime_robots_allowed(fetcher)
        try:
            with self.assertRaises(DiscoveryFetchError):
                fetcher.fetch(self.source, self.source.source_url)
            self.assertEqual(page.goto_calls, [])
        finally:
            fetcher.close()

    def test_ipv6_private_address_rejected(self):
        resolver = self._resolver({"www2.daad.de": {1: [], 28: ["fc00::1"]}})
        page = self._page_for(self.source.source_url)
        fetcher = self._helper()._fetcher(page, robots=False, resolver=resolver)
        self._prime_robots_allowed(fetcher)
        try:
            with self.assertRaises(DiscoveryFetchError):
                fetcher.fetch(self.source, self.source.source_url)
            self.assertEqual(page.goto_calls, [])
        finally:
            fetcher.close()

    def test_link_local_and_reserved_addresses_rejected(self):
        for ip in ("169.254.169.254", "240.0.0.1"):
            with self.subTest(ip=ip):
                resolver = self._resolver({"www2.daad.de": {1: [ip], 28: []}})
                page = self._page_for(self.source.source_url)
                fetcher = self._helper()._fetcher(page, robots=False, resolver=resolver)
                self._prime_robots_allowed(fetcher)
                try:
                    with self.assertRaises(DiscoveryFetchError):
                        fetcher.fetch(self.source, self.source.source_url)
                    self.assertEqual(page.goto_calls, [])
                finally:
                    fetcher.close()

    def test_mixed_public_and_private_dns_results_rejected(self):
        resolver = self._resolver({"www2.daad.de": {1: ["93.184.216.34", "192.168.1.10"], 28: []}})
        page = self._page_for(self.source.source_url)
        fetcher = self._helper()._fetcher(page, robots=False, resolver=resolver)
        self._prime_robots_allowed(fetcher)
        try:
            with self.assertRaises(DiscoveryFetchError):
                fetcher.fetch(self.source, self.source.source_url)
            self.assertEqual(page.goto_calls, [])
        finally:
            fetcher.close()

    def test_dns_resolution_failure_rejected(self):
        import dns.exception

        def resolver(host, record_type, lifetime=None, search=False):
            raise dns.exception.Timeout("timed out")

        page = self._page_for(self.source.source_url)
        fetcher = self._helper()._fetcher(page, robots=False, resolver=resolver)
        self._prime_robots_allowed(fetcher)
        try:
            with self.assertRaises(DiscoveryFetchError) as raised:
                fetcher.fetch(self.source, self.source.source_url)
            self.assertEqual(raised.exception.category, "dns_error")
            self.assertEqual(page.goto_calls, [])
        finally:
            fetcher.close()

    def test_safe_public_address_allowed(self):
        resolver = self._resolver({"www2.daad.de": {1: ["93.184.216.34"], 28: []}})
        page = self._page_for(self.source.source_url)
        fetcher = self._helper()._fetcher(page, robots=False, resolver=resolver)
        self._prime_robots_allowed(fetcher)
        try:
            result = fetcher.fetch(self.source, self.source.source_url)
            self.assertIsInstance(result, FetchedPage)
            self.assertEqual(len(page.goto_calls), 1)
        finally:
            fetcher.close()

    def test_import_url_rejects_private_ip(self):
        resolver = self._resolver({"example.com": {1: ["127.0.0.1"], 28: []}})
        fetcher = self._base_fetcher(
            resolver=resolver,
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        try:
            with self.assertRaises(DiscoveryFetchError):
                fetcher.fetch_import_url("https://example.com/page", "webpage")
        finally:
            fetcher.close()

    def test_import_url_allows_safe_public_host(self):
        resolver = self._resolver({"example.com": {1: ["93.184.216.34"], 28: []}})
        page = _FakePage(
            response=_FakeResponse(
                url="https://example.com/page",
                headers={"content-type": "text/html"},
                body=b"<html/>",
            ),
            html="<html><body><p>Readable scholarship content for import page.</p></body></html>",
        )
        fetcher = self._base_fetcher(
            resolver=resolver,
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([page]))),
        )
        try:
            fetcher._resolve_public_addresses("example.com", 443)
            # Import now honours robots.txt; prime it as allowed so this test
            # stays about the host being safe to reach.
            fetcher._robots["example.com"] = None
            headers = Message()
            headers["Content-Type"] = "text/html"
            with patch.object(
                fetcher,
                "_request",
                return_value=(
                    200,
                    headers,
                    b"<html><body><p>Readable scholarship content for import page.</p></body></html>",
                ),
            ):
                result = fetcher.fetch_import_url("https://example.com/page", "webpage")
            self.assertEqual(result.url, "https://example.com/page")
            # A fetcher built with a browser now reads an import page through
            # it: the plain HTTP path sends a bot User-Agent that official
            # sites answer with 403. The host validation above is unchanged.
            self.assertEqual(len(page.goto_calls), 1)
        finally:
            fetcher.close()

    def test_redirect_to_private_ip_blocked_before_browser_connection(self):
        resolver = self._resolver({
            "www2.daad.de": {1: ["93.184.216.34"], 28: []},
            "evil.internal": {1: ["10.1.2.3"], 28: []},
        })
        redirected = "https://evil.internal/steal"
        response = _FakeResponse(url=redirected, body=b"bad")
        page = _FakePage(response=response, html="<p>bad</p>")
        fetcher = self._helper()._fetcher(page, robots=False, resolver=resolver)
        self._prime_robots_allowed(fetcher)
        try:
            with self.assertRaises(DiscoveryFetchError):
                fetcher.fetch(self.source, self.source.source_url)
            self.assertTrue(page.closed)
        finally:
            fetcher.close()

    def test_subresource_resolving_to_private_ip_is_blocked(self):
        resolver = self._resolver({
            "www2.daad.de": {1: ["93.184.216.34"], 28: []},
            "assets.example.test": {1: ["192.168.0.20"], 28: []},
        })
        fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=resolver,
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        page = _FakePage()
        failures = self._helper()._install_route_policy(fetcher, page)
        route = _FakeRoute(
            _FakeRequest("https://assets.example.test/app.js", page, navigation=False)
        )
        try:
            page._route_handler(route)
            self.assertTrue(route.aborted)
            self.assertFalse(route.continued)
            self.assertTrue(any(f.category == "dns_error" for f in failures))
        finally:
            fetcher.close()

    def test_allowed_subresource_public_ip_is_allowed(self):
        resolver = self._resolver({
            "www2.daad.de": {1: ["93.184.216.34"], 28: []},
            "assets.example.test": {1: ["93.184.216.35"], 28: []},
        })
        fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=resolver,
            allowed_request_hosts={"www2.daad.de", "assets.example.test"},
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        page = _FakePage()
        failures = self._helper()._install_route_policy(fetcher, page)
        route = _FakeRoute(
            _FakeRequest("https://assets.example.test/app.js", page, navigation=False)
        )
        try:
            page._route_handler(route)
            self.assertTrue(route.continued)
            self.assertFalse(route.aborted)
            self.assertEqual([f.category for f in failures if getattr(f, "category", None) == "dns_error"], [])
        finally:
            fetcher.close()

    def test_request_budget_and_cleanup_after_rejection(self):
        budget = DiscoveryRunBudget(
            max_sources=1,
            max_pages=1,
            max_pages_per_source=1,
            max_http_attempts=5,
            max_candidates=0,
            max_provider_attempts=0,
            duration_seconds=10,
            start_deadline_timer=False,
        )
        budget.start()
        resolver = self._resolver({"www2.daad.de": {1: ["127.0.0.1"], 28: []}})
        page = self._page_for(self.source.source_url)
        fetcher = self._helper()._fetcher(page, robots=False, resolver=resolver, run_budget=budget)
        self._prime_robots_allowed(fetcher)
        try:
            with self.assertRaises(DiscoveryFetchError):
                fetcher.fetch(self.source, self.source.source_url)
            self.assertEqual(budget.snapshot()["http_attempts"], 0)
            self.assertEqual(page.goto_calls, [])
            fetcher.close()
            self.assertEqual(fetcher.cleanup_errors, [])
        finally:
            budget.close()

    def test_dns_rebinding_cannot_change_pins_during_browser_lifecycle(self):
        calls = {}

        def resolver(host, record_type, lifetime=None, search=False):
            import dns.rdatatype
            import dns.resolver as _dns_resolver

            host_key = (host or "").strip(".").lower()
            if host_key != "www2.daad.de":
                raise _dns_resolver.NoAnswer()
            if int(record_type) == int(dns.rdatatype.AAAA):
                raise _dns_resolver.NoAnswer()
            calls[host_key] = calls.get(host_key, 0) + 1
            ip = "93.184.216.34" if calls[host_key] == 1 else "10.0.0.8"
            return [type("R", (), {"address": ip})()]

        page = self._page_for(self.source.source_url)
        helper = self._helper()
        fetcher = helper._fetcher(
            page,
            robots=False,
            resolver=resolver,
            allowed_request_hosts={"www2.daad.de"},
        )
        fetcher._robots[self.source_host] = None
        try:
            fetcher.prepin_hostnames([self.source_host])
            result = fetcher.fetch(self.source, self.source.source_url)
            self.assertIsInstance(result, FetchedPage)
            self.assertEqual(calls[self.source_host], 1)
            self.assertEqual(fetcher._pinned_host_ips[self.source_host], ["93.184.216.34"])
            self.assertIn("MAP www2.daad.de 93.184.216.34", fetcher._host_resolver_rules)
            self.assertIn("MAP * ~NOTFOUND", fetcher._host_resolver_rules)
            resolver_arg = [
                arg
                for arg in fetcher._test_pw.chromium.launch_calls[0]["args"]
                if arg.startswith("--host-resolver-rules=")
            ][0]
            self.assertIn("MAP www2.daad.de 93.184.216.34", resolver_arg)
            self.assertIn("MAP * ~NOTFOUND", resolver_arg)

            redirected_request = _FakeRequest(
                "https://www2.daad.de/scholarships/redirected",
                page,
                redirected_from=_FakeRequest(self.source.source_url, page),
            )
            accepted_redirect = _FakeRoute(redirected_request)
            page._route_handler(accepted_redirect)
            self.assertTrue(accepted_redirect.continued)

            unexpected = _FakeRoute(
                _FakeRequest(
                    "https://unexpected.example.test/scholarship",
                    page,
                    redirected_from=_FakeRequest(self.source.source_url, page),
                )
            )
            page._route_handler(unexpected)
            self.assertTrue(unexpected.aborted)
            self.assertEqual(fetcher._policy_failures[-1].category, "request_host_not_allowed")
            self.assertEqual(calls[self.source_host], 1)
        finally:
            fetcher.close()

    def test_multiple_source_hostnames_pinned_before_browser_launch(self):
        resolver = self._resolver({
            "source-a.test": {1: ["93.184.216.34"], 28: []},
            "source-b.test": {1: ["93.184.216.35"], 28: []},
        })
        fetcher = self._base_fetcher(
            resolver=resolver,
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        try:
            fetcher.prepin_hostnames(["source-a.test", "source-b.test"])
            self.assertIn("source-a.test", fetcher._pinned_host_ips)
            self.assertIn("source-b.test", fetcher._pinned_host_ips)
            self.assertIsNone(fetcher._browser)
            self.assertIn("MAP source-a.test 93.184.216.34", fetcher._host_resolver_rules)
            self.assertIn("MAP source-b.test 93.184.216.35", fetcher._host_resolver_rules)
            self.assertIn("MAP * ~NOTFOUND", fetcher._host_resolver_rules)
        finally:
            fetcher.close()

    def test_prepin_reuses_existing_pin_avoids_duplicate_dns(self):
        calls = {"n": 0}

        def resolving_resolver(host, record_type, lifetime=None, search=False):
            import dns.resolver as _dns_resolver
            calls["n"] += 1
            host_key = (host or "").strip(".").lower()
            # Only resolve source-a.test for A record (type=1); skip AAAA
            if host_key == "source-a.test" and record_type == 1:
                return [type("R", (), {"address": "93.184.216.34"})()]
            raise _dns_resolver.NoAnswer()

        fetcher = self._base_fetcher(
            resolver=resolving_resolver,
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        try:
            fetcher.prepin_hostnames(["source-a.test"])
            first_calls = calls["n"]
            fetcher.prepin_hostnames(["source-a.test"])
            self.assertEqual(calls["n"], first_calls)
            self.assertIn("source-a.test", fetcher._pinned_host_ips)
        finally:
            fetcher.close()

    def test_unexpected_hostname_after_browser_launch_still_rejected(self):
        resolver = self._resolver({
            "source-a.test": {1: ["93.184.216.34"], 28: []},
            "source-b.test": {1: ["93.184.216.35"], 28: []},
        })
        fetcher = self._base_fetcher(
            resolver=resolver,
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        try:
            fetcher.prepin_hostnames(["source-a.test"])
            fetcher._ensure_browser()
            self.assertIsNotNone(fetcher._browser)
            with self.assertRaises(DiscoveryFetchError) as raised:
                fetcher.prepin_hostnames(["source-b.test"])
            self.assertEqual(raised.exception.category, "browser_pinning_unavailable")
            self.assertIn("source-a.test", fetcher._pinned_host_ips)
            self.assertNotIn("source-b.test", fetcher._pinned_host_ips)
        finally:
            fetcher.close()

    def test_unsafe_dns_resolution_fails_closed_during_prepin(self):
        resolver = self._resolver({"unsafe.test": {1: ["10.0.0.5"], 28: []}})
        fetcher = self._base_fetcher(
            resolver=resolver,
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        try:
            with self.assertRaises(DiscoveryFetchError) as raised:
                fetcher.prepin_hostnames(["unsafe.test"])
            self.assertEqual(raised.exception.category, "dns_error")
            self.assertNotIn("unsafe.test", fetcher._pinned_host_ips)
        finally:
            fetcher.close()

    def test_failed_dns_resolution_fails_closed_during_prepin(self):
        resolver = self._resolver({"missing.test": {1: [], 28: []}})
        fetcher = self._base_fetcher(
            resolver=resolver,
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        try:
            with self.assertRaises(DiscoveryFetchError) as raised:
                fetcher.prepin_hostnames(["missing.test"])
            self.assertEqual(raised.exception.category, "dns_error")
            self.assertNotIn("missing.test", fetcher._pinned_host_ips)
        finally:
            fetcher.close()

    def test_single_source_hostname_pinned_before_launch_preserved(self):
        resolver = self._resolver({
            "source-a.test": {1: ["93.184.216.34"], 28: []},
        })
        fetcher = self._base_fetcher(
            resolver=resolver,
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        try:
            fetcher.prepin_hostnames(["source-a.test"])
            self.assertIn("source-a.test", fetcher._pinned_host_ips)
            self.assertEqual(
                fetcher._host_resolver_rules,
                "MAP source-a.test 93.184.216.34, MAP * ~NOTFOUND",
            )
        finally:
            fetcher.close()

    def test_prepin_hostnames_resolves_through_fetcher_launch_arguments(self):
        resolver = self._resolver({
            "source-a.test": {1: ["93.184.216.34"], 28: []},
            "source-b.test": {1: ["93.184.216.35"], 28: []},
        })
        fetcher = self._base_fetcher(
            resolver=resolver,
            playwright_factory=lambda: _FakePlaywright(_FakeBrowser(_FakeContext([]))),
        )
        try:
            fetcher.prepin_hostnames(["source-a.test", "source-b.test"])
            args = fetcher._browser_launch_arguments()
            resolver_args = [a for a in args if a.startswith("--host-resolver-rules=")]
            self.assertEqual(len(resolver_args), 1)
            self.assertIn("MAP source-a.test 93.184.216.34", resolver_args[0])
            self.assertIn("MAP source-b.test 93.184.216.35", resolver_args[0])
            self.assertIn("MAP * ~NOTFOUND", resolver_args[0])
        finally:
            fetcher.close()


if __name__ == "__main__":
    unittest.main()
