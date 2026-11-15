"""Long pages: import uses discovery's request pipeline, not one big request.

A long page used to be sent in a single call. The page text was capped but the
link list was not, and the whole 86-field schema went with every request, so
the org TPM limiter refused it with payload_too_large and import reported 503.

These tests pin the chunking, the per-request token cap, the recovery ladder,
the merged result, and the error categories an administrator can act on.

No live requests: every provider call is a mock.

Run from the backend folder:
    python -m unittest tests.test_scholarship_import_chunking -v
"""
import json
import math
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import ScholarshipDiscoverySettings
from app.core.permissions import require_admin
from app.routers import admin_scholarships
from app.services.groq_provider import GroqProviderError
from app.services.scholarship_discovery_extraction import (
    ESTIMATED_CHARS_PER_TOKEN,
    MAX_413_RECOVERY_LEVELS,
    TPM_AUTO_TIGHTEN_FRACTION,
)
from app.services.scholarship_discovery_fetch import FetchedPage
from app.services.scholarship_import import (
    GroqScholarshipImportExtractor,
    ScholarshipImportError,
    _import_error_for_provider_failure,
    extract_scholarship_source,
    merge_import_field_sets,
)

SECTION = (
    "The Example Master's Award supports Master's students at Example University "
    "in Germany. It covers full tuition and pays a monthly stipend. "
    "The application deadline is 31 July 2027. "
)


def _settings(**changes):
    values = {
        "enabled": False,
        "request_timeout_seconds": 2,
        "max_response_bytes": 2_000_000,
        "max_extracted_chars": 200_000,
        "max_pages_per_source": 3,
        "max_retries": 0,
        "request_delay_seconds": 0,
        "user_agent": "FitScholarImportTest/1.0",
        "model": "mock-model",
        "groq_model": "mock-model",
        "groq_rate_limit_retries": 0,
        # The default 8,000 TPM is what refuses import's one-shot request in
        # production. These tests are about chunking, so unless a test says
        # otherwise the limiter is given room and the assertions stay about
        # the request sizes rather than the limiter's rolling window.
        "groq_tpm_limit": 10_000_000,
        "groq_fallback_tpm_limit": 10_000_000,
    }
    values.update(changes)
    return ScholarshipDiscoverySettings(**values)


def _long_page(chars=80_000, *, links=(), page_texts=None, page_count=None):
    text = (SECTION * (chars // len(SECTION) + 1))[:chars]
    return FetchedPage(
        url="https://awards.example/call",
        content_type="text/html",
        text=text,
        links=tuple(links),
        content_hash="a" * 64,
        page_count=page_count,
        page_texts=tuple(page_texts) if page_texts else (text,),
    )


def _client(contents='{"fields":{}}'):
    client = Mock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=contents))],
    )
    return client


def _prompts(client):
    return [
        call.kwargs["messages"][1]["content"]
        for call in client.chat.completions.create.call_args_list
    ]


def _request_chars(prompt):
    """Every character the provider was sent in one request."""
    return sum(len(message) for message in (prompt,))


