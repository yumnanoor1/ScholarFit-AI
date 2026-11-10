import json
import unittest
from dataclasses import replace
from email.message import Message
from types import SimpleNamespace
from unittest.mock import Mock, patch

import dns.rdatatype
import dns.resolver
import fitz
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.config import ScholarshipDiscoverySettings, scholarship_discovery_settings
from app.core.permissions import require_admin
from app.routers import admin_scholarships
from app.schemas.scholarship_import import (
    ScholarshipImportDraft,
    ScholarshipImportField,
    ScholarshipImportSource,
)
from app.services.scholarship_discovery_fetch import (
    DiscoveryFetchError,
    FetchedPage,
    OfficialSourceFetcher,
)
from app.services.scholarship_import import (
    GeminiScholarshipImportExtractor,
    ScholarshipImportError,
    extract_scholarship_source,
)


def _settings(**changes):
    values = {
        "enabled": False,
        "request_timeout_seconds": 2,
        "max_response_bytes": 2048,
        "max_extracted_chars": 2000,
        "max_pages_per_source": 3,
        "max_retries": 0,
        "request_delay_seconds": 0,
        "user_agent": "FitScholarImportTest/1.0",
        "model": "mock-model",
    }
    values.update(changes)
    return ScholarshipDiscoverySettings(**values)


def _page(text, *, url="https://awards.example/call", content_type="text/html", links=()):
    return FetchedPage(
        url=url,
        content_type=content_type,
        text=text,
        links=tuple(links),
        content_hash="a" * 64,
        page_texts=(text,),
    )


def _pdf(pages=2):
    document = fitz.open()
    for index in range(pages):
        page = document.new_page()
        page.insert_text((72, 72), f"Scholarship call page {index + 1}")
    body = document.tobytes()
    document.close()
    return body


def _headers(content_type="text/html", location=None):
    headers = Message()
    headers["Content-Type"] = content_type
    if location:
        headers["Location"] = location
    return headers


class _FakeResolver:
    def __init__(self, addresses=None):
        self.addresses = addresses or {}
        self.calls = []

    def __call__(self, host, record_type, *, lifetime, search):
        self.calls.append((host, record_type, lifetime, search))
        if record_type == dns.rdatatype.AAAA:
            raise dns.resolver.NoAnswer()
        address = self.addresses.get(host, "8.8.8.8")
        return [SimpleNamespace(address=address)]


class _FakeFetcher:
    def __init__(self, page=None):
        self.page = page
        self.requested = []

    def fetch_import_url(self, url, source_type):
        self.requested.append((url, source_type))
        return self.page

    def extract_uploaded_pdf(self, body):
        self.requested.append(("upload", len(body)))
        return self.page


class _FakeExtractor:
    def __init__(self, fields):
        self.fields = fields
        self.page = None

    def extract(self, page):
        self.page = page
        return self.fields


