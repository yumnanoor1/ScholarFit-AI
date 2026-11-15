"""When the official site refuses us, and what an admin can do instead.

A 403 from the host used to surface as 502 Bad Gateway, which reads as "our
server is broken" and offers nothing to do next. These tests pin the mapping
onto a 424 carrying {category, http_status, message}, the robots rule now
applied to import, the pasted-text path, and that a non-admin gets none of it.

No live requests: every fetch is a fake or a patched Playwright factory.

Run from the backend folder:
    python -m unittest tests.test_scholarship_import_blocked -v
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.config import ScholarshipDiscoverySettings
from app.core.permissions import require_admin
from app.routers import admin_scholarships
from app.services.scholarship_discovery_fetch import (
    DiscoveryFetchError,
    FetchedPage,
    OfficialSourceFetcher,
)
from app.services.scholarship_import import (
    SOURCE_BLOCKED_STATUSES,
    ScholarshipImportError,
    _import_error_for_fetch_failure,
    extract_scholarship_source,
)

PAGE_TEXT = (
    "The Example Master's Award supports Master's students at Example University "
    "in Germany. The application deadline is 31 July 2027."
)


def _settings(**changes):
    values = {
        "enabled": False,
        "request_timeout_seconds": 2,
        "max_response_bytes": 4096,
        "max_extracted_chars": 2000,
        "max_pages_per_source": 3,
        "max_retries": 0,
        "request_delay_seconds": 0,
        "user_agent": "FitScholarImportTest/1.0",
        "model": "mock-model",
        "groq_model": "mock-model",
        "groq_rate_limit_retries": 0,
    }
    values.update(changes)
    return ScholarshipDiscoverySettings(**values)


class _RefusingFetcher:
    """A fetcher whose host answers with one status, and which records cleanup."""

    def __init__(self, failure):
        self.failure = failure
        self.closed = 0

    def fetch_import_url(self, url, source_type):
        raise self.failure

    def close(self):
        self.closed += 1


class _FakeExtractor:
    def __init__(self):
        self.page = None

    def extract(self, page):
        self.page = page
        return {
            "name": {
                "value": "Example Master's Award",
                "evidence": "The Example Master's Award",
                "confidence": "high",
            },
            "country": {
                "value": "Germany",
                "evidence": "in Germany",
                "confidence": "high",
            },
        }


class ErrorMappingTests(unittest.TestCase):
    """Which status an administrator sees for which failure."""

    def test_a_refusal_is_a_424_naming_the_category_and_status(self):
        for status in sorted(SOURCE_BLOCKED_STATUSES):
            with self.subTest(status=status):
                error = _import_error_for_fetch_failure(
                    DiscoveryFetchError("refused", status_code=status),
                )
                self.assertEqual(error.status_code, 424)
                self.assertEqual(error.error_category, "source_blocked")
                self.assertEqual(error.http_status, status)
                self.assertIn(str(status), str(error))

    def test_robots_disallowing_us_is_also_a_refusal(self):
        error = _import_error_for_fetch_failure(
            DiscoveryFetchError("robots", category="robots_check_failed"),
        )
        self.assertEqual(error.status_code, 424)
        self.assertEqual(error.error_category, "source_blocked")
        self.assertIn("robots.txt", str(error))

    def test_a_real_upstream_failure_is_still_a_502(self):
        for status in (500, 502, 503, 504):
            with self.subTest(status=status):
                error = _import_error_for_fetch_failure(
                    DiscoveryFetchError("broken", status_code=status),
                )
                self.assertEqual(error.status_code, 502)
        for category in ("timeout", "connection_error", "dns_error"):
            with self.subTest(category=category):
                error = _import_error_for_fetch_failure(
                    DiscoveryFetchError("no answer", category=category),
                )
                self.assertEqual(error.status_code, 502)

    def test_a_missing_page_is_the_admin_s_to_correct_not_a_gateway_error(self):
        error = _import_error_for_fetch_failure(
            DiscoveryFetchError("missing", status_code=404),
        )
        self.assertEqual(error.status_code, 422)
        self.assertEqual(error.http_status, 404)
        self.assertNotEqual(error.status_code, 502)


class BlockedSourceEndpointTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(admin_scholarships.router)
        self.app.dependency_overrides[require_admin] = lambda: SimpleNamespace(
            id=1, role="admin", email="admin@example.com",
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()

    def _post_url(self, url="https://awards.example/call"):
        return self.client.post(
            "/admin/scholarships/import/extract",
            data={"source_type": "webpage", "url": url},
        )

    def test_a_403_from_the_host_is_reported_as_source_blocked(self):
        fetcher = _RefusingFetcher(DiscoveryFetchError("refused", status_code=403))
        with patch(
            "app.services.scholarship_import._build_import_fetcher",
            return_value=fetcher,
        ):
            response = self._post_url()
        self.assertEqual(response.status_code, 424, response.text)
        detail = response.json()["detail"]
        self.assertEqual(detail["category"], "source_blocked")
        self.assertEqual(detail["http_status"], 403)
        self.assertIn("403", detail["message"])
        # The failure must not read as our server being broken.
        self.assertNotIn(response.status_code, (500, 502))

    def test_the_fetcher_is_closed_even_when_the_host_refuses(self):
        fetcher = _RefusingFetcher(DiscoveryFetchError("refused", status_code=403))
        with patch(
            "app.services.scholarship_import._build_import_fetcher",
            return_value=fetcher,
        ):
            self._post_url()
        self.assertEqual(fetcher.closed, 1, "a fetcher we created is ours to close")

    def test_a_server_error_at_the_host_is_still_a_502(self):
        fetcher = _RefusingFetcher(DiscoveryFetchError("down", status_code=503))
        with patch(
            "app.services.scholarship_import._build_import_fetcher",
            return_value=fetcher,
        ):
            response = self._post_url()
        self.assertEqual(response.status_code, 502, response.text)

    def test_robots_refusing_import_is_reported_the_same_way(self):
        fetcher = _RefusingFetcher(
            DiscoveryFetchError("robots", category="robots_check_failed"),
        )
        with patch(
            "app.services.scholarship_import._build_import_fetcher",
            return_value=fetcher,
        ):
            response = self._post_url()
        self.assertEqual(response.status_code, 424, response.text)
        self.assertEqual(response.json()["detail"]["category"], "source_blocked")


class PastedTextTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(admin_scholarships.router)
        self.app.dependency_overrides[require_admin] = lambda: SimpleNamespace(
            id=1, role="admin", email="admin@example.com",
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()

    def _post_text(self, **body):
        payload = {"text": PAGE_TEXT, "url": "https://awards.example/call"}
        payload.update(body)
        return self.client.post("/admin/scholarships/import/extract-text", json=payload)

    def test_pasted_text_is_extracted_with_the_url_kept_as_provenance(self):
        with patch(
            "app.services.scholarship_import.GroqScholarshipImportExtractor",
            return_value=_FakeExtractor(),
        ):
            response = self._post_text()
        self.assertEqual(response.status_code, 200, response.text)
        draft = response.json()
        self.assertEqual(draft["source"]["kind"], "pasted_text")
        self.assertEqual(draft["source"]["url"], "https://awards.example/call")
        self.assertEqual(draft["values"]["name"], "Example Master's Award")
        self.assertEqual(draft["fields"]["name"]["status"], "extracted")

    def test_the_same_evidence_check_runs_against_the_pasted_text(self):
        # A quote that is not in the pasted text cannot be accepted as
        # evidence, exactly as on the URL path.
        class _Unsupported(_FakeExtractor):
            def extract(self, page):
                super().extract(page)
                return {
                    "name": {
                        "value": "Example Master's Award",
                        "evidence": "a sentence that is not on the page at all",
                        "confidence": "high",
                    },
                }

        with patch(
            "app.services.scholarship_import.GroqScholarshipImportExtractor",
            return_value=_Unsupported(),
        ):
            response = self._post_text()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotEqual(response.json()["fields"]["name"]["status"], "extracted")

    def test_nothing_is_fetched_for_pasted_text(self):
        calls = []

        class _NeverFetch(OfficialSourceFetcher):
            def fetch_import_url(self, url, source_type):  # pragma: no cover
                calls.append(url)
                raise AssertionError("pasted text must not fetch anything")

        fetcher = _NeverFetch(_settings())
        draft = extract_scholarship_source(
            "pasted_text",
            text=PAGE_TEXT,
            url="https://awards.example/call",
            settings=_settings(),
            fetcher=fetcher,
            extractor=_FakeExtractor(),
        )
        self.assertEqual(calls, [])
        self.assertEqual(draft.source.kind, "pasted_text")

    def test_empty_or_oversized_text_is_refused(self):
        self.assertEqual(self._post_text(text="").status_code, 422)
        self.assertEqual(self._post_text(text="   ").status_code, 400)
        self.assertEqual(self._post_text(text="x" * 200_001).status_code, 422)

    def test_an_unsafe_provenance_url_is_refused(self):
        for url in ("file:///etc/passwd", "http://127.0.0.1/admin", "not a url"):
            with self.subTest(url=url):
                response = self._post_text(url=url)
                self.assertGreaterEqual(response.status_code, 400)
                self.assertLess(response.status_code, 500, response.text)

    def test_text_without_a_url_still_works(self):
        with patch(
            "app.services.scholarship_import.GroqScholarshipImportExtractor",
            return_value=_FakeExtractor(),
        ):
            response = self._post_text(url=None)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["source"]["url"])

    def test_unexpected_fields_are_refused(self):
        response = self.client.post(
            "/admin/scholarships/import/extract-text",
            json={"text": PAGE_TEXT, "url": None, "extra": "no"},
        )
        self.assertEqual(response.status_code, 422)

    def test_pasted_text_needs_an_admin(self):
        denied = FastAPI()
        denied.include_router(admin_scholarships.router)

        def deny():
            raise HTTPException(status_code=403, detail="Admin access required.")

        denied.dependency_overrides[require_admin] = deny
        with TestClient(denied) as client:
            for path, body in (
                ("/admin/scholarships/import/extract-text", {"text": PAGE_TEXT}),
            ):
                with self.subTest(path=path):
                    response = client.post(path, json=body)
                    self.assertEqual(response.status_code, 403, response.text)


class FetcherCleanupTests(unittest.TestCase):
    """A fetcher import creates is import's to close.

    With the browser path enabled that fetcher owns a Chromium process, so a
    missed close leaks one per import.
    """

    class _Spy:
        def __init__(self):
            self.closed = 0

        def fetch_import_url(self, url, source_type):
            return FetchedPage(
                url=url, content_type="text/html", text=PAGE_TEXT, links=(),
                content_hash="c" * 64, page_texts=(PAGE_TEXT,),
            )

        def close(self):
            self.closed += 1

    def test_a_fetcher_import_created_is_closed_after_a_successful_draft(self):
        spy = self._Spy()
        with patch(
            "app.services.scholarship_import._build_import_fetcher", return_value=spy,
        ), patch(
            "app.services.scholarship_import.GroqScholarshipImportExtractor",
            return_value=_FakeExtractor(),
        ):
            draft = extract_scholarship_source(
                "webpage", url="https://awards.example/call", settings=_settings(),
            )
        self.assertEqual(spy.closed, 1)
        self.assertEqual(draft.fields["name"].status, "extracted")

    def test_a_fetcher_the_caller_supplied_is_left_open(self):
        spy = self._Spy()
        with patch(
            "app.services.scholarship_import.GroqScholarshipImportExtractor",
            return_value=_FakeExtractor(),
        ):
            extract_scholarship_source(
                "webpage", url="https://awards.example/call",
                settings=_settings(), fetcher=spy,
            )
        self.assertEqual(spy.closed, 0, "the caller closes what the caller opened")


class ImportFetcherChoiceTests(unittest.TestCase):
    """Which fetcher import builds, and the robots rule it now applies."""

    def test_without_the_flag_import_uses_the_plain_http_fetcher(self):
        from app.services.scholarship_import import _build_import_fetcher

        with patch("app.services.scholarship_import.import_uses_browser", return_value=False):
            fetcher = _build_import_fetcher(_settings())
        self.addCleanup(fetcher.close)
        self.assertIsInstance(fetcher, OfficialSourceFetcher)
        self.assertFalse(fetcher.chromium_enabled)

    def test_with_the_flag_import_reads_pages_through_the_browser(self):
        from app.services.scholarship_import import _build_import_fetcher

        with patch("app.services.scholarship_import.import_uses_browser", return_value=True):
            fetcher = _build_import_fetcher(_settings())
        self.addCleanup(fetcher.close)
        self.assertTrue(
            fetcher.chromium_enabled,
            "the browser path is what gets the page a 403-ing site shows a person",
        )

    def test_import_now_honours_robots(self):
        fetcher = OfficialSourceFetcher(_settings())
        with patch.object(fetcher, "_robots_allowed", return_value=False):
            with self.assertRaises(DiscoveryFetchError) as caught:
                fetcher.fetch_import_url("https://awards.example/call", "webpage")
        self.assertEqual(caught.exception.category, "robots_check_failed")
        # ...and the admin sees a refusal, not a gateway error.
        self.assertEqual(_import_error_for_fetch_failure(caught.exception).status_code, 424)

    def test_an_allowed_page_is_read_through_the_browser_when_enabled(self):
        page = FetchedPage(
            url="https://awards.example/call",
            content_type="text/html",
            text=PAGE_TEXT,
            links=(),
            content_hash="b" * 64,
            page_texts=(PAGE_TEXT,),
        )
        fetcher = OfficialSourceFetcher(_settings(), playwright_factory=lambda: None)
        with patch.object(fetcher, "_robots_allowed", return_value=True), \
                patch.object(fetcher, "_fetch_playwright_page", return_value=page) as browser:
            result = fetcher.fetch_import_url("https://awards.example/call", "webpage")
        self.assertEqual(browser.call_count, 1, "the browser path was used")
        self.assertEqual(result.text, PAGE_TEXT)

    def test_a_pdf_url_never_goes_through_the_browser(self):
        fetcher = OfficialSourceFetcher(_settings(), playwright_factory=lambda: None)
        with patch.object(fetcher, "_robots_allowed", return_value=True), \
                patch.object(fetcher, "_fetch_playwright_page") as browser, \
                patch.object(fetcher, "_fetch_bytes", side_effect=DiscoveryFetchError("stop")):
            with self.assertRaises(DiscoveryFetchError):
                fetcher.fetch_import_url("https://awards.example/call.pdf", "pdf_url")
        self.assertEqual(browser.call_count, 0, "there is nothing for a browser to render")

    def test_pasted_text_keeps_the_character_limit(self):
        fetcher = OfficialSourceFetcher(_settings(max_extracted_chars=50))
        page = fetcher.page_from_pasted_text("y" * 500, None)
        self.assertEqual(len(page.text), 50)

    def test_oversized_pasted_text_is_refused_by_the_fetcher(self):
        fetcher = OfficialSourceFetcher(_settings(max_response_bytes=100))
        with self.assertRaises(DiscoveryFetchError):
            fetcher.page_from_pasted_text("z" * 200, None)


if __name__ == "__main__":
    unittest.main()