class LongPageChunkingTests(unittest.TestCase):
    def test_an_eighty_thousand_character_page_is_split_and_extracted(self):
        client = _client(json.dumps({"fields": {
            "name": {
                "value": "The Example Master's Award",
                "evidence": "The Example Master's Award",
                "confidence": "high",
            },
        }}))
        extractor = GroqScholarshipImportExtractor(_settings(), client=client)

        fields = extractor.extract(_long_page(80_000))

        self.assertGreater(extractor.last_chunk_count, 1, "the page must be split")
        self.assertEqual(extractor.last_request_count, extractor.last_chunk_count)
        self.assertEqual(fields["name"]["value"], "The Example Master's Award")

    def test_every_request_stays_under_the_token_cap(self):
        token_cap = 6_000
        client = _client()
        extractor = GroqScholarshipImportExtractor(
            _settings(groq_max_request_tokens=token_cap), client=client,
        )

        extractor.extract(_long_page(80_000))

        allowed_tokens = int(token_cap * TPM_AUTO_TIGHTEN_FRACTION)
        prompts = _prompts(client)
        self.assertGreater(len(prompts), 1)
        for index, prompt in enumerate(prompts):
            estimated = math.ceil(_request_chars(prompt) / ESTIMATED_CHARS_PER_TOKEN)
            with self.subTest(request=index + 1):
                self.assertLessEqual(
                    estimated,
                    allowed_tokens,
                    f"request {index + 1} of {len(prompts)} estimated {estimated} tokens, "
                    f"over the {allowed_tokens} the limiter admits",
                )

    def test_the_whole_page_is_covered_with_nothing_dropped(self):
        client = _client()
        extractor = GroqScholarshipImportExtractor(
            _settings(max_provider_chunk_chars=2_000, groq_max_request_tokens=None),
            client=client,
        )
        page = _long_page(20_000)

        extractor.extract(page)

        sent = ""
        for prompt in _prompts(client):
            payload = json.loads(prompt.split("Untrusted source data:\n", 1)[1])
            sent += payload["pages"][0]["text"]
        # Pruning removes repeated lines; this page is one long line, so every
        # character must survive into some request.
        self.assertEqual(len(sent), len(page.text))
        self.assertEqual(sent, page.text)

    def test_the_links_travel_once_not_with_every_chunk(self):
        links = tuple(
            (f"https://awards.example/page/{index}", f"Link {index}")
            for index in range(40)
        )
        client = _client()
        extractor = GroqScholarshipImportExtractor(
            _settings(max_provider_chunk_chars=2_000, groq_max_request_tokens=None),
            client=client,
        )

        extractor.extract(_long_page(20_000, links=links))

        prompts = _prompts(client)
        self.assertGreater(len(prompts), 1)
        with_links = [
            prompt for prompt in prompts
            if json.loads(prompt.split("Untrusted source data:\n", 1)[1])["linked_urls"]
        ]
        self.assertEqual(len(with_links), 1, "links are evidence for the page, sent once")

    def test_the_link_list_is_bounded_however_many_the_page_has(self):
        links = tuple(
            (f"https://awards.example/page/{index}", f"Link {index}")
            for index in range(5_000)
        )
        client = _client()
        extractor = GroqScholarshipImportExtractor(_settings(), client=client)

        extractor.extract(_long_page(4_000, links=links))

        payload = json.loads(_prompts(client)[0].split("Untrusted source data:\n", 1)[1])
        self.assertLessEqual(len(payload["linked_urls"]), 60)

    def test_repeated_navigation_lines_are_pruned_before_chunking(self):
        boilerplate = "\n".join(["Home | About | Contact"] * 400)
        page = FetchedPage(
            url="https://awards.example/call",
            content_type="text/html",
            text=boilerplate + "\n" + SECTION,
            links=(),
            content_hash="b" * 64,
            page_texts=(boilerplate + "\n" + SECTION,),
        )
        client = _client()
        extractor = GroqScholarshipImportExtractor(
            _settings(max_provider_chunk_chars=2_000, groq_max_request_tokens=None),
            client=client,
        )

        extractor.extract(page)

        payload = json.loads(_prompts(client)[0].split("Untrusted source data:\n", 1)[1])
        self.assertEqual(
            payload["pages"][0]["text"].count("Home | About | Contact"),
            1,
            "the repeated navigation line is sent once, not 400 times",
        )

    def test_a_pdf_keeps_its_page_numbers_through_chunking(self):
        pages = (SECTION * 40, SECTION * 40)
        page = _long_page(
            page_texts=pages, page_count=2,
            chars=len(pages[0]) + len(pages[1]),
        )
        client = _client()
        extractor = GroqScholarshipImportExtractor(
            _settings(max_provider_chunk_chars=1_000, groq_max_request_tokens=None),
            client=client,
        )

        extractor.extract(page)

        numbers = set()
        for prompt in _prompts(client):
            payload = json.loads(prompt.split("Untrusted source data:\n", 1)[1])
            numbers.add(payload["pages"][0]["page_number"])
        self.assertEqual(numbers, {1, 2}, "evidence page numbers survive the split")


