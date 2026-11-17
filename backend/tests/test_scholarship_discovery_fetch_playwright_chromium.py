"""Real-Chromium integration checks for the Playwright DNS-pinning fetcher.

These tests use only local loopback servers and synthetic ``.test`` hostnames.
They do not contact external sites or perform real DNS lookups. Loopback
resolver mappings are exercised in a standalone Chromium harness so the
production fetcher's SSRF validation is never bypassed.
"""

import http.server
import os
import socket
import socketserver
import threading
import unittest
from types import SimpleNamespace

from app.services.scholarship_discovery_fetch import (
    DiscoveryFetchError,
    OfficialSourceFetcher,
)
from app.services.scholarship_discovery_sources import DiscoverySource

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    _PLAYWRIGHT_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment-dependent
    PlaywrightError = Exception
    sync_playwright = None
    _PLAYWRIGHT_IMPORT_ERROR = exc


_CATCH_ALL_RULE = "MAP * ~NOTFOUND"


def _settings(**changes):
    values = {
        "request_timeout_seconds": 2,
        "max_response_bytes": 4096,
        "max_extracted_chars": 5000,
        "max_pages_per_source": 5,
        "max_retries": 1,
        "request_delay_seconds": 0,
        "user_agent": "FitScholarChromiumIntegrationTest/1.0",
        "min_extracted_chars": 20,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _synthetic_source():
    return DiscoverySource(
        source_id="synthetic-chromium-test",
        name="Synthetic Chromium Test",
        official_domain="synthetic.test",
        category="test",
        country_or_region="test",
        source_url="http://synthetic.test/",
        source_classification="official_provider",
    )


def _synthetic_resolver(host, record_type, lifetime=None, search=False):
    import dns.rdatatype
    import dns.resolver as _dns_resolver

    if int(record_type) == int(dns.rdatatype.A):
        return [type("R", (), {"address": "93.184.216.34"})()]
    raise _dns_resolver.NoAnswer()


class _LocalHTTPHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/sw.js":
            body = b"self.addEventListener('install', () => self.skipWaiting());"
            content_type = "application/javascript"
        elif self.path.startswith("/ipv6"):
            body = b"<html><body>ipv6-local-ok</body></html>"
            content_type = "text/html"
        elif self.path.startswith("/ipv4"):
            body = b"<html><body>ipv4-local-ok</body></html>"
            content_type = "text/html"
        else:
            body = b"<html><body>local-ok</body></html>"
            content_type = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    address_family = socket.AF_INET6
    daemon_threads = True
    allow_reuse_address = True


def _start_server(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _stop_server(server):
    server.shutdown()
    server.server_close()


def _resolver_arguments(launch_arguments):
    return [
        argument
        for argument in launch_arguments
        if argument.strip().lower().startswith("--host-resolver-rules")
    ]


class _ChromiumTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            raise unittest.SkipTest(
                f"Playwright is unavailable: {_PLAYWRIGHT_IMPORT_ERROR}"
            )
        cls._playwright = sync_playwright().start()
        if not os.path.exists(cls._playwright.chromium.executable_path):
            cls._playwright.stop()
            cls._playwright = None
            raise unittest.SkipTest("Chromium executable is not installed")

    @classmethod
    def tearDownClass(cls):
        playwright = getattr(cls, "_playwright", None)
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
            cls._playwright = None

    def _launch(self, resolver_rules):
        return self._playwright.chromium.launch(
            headless=True,
            args=[f"--host-resolver-rules={resolver_rules}"],
        )

    def _goto_failure(self, page, url):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=5000)
        except PlaywrightError as exc:
            return str(exc)
        self.fail(f"Expected navigation to fail for {url}")


class RealChromiumResolverRuleTests(_ChromiumTestBase):
    def test_chromium_accepts_fetcher_generated_resolver_argument(self):
        fetcher = OfficialSourceFetcher(_settings())
        launch_arguments = fetcher._browser_launch_arguments()
        resolver_arguments = _resolver_arguments(launch_arguments)

        self.assertEqual(len(resolver_arguments), 1)
        self.assertEqual(resolver_arguments[0], f"--host-resolver-rules={_CATCH_ALL_RULE}")

        browser = self._playwright.chromium.launch(
            headless=True,
            args=launch_arguments,
        )
        try:
            self.assertTrue(browser.is_connected())
            self.assertRegex(browser.version, r"^\d+\.\d+\.\d+")
        finally:
            browser.close()

    def test_unpinned_synthetic_hostname_fails_under_catch_all_notfound(self):
        fetcher = OfficialSourceFetcher(_settings())
        resolver_arguments = _resolver_arguments(fetcher._browser_launch_arguments())
        self.assertEqual(len(resolver_arguments), 1)
        self.assertEqual(resolver_arguments[0], f"--host-resolver-rules={_CATCH_ALL_RULE}")

        browser = self._playwright.chromium.launch(
            headless=True,
            args=[resolver_arguments[0]],
        )
        context = browser.new_context()
        page = context.new_page()
        try:
            failure = self._goto_failure(page, "http://unpinned.test/")
            self.assertIn("net::ERR_NAME_NOT_RESOLVED", failure)
        finally:
            context.close()
            browser.close()

    def test_ipv4_resolver_mapping_reaches_local_server(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _LocalHTTPHandler)
        _start_server(server)
        port = server.server_address[1]
        host = "synthetic-v4.test"
        mapped_ip = OfficialSourceFetcher._host_resolver_rule_ip("127.0.0.1")
        self.assertEqual(mapped_ip, "127.0.0.1")

        browser = self._launch(f"MAP {host} {mapped_ip}, MAP * ~NOTFOUND")
        context = browser.new_context()
        page = context.new_page()
        try:
            response = page.goto(
                f"http://{host}:{port}/ipv4",
                wait_until="domcontentloaded",
                timeout=5000,
            )
            self.assertIsNotNone(response)
            self.assertEqual(response.status, 200)
            self.assertIn("ipv4-local-ok", page.content())
        finally:
            context.close()
            browser.close()
            _stop_server(server)

    def test_ipv6_resolver_mapping_uses_bracketed_production_format(self):
        try:
            server = _ThreadingHTTPServer(("::1", 0), _LocalHTTPHandler)
        except OSError as exc:
            self.skipTest(f"IPv6 loopback is unavailable in this environment: {exc}")
        _start_server(server)
        port = server.server_address[1]
        host = "synthetic-v6.test"
        production_ip = OfficialSourceFetcher._host_resolver_rule_ip("::1")
        self.assertEqual(production_ip, "[::1]")

        try:
            browser = self._launch(f"MAP {host} {production_ip}, MAP * ~NOTFOUND")
            context = browser.new_context()
            page = context.new_page()
            try:
                response = page.goto(
                    f"http://{host}:{port}/ipv6",
                    wait_until="domcontentloaded",
                    timeout=5000,
                )
                self.assertIsNotNone(response)
                self.assertEqual(response.status, 200)
                self.assertIn("ipv6-local-ok", page.content())
            finally:
                context.close()
                browser.close()
        finally:
            _stop_server(server)


class RealChromiumServiceWorkerTests(_ChromiumTestBase):
    _REGISTRATION_SCRIPT = """
    async () => {
      if (!('serviceWorker' in navigator)) {
        return {supported: false, registration: null, error: null};
      }
      try {
        const registration = await navigator.serviceWorker.register('/sw.js');
        return {
          supported: true,
          registration: registration
            ? {scope: registration.scope}
            : null,
          error: null,
        };
      } catch (error) {
        return {
          supported: true,
          registration: null,
          error: String(error),
        };
      }
    }
    """

    def test_service_workers_are_blocked_in_actual_chromium_context(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _LocalHTTPHandler)
        _start_server(server)
        port = server.server_address[1]
        browser = self._playwright.chromium.launch(headless=True)
        try:
            blocked_context = browser.new_context(service_workers="block")
            blocked_page = blocked_context.new_page()
            try:
                blocked_page.goto(
                    f"http://127.0.0.1:{port}/",
                    wait_until="domcontentloaded",
                    timeout=5000,
                )
                blocked_result = blocked_page.evaluate(self._REGISTRATION_SCRIPT)
                self.assertTrue(blocked_result["supported"])
                self.assertIsNone(blocked_result["registration"])
            finally:
                blocked_context.close()

            allowed_context = browser.new_context(service_workers="allow")
            allowed_page = allowed_context.new_page()
            try:
                allowed_page.goto(
                    f"http://127.0.0.1:{port}/",
                    wait_until="domcontentloaded",
                    timeout=5000,
                )
                allowed_result = allowed_page.evaluate(self._REGISTRATION_SCRIPT)
                self.assertTrue(allowed_result["supported"])
                self.assertIsNotNone(allowed_result["registration"])
            finally:
                allowed_context.close()
        finally:
            browser.close()
            _stop_server(server)


@unittest.skipUnless(sync_playwright is not None, "Playwright is unavailable")
class RealChromiumFetcherIntegrationTests(unittest.TestCase):
    def test_fetcher_launch_receives_exactly_one_generated_resolver_rule(self):
        playwright = sync_playwright().start()
        captured_launch_options = {}

        def recording_launcher(**launch_options):
            captured_launch_options.update(launch_options)
            return playwright.chromium.launch(**launch_options)

        fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=_synthetic_resolver,
            playwright_factory=lambda: playwright,
            browser_launcher=recording_launcher,
        )
        try:
            source = _synthetic_source()
            fetcher._safe_fetch_url(
                source,
                source.source_url,
                request_type="main_frame_navigation",
            )
            fetcher._ensure_browser()
            browser = fetcher._browser
            resolver_arguments = _resolver_arguments(
                captured_launch_options.get("args", [])
            )

            self.assertEqual(len(resolver_arguments), 1)
            self.assertEqual(
                resolver_arguments[0],
                f"--host-resolver-rules={fetcher._host_resolver_rules}",
            )
            self.assertIn("MAP synthetic.test 93.184.216.34", resolver_arguments[0])
            self.assertIn("MAP * ~NOTFOUND", resolver_arguments[0])
            self.assertTrue(browser.is_connected())
        finally:
            fetcher.close()
            try:
                playwright.stop()
            except Exception:
                pass

    def test_cleanup_after_failed_navigation_in_real_chromium(self):
        playwright = sync_playwright().start()
        fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=_synthetic_resolver,
            playwright_factory=lambda: playwright,
        )
        browser = None
        try:
            source = _synthetic_source()
            fetcher._safe_fetch_url(
                source,
                source.source_url,
                request_type="main_frame_navigation",
            )
            context = fetcher._ensure_browser()
            browser = fetcher._browser
            context.set_offline(True)

            with self.assertRaises(DiscoveryFetchError) as raised:
                fetcher._navigate_html(source, source.source_url)

            self.assertIn(raised.exception.category, {"connection_error", "timeout"})
            self.assertEqual(context.pages, [])
            self.assertEqual(fetcher.cleanup_errors, [])
            self.assertTrue(browser.is_connected())
        finally:
            fetcher.close()
            try:
                playwright.stop()
            except Exception:
                pass

        self.assertFalse(browser.is_connected())
        self.assertIsNone(fetcher._browser)
        self.assertIsNone(fetcher._context)
        self.assertIsNone(fetcher._playwright)


if __name__ == "__main__":
    unittest.main()