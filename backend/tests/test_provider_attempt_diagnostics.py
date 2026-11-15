import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import scholarship_discovery, scholarship_discovery_extraction
from app.services.groq_provider import GroqProviderError
from app.services.scholarship_discovery_extraction import ScholarshipExtractionError


class _ProviderFailure(Exception):
    def __init__(self, code):
        self.code = code
        self.status_code = code
        super().__init__("sanitized provider failure")


def _page():
    return SimpleNamespace(
        text="Finland Master's Award scholarship is available to Master's applicants to study in Finland.",
        url="https://official.example/scholarships",
        links=(),
        content_hash="a" * 64,
        content_type="text/html",
        page_count=None,
        insufficient_content=False,
        original_text_length=100,
        retained_text_length=100,
        text_truncated=False,
    )


def _source():
    return SimpleNamespace(
        source_id="offline-test-source",
        name="Offline source",
        official_domain="official.example",
        source_classification="government_authority",
        category="official_university_scholarship",
        country_or_region="Finland",
        source_url="https://official.example/scholarships",
        trust_basis="Official source",
        trust_reviewed=True,
        crawl_enabled=True,
        discovery_only=False,
    )


class ProviderAttemptDiagnosticsTests(unittest.TestCase):
    def test_groq_permission_failure_records_only_groq_attempt(self):
        groq = MagicMock()
        groq.chat.completions.create.side_effect = _ProviderFailure(403)
        extractor = scholarship_discovery_extraction.GroqScholarshipExtractor(
            SimpleNamespace(groq_model="g"),
            groq_client=groq,
        )
        extractor._prompt_within_budget = MagicMock(return_value="prompt")
        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor.extract(_page(), _source())
        self.assertEqual(raised.exception.category, "permission_error")
        d = extractor.last_provider_diagnostics
        self.assertEqual(d["providers_attempted"], ["groq"])
        self.assertEqual(d["final_provider"], "groq")
        self.assertEqual(d["final_error_category"], "permission_error")
        self.assertEqual(d["final_http_status"], 403)
        self.assertEqual(d["attempts"][0]["provider"], "groq")
        self.assertEqual(d["attempts"][0]["status"], "failed")
        self.assertEqual(d["attempts"][0]["error_category"], "permission_error")

    def test_groq_schema_error_is_sanitized_and_not_retried_with_another_provider(self):
        groq = MagicMock()
        groq.chat.completions.create.side_effect = GroqProviderError(
            "malformed_request",
            400,
            provider_error_details={
                "type": "invalid_request_error",
                "code": "invalid_json_schema",
                "param": "response_format",
                "message": "untrusted provider text",
            },
        )
        extractor = scholarship_discovery_extraction.GroqScholarshipExtractor(
            SimpleNamespace(groq_model="g"),
            groq_client=groq,
        )
        extractor._prompt_within_budget = MagicMock(return_value="prompt")
        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor.extract(_page(), _source())
        self.assertEqual(raised.exception.category, "malformed_request")
        self.assertEqual(raised.exception.http_status, 400)
        d = extractor.last_provider_diagnostics
        self.assertEqual(d["providers_attempted"], ["groq"])
        self.assertEqual(d["final_provider"], "groq")
        self.assertEqual(d["final_error_category"], "malformed_request")
        self.assertEqual(d["final_http_status"], 400)
        self.assertEqual(d["attempts"][0]["provider"], "groq")
        self.assertEqual(d["attempts"][0]["status"], "failed")
        self.assertEqual(d["attempts"][0]["error_category"], "malformed_request")
        self.assertEqual(d["attempts"][0]["http_status"], 400)
        self.assertEqual(d["attempts"][0]["provider_error_details"], {
            "type": "invalid_request_error",
            "code": "invalid_json_schema",
            "param": "response_format",
        })
        serialized = json.dumps(d)
        self.assertNotIn("Authorization", serialized)
        self.assertNotIn("api_key", serialized.lower())
        self.assertNotIn("prompt", serialized)
        self.assertNotIn("untrusted provider text", serialized)

    def test_discovery_records_provider_diagnostics_on_extraction_failure(self):
        source = _source()
        page = _page()
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        db.query.return_value.filter.return_value.first.return_value = None
        db.get_bind.return_value.dialect.name = "sqlite"
        settings = SimpleNamespace(enabled=True, stale_run_timeout_hours=1)
        fetcher = MagicMock()
        fetcher.crawl.return_value = [page]
        fetcher.last_crawl_stats = {
            "linked_urls_discovered": 0, "linked_pages_attempted": 0, "linked_pages_fetched": 0,
            "linked_pages_failed": 0, "linked_pages_skipped_safety": 0, "linked_pages_skipped_relevance": 0,
            "linked_pages_skipped": 0,
        }
        extractor = MagicMock()

        def extract_side_effect(*args, **kwargs):
            extractor.last_provider_diagnostics = {
                "providers_attempted": ["groq"],
                "attempts": [{"provider": "groq", "status": "failed", "error_category": "provider_error", "http_status": 400}],
                "final_provider": "groq",
                "final_error_category": "provider_error",
                "final_http_status": 400,
                "processing_stopped_after_failed_page": True,
            }
            extractor.last_rejection_reasons = []
            extractor.last_rejected_count = 0
            raise ScholarshipExtractionError("fail", category="provider_error", http_status=400)

        extractor.extract.side_effect = extract_side_effect

        def save_run_side_effect(db, run, summary, source_results, status, lock_check=None):
            if status != "running":
                run.finished_at = datetime.now(timezone.utc)

        with patch("app.services.scholarship_discovery._register_evidence"), \
             patch("app.services.scholarship_discovery.record_publication_source_success"), \
             patch("app.services.scholarship_discovery.record_publication_source_failure"), \
             patch("app.services.scholarship_discovery.resolve_trusted_source_url", return_value=page.url), \
             patch("app.services.scholarship_discovery.has_open_review_for_identity", return_value=False), \
             patch("app.services.scholarship_discovery.find_identity_record", return_value=None), \
             patch("app.services.scholarship_discovery.find_possible_duplicate_records", return_value=[]), \
             patch("app.services.scholarship_discovery._save_run", side_effect=save_run_side_effect):
                result = scholarship_discovery.run_discovery(
                    db,
                    settings=settings,
                    sources=[source],
                    fetcher=fetcher,
                    extractor=extractor,
                    trigger_type="scheduled",
                    scheduled_for=datetime.now(timezone.utc),
                )
        self.assertEqual(result["status"], "failed")
        sr = result["sources"][0]
        self.assertEqual(sr["error"], "provider_error")
        self.assertEqual(sr["http_status"], 400)
        self.assertTrue(sr["processing_stopped_after_failed_page"])
        self.assertEqual(sr["provider_attempt_diagnostics"]["final_provider"], "groq")
        self.assertEqual(sr["provider_attempt_diagnostics"]["final_http_status"], 400)
        self.assertEqual(sr["provider_attempt_diagnostics"]["providers_attempted"], ["groq"])


if __name__ == "__main__":
    unittest.main()