class ReportedFailureTests(unittest.TestCase):
    """The failure this change was made for.

    "Scholarship import extraction failed: category=payload_too_large
    http_status=None" then 503. http_status=None means the refusal was local:
    the org TPM limiter would not admit the request at all. With the shipped
    defaults a single import request estimated ~8,470 tokens against an
    admission limit of 8,000 * 0.9 = 7,200.
    """

    def test_a_long_page_now_extracts_under_the_real_default_tpm_limit(self):
        client = _client(json.dumps({"fields": {
            "name": {
                "value": "The Example Master's Award",
                "evidence": "The Example Master's Award",
                "confidence": "high",
            },
        }}))
        # The shipped defaults, not a generous test value.
        settings = _settings(groq_tpm_limit=8_000, groq_fallback_tpm_limit=8_000,
                             groq_max_request_tokens=6_000)
        extractor = GroqScholarshipImportExtractor(settings, client=client)

        fields = extractor.extract(_long_page(80_000))

        self.assertEqual(fields["name"]["value"], "The Example Master's Award")
        self.assertGreater(extractor.last_chunk_count, 10)
        admission_limit = int(8_000 * TPM_AUTO_TIGHTEN_FRACTION)
        for index, prompt in enumerate(_prompts(client)):
            estimated = math.ceil(len(prompt) / ESTIMATED_CHARS_PER_TOKEN)
            with self.subTest(request=index + 1):
                self.assertLessEqual(
                    estimated,
                    admission_limit,
                    "a request the limiter would refuse locally",
                )


class RequestOverheadTests(unittest.TestCase):
    """The field contract has to leave room for the page.

    The full JSON schema for 86 fields is ~12,700 characters and goes with
    every chunk. Against a 6,000 token cap that left 128 characters of text
    per request: 625 requests for one page. The compact contract keeps the
    same rules in a fraction of the tokens.
    """

    def test_the_contract_is_small_enough_to_leave_room_for_text(self):
        from app.services.scholarship_import import (
            MAX_IMPORT_PROMPT_OVERHEAD_CHARS,
            IMPORTABLE_FIELDS,
        )
        from app.schemas.opportunity import ScholarshipWriteBase
        from app.services.scholarship_discovery_extraction import (
            text_chars_within_token_cap,
        )

        properties = ScholarshipWriteBase.model_json_schema(mode="validation")["properties"]
        full = json.dumps(
            {name: properties[name] for name in sorted(IMPORTABLE_FIELDS)},
            ensure_ascii=False,
        )
        compact = GroqScholarshipImportExtractor._compact_schema()
        self.assertLess(len(compact), len(full) // 3)

        extractor = GroqScholarshipImportExtractor(_settings())
        overhead = len(extractor._instructions(compact)) + MAX_IMPORT_PROMPT_OVERHEAD_CHARS
        per_request = text_chars_within_token_cap(6_000, overhead, fallback_chars=6_000)
        self.assertGreater(
            per_request,
            2_000,
            "a 6,000 token cap must still carry a useful amount of page text",
        )
        self.assertLess(
            math.ceil(80_000 / per_request),
            40,
            "an 80,000 character page must not need dozens upon dozens of requests",
        )

    def test_the_contract_still_names_every_importable_field(self):
        from app.services.scholarship_import import IMPORTABLE_FIELDS

        compact = GroqScholarshipImportExtractor._compact_schema()
        missing = [name for name in IMPORTABLE_FIELDS if name not in compact]
        self.assertEqual(missing, [], "a field the model is not told about cannot be extracted")

    def test_the_contract_states_the_closed_value_sets(self):
        compact = GroqScholarshipImportExtractor._compact_schema()
        # A few enums the extraction depends on being exact.
        self.assertIn("varies_by_institution", compact)
        self.assertIn("deadline_type=", compact)
        self.assertIn("funding_level=", compact)
        self.assertIn("Arrays only:", compact)


class RecoveryTests(unittest.TestCase):
    def test_a_refused_chunk_is_split_further_rather_than_retried(self):
        client = Mock()
        calls = {"count": 0}

        def respond(**kwargs):
            calls["count"] += 1
            text = kwargs["messages"][1]["content"]
            payload = json.loads(text.split("Untrusted source data:\n", 1)[1])
            # Refuse anything still carrying a lot of text; accept the pieces.
            if len(payload["pages"][0]["text"]) > 1_500:
                raise GroqProviderError(
                    "payload_too_large",
                    limit_details={"limit_type": "TPM", "limit": 6_000, "requested": 20_000},
                )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"fields":{}}'))],
            )

        client.chat.completions.create.side_effect = respond
        extractor = GroqScholarshipImportExtractor(
            _settings(max_provider_chunk_chars=6_000, groq_max_request_tokens=None),
            client=client,
        )

        extractor.extract(_long_page(12_000))

        self.assertGreater(extractor.last_recovery_count, 0, "the chunk was split, not retried")
        self.assertGreater(calls["count"], extractor.last_chunk_count)

    def test_recovery_gives_up_after_the_shared_level_limit(self):
        client = Mock()
        client.chat.completions.create.side_effect = GroqProviderError(
            "payload_too_large",
            limit_details={"limit_type": "TPM", "limit": 10, "requested": 90_000},
        )
        extractor = GroqScholarshipImportExtractor(
            _settings(max_provider_chunk_chars=4_000, groq_max_request_tokens=None),
            client=client,
        )

        with self.assertRaises(ScholarshipImportError) as caught:
            extractor.extract(_long_page(8_000))

        self.assertEqual(caught.exception.error_category, "page_too_large")
        self.assertGreaterEqual(MAX_413_RECOVERY_LEVELS, 1)

    def test_a_partial_read_is_returned_rather_than_refused(self):
        """One bad section must not lose the sections that worked."""
        client = Mock()
        state = {"calls": 0}

        def respond(**kwargs):
            state["calls"] += 1
            if state["calls"] == 2:
                raise GroqProviderError("server_error", http_status=500)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps({"fields": {
                    "name": {
                        "value": "The Example Master's Award",
                        "evidence": "The Example Master's Award",
                        "confidence": "high",
                    },
                }}),
            ))])

        client.chat.completions.create.side_effect = respond
        extractor = GroqScholarshipImportExtractor(
            _settings(max_provider_chunk_chars=2_000, groq_max_request_tokens=None),
            client=client,
        )

        fields = extractor.extract(_long_page(10_000))

        self.assertEqual(fields["name"]["value"], "The Example Master's Award")