class FetchSecurityTests(unittest.TestCase):
    def test_generic_import_url_rejects_unsupported_schemes_and_embedded_credentials(self):
        fetcher = OfficialSourceFetcher(_settings())
        for url in (
            "file://awards.example/call",
            "ftp://awards.example/call",
            "https://admin:secret@awards.example/call",
            "https://awards.example:8443/call",
            "https://[invalid/call",
        ):
            with self.subTest(url=url), self.assertRaises(DiscoveryFetchError):
                fetcher._validate_url(None, url)

    def test_private_dns_addresses_are_rejected(self):
        fetcher = OfficialSourceFetcher(
            _settings(),
            resolver=_FakeResolver({"private.example": "10.0.0.4"}),
        )
        with self.assertRaisesRegex(DiscoveryFetchError, "public addresses"):
            fetcher._resolve_public_addresses("private.example", 443)

    def test_every_redirect_destination_is_revalidated(self):
        resolver = _FakeResolver({"private.example": "127.0.0.1"})
        fetcher = OfficialSourceFetcher(_settings(), resolver=resolver)

        def fake_request(source, url):
            parts = fetcher._validate_url(source, url)
            fetcher._resolve_public_addresses(parts.hostname, parts.port or 443)
            return 302, _headers(location="http://private.example/redirect"), b""

        with patch.object(fetcher, "_request", side_effect=fake_request):
            with self.assertRaises(DiscoveryFetchError):
                fetcher._fetch_bytes(None, "https://awards.example/call")
        self.assertTrue(any(
            call[0] == "private.example" and call[1] == dns.rdatatype.A
            for call in resolver.calls
        ))

    def test_redirect_to_a_different_public_host_is_allowed_after_revalidation(self):
        fetcher = OfficialSourceFetcher(_settings(), resolver=_FakeResolver())
        responses = [
            (302, _headers(location="https://cdn.example/call"), b""),
            (200, _headers(), b"<p>Scholarship details</p>"),
        ]

        def fake_request(source, url):
            parts = fetcher._validate_url(source, url)
            fetcher._resolve_public_addresses(parts.hostname, parts.port or 443)
            return responses.pop(0)

        with patch.object(fetcher, "_request", side_effect=fake_request):
            final_url, headers, body = fetcher._fetch_bytes(None, "https://awards.example/call")
        self.assertEqual(final_url, "https://cdn.example/call")
        self.assertEqual(headers.get_content_type(), "text/html")
        self.assertIn(b"Scholarship", body)

    def test_import_fetcher_parses_webpage_text_and_link_evidence(self):
        fetcher = OfficialSourceFetcher(_settings())
        body = b"<html><script>ignore this</script><a href='/apply'>Apply here</a><p>Award details.</p></html>"
        with patch.object(
            fetcher,
            "_fetch_bytes",
            return_value=("https://awards.example/call", _headers(), body),
        ):
            page = fetcher.fetch_import_url("https://awards.example/call", "webpage")
        self.assertIn("Award details.", page.text)
        self.assertNotIn("ignore this", page.text)
        self.assertEqual(page.links, (("/apply", "Apply here"),))
        self.assertEqual(page.page_texts, (page.text,))

    def test_import_fetcher_parses_direct_pdf_url_and_rejects_mime_mismatch(self):
        fetcher = OfficialSourceFetcher(_settings())
        body = _pdf()
        with patch.object(
            fetcher,
            "_fetch_bytes",
            return_value=("https://awards.example/call.pdf", _headers("application/pdf"), body),
        ):
            page = fetcher.fetch_import_url("https://awards.example/call.pdf", "pdf_url")
        self.assertEqual(page.content_type, "application/pdf")
        self.assertEqual(page.page_count, 2)
        self.assertIn("Scholarship call page 2", page.page_texts[1])
        with patch.object(
            fetcher,
            "_request",
            return_value=(200, _headers("application/octet-stream"), body),
        ):
            with self.assertRaisesRegex(DiscoveryFetchError, "Unsupported content type"):
                fetcher._fetch_bytes(
                    None,
                    "https://awards.example/call.pdf",
                    allowed_types={"application/pdf"},
                )