class ErrorMappingTests(unittest.TestCase):
    def test_a_size_refusal_that_survived_chunking_is_page_too_large(self):
        error = _import_error_for_provider_failure(
            GroqProviderError("payload_too_large"), chunk_count=12,
        )
        self.assertEqual(error.status_code, 424)
        self.assertEqual(error.error_category, "page_too_large")
        self.assertIn("pasting only the scholarship section", str(error))
        self.assertIn("official PDF", str(error))
        self.assertNotEqual(error.status_code, 503)

    def test_a_busy_provider_is_provider_busy_not_unavailable(self):
        for category in ("quota_error", "quota_exhausted"):
            with self.subTest(category=category):
                error = _import_error_for_provider_failure(
                    GroqProviderError(category, http_status=429), chunk_count=3,
                )
                self.assertEqual(error.status_code, 424)
                self.assertEqual(error.error_category, "provider_busy")

    def test_a_genuinely_unavailable_provider_is_still_503(self):
        for category in ("server_error", "connection_error", "unknown"):
            with self.subTest(category=category):
                error = _import_error_for_provider_failure(
                    GroqProviderError(category, http_status=503), chunk_count=3,
                )
                self.assertEqual(error.status_code, 503)


class MergeTests(unittest.TestCase):
    def test_the_best_evidenced_candidate_per_field_wins(self):
        merged = merge_import_field_sets([
            {"name": {"value": "Weak", "confidence": "low"}},
            {"name": {"value": "Strong", "confidence": "high"}},
            {"country": {"value": "Germany", "confidence": "medium"}},
        ])
        self.assertEqual(merged["name"]["value"], "Strong")
        self.assertEqual(merged["country"]["value"], "Germany")

    def test_between_equal_confidence_the_earlier_section_wins(self):
        merged = merge_import_field_sets([
            {"name": {"value": "First", "confidence": "high"}},
            {"name": {"value": "Second", "confidence": "high"}},
        ])
        self.assertEqual(merged["name"]["value"], "First")

    def test_nothing_to_merge_is_an_empty_set(self):
        self.assertEqual(merge_import_field_sets([]), {})
        self.assertEqual(merge_import_field_sets(None), {})
        self.assertEqual(merge_import_field_sets(["not a dict"]), {})


class SeveralCandidatesTests(unittest.TestCase):
    def test_a_page_describing_two_awards_offers_both(self):
        first = SECTION
        second = (
            "The Second Chance Grant supports Master's students at Example University "
            "in Austria. The application deadline is 1 March 2028. "
        )
        page = FetchedPage(
            url="https://awards.example/call",
            content_type="text/html",
            text=first + second,
            links=(),
            content_hash="c" * 64,
            page_texts=(first + second,),
        )

        class _TwoCandidates:
            last_chunk_count = 2

            def extract_candidates(self, _page):
                return [
                    {"name": {
                        "value": "The Example Master's Award",
                        "evidence": "The Example Master's Award",
                        "confidence": "high",
                    }},
                    {"name": {
                        "value": "The Second Chance Grant",
                        "evidence": "The Second Chance Grant",
                        "confidence": "high",
                    }},
                ]

        draft = extract_scholarship_source(
            "pasted_text",
            text=page.text,
            url="https://awards.example/call",
            settings=_settings(),
            fetcher=SimpleNamespace(
                page_from_pasted_text=lambda text, source_url: page,
                close=lambda: None,
            ),
            extractor=_TwoCandidates(),
        )

        labels = [candidate.label for candidate in draft.candidates]
        self.assertEqual(labels, ["The Example Master's Award", "The Second Chance Grant"])
        self.assertTrue(any("2 possible scholarships" in warning for warning in draft.warnings))
        # The merged draft still carries a usable view.
        self.assertEqual(draft.fields["name"]["status"] if isinstance(draft.fields["name"], dict)
                         else draft.fields["name"].status, "extracted")

    def test_one_award_offers_no_choice_to_make(self):
        class _OneCandidate:
            last_chunk_count = 3

            def extract_candidates(self, _page):
                return [
                    {"name": {
                        "value": "The Example Master's Award",
                        "evidence": "The Example Master's Award",
                        "confidence": "high",
                    }},
                    {},
                ]

        page = _long_page(4_000)
        draft = extract_scholarship_source(
            "pasted_text",
            text=page.text,
            settings=_settings(),
            fetcher=SimpleNamespace(
                page_from_pasted_text=lambda text, source_url: page,
                close=lambda: None,
            ),
            extractor=_OneCandidate(),
        )
        self.assertEqual(draft.candidates, [])
        self.assertEqual(draft.chunk_count, 3)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(admin_scholarships.router)
        self.app.dependency_overrides[require_admin] = lambda: SimpleNamespace(
            id=1, role="admin", email="admin@example.com",
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()

    def test_a_page_too_large_is_a_424_with_the_category_not_a_503(self):
        class _Refuses:
            last_chunk_count = 9

            def extract_candidates(self, _page):
                raise ScholarshipImportError(
                    "This page is very long. Try pasting only the scholarship section, "
                    "or upload the official PDF.",
                    status_code=424,
                    error_category="page_too_large",
                )

        with patch(
            "app.services.scholarship_import.GroqScholarshipImportExtractor",
            return_value=_Refuses(),
        ):
            response = self.client.post(
                "/admin/scholarships/import/extract-text",
                json={"text": SECTION * 200, "url": "https://awards.example/call"},
            )

        self.assertEqual(response.status_code, 424, response.text)
        detail = response.json()["detail"]
        self.assertEqual(detail["category"], "page_too_large")
        self.assertIn("pasting only the scholarship section", detail["message"])

    def test_a_busy_provider_is_a_424_an_admin_can_act_on(self):
        class _Busy:
            last_chunk_count = 2

            def extract_candidates(self, _page):
                raise _import_error_for_provider_failure(
                    GroqProviderError("quota_error", http_status=429), chunk_count=2,
                )

        with patch(
            "app.services.scholarship_import.GroqScholarshipImportExtractor",
            return_value=_Busy(),
        ):
            response = self.client.post(
                "/admin/scholarships/import/extract-text",
                json={"text": SECTION * 10},
            )

        self.assertEqual(response.status_code, 424, response.text)
        self.assertEqual(response.json()["detail"]["category"], "provider_busy")


if __name__ == "__main__":
    unittest.main()