class ExtractionTests(unittest.TestCase):
    def test_webpage_import_extracts_supported_fields_and_marks_missing_fields(self):
        source_text = "The Horizon Award provides full tuition to eligible students."
        page = _page(source_text)
        draft = extract_scholarship_source(
            "webpage",
            url=page.url,
            settings=_settings(),
            fetcher=_FakeFetcher(page),
            extractor=_FakeExtractor({
                "name": {
                    "value": "Horizon Award",
                    "evidence": "The Horizon Award",
                    "confidence": "high",
                },
                "funding_level": {
                    "value": "full",
                    "evidence": "provides full tuition",
                    "confidence": "medium",
                },
            }),
        )
        self.assertEqual(draft.values, {"name": "Horizon Award", "funding_level": "full"})
        self.assertEqual(draft.fields["name"].status, "extracted")
        self.assertTrue(draft.fields["name"].suggestion_valid)
        self.assertEqual(draft.fields["name"].source_label, "awards.example")
        self.assertEqual(draft.fields["name"].source_url, page.url)
        self.assertEqual(draft.fields["provider"].status, "not_found")
        self.assertEqual(draft.fields["provider"].source_url, page.url)
        self.assertEqual(draft.source.kind, "webpage")
        self.assertEqual(draft.source.url, page.url)

    def test_pdf_url_extracts_page_provenance(self):
        body = _pdf()
        settings = _settings()
        fetcher = OfficialSourceFetcher(settings)
        page = fetcher.extract_uploaded_pdf(body)
        page = replace(page, url="https://awards.example/call.pdf")
        draft = extract_scholarship_source(
            "pdf_url",
            url=page.url,
            settings=settings,
            fetcher=_FakeFetcher(page),
            extractor=_FakeExtractor({
                "name": {
                    "value": "Page Two Award",
                    "evidence": "Scholarship call page 2",
                    "page_number": 2,
                    "confidence": "high",
                },
            }),
        )
        self.assertEqual(draft.values["name"], "Page Two Award")
        self.assertEqual(draft.fields["name"].page_number, 2)

    def test_manual_pdf_upload_handles_multiple_pages(self):
        settings = _settings()
        fetcher = OfficialSourceFetcher(settings)
        body = _pdf(pages=3)
        page = fetcher.extract_uploaded_pdf(body)
        draft = extract_scholarship_source(
            "pdf_upload",
            file_bytes=body,
            filename=r"C:\uploads\call.pdf",
            settings=settings,
            fetcher=_FakeFetcher(page),
            extractor=_FakeExtractor({
                "name": {
                    "value": "Multi Page Award",
                    "evidence": "Scholarship call page 3",
                    "page_number": 3,
                    "confidence": "high",
                },
            }),
        )
        self.assertEqual(page.page_count, 3)
        self.assertEqual(draft.fields["name"].page_number, 3)
        self.assertEqual(draft.source.label, "call.pdf")

    def test_low_confidence_and_unmatched_evidence_are_uncertain(self):
        page = _page("The scholarship offers a stipend.")
        draft = extract_scholarship_source(
            "webpage",
            url=page.url,
            settings=_settings(),
            fetcher=_FakeFetcher(page),
            extractor=_FakeExtractor({
                "stipend_status": {
                    "value": "provided",
                    "evidence": "The scholarship offers a stipend.",
                    "confidence": "low",
                },
                "name": {
                    "value": "Guess",
                    "evidence": "A quote not on the page",
                    "confidence": "high",
                },
                "english_requirement_type": {
                    "value": "not_specified",
                    "evidence": "The scholarship offers a stipend.",
                    "confidence": [],
                },
            }),
        )
        self.assertEqual(draft.fields["stipend_status"].status, "uncertain")
        self.assertEqual(draft.fields["name"].status, "uncertain")
        self.assertEqual(draft.fields["english_requirement_type"].status, "uncertain")
        self.assertIsNone(draft.fields["english_requirement_type"].confidence)
        self.assertNotIn("stipend_status", draft.values)
        self.assertNotIn("name", draft.values)

    def test_invalid_enum_and_inconsistent_structured_values_are_withheld(self):
        page = _page("The Horizon Award requires a GPA of 3.5 on a 4.0 scale.")
        draft = extract_scholarship_source(
            "webpage",
            url=page.url,
            settings=_settings(),
            fetcher=_FakeFetcher(page),
            extractor=_FakeExtractor({
                "funding_level": {
                    "value": "guaranteed full",
                    "evidence": "The Horizon Award requires",
                    "confidence": "high",
                },
                "min_gpa": {
                    "value": 3.5,
                    "evidence": "GPA of 3.5",
                    "confidence": "high",
                },
                "min_gpa_scale": {
                    "value": 4.0,
                    "evidence": "4.0 scale",
                    "confidence": "high",
                },
            }),
        )
        self.assertEqual(draft.fields["funding_level"].status, "uncertain")
        self.assertFalse(draft.fields["funding_level"].suggestion_valid)
        self.assertEqual(draft.fields["min_gpa"].status, "extracted")
        self.assertNotIn("funding_level", draft.values)
        self.assertEqual(draft.values["min_gpa"], 3.5)

    def test_incomplete_gpa_pair_is_withheld_by_schema_consistency(self):
        page = _page("Minimum GPA 3.5")
        draft = extract_scholarship_source(
            "webpage",
            url=page.url,
            settings=_settings(),
            fetcher=_FakeFetcher(page),
            extractor=_FakeExtractor({
                "min_gpa": {"value": 3.5, "evidence": "Minimum GPA 3.5", "confidence": "high"},
            }),
        )
        self.assertEqual(draft.values, {})
        self.assertEqual(draft.fields["min_gpa"].status, "uncertain")
        self.assertIn("conflict", draft.fields["min_gpa"].note)

    def test_inconsistent_amount_does_not_withhold_unrelated_supported_fields(self):
        page = _page("The Horizon Award provides a stipend of 1,000.")
        draft = extract_scholarship_source(
            "webpage",
            url=page.url,
            settings=_settings(),
            fetcher=_FakeFetcher(page),
            extractor=_FakeExtractor({
                "name": {
                    "value": "Horizon Award",
                    "evidence": "The Horizon Award",
                    "confidence": "high",
                },
                "stipend_amount": {
                    "value": 1000,
                    "evidence": "stipend of 1,000",
                    "confidence": "high",
                },
            }),
        )
        self.assertEqual(draft.values["name"], "Horizon Award")
        self.assertNotIn("stipend_amount", draft.values)
        self.assertEqual(draft.fields["name"].status, "extracted")
        self.assertEqual(draft.fields["stipend_amount"].status, "uncertain")

    def test_unlisted_source_url_is_not_accepted(self):
        page = _page(
            "Apply at the linked application portal.",
            links=(("/apply", "application portal"),),
        )
        draft = extract_scholarship_source(
            "webpage",
            url=page.url,
            settings=_settings(),
            fetcher=_FakeFetcher(page),
            extractor=_FakeExtractor({
                "official_application_url": {
                    "value": "https://unrelated.example/apply",
                    "evidence": "application portal",
                    "confidence": "high",
                },
            }),
        )
        self.assertEqual(draft.fields["official_application_url"].status, "uncertain")
        self.assertNotIn("official_application_url", draft.values)

    def test_application_url_in_pdf_text_is_supported_with_source_evidence(self):
        source_text = "Apply at https://apply.example/form"
        page = FetchedPage(
            url="https://awards.example/call.pdf",
            content_type="application/pdf",
            text=source_text,
            links=(),
            content_hash="b" * 64,
            page_count=1,
            page_texts=(source_text,),
        )
        draft = extract_scholarship_source(
            "pdf_upload",
            file_bytes=_pdf(1),
            filename="call.pdf",
            settings=_settings(),
            fetcher=_FakeFetcher(page),
            extractor=_FakeExtractor({
                "official_application_url": {
                    "value": "https://apply.example/form",
                    "evidence": "Apply at https://apply.example/form",
                    "page_number": 1,
                    "confidence": "high",
                },
            }),
        )
        self.assertEqual(draft.values["official_application_url"], "https://apply.example/form")
        self.assertEqual(draft.fields["official_application_url"].page_number, 1)

    def test_gemini_extractor_uses_mocked_client_and_untrusted_source_prompt(self):
        response = SimpleNamespace(text=json.dumps({
            "fields": {
                "name": {
                    "value": "Horizon Award",
                    "evidence": "The Horizon Award",
                    "confidence": "high",
                },
            },
        }))
        client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock(return_value=response)))
        extractor = GeminiScholarshipImportExtractor(_settings(), client=client)
        result = extractor.extract(_page("The Horizon Award is available."))
        self.assertIn("name", result)
        prompt = client.models.generate_content.call_args.kwargs["contents"]
        self.assertIn("untrusted evidence", prompt)
        self.assertIn("Allowed scholarship field schema", prompt)
        self.assertEqual(
            client.models.generate_content.call_args.kwargs["model"],
            "mock-model",
        )
        self.assertEqual(
            client.models.generate_content.call_args.kwargs["config"]["http_options"].timeout,
            60_000,
        )

    def test_import_uses_shared_model_and_reports_sanitized_provider_category(self):
        with patch.dict(
            "os.environ",
            {
                "GEMINI_MODEL": "gemini-3-flash-preview",
                "SCHOLARSHIP_DISCOVERY_MODEL": "legacy-model",
            },
            clear=True,
        ):
            settings = scholarship_discovery_settings()
        client = Mock()
        client.models.generate_content.side_effect = type(
            "FakeProviderError",
            (Exception,),
            {"code": 403},
        )("credential=private")
        extractor = GeminiScholarshipImportExtractor(settings, client=client)

        with self.assertRaises(ScholarshipImportError) as raised:
            extractor.extract(_page("The Horizon Award is available."))

        self.assertEqual(
            client.models.generate_content.call_args.kwargs["model"],
            "gemini-3-flash-preview",
        )
        self.assertEqual(raised.exception.error_category, "permission_error")
        self.assertEqual(raised.exception.http_status, 403)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("permission_error", str(raised.exception))
        self.assertNotIn("private", str(raised.exception))

    def test_bad_pdf_signature_size_and_page_count_are_rejected(self):
        settings = _settings(max_response_bytes=1024, max_pages_per_source=2)
        fetcher = OfficialSourceFetcher(settings)
        with self.assertRaisesRegex(DiscoveryFetchError, "signature"):
            fetcher.extract_uploaded_pdf(b"not a pdf")
        with self.assertRaisesRegex(ScholarshipImportError, "size limit"):
            extract_scholarship_source(
                "pdf_upload",
                file_bytes=b"x" * 1025,
                settings=settings,
                fetcher=fetcher,
                extractor=_FakeExtractor({}),
            )
        with self.assertRaisesRegex(DiscoveryFetchError, "page limit"):
            OfficialSourceFetcher(_settings(max_pages_per_source=2)).extract_uploaded_pdf(_pdf(3))

    def test_encrypted_and_unreadable_pdfs_are_rejected(self):
        document = fitz.open()
        document.new_page().insert_text((72, 72), "Protected content")
        encrypted = document.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
        document.close()
        with self.assertRaisesRegex(DiscoveryFetchError, "Encrypted"):
            OfficialSourceFetcher(_settings()).extract_uploaded_pdf(encrypted)
        with self.assertRaises(DiscoveryFetchError):
            OfficialSourceFetcher(_settings()).extract_uploaded_pdf(b"%PDF-1.7\ninvalid content")


class AdminEndpointTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(admin_scholarships.router)
        self.app.dependency_overrides[require_admin] = lambda: SimpleNamespace(role="admin")
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()

    @staticmethod
    def _draft():
        return ScholarshipImportDraft(
            values={"name": "Draft Award"},
            fields={"name": ScholarshipImportField(status="extracted", value="Draft Award")},
            source=ScholarshipImportSource(
                kind="webpage",
                label="awards.example",
                url="https://awards.example/call",
                content_type="text/html",
            ),
        )

    def test_webpage_request_returns_draft_without_a_database_dependency(self):
        with (
            patch.object(admin_scholarships, "scholarship_discovery_settings", return_value=_settings()),
            patch.object(admin_scholarships, "extract_scholarship_source", return_value=self._draft()) as extract,
        ):
            response = self.client.post(
                "/admin/scholarships/import/extract",
                data={"source_type": "webpage", "url": "https://awards.example/call"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["values"]["name"], "Draft Award")
        extract.assert_called_once()
        route = next(
            route for route in admin_scholarships.router.routes
            if route.path == "/admin/scholarships/import/extract"
        )
        self.assertNotIn(
            admin_scholarships.get_db,
            [dependency.call for dependency in route.dependant.dependencies],
        )

    def test_import_provider_category_is_returned_without_raw_error_details(self):
        with (
            patch.object(admin_scholarships, "scholarship_discovery_settings", return_value=_settings()),
            patch.object(
                admin_scholarships,
                "extract_scholarship_source",
                side_effect=ScholarshipImportError(
                    "Scholarship extraction is unavailable (quota_error). Try again later.",
                    status_code=503,
                    error_category="quota_error",
                    http_status=429,
                ),
            ),
        ):
            response = self.client.post(
                "/admin/scholarships/import/extract",
                data={"source_type": "webpage", "url": "https://awards.example/call"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("quota_error", response.json()["detail"])
        self.assertNotIn("429", response.json()["detail"])
        self.assertNotIn("credential", response.text)

    def test_upload_size_and_content_type_are_checked_before_extraction(self):
        settings = _settings(max_response_bytes=1024)
        with patch.object(admin_scholarships, "scholarship_discovery_settings", return_value=settings):
            oversized = self.client.post(
                "/admin/scholarships/import/extract",
                data={"source_type": "pdf_upload"},
                files={"file": ("large.pdf", b"x" * 1025, "application/pdf")},
            )
            wrong_type = self.client.post(
                "/admin/scholarships/import/extract",
                data={"source_type": "pdf_upload"},
                files={"file": ("call.txt", b"%PDF-1.7", "text/plain")},
            )
        self.assertEqual(oversized.status_code, 413, oversized.text)
        self.assertEqual(wrong_type.status_code, 415, wrong_type.text)

    def test_admin_authorization_is_required_for_import_route(self):
        denied_app = FastAPI()
        denied_app.include_router(admin_scholarships.router)

        def deny():
            raise HTTPException(status_code=403, detail="Admin access required.")

        denied_app.dependency_overrides[require_admin] = deny
        with TestClient(denied_app) as client:
            response = client.post(
                "/admin/scholarships/import/extract",
                data={"source_type": "webpage", "url": "https://awards.example/call"},
            )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
