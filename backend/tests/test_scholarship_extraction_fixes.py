"""Regression tests for the scholarship discovery extraction fixes.

Offline only: no Groq requests, no website requests, no database access.

Run from backend/:  python -m pytest tests/test_scholarship_extraction_fixes.py -q
Or from the repo root: python -m pytest backend/tests/test_scholarship_extraction_fixes.py -q

The behaviour under test:
  * Groq HTTP 413 with type=tokens / code=rate_limit_exceeded is a PER-REQUEST
    token limit. Waiting cannot help; the request must get smaller.
  * Groq HTTP 429 on a per-day limit (TPD/RPD) cannot recover inside a run.
  * Evidence quotes may come from the URL-redacted text the model was shown.
  * One failed chunk or page must not discard what the others produced.
"""
import io
import json
import logging
import os
import unittest
import urllib.parse
from email.message import Message
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services import groq_provider
from app.services.groq_provider import (
    GroqProviderError,
    extract_rate_limit_details,
    generate_json_completion,
    sanitize_rate_limit_details,
)
from app.services.scholarship_discovery_extraction import (
    MAX_CANDIDATES_PER_PAGE,
    GroqScholarshipExtractor,
    ScholarshipExtractionError,
    _has_quote,
    _split_text_into_chunks,
    _validate_candidate,
)
from app.services.scholarship_discovery_fetch import (
    DiscoveryFetchError,
    FetchedPage,
    OfficialSourceFetcher,
)
from app.services.scholarship_discovery_sources import DiscoverySource

# Real Groq message shapes. The organization id and the message text itself
# must never survive into an error object, a log line or diagnostics.
ORG_SECRET = "org_secret123"
TPM_413_MESSAGE = (
    "Request too large for model `openai/gpt-oss-20b` in organization "
    f"`{ORG_SECRET}` service tier `on_demand` on tokens per minute (TPM): "
    "Limit 8000, Requested 9965, please reduce your message size and try again."
)
TPD_429_MESSAGE = (
    "Rate limit reached for model `openai/gpt-oss-20b` in organization "
    f"`{ORG_SECRET}` service tier `on_demand` on tokens per day (TPD): "
    "Limit 200000, Used 199000, Requested 7464. Please try again in 6m50.832s."
)
TPM_429_MESSAGE = (
    "Rate limit reached for model `openai/gpt-oss-20b` in organization "
    f"`{ORG_SECRET}` on tokens per minute (TPM): Limit 8000, Used 7900, "
    "Requested 500. Please try again in 1.5s."
)

FINLAND_TEXT = (
    "The Finland Master's Scholarship is available to Master's students. "
    "Host country: Finland."
)


class _GroqLimitError(Exception):
    """Mimics the groq SDK's error object for a token-limit rejection."""

    def __init__(self, status, message, error_type="tokens", code="rate_limit_exceeded"):
        super().__init__(message)
        self.status_code = status
        self.body = {
            "error": {"message": message, "type": error_type, "code": code},
        }


def _page(text=FINLAND_TEXT, links=(), url="https://official.example/scholarships"):
    return FetchedPage(
        url=url,
        content_type="text/html",
        text=text,
        links=links,
        content_hash="a" * 64,
    )


def _source(source_id="offline-source"):
    return DiscoverySource(
        source_id=source_id,
        name="Offline source",
        official_domain="official.example",
        category="government_scholarship_programme",
        country_or_region="test",
        source_url="https://official.example/scholarships",
        source_classification="government_authority",
    )


def _extractor(**overrides):
    settings = dict(
        model="offline-groq",
        groq_model="offline-groq",
        max_provider_chunk_chars=12_000,
        groq_max_completion_tokens=500,
        groq_rate_limit_retries=0,
        groq_fallback_enabled=False,
        # Generous by default; individual tests tighten it.
        groq_max_request_tokens=100_000,
    )
    settings.update(overrides)
    return GroqScholarshipExtractor(
        SimpleNamespace(**settings),
        client=Mock(),
        groq_client=Mock(),
    )


def _candidate(
    name="Finland Master's Scholarship",
    offer_quote="The Finland Master's Scholarship is available",
    host_location="Host country: Finland",
    extra_evidence=None,
):
    evidence = {
        "name": name,
        "country": "Finland",
        "degree_level": "Master's students",
        "host_location": host_location,
    }
    if extra_evidence:
        evidence.update(extra_evidence)
    return {
        "values": {"name": name, "country": "Finland", "degree_level": "Master"},
        "evidence": evidence,
        "host_city": "",
        "masters_only": True,
        "masters_evidence": "Master's students",
        "scholarship_offer_evidence": offer_quote,
    }


def _response(*candidates):
    return json.dumps({"scholarships": list(candidates)})


def _prompt_payload(prompt):
    """The JSON block the prompt sends to the model."""
    return json.loads(prompt.split("Source page data (JSON):\n", 1)[1])


# ---------------------------------------------------------------------------
# A. Provider limit observability
# ---------------------------------------------------------------------------
class GroqLimitDiagnosticsTests(unittest.TestCase):
    def tearDown(self):
        groq_provider._REQUEST_LIMITERS.clear()
        groq_provider._UNAVAILABLE_KEY_SLOTS.clear()

    def test_tpm_413_body_is_parsed_into_limit_details(self):
        self.assertEqual(
            extract_rate_limit_details({"error": {"message": TPM_413_MESSAGE}}),
            {"limit_type": "TPM", "limit": 8000, "requested": 9965},
        )

    def test_tpd_429_body_keeps_used_and_requested(self):
        self.assertEqual(
            extract_rate_limit_details({"error": {"message": TPD_429_MESSAGE}}),
            {
                "limit_type": "TPD",
                "limit": 200_000,
                "used": 199_000,
                "requested": 7464,
            },
        )

    def test_unparsable_message_yields_no_limit_details(self):
        self.assertEqual(
            extract_rate_limit_details({"error": {"message": "something went wrong"}}),
            {},
        )
        self.assertEqual(extract_rate_limit_details(None), {})

    def test_limit_details_reject_unknown_labels_and_non_integers(self):
        self.assertEqual(sanitize_rate_limit_details({"limit_type": "GPM"}), {})
        self.assertEqual(
            sanitize_rate_limit_details({
                "limit_type": "TPM",
                "limit": "8000",
                "used": True,
                "requested": -1,
            }),
            {"limit_type": "TPM"},
        )

    def test_413_keeps_type_and_code_and_logs_only_integers(self):
        client = Mock()
        client.chat.completions.create.side_effect = _GroqLimitError(
            413,
            TPM_413_MESSAGE,
        )
        with self.assertLogs("app.services.groq_provider", level="WARNING") as logs:
            with self.assertRaises(GroqProviderError) as raised:
                generate_json_completion(
                    client,
                    model="openai/gpt-oss-20b",
                    system_instruction="system",
                    contents="user",
                )
        error = raised.exception
        self.assertEqual(error.category, "payload_too_large")
        self.assertEqual(error.http_status, 413)
        self.assertEqual(
            error.provider_error_details,
            {"type": "tokens", "code": "rate_limit_exceeded"},
        )
        self.assertEqual(
            error.limit_details,
            {"limit_type": "TPM", "limit": 8000, "requested": 9965},
        )
        output = "\n".join(logs.output)
        self.assertIn("limit_type=TPM", output)
        self.assertIn("limit=8000", output)
        self.assertIn("requested=9965", output)
        # The organization id and the raw message must not be logged.
        self.assertNotIn(ORG_SECRET, output)
        self.assertNotIn("please reduce your message size", output)
        self.assertNotIn(ORG_SECRET, json.dumps(error.limit_details))

    def test_tpd_429_is_quota_exhausted_and_issues_one_request(self):
        client = Mock()
        client.chat.completions.create.side_effect = _GroqLimitError(
            429,
            TPD_429_MESSAGE,
            error_type="tokens",
            code="rate_limit_exceeded",
        )
        settings = SimpleNamespace(groq_rate_limit_retries=3)
        sleeps = []
        with patch.object(groq_provider.time, "sleep", sleeps.append):
            with self.assertRaises(GroqProviderError) as raised:
                generate_json_completion(
                    client,
                    model="openai/gpt-oss-20b",
                    system_instruction="system",
                    contents="user",
                    rate_limit_settings=settings,
                )
        self.assertEqual(raised.exception.category, "quota_exhausted")
        self.assertEqual(raised.exception.limit_details["limit_type"], "TPD")
        # Retries are configured, but a per-day limit is not retried.
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_per_minute_429_is_still_retried(self):
        client = Mock()
        client.chat.completions.create.side_effect = _GroqLimitError(
            429,
            TPM_429_MESSAGE,
        )
        settings = SimpleNamespace(groq_rate_limit_retries=2)
        with patch.object(groq_provider.time, "sleep", lambda _seconds: None):
            with self.assertRaises(GroqProviderError) as raised:
                generate_json_completion(
                    client,
                    model="openai/gpt-oss-20b",
                    system_instruction="system",
                    contents="user",
                    rate_limit_settings=settings,
                )
        self.assertEqual(raised.exception.category, "quota_error")
        self.assertEqual(client.chat.completions.create.call_count, 3)

    def test_rate_limit_wait_longer_than_allowed_is_abandoned(self):
        response = SimpleNamespace(headers={"retry-after": "3600"})
        error = _GroqLimitError(429, "Rate limit reached for model `x`.")
        error.response = response
        client = Mock()
        client.chat.completions.create.side_effect = error
        settings = SimpleNamespace(groq_rate_limit_retries=5)
        sleeps = []
        with patch.object(groq_provider.time, "sleep", sleeps.append):
            with self.assertRaises(GroqProviderError):
                generate_json_completion(
                    client,
                    model="openai/gpt-oss-20b",
                    system_instruction="system",
                    contents="user",
                    rate_limit_settings=settings,
                )
        # One attempt, then the hour-long wait is refused rather than slept.
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertEqual(sleeps, [])


# ---------------------------------------------------------------------------
# B. Token preflight: requests are made smaller, never resent unchanged
# ---------------------------------------------------------------------------
class TokenPreflightTests(unittest.TestCase):
    def test_oversized_chunk_is_split_locally_before_anything_is_sent(self):
        # Measured with groq_max_completion_tokens=200: a 1500-char chunk
        # costs 2292 estimated tokens and a 750-char half costs 2058, so a
        # 2100-token cap forces the local split and leaves the halves room.
        # The numbers move whenever the prompt changes; the subject of the
        # test is that the split happens locally, before anything is sent.
        extractor = _extractor(
            groq_max_completion_tokens=200,
            groq_max_request_tokens=2_100,
            max_provider_chunk_chars=1_500,
        )
        prompts = []
        extractor._generate_groq = Mock(
            side_effect=lambda prompt: (prompts.append(prompt), _response())[1],
        )
        self.assertEqual(extractor.extract(_page("word " * 300), _source()), [])

        self.assertGreater(len(prompts), 1)
        for prompt in prompts:
            self.assertLessEqual(extractor._estimated_request_tokens(prompt), 2_100)
        # Split locally: the recovery was driven by a preflight rejection with
        # no HTTP status, not by a provider 413.
        requests = [
            request
            for chunk in extractor.last_provider_diagnostics["chunk_diagnostics"]
            for request in chunk.get("requests", [])
        ]
        preflight = [
            request
            for request in requests
            if request.get("request_stage") == "request_preflight"
        ]
        self.assertTrue(preflight)
        self.assertIsNone(preflight[0]["http_status"])
        self.assertFalse(preflight[0]["request_started"])

    def test_every_request_stays_within_the_token_cap(self):
        extractor = _extractor(
            groq_max_completion_tokens=200,
            groq_max_request_tokens=2_100,
            max_provider_chunk_chars=1_500,
        )
        prompts = []
        extractor._generate_groq = Mock(
            side_effect=lambda prompt: (prompts.append(prompt), _response())[1],
        )
        extractor.extract(_page("official scholarship text " * 240), _source())

        self.assertGreater(len(prompts), 1)
        self.assertTrue(
            all(extractor._estimated_request_tokens(p) <= 2_100 for p in prompts),
            [extractor._estimated_request_tokens(p) for p in prompts],
        )

    def test_unfittable_request_fails_locally_without_being_sent(self):
        # The prompt wrapper alone costs ~1627 tokens, so a 950-token cap can
        # never fit any page text. It must fail locally, not at the provider.
        extractor = _extractor(
            groq_max_completion_tokens=200,
            groq_max_request_tokens=950,
            max_provider_chunk_chars=4_000,
        )
        prompts = []
        extractor._generate_groq = Mock(
            side_effect=lambda prompt: (prompts.append(prompt), _response())[1],
        )
        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor.extract(_page("word " * 800), _source())

        self.assertEqual(raised.exception.category, "payload_too_large")
        # Local rejection: no provider status, and nothing oversized was sent.
        self.assertIsNone(raised.exception.http_status)
        for prompt in prompts:
            self.assertLessEqual(extractor._estimated_request_tokens(prompt), 950)

    def test_zero_disables_the_token_preflight(self):
        extractor = _extractor(
            groq_max_request_tokens=0,
            max_provider_chunk_chars=100_000,
        )
        extractor._generate_groq = Mock(return_value=_response())
        extractor.extract(_page("word " * 20_000), _source())
        extractor._generate_groq.assert_called_once()

    def test_env_var_supplies_the_cap_when_settings_lack_it(self):
        extractor = _extractor()
        del extractor.settings.groq_max_request_tokens
        with patch.dict(os.environ, {"GROQ_MAX_REQUEST_TOKENS": "4321"}):
            self.assertEqual(extractor._max_request_tokens(), 4321)
        with patch.dict(os.environ, {"GROQ_MAX_REQUEST_TOKENS": "0"}):
            self.assertIsNone(extractor._max_request_tokens())
        with patch.dict(os.environ, {"GROQ_MAX_REQUEST_TOKENS": "not-a-number"}):
            self.assertEqual(extractor._max_request_tokens(), 6_000)

    def test_size_diagnostics_report_the_token_estimate(self):
        extractor = _extractor(groq_max_request_tokens=50_000)
        extractor._generate_groq = Mock(return_value=_response())
        extractor.extract(_page(), _source())
        requests = [
            request
            for chunk in extractor.last_provider_diagnostics["chunk_diagnostics"]
            for request in chunk["requests"]
        ]
        diagnostics = requests[0]["size_diagnostics"]
        self.assertGreater(diagnostics["estimated_request_tokens"], 0)
        self.assertEqual(diagnostics["max_request_tokens"], 50_000)


# ---------------------------------------------------------------------------
# C. Auto-tightening from a provider-reported TPM limit
# ---------------------------------------------------------------------------
class TokenCapAutoTightenTests(unittest.TestCase):
    def test_tpm_413_lowers_the_cap_for_later_requests(self):
        extractor = _extractor(
            groq_max_request_tokens=100_000,
            max_provider_chunk_chars=20_000,
        )
        prompts = []
        first = {"sent": False}

        def generate(prompt):
            prompts.append(prompt)
            if not first["sent"]:
                first["sent"] = True
                raise ScholarshipExtractionError(
                    "token limit",
                    category="payload_too_large",
                    http_status=413,
                    provider_error_details={
                        "type": "tokens",
                        "code": "rate_limit_exceeded",
                    },
                    limit_details={
                        "limit_type": "TPM",
                        "limit": 8000,
                        "requested": 9965,
                    },
                )
            return _response()

        extractor._generate_groq = Mock(side_effect=generate)
        with self.assertLogs(
            "app.services.scholarship_discovery_extraction",
            level="WARNING",
        ) as logs:
            extractor.extract(_page("official scholarship text " * 1_200), _source())

        # 90% of the reported 8000-token limit.
        self.assertEqual(extractor._tightened_max_request_tokens, 7_200)
        self.assertEqual(extractor._max_request_tokens(), 7_200)
        self.assertIn("effective_max_request_tokens=7200", "\n".join(logs.output))

        # The first request was over the learned cap; none after it may be.
        self.assertGreater(len(prompts), 1)
        for prompt in prompts[1:]:
            self.assertLessEqual(extractor._estimated_request_tokens(prompt), 7_200)

    def test_oversized_request_is_never_resent_unchanged(self):
        extractor = _extractor(
            groq_max_request_tokens=100_000,
            max_provider_chunk_chars=20_000,
        )
        prompts = []

        def generate(prompt):
            prompts.append(prompt)
            raise ScholarshipExtractionError(
                "token limit",
                category="payload_too_large",
                http_status=413,
                limit_details={"limit_type": "TPM", "limit": 8000},
            )

        extractor._generate_groq = Mock(side_effect=generate)
        with self.assertRaises(ScholarshipExtractionError):
            extractor.extract(_page("official scholarship text " * 1_200), _source())

        self.assertGreater(len(prompts), 1)
        # No prompt is ever repeated verbatim: each retry is strictly smaller.
        self.assertEqual(len(prompts), len(set(prompts)))
        for prompt in prompts[1:]:
            self.assertLess(len(prompt), len(prompts[0]))

    def test_disabled_preflight_is_not_re_enabled_by_a_413(self):
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._note_provider_token_limit(
            ScholarshipExtractionError(
                "token limit",
                category="payload_too_large",
                http_status=413,
                limit_details={"limit_type": "TPM", "limit": 8000},
            ),
        )
        self.assertIsNone(extractor._max_request_tokens())

    def test_non_tpm_limits_do_not_change_the_cap(self):
        extractor = _extractor(groq_max_request_tokens=5_000)
        for limit_type in ("TPD", "RPM", "RPD"):
            extractor._note_provider_token_limit(
                ScholarshipExtractionError(
                    "limit",
                    category="quota_error",
                    http_status=429,
                    limit_details={"limit_type": limit_type, "limit": 10},
                ),
            )
        self.assertIsNone(extractor._tightened_max_request_tokens)
        self.assertEqual(extractor._max_request_tokens(), 5_000)

    def test_provider_limit_reaches_request_diagnostics(self):
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(
            side_effect=ScholarshipExtractionError(
                "token limit",
                category="provider_error",
                http_status=429,
                limit_details={
                    "limit_type": "TPD",
                    "limit": 200_000,
                    "used": 199_000,
                },
            ),
        )
        with self.assertRaises(ScholarshipExtractionError):
            extractor.extract(_page(), _source())
        requests = [
            request
            for chunk in extractor.last_provider_diagnostics["chunk_diagnostics"]
            for request in chunk["requests"]
        ]
        self.assertEqual(
            requests[0]["provider_limit"],
            {"limit_type": "TPD", "limit": 200_000, "used": 199_000},
        )


# ---------------------------------------------------------------------------
# D. Linked URLs are offered once per page
# ---------------------------------------------------------------------------
class LinkedURLBudgetTests(unittest.TestCase):
    @staticmethod
    def _page_with_links(chunk_count=3):
        links = tuple(
            (f"https://official.example/scholarship-{index}", "Scholarship details")
            for index in range(20)
        )
        return _page("official scholarship text " * (420 * chunk_count), links=links)

    def test_linked_urls_are_sent_with_the_first_chunk_only(self):
        extractor = _extractor(
            max_provider_chunk_chars=4_000,
            groq_max_request_tokens=0,
        )
        prompts = []
        extractor._generate_groq = Mock(
            side_effect=lambda prompt: (prompts.append(prompt), _response())[1],
        )
        extractor.extract(self._page_with_links(), _source())

        self.assertGreater(len(prompts), 1)
        payloads = [_prompt_payload(prompt) for prompt in prompts]
        self.assertTrue(payloads[0]["linked_urls"])
        for payload in payloads[1:]:
            self.assertEqual(payload["linked_urls"], [])
            self.assertTrue(payload["linked_urls_limited"])

    def test_later_chunks_are_smaller_than_the_first(self):
        extractor = _extractor(
            max_provider_chunk_chars=4_000,
            groq_max_request_tokens=0,
        )
        prompts = []
        extractor._generate_groq = Mock(
            side_effect=lambda prompt: (prompts.append(prompt), _response())[1],
        )
        extractor.extract(self._page_with_links(), _source())
        # Equal-sized text chunks, so the difference is the dropped URL block.
        self.assertLess(len(prompts[1]), len(prompts[0]))

    def test_recovery_sub_chunks_do_not_repeat_the_urls(self):
        extractor = _extractor(
            max_provider_chunk_chars=20_000,
            groq_max_request_tokens=0,
        )
        prompts = []
        first = {"sent": False}

        def generate(prompt):
            prompts.append(prompt)
            if not first["sent"]:
                first["sent"] = True
                raise ScholarshipExtractionError(
                    "oversized",
                    category="payload_too_large",
                    http_status=413,
                )
            return _response()

        extractor._generate_groq = Mock(side_effect=generate)
        extractor.extract(self._page_with_links(chunk_count=1), _source())

        payloads = [_prompt_payload(prompt) for prompt in prompts]
        self.assertTrue(payloads[0]["linked_urls"])
        # First sub-chunk may re-offer them; the second must not.
        self.assertEqual(payloads[-1]["linked_urls"], [])


# ---------------------------------------------------------------------------
# E. Evidence quotes against the redacted text the model was shown
# ---------------------------------------------------------------------------
class RedactedEvidenceQuoteTests(unittest.TestCase):
    RAW = (
        "The Finland Master's Scholarship is available to Master's students. "
        "Apply at https://official.example/apply?ref=1#form or see www.daad.de "
        "for details. Host country: Finland."
    )

    def _extract_one(self, offer_quote):
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(
            return_value=_response(_candidate(offer_quote=offer_quote)),
        )
        return extractor, extractor.extract(_page(self.RAW), _source())

    def test_quote_with_a_redacted_bare_domain_is_accepted(self):
        # The model saw "[redacted URL]" where the raw page says www.daad.de.
        extractor, extracted = self._extract_one(
            "or see [redacted URL] for details",
        )
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extractor.last_rejected_count, 0)

    def test_quote_with_a_stripped_fragment_is_accepted(self):
        # safe_source_url drops "#form" from the URL the model was shown.
        extractor, extracted = self._extract_one(
            "Apply at https://official.example/apply?ref=1 or see",
        )
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extractor.last_rejected_count, 0)

    def test_quote_matching_the_raw_page_is_still_accepted(self):
        extractor, extracted = self._extract_one(
            "The Finland Master's Scholarship is available",
        )
        self.assertEqual(len(extracted), 1)

    def test_quote_absent_from_both_texts_is_still_rejected(self):
        extractor, extracted = self._extract_one(
            "This scholarship is available and offers a full tuition waiver",
        )
        self.assertEqual(extracted, [])
        self.assertEqual(extractor.last_rejected_count, 1)
        self.assertIn(
            "evidence_mismatch:scholarship_offer_evidence",
            extractor.last_rejection_detail_counts,
        )


# ---------------------------------------------------------------------------
# F. Candidate overflow
# ---------------------------------------------------------------------------
class CandidateLimitTests(unittest.TestCase):
    def test_overflow_keeps_the_first_n_and_counts_the_rest(self):
        extractor = _extractor(groq_max_request_tokens=0)
        overflow = 4
        candidates = [
            _candidate(name=f"Finland Master's Scholarship {index}")
            for index in range(MAX_CANDIDATES_PER_PAGE + overflow)
        ]
        # Every candidate quotes the page, so only the limit can reject them.
        text = FINLAND_TEXT + "".join(
            f" Finland Master's Scholarship {index} is available."
            for index in range(MAX_CANDIDATES_PER_PAGE + overflow)
        )
        for index, candidate in enumerate(candidates):
            quote = f"Finland Master's Scholarship {index} is available"
            candidate["scholarship_offer_evidence"] = quote
            candidate["evidence"]["name"] = f"Finland Master's Scholarship {index}"
        extractor._generate_groq = Mock(return_value=_response(*candidates))

        extracted = extractor.extract(_page(text), _source())

        self.assertEqual(len(extracted), MAX_CANDIDATES_PER_PAGE)
        self.assertEqual(extractor.last_rejected_count, overflow)
        self.assertEqual(
            extractor.last_rejection_detail_counts["candidate_limit_exceeded"],
            overflow,
        )
        self.assertEqual(
            extractor.last_provider_diagnostics["candidate_limit_overflow"],
            overflow,
        )
        # No longer reported as a malformed response.
        self.assertEqual(extractor.last_outcome_status, "candidates_accepted")

    def test_a_genuinely_malformed_response_still_fails(self):
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value="not json at all")
        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor.extract(_page(), _source())
        self.assertEqual(raised.exception.category, "malformed_response")


# ---------------------------------------------------------------------------
# G. Granular rejection codes
# ---------------------------------------------------------------------------
class RejectionDetailTests(unittest.TestCase):
    def test_out_of_scope_degree_level_is_reported_specifically(self):
        extractor = _extractor(groq_max_request_tokens=0)
        candidate = _candidate()
        candidate["values"]["degree_level"] = "Bachelor"
        extractor._generate_groq = Mock(return_value=_response(candidate))

        self.assertEqual(extractor.extract(_page(), _source()), [])
        self.assertEqual(
            extractor.last_rejection_detail_counts,
            {"out_of_scope:degree_level": 1},
        )
        # The coarse counters stay as they were, for existing consumers.
        self.assertEqual(
            extractor.last_rejection_reasons,
            ["OutOfScopeScholarship"],
        )

    def test_evidence_mismatch_names_the_field(self):
        extractor = _extractor(groq_max_request_tokens=0)
        candidate = _candidate(host_location="Host country: Germany somewhere")
        extractor._generate_groq = Mock(return_value=_response(candidate))

        self.assertEqual(extractor.extract(_page(), _source()), [])
        self.assertIn(
            "evidence_mismatch:host_location",
            extractor.last_rejection_detail_counts,
        )

    def test_invalid_shape_is_reported_for_a_non_object_candidate(self):
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response("not-an-object"))

        self.assertEqual(extractor.extract(_page(), _source()), [])
        self.assertEqual(extractor.last_rejection_detail_counts, {"non_object": 1})

    def test_rejection_codes_never_carry_free_text(self):
        extractor = _extractor(groq_max_request_tokens=0)
        candidate = _candidate()
        candidate["values"]["name"] = "   "
        extractor._generate_groq = Mock(return_value=_response(candidate))
        extractor.extract(_page(), _source())
        for code in extractor.last_rejection_detail_counts:
            self.assertRegex(code, r"\A[a-z_]{1,40}(?::[a-z_]{1,40})?\Z")


# ---------------------------------------------------------------------------
# H. A failed chunk does not discard the others
# ---------------------------------------------------------------------------
class PartialChunkFailureTests(unittest.TestCase):
    @staticmethod
    def _two_chunk_page():
        first = (
            "The Finland Master's Scholarship is available to Master's students. "
            "Host country: Finland. "
        )
        return _page(first + ("filler official text " * 200)), first

    def test_chunk_two_failure_keeps_chunk_one_candidates(self):
        extractor = _extractor(
            max_provider_chunk_chars=1_000,
            groq_max_request_tokens=0,
        )
        page, _first = self._two_chunk_page()
        calls = {"count": 0}

        def generate(_prompt):
            calls["count"] += 1
            if calls["count"] == 1:
                return _response(_candidate())
            raise ScholarshipExtractionError(
                "bad response",
                category="malformed_response",
            )

        extractor._generate_groq = Mock(side_effect=generate)
        extracted = extractor.extract(page, _source())

        self.assertEqual(len(extracted), 1)
        diagnostics = extractor.last_provider_diagnostics
        self.assertTrue(diagnostics["partial_chunk_failure"])
        # Every chunk after the first failed; all are recorded, none discard
        # the candidate chunk one produced.
        self.assertGreaterEqual(diagnostics["failed_chunk_count"], 1)
        self.assertEqual(
            set(diagnostics["failed_chunk_categories"]),
            {"malformed_response"},
        )
        self.assertEqual(
            len(diagnostics["failed_chunk_categories"]),
            diagnostics["failed_chunk_count"],
        )
        self.assertEqual(extractor.last_outcome_status, "candidates_accepted")

    def test_all_chunks_failing_raises_the_first_error(self):
        extractor = _extractor(
            max_provider_chunk_chars=1_000,
            groq_max_request_tokens=0,
        )
        page, _first = self._two_chunk_page()
        errors = [
            ScholarshipExtractionError("first", category="malformed_response"),
            ScholarshipExtractionError("second", category="provider_error"),
        ]
        extractor._generate_groq = Mock(side_effect=errors)

        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor.extract(page, _source())
        self.assertIs(raised.exception, errors[0])
        self.assertEqual(extractor.last_outcome_status, "malformed_response")

    def test_quota_failure_stops_immediately(self):
        extractor = _extractor(
            max_provider_chunk_chars=1_000,
            groq_max_request_tokens=0,
        )
        page, _first = self._two_chunk_page()
        extractor._generate_groq = Mock(
            side_effect=ScholarshipExtractionError(
                "quota",
                category="quota_exhausted",
                http_status=429,
            ),
        )
        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor.extract(page, _source())
        self.assertEqual(raised.exception.category, "quota_exhausted")
        self.assertEqual(extractor._generate_groq.call_count, 1)

    def test_single_chunk_failure_still_raises(self):
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(
            side_effect=ScholarshipExtractionError(
                "bad",
                category="malformed_response",
            ),
        )
        with self.assertRaises(ScholarshipExtractionError):
            extractor.extract(_page(), _source())


# ---------------------------------------------------------------------------
# I. Chunking
# ---------------------------------------------------------------------------
class ChunkBoundaryTests(unittest.TestCase):
    def test_chunking_is_lossless_and_bounded(self):
        text = "First sentence here.\nSecond sentence follows.\nThird one ends it."
        for max_chars in (8, 13, 20, 31, 64, 500):
            chunks = _split_text_into_chunks(text, max_chars)
            self.assertEqual("".join(chunks), text, max_chars)
            self.assertTrue(all(len(c) <= max_chars for c in chunks), max_chars)

    def test_chunks_end_on_a_boundary_when_one_exists(self):
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda"
        chunks = _split_text_into_chunks(text, 20)
        for chunk in chunks[:-1]:
            self.assertTrue(
                chunk.endswith((" ", "\n")),
                f"chunk did not end on a boundary: {chunk!r}",
            )
        self.assertEqual("".join(chunks), text)

    def test_line_breaks_are_preferred_over_spaces(self):
        text = "aaa bbb ccc\nddd eee fff ggg"
        chunks = _split_text_into_chunks(text, 16)
        self.assertTrue(chunks[0].endswith("\n"), chunks)

    def test_unseparated_text_falls_back_to_a_hard_cut(self):
        text = "x" * 50
        chunks = _split_text_into_chunks(text, 20)
        self.assertEqual([len(c) for c in chunks], [20, 20, 10])
        self.assertEqual("".join(chunks), text)

    def test_chunks_never_fall_below_half_the_window(self):
        text = ("word " * 400).strip()
        chunks = _split_text_into_chunks(text, 100)
        for chunk in chunks[:-1]:
            self.assertGreaterEqual(len(chunk), 50)

    def test_recovery_mode_keeps_exact_halves(self):
        text = "alpha beta gamma delta epsilon zet"  # 34 characters
        self.assertEqual(len(text), 34)
        chunks = _split_text_into_chunks(text, 17, prefer_boundaries=False)
        self.assertEqual([len(c) for c in chunks], [17, 17])
        self.assertEqual("".join(chunks), text)
        # Boundary mode would instead cut on a space.
        boundary_chunks = _split_text_into_chunks(text, 17)
        self.assertTrue(boundary_chunks[0].endswith(" "))
        self.assertEqual("".join(boundary_chunks), text)

    def test_empty_text_and_invalid_limit(self):
        self.assertEqual(_split_text_into_chunks("", 10), [])
        with self.assertRaises(ValueError):
            _split_text_into_chunks("text", 0)


# ---------------------------------------------------------------------------
# J. Crawl depth and prioritization
# ---------------------------------------------------------------------------
def _crawl_settings(**changes):
    values = dict(
        enabled=True,
        request_timeout_seconds=2,
        max_response_bytes=2048,
        max_extracted_chars=2000,
        max_pages_per_source=10,
        max_retries=0,
        request_delay_seconds=0,
        user_agent="FitScholarTest/1.0",
        model="test-model",
    )
    values.update(changes)
    from app.core.config import ScholarshipDiscoverySettings

    return ScholarshipDiscoverySettings(**values)


class CrawlDepthTests(unittest.TestCase):
    @staticmethod
    def _html(*hrefs):
        body = b"<p>Official scholarship information.</p>"
        for href in hrefs:
            body += f"<a href='{href}'>Scholarship details</a>".encode()
        return body

    def _crawl(self, pages_html, *, max_depth, source=None, max_pages=10):
        source = source or _source()
        fetcher = OfficialSourceFetcher(
            _crawl_settings(max_pages_per_source=max_pages),
            max_crawl_depth=max_depth,
        )
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"
        requested = []

        def fake_fetch_bytes(_src, url, allowed_types=None, *, on_request_attempt=None):
            requested.append(url)
            if on_request_attempt is not None:
                on_request_attempt()
            path = urllib.parse.urlsplit(url)
            key = path.path + (f"?{path.query}" if path.query else "")
            if key not in pages_html:
                raise DiscoveryFetchError("not found", status_code=404)
            return url, headers, pages_html[key]

        with patch.object(fetcher, "_robots_allowed", return_value=True):
            with patch.object(fetcher, "_fetch_bytes", side_effect=fake_fetch_bytes):
                crawled = fetcher.crawl(source)
        return fetcher, requested, crawled

    def test_depth_zero_fetches_the_root_page_only(self):
        pages = {
            "/scholarships": self._html("/scholarships/first"),
            "/scholarships/first": self._html("/scholarships/second"),
            "/scholarships/second": self._html(),
        }
        _fetcher, requested, crawled = self._crawl(pages, max_depth=0)
        self.assertEqual(len(crawled), 1)
        self.assertEqual(requested, ["https://official.example/scholarships"])

    def test_depth_one_does_not_follow_linked_pages_links(self):
        pages = {
            "/scholarships": self._html("/scholarships/first"),
            "/scholarships/first": self._html("/scholarships/second"),
            "/scholarships/second": self._html(),
        }
        _fetcher, requested, crawled = self._crawl(pages, max_depth=1)
        self.assertEqual(len(crawled), 2)
        self.assertNotIn("https://official.example/scholarships/second", requested)

    def test_depth_two_follows_one_more_hop(self):
        pages = {
            "/scholarships": self._html("/scholarships/first"),
            "/scholarships/first": self._html("/scholarships/second"),
            "/scholarships/second": self._html(),
        }
        _fetcher, requested, _crawled = self._crawl(pages, max_depth=2)
        self.assertIn("https://official.example/scholarships/second", requested)

    def test_unique_urls_are_counted_separately_from_references(self):
        pages = {
            "/scholarships": self._html(
                "/scholarships/first#a",
                "/scholarships/first#b",
                "/scholarships/first",
            ),
            "/scholarships/first": self._html(),
        }
        fetcher, _requested, _crawled = self._crawl(pages, max_depth=1)
        stats = fetcher.last_crawl_stats
        self.assertEqual(stats["linked_url_references"], 3)
        self.assertEqual(stats["linked_urls_discovered"], 1)

    def test_daad_database_links_are_fetched_before_generic_ones(self):
        source = DiscoverySource(
            source_id="daad",
            name="DAAD Scholarship Database",
            official_domain="official.example",
            category="government_scholarship_programme",
            country_or_region="Germany",
            source_url="https://official.example/scholarships",
            source_classification="government_authority",
        )
        pages = {
            "/scholarships": self._html(
                "/study/overview",
                "/stipendium/datenbank/entry",
                "/scholarships/generic",
            ),
            "/study/overview": self._html(),
            "/stipendium/datenbank/entry": self._html(),
            "/scholarships/generic": self._html(),
        }
        _fetcher, requested, _crawled = self._crawl(
            pages,
            max_depth=1,
            source=source,
            max_pages=2,
        )
        # Only two pages are fetched; the database entry must be the second.
        self.assertEqual(
            requested,
            [
                "https://official.example/scholarships",
                "https://official.example/stipendium/datenbank/entry",
            ],
        )

    def test_source_pattern_links_bypass_the_generic_relevance_filter(self):
        source = DiscoverySource(
            source_id="daad",
            name="DAAD Scholarship Database",
            official_domain="official.example",
            category="government_scholarship_programme",
            country_or_region="Germany",
            source_url="https://official.example/scholarships",
            source_classification="government_authority",
        )
        # "/db/entry?detail=42" holds no relevant term in its path.
        pages = {
            "/scholarships": self._html("/db/entry?detail=42"),
            "/db/entry?detail=42": self._html(),
        }
        _fetcher, requested, _crawled = self._crawl(
            pages,
            max_depth=1,
            source=source,
        )
        self.assertIn(
            "https://official.example/db/entry?detail=42",
            requested,
        )

    def test_configured_max_crawl_depth_fallback_is_validated(self):
        # Fallback helper for settings objects without the field.
        from app.services.scholarship_discovery_fetch import (
            configured_max_crawl_depth,
        )

        with patch.dict(os.environ, {"SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH": "2"}):
            self.assertEqual(configured_max_crawl_depth(), 2)
        with patch.dict(os.environ, {"SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH": "0"}):
            self.assertEqual(configured_max_crawl_depth(), 0)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH", None)
            self.assertEqual(configured_max_crawl_depth(), 1)
        for invalid in ("x", "-1", "99"):
            with patch.dict(
                os.environ,
                {"SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH": invalid},
            ):
                with self.assertRaises(RuntimeError):
                    configured_max_crawl_depth()

    def test_settings_field_takes_precedence_over_the_env_fallback(self):
        settings = _crawl_settings(max_crawl_depth=3)
        with patch.dict(os.environ, {"SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH": "0"}):
            fetcher = OfficialSourceFetcher(settings)
        self.assertEqual(fetcher.max_crawl_depth, 3)

    def test_env_fallback_is_used_only_without_the_field(self):
        import dataclasses

        # A settings object predating the field, as older test doubles are.
        fields = dataclasses.asdict(_crawl_settings())
        fields.pop("max_crawl_depth")
        settings = SimpleNamespace(**fields)
        self.assertFalse(hasattr(settings, "max_crawl_depth"))
        with patch.dict(os.environ, {"SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH": "4"}):
            fetcher = OfficialSourceFetcher(settings)
        self.assertEqual(fetcher.max_crawl_depth, 4)

    def test_explicit_argument_overrides_both(self):
        settings = _crawl_settings(max_crawl_depth=3)
        with patch.dict(os.environ, {"SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH": "5"}):
            fetcher = OfficialSourceFetcher(settings, max_crawl_depth=0)
        self.assertEqual(fetcher.max_crawl_depth, 0)


# ---------------------------------------------------------------------------
# K. Pipeline: a failed page does not stop the source
# ---------------------------------------------------------------------------
def _pipeline_page(index):
    return SimpleNamespace(
        text=(
            f"Finland Master's Award {index} scholarship is available to "
            "Master's applicants to study in Finland."
        ),
        url=f"https://official.example/scholarships/{index}",
        links=(),
        content_hash=f"{index:064d}",
        content_type="text/html",
        page_count=None,
        insufficient_content=False,
        original_text_length=100,
        retained_text_length=100,
        text_truncated=False,
    )


def _pipeline_source():
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


class PipelinePageFailureTests(unittest.TestCase):
    """run_discovery with a mocked db, fetcher and extractor. No I/O."""

    def _run(self, make_extract, pages):
        from datetime import datetime, timezone

        from app.services import scholarship_discovery

        db = Mock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        db.query.return_value.filter.return_value.first.return_value = None
        db.get_bind.return_value.dialect.name = "sqlite"
        settings = SimpleNamespace(enabled=True, stale_run_timeout_hours=1)
        fetcher = Mock()
        fetcher.crawl.return_value = pages
        fetcher.last_crawl_stats = {
            "linked_urls_discovered": 0,
            "linked_url_references": 0,
            "linked_pages_attempted": 0,
            "linked_pages_fetched": 0,
            "linked_pages_failed": 0,
            "linked_pages_skipped_safety": 0,
            "linked_pages_skipped_relevance": 0,
            "linked_pages_skipped": 0,
        }
        extractor = Mock()
        extractor.last_provider_diagnostics = {}
        extractor.last_rejection_reasons = []
        extractor.last_rejection_detail_counts = {}
        extractor.last_rejected_count = 0
        extractor.extract.side_effect = make_extract(extractor)
        recorded_success = []

        def save_run(_db, run, _summary, _source_results, status, lock_check=None):
            if status != "running":
                run.finished_at = datetime.now(timezone.utc)

        patches = [
            patch("app.services.scholarship_discovery._register_evidence"),
            patch(
                "app.services.scholarship_discovery.record_publication_source_success",
                side_effect=lambda _db, _sid, url, _hash: recorded_success.append(url),
            ),
            patch("app.services.scholarship_discovery.record_publication_source_failure"),
            patch(
                "app.services.scholarship_discovery.resolve_trusted_source_url",
                side_effect=lambda base, _url, _source: base,
            ),
            patch(
                "app.services.scholarship_discovery.has_open_review_for_identity",
                return_value=False,
            ),
            patch(
                "app.services.scholarship_discovery.find_identity_record",
                return_value=None,
            ),
            patch(
                "app.services.scholarship_discovery.find_possible_duplicate_records",
                return_value=[],
            ),
            patch(
                "app.services.scholarship_discovery._persist_candidate",
                return_value=(None, True),
            ),
            patch("app.services.scholarship_discovery._save_run", side_effect=save_run),
        ]
        for started in patches:
            started.start()
        try:
            result = scholarship_discovery.run_discovery(
                db,
                settings=settings,
                sources=[_pipeline_source()],
                fetcher=fetcher,
                extractor=extractor,
                trigger_type="scheduled",
                scheduled_for=datetime.now(timezone.utc),
            )
        finally:
            for started in reversed(patches):
                started.stop()
        return result, extractor, recorded_success

    def test_one_failed_page_does_not_stop_later_pages(self):
        pages = [_pipeline_page(index) for index in range(3)]

        def make_extract(extractor):
            calls = {"count": 0}

            def extract(_page, _source):
                calls["count"] += 1
                extractor.last_rejection_detail_counts = {}
                extractor.last_rejected_count = 0
                if calls["count"] == 2:
                    raise ScholarshipExtractionError(
                        "bad response",
                        category="malformed_response",
                    )
                return []

            return extract

        result, extractor, _recorded = self._run(make_extract, pages)

        # All three pages were attempted even though page two failed.
        self.assertEqual(extractor.extract.call_count, 3)
        source_result = result["sources"][0]
        self.assertEqual(source_result["pages_extracted"], 2)
        self.assertEqual(source_result["pages_failed"], 1)
        self.assertEqual(source_result["extraction_status"], "some_pages_failed")
        self.assertEqual(source_result["status"], "partial_failure")
        self.assertEqual(
            source_result["page_failures"],
            [{"page_index": 2, "category": "malformed_response", "http_status": None}],
        )
        # The source is counted once, not once per failed page.
        self.assertEqual(result["summary"]["sources_failed"], 1)

    def test_publication_success_is_not_recorded_for_a_failed_page(self):
        pages = [_pipeline_page(0), _pipeline_page(1)]

        def make_extract(extractor):
            calls = {"count": 0}

            def extract(_page, _source):
                calls["count"] += 1
                extractor.last_rejection_detail_counts = {}
                extractor.last_rejected_count = 0
                if calls["count"] == 1:
                    raise ScholarshipExtractionError(
                        "bad response",
                        category="malformed_response",
                    )
                return []

            return extract

        _result, _extractor, recorded = self._run(make_extract, pages)
        # Only the page that actually extracted is recorded as a success.
        self.assertEqual(len(recorded), 1)

    def test_quota_exhaustion_stops_the_source(self):
        pages = [_pipeline_page(index) for index in range(3)]

        def make_extract(extractor):
            def extract(_page, _source):
                extractor.last_rejection_detail_counts = {}
                extractor.last_rejected_count = 0
                raise ScholarshipExtractionError(
                    "quota",
                    category="quota_exhausted",
                    http_status=429,
                )

            return extract

        result, extractor, recorded = self._run(make_extract, pages)
        self.assertEqual(extractor.extract.call_count, 1)
        source_result = result["sources"][0]
        self.assertTrue(source_result["processing_stopped_after_failed_page"])
        self.assertEqual(source_result["extraction_status"], "all_pages_failed")
        self.assertEqual(source_result["pages_extracted"], 0)
        self.assertEqual(recorded, [])

    def test_candidate_rejection_details_are_reported_per_source(self):
        pages = [_pipeline_page(0)]

        def make_extract(extractor):
            def extract(_page, _source):
                extractor.last_rejection_detail_counts = {
                    "out_of_scope:degree_level": 2,
                    "evidence_mismatch:host_location": 1,
                    "not a valid code!": 9,
                }
                extractor.last_rejected_count = 3
                return []

            return extract

        result, _extractor, _recorded = self._run(make_extract, pages)
        details = result["sources"][0]["candidate_rejection_details"]
        # The malformed code is dropped; only allowlisted codes are reported.
        self.assertEqual(
            details,
            {"out_of_scope:degree_level": 2, "evidence_mismatch:host_location": 1},
        )


# ---------------------------------------------------------------------------
# L. Settings fields for the token cap and crawl depth
# ---------------------------------------------------------------------------
class DiscoverySettingsFieldTests(unittest.TestCase):
    """GROQ_MAX_REQUEST_TOKENS and SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH."""

    MANAGED = (
        "GROQ_MAX_REQUEST_TOKENS",
        "SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH",
        "GROQ_MAX_INPUT_CHARS",
    )

    def _load(self, **env):
        """Load settings with only the given variables set."""
        from app.core.config import scholarship_discovery_settings

        with patch.dict(os.environ, env):
            for name in self.MANAGED:
                if name not in env:
                    os.environ.pop(name, None)
            return scholarship_discovery_settings()

    # -- GROQ_MAX_REQUEST_TOKENS -------------------------------------------
    def test_token_cap_defaults_to_6000_when_unset(self):
        self.assertEqual(self._load().groq_max_request_tokens, 6_000)

    def test_token_cap_zero_disables_the_preflight(self):
        self.assertIsNone(
            self._load(GROQ_MAX_REQUEST_TOKENS="0").groq_max_request_tokens,
        )

    def test_token_cap_accepts_an_in_range_value(self):
        self.assertEqual(
            self._load(GROQ_MAX_REQUEST_TOKENS="7500").groq_max_request_tokens,
            7_500,
        )

    def test_token_cap_rejects_a_non_integer_without_echoing_it(self):
        secret = "not-an-integer-9f3a"
        with self.assertRaises(RuntimeError) as raised:
            self._load(GROQ_MAX_REQUEST_TOKENS=secret)
        message = str(raised.exception)
        self.assertIn("GROQ_MAX_REQUEST_TOKENS", message)
        self.assertNotIn(secret, message)

    def test_token_cap_rejects_an_out_of_range_value(self):
        for invalid in ("-1", "1000001"):
            with self.subTest(value=invalid):
                with self.assertRaises(RuntimeError) as raised:
                    self._load(GROQ_MAX_REQUEST_TOKENS=invalid)
                self.assertIn("GROQ_MAX_REQUEST_TOKENS", str(raised.exception))

    # -- SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH ------------------------------
    def test_crawl_depth_defaults_to_one(self):
        self.assertEqual(self._load().max_crawl_depth, 1)

    def test_crawl_depth_accepts_the_full_range(self):
        for value in ("0", "1", "5"):
            with self.subTest(value=value):
                settings = self._load(
                    SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH=value,
                )
                self.assertEqual(settings.max_crawl_depth, int(value))

    def test_crawl_depth_rejects_out_of_range_and_non_integers(self):
        for invalid in ("6", "-1", "deep"):
            with self.subTest(value=invalid):
                with self.assertRaises(RuntimeError) as raised:
                    self._load(SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH=invalid)
                self.assertIn(
                    "SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH",
                    str(raised.exception),
                )

    # -- chunk size default -------------------------------------------------
    def test_chunk_chars_default_is_6000(self):
        from app.core.config import ScholarshipDiscoverySettings

        self.assertEqual(
            ScholarshipDiscoverySettings.max_provider_chunk_chars,
            6_000,
        )
        self.assertEqual(self._load().max_provider_chunk_chars, 6_000)

    def test_chunk_chars_default_fits_inside_the_token_cap(self):
        """Every REAL registry source must fit a full chunk at the defaults.

        Checked against app.services.scholarship_discovery_sources rather than
        a short synthetic fixture, because the prompt carries the source name,
        source URL and (for a single European country) registry_host_country.
        Those differ per source by hundreds of characters, so a fixture with a
        short name and a non-European country hides the real worst case. This
        test is what stops prompt growth from silently pushing production
        requests over GROQ_MAX_REQUEST_TOKENS.
        """
        from app.services.scholarship_discovery_sources import SOURCES_BY_ID

        settings = self._load()
        cap = settings.groq_max_request_tokens
        self.assertIsNotNone(cap, "the token preflight must be on by default")
        extractor = GroqScholarshipExtractor(settings, groq_client=Mock())
        chunk = "x" * settings.max_provider_chunk_chars
        self.assertGreaterEqual(len(SOURCES_BY_ID), 10)

        worst_tokens = 0
        worst_source = None
        for source_id, source in SOURCES_BY_ID.items():
            page = FetchedPage(
                url=source.source_url,
                content_type="text/html",
                text=chunk,
                links=(),
                content_hash="a" * 64,
            )
            tokens = extractor._estimated_request_tokens(
                extractor._prompt(page, source, False),
            )
            if tokens > worst_tokens:
                worst_tokens, worst_source = tokens, source_id

        self.assertLessEqual(
            worst_tokens,
            cap,
            f"a full {settings.max_provider_chunk_chars}-char chunk for source "
            f"{worst_source!r} needs {worst_tokens} tokens, over the {cap} cap: "
            "lower GROQ_MAX_INPUT_CHARS or raise GROQ_MAX_REQUEST_TOKENS",
        )

    MINIMUM_RETAINED_LINKS = 10

    def test_default_chunk_leaves_room_for_linked_urls(self):
        """A full first chunk must still carry linked URLs, not drop them all.

        The linked-URL block shares the token budget with the page text, so a
        chunk size that only just fits leaves no room for the links that let
        the crawl reach scholarship detail pages and call documents.

        Measured with 40 real-length DAAD database URLs (112 characters each):
        at GROQ_MAX_INPUT_CHARS=8000 the prompt did not fit at all and was
        rejected locally even with zero links; at 6000 it keeps 17 of 40. The
        floor below is deliberately well under 17, so ordinary prompt edits do
        not trip it but a regression back toward the 8000 behaviour does.
        """
        from app.services.scholarship_discovery_sources import SOURCES_BY_ID

        settings = self._load()
        extractor = GroqScholarshipExtractor(settings, groq_client=Mock())
        source = SOURCES_BY_ID["daad-helmut-schmidt"]
        links = tuple(
            (f"{source.source_url}/detail-{index:04d}", "Scholarship details")
            for index in range(40)
        )
        page = FetchedPage(
            url=source.source_url,
            content_type="text/html",
            text="word " * (settings.max_provider_chunk_chars // 5),
            links=links,
            content_hash="a" * 64,
        )
        diagnostics: dict = {}
        extractor._prompt_within_budget(
            page,
            source,
            provider="groq",
            page_text=page.text,
            request_size_diagnostics=diagnostics,
            include_linked_urls=True,
        )
        self.assertLessEqual(
            diagnostics["estimated_request_tokens"],
            settings.groq_max_request_tokens,
        )
        self.assertGreaterEqual(
            diagnostics["linked_url_count_after_pruning"],
            self.MINIMUM_RETAINED_LINKS,
            "a full default-size chunk retained too few linked URLs to reach "
            f"detail pages: {diagnostics}",
        )

    # -- the manual / diagnostic profiles keep both fields ------------------
    def test_controlled_manual_settings_keep_both_fields(self):
        from app.services.scholarship_discovery_budget import (
            controlled_manual_settings,
        )

        settings = self._load(
            GROQ_MAX_REQUEST_TOKENS="4321",
            SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH="2",
        )
        manual = controlled_manual_settings(settings)
        self.assertEqual(manual.groq_max_request_tokens, 4_321)
        self.assertEqual(manual.max_crawl_depth, 2)
        # The clamped limits still apply.
        self.assertLessEqual(manual.max_pages_per_source, 3)

    def test_controlled_manual_settings_keep_a_disabled_token_cap(self):
        from app.services.scholarship_discovery_budget import (
            controlled_manual_settings,
        )

        settings = self._load(GROQ_MAX_REQUEST_TOKENS="0")
        self.assertIsNone(
            controlled_manual_settings(settings).groq_max_request_tokens,
        )

    def test_diagnostic_single_source_budget_does_not_drop_settings(self):
        from app.services.scholarship_discovery_budget import (
            controlled_manual_settings,
            diagnostic_single_source_budget,
            validate_diagnostic_single_source_budget,
        )

        # The diagnostic profile builds a budget, not settings; the settings
        # it is used with keep both fields.
        budget = diagnostic_single_source_budget()
        validate_diagnostic_single_source_budget(budget)
        settings = controlled_manual_settings(
            self._load(
                GROQ_MAX_REQUEST_TOKENS="5000",
                SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH="0",
            ),
        )
        self.assertEqual(settings.groq_max_request_tokens, 5_000)
        self.assertEqual(settings.max_crawl_depth, 0)

    # -- settings beat the environment fallback -----------------------------
    def test_extractor_prefers_the_settings_field_over_the_env_fallback(self):
        settings = self._load(GROQ_MAX_REQUEST_TOKENS="4321")
        extractor = GroqScholarshipExtractor(settings, groq_client=Mock())
        with patch.dict(os.environ, {"GROQ_MAX_REQUEST_TOKENS": "999"}):
            self.assertEqual(extractor._max_request_tokens(), 4_321)

    def test_extractor_honours_a_disabled_cap_from_settings(self):
        settings = self._load(GROQ_MAX_REQUEST_TOKENS="0")
        extractor = GroqScholarshipExtractor(settings, groq_client=Mock())
        # None on the settings means "explicitly disabled", not "unset": the
        # environment must not switch the preflight back on.
        with patch.dict(os.environ, {"GROQ_MAX_REQUEST_TOKENS": "6000"}):
            self.assertIsNone(extractor._max_request_tokens())

    def test_extractor_falls_back_to_env_only_without_the_field(self):
        extractor = _extractor()
        del extractor.settings.groq_max_request_tokens
        with patch.dict(os.environ, {"GROQ_MAX_REQUEST_TOKENS": "4321"}):
            self.assertEqual(extractor._max_request_tokens(), 4_321)

    def test_run_discovery_passes_the_configured_crawl_depth(self):
        from app.services.scholarship_discovery_fetch import OfficialSourceFetcher

        settings = self._load(SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH="0")
        with patch.dict(os.environ, {"SCHOLARSHIP_DISCOVERY_MAX_CRAWL_DEPTH": "5"}):
            fetcher = OfficialSourceFetcher(
                settings,
                max_crawl_depth=getattr(settings, "max_crawl_depth", None),
            )
        self.assertEqual(fetcher.max_crawl_depth, 0)


# ---------------------------------------------------------------------------
# M. Allowed field list in the prompt, and unknown keys dropped not rejected
# ---------------------------------------------------------------------------
class AllowedFieldListPromptTests(unittest.TestCase):
    def _prompt(self):
        extractor = _extractor()
        return extractor._prompt(_page(), _source(), False)

    def test_prompt_lists_the_allowed_value_fields(self):
        from app.services.scholarship_discovery_extraction import (
            _allowed_value_field_names,
        )

        prompt = self._prompt()
        names = _allowed_value_field_names()
        self.assertIn("host_city", names)
        # A representative spread, not just one name.
        for name in ("name", "country", "degree_level", "deadline", "host_city"):
            self.assertIn(name, names)
            self.assertIn(name, prompt)
        self.assertIn(", ".join(names), prompt)
        self.assertIn("The only permitted keys inside `values` are exactly these", prompt)

    def test_prompt_no_longer_tells_the_model_to_guess(self):
        prompt = self._prompt()
        self.assertNotIn("existing ScholarshipCreate field names only", prompt)

    def test_prompt_omits_every_protected_field_name(self):
        from app.services.scholarship_discovery_extraction import (
            PROTECTED_FIELDS,
            _allowed_value_field_names,
        )

        names = _allowed_value_field_names()
        for protected in PROTECTED_FIELDS | {"verification_status"}:
            self.assertNotIn(protected, names)
        # The listed block itself must not name a protected field.
        listed = ", ".join(names)
        for protected in PROTECTED_FIELDS | {"verification_status"}:
            self.assertNotIn(protected, listed)

    def test_source_data_json_is_compact_without_losing_page_text(self):
        page = _page("Official award details.\nDeadline: 30 June 2027.")
        prompt = _extractor()._prompt(page, _source(), False)
        serialized = prompt.split("Source page data (JSON):\n", 1)[1]
        payload = json.loads(serialized)

        self.assertEqual(payload["official_page_text"], page.text)
        self.assertNotIn('": ', serialized)

    def test_allowed_field_names_are_sorted_with_host_city_last(self):
        from app.services.scholarship_discovery_extraction import (
            _allowed_value_field_names,
        )

        names = _allowed_value_field_names()
        self.assertEqual(names[-1], "host_city")
        self.assertEqual(list(names[:-1]), sorted(names[:-1]))
        self.assertEqual(len(set(names)), len(names))


class UnknownFieldHandlingTests(unittest.TestCase):
    def _extract(self, extra_values):
        extractor = _extractor(groq_max_request_tokens=0)
        candidate = _candidate()
        candidate["values"].update(extra_values)
        extractor._generate_groq = Mock(return_value=_response(candidate))
        return extractor, extractor.extract(_page(), _source())

    def test_unknown_field_is_dropped_and_the_candidate_kept(self):
        extractor, extracted = self._extract({"tuition_fee_waiver": "full"})

        self.assertEqual(len(extracted), 1)
        candidate = extracted[0]
        # The invented key never reaches the stored values.
        self.assertNotIn("tuition_fee_waiver", candidate.values)
        self.assertIn("unsupported_fields_dropped", candidate.review_reasons)
        self.assertTrue(candidate.requires_review)
        self.assertEqual(candidate.dropped_fields, ("tuition_fee_waiver",))
        # Dropping is not a rejection.
        self.assertEqual(extractor.last_rejected_count, 0)
        self.assertEqual(extractor.last_rejection_detail_counts, {})
        self.assertEqual(extractor.last_outcome_status, "candidates_accepted")
        self.assertEqual(
            extractor.last_dropped_field_counts,
            {"tuition_fee_waiver": 1},
        )

    def test_several_unknown_fields_are_all_dropped_and_counted(self):
        extractor, extracted = self._extract({
            "tuition_fee_waiver": "full",
            "made_up_key": "x",
        })

        self.assertEqual(len(extracted), 1)
        self.assertEqual(
            extracted[0].dropped_fields,
            ("made_up_key", "tuition_fee_waiver"),
        )
        self.assertEqual(
            extractor.last_dropped_field_counts,
            {"made_up_key": 1, "tuition_fee_waiver": 1},
        )
        self.assertEqual(extractor.last_rejected_count, 0)
        # One review reason however many keys were dropped.
        self.assertEqual(
            list(extracted[0].review_reasons).count("unsupported_fields_dropped"),
            1,
        )

    def test_a_protected_field_still_rejects_the_candidate(self):
        extractor, extracted = self._extract({"verification_status": "verified"})

        self.assertEqual(extracted, [])
        self.assertEqual(extractor.last_rejected_count, 1)
        self.assertEqual(
            extractor.last_rejection_detail_counts,
            {"protected_field": 1},
        )
        self.assertEqual(extractor.last_outcome_status, "candidates_rejected")
        self.assertEqual(extractor.last_dropped_field_counts, {})

    def test_every_protected_field_is_rejected_not_dropped(self):
        from app.services.scholarship_discovery_extraction import PROTECTED_FIELDS

        for protected in sorted(PROTECTED_FIELDS):
            with self.subTest(field=protected):
                extractor, extracted = self._extract({protected: "x"})
                self.assertEqual(extracted, [])
                self.assertEqual(
                    extractor.last_rejection_detail_counts,
                    {"protected_field": 1},
                )

    def test_a_clean_candidate_drops_nothing(self):
        extractor, extracted = self._extract({})
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0].dropped_fields, ())
        self.assertNotIn(
            "unsupported_fields_dropped",
            extracted[0].review_reasons,
        )
        self.assertEqual(extractor.last_dropped_field_counts, {})

    def test_dropped_field_evidence_is_dropped_too(self):
        extractor = _extractor(groq_max_request_tokens=0)
        candidate = _candidate()
        candidate["values"]["made_up_key"] = "x"
        candidate["evidence"]["made_up_key"] = "The Finland Master's Scholarship"
        extractor._generate_groq = Mock(return_value=_response(candidate))

        extracted = extractor.extract(_page(), _source())
        self.assertEqual(len(extracted), 1)
        self.assertNotIn("made_up_key", extracted[0].values)
        self.assertNotIn("made_up_key", extracted[0].evidence)


class DiagnosticRejectionDetailOutputTests(unittest.TestCase):
    """_sanitize_candidate_diagnostics output is labels and integers only."""

    def _sanitize(self, extractor, accepted):
        import importlib

        module = importlib.import_module("diagnose_single_source_extraction")
        return module._sanitize_candidate_diagnostics(
            extractor,
            extractor.last_provider_diagnostics,
            accepted,
        )

    def test_rejection_detail_counts_are_reported(self):
        extractor = _extractor(groq_max_request_tokens=0)
        candidate = _candidate()
        candidate["values"]["degree_level"] = "Bachelor"
        extractor._generate_groq = Mock(return_value=_response(candidate))
        extractor.extract(_page(), _source())

        report = self._sanitize(extractor, 0)
        self.assertEqual(
            report["rejection_detail_counts"],
            {"out_of_scope:degree_level": 1},
        )
        self.assertEqual(report["outcome_status"], "candidates_rejected")

    def test_unknown_field_names_are_reported_for_dropped_keys(self):
        extractor = _extractor(groq_max_request_tokens=0)
        candidate = _candidate()
        candidate["values"]["tuition_fee_waiver"] = "full"
        extractor._generate_groq = Mock(return_value=_response(candidate))
        extracted = extractor.extract(_page(), _source())

        report = self._sanitize(extractor, len(extracted))
        self.assertEqual(
            report["unsupported_field_names"],
            {"tuition_fee_waiver": 1},
        )
        # Dropping is not a rejection.
        self.assertEqual(report["rejection_detail_counts"], {})
        self.assertEqual(report["rejected_candidate_count"], 0)
        self.assertEqual(report["accepted_candidate_count"], 1)

    def test_unknown_field_names_are_absent_when_nothing_was_dropped(self):
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response(_candidate()))
        extracted = extractor.extract(_page(), _source())

        report = self._sanitize(extractor, len(extracted))
        self.assertNotIn("unsupported_field_names", report)

    def test_report_never_contains_evidence_or_page_text(self):
        extractor = _extractor(groq_max_request_tokens=0)
        candidate = _candidate()
        candidate["values"]["tuition_fee_waiver"] = "full"
        candidate["values"]["degree_level"] = "Bachelor"
        extractor._generate_groq = Mock(return_value=_response(candidate))
        extractor.extract(_page(), _source())

        serialized = json.dumps(self._sanitize(extractor, 0))
        for leaked in (
            "Finland Master's Scholarship",
            "Host country: Finland",
            "Master's students",
            FINLAND_TEXT,
            "official.example",
        ):
            self.assertNotIn(leaked, serialized)

    def test_malformed_codes_and_names_are_filtered_out(self):
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response())
        extractor.extract(_page(), _source())
        extractor.last_rejection_detail_counts = {
            "out_of_scope:degree_level": 2,
            "Not A Code": 5,
            "page text leaked here": 1,
            "negative": -3,
        }
        extractor.last_dropped_field_counts = {
            "good_name": 1,
            "Bad-Name": 2,
            "a sentence of page text": 4,
        }
        report = self._sanitize(extractor, 0)
        self.assertEqual(
            report["rejection_detail_counts"],
            {"out_of_scope:degree_level": 2},
        )
        self.assertEqual(report["unsupported_field_names"], {"good_name": 1})

    def test_missing_counters_report_unavailable(self):
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response())
        extractor.extract(_page(), _source())
        del extractor.last_rejection_detail_counts
        report = self._sanitize(extractor, 0)
        self.assertEqual(report["rejection_detail_counts"], "unavailable")


# ---------------------------------------------------------------------------
# N. No null placeholders; host country goes in `country`
# ---------------------------------------------------------------------------
class OmissionPromptTests(unittest.TestCase):
    MODELS = (
        "llama-3.3-70b-versatile",
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "some-other-model",
    )

    def _prompt(self, model, strict_output=False):
        extractor = _extractor(groq_model=model)
        return extractor._prompt(_page(), _source(), strict_output)

    def test_no_model_is_told_to_emit_null_placeholders(self):
        for model in self.MODELS:
            for strict_output in (False, True):
                with self.subTest(model=model, strict_output=strict_output):
                    prompt = self._prompt(model, strict_output)
                    self.assertNotIn("use null", prompt)
                    self.assertNotIn(
                        "For optional values without evidence",
                        prompt,
                    )

    def test_every_model_is_told_to_omit_unevidenced_fields(self):
        for model in self.MODELS:
            with self.subTest(model=model):
                prompt = self._prompt(model)
                self.assertIn(
                    "Do not infer missing values; omit unknown fields.",
                    prompt,
                )
                self.assertIn(
                    "do not output null or empty-string placeholders",
                    prompt,
                )

    def test_prompt_names_country_as_the_host_country_field(self):
        prompt = self._prompt("openai/gpt-oss-20b")
        self.assertIn(
            "Put the scholarship's host country in `country` and its host "
            "city in `host_city`.",
            prompt,
        )
        self.assertIn("There is no `host_country` field", prompt)

    def test_host_country_is_not_an_allowed_field_name(self):
        from app.services.scholarship_discovery_extraction import (
            _allowed_value_field_names,
        )

        names = _allowed_value_field_names()
        self.assertNotIn("host_country", names)
        self.assertIn("country", names)
        self.assertIn("host_city", names)

    def test_strict_schema_helper_is_still_available(self):
        # Task 1 keeps the strict-schema helpers for callers that ask.
        from app.services.scholarship_discovery_extraction import (
            _strict_extraction_schema,
        )

        schema = _strict_extraction_schema()
        self.assertEqual(schema["required"], ["scholarships"])


# ---------------------------------------------------------------------------
# O. Reasoning effort for gpt-oss extraction
# ---------------------------------------------------------------------------
class ReasoningEffortTests(unittest.TestCase):
    GPT_OSS = ("openai/gpt-oss-20b", "openai/gpt-oss-120b")

    def _sent_kwargs(self, **overrides):
        """Capture the kwargs of the extraction request actually issued."""
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=_response()),
                finish_reason="stop",
            )],
            usage=SimpleNamespace(
                completion_tokens=120,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=40),
            ),
        )
        settings = dict(
            model="offline-groq",
            max_provider_chunk_chars=12_000,
            groq_max_completion_tokens=500,
            groq_rate_limit_retries=0,
            groq_fallback_enabled=False,
            groq_max_request_tokens=0,
        )
        settings.update(overrides)
        extractor = GroqScholarshipExtractor(
            SimpleNamespace(**settings),
            groq_client=client,
        )
        extractor.extract(_page(), _source())
        return client.chat.completions.create.call_args.kwargs, extractor

    def test_gpt_oss_models_default_to_low_effort(self):
        for model in self.GPT_OSS:
            with self.subTest(model=model):
                kwargs, _ = self._sent_kwargs(groq_model=model)
                self.assertEqual(kwargs["reasoning_effort"], "low")

    def test_other_models_send_no_reasoning_effort_key(self):
        for model in ("llama-3.3-70b-versatile", "some-other-model"):
            with self.subTest(model=model):
                kwargs, _ = self._sent_kwargs(groq_model=model)
                self.assertNotIn("reasoning_effort", kwargs)

    def test_setting_overrides_the_model_default(self):
        kwargs, _ = self._sent_kwargs(
            groq_model="openai/gpt-oss-20b",
            groq_extraction_reasoning_effort="high",
        )
        self.assertEqual(kwargs["reasoning_effort"], "high")

    def test_setting_applies_to_a_model_without_a_default(self):
        kwargs, _ = self._sent_kwargs(
            groq_model="llama-3.3-70b-versatile",
            groq_extraction_reasoning_effort="medium",
        )
        self.assertEqual(kwargs["reasoning_effort"], "medium")

    def test_an_unsupported_setting_value_falls_back_to_the_model_default(self):
        with self.assertLogs(
            "app.services.scholarship_discovery_extraction",
            level="WARNING",
        ):
            kwargs, _ = self._sent_kwargs(
                groq_model="openai/gpt-oss-20b",
                groq_extraction_reasoning_effort="turbo",
            )
        self.assertEqual(kwargs["reasoning_effort"], "low")

    def test_text_fallback_carries_the_same_effort(self):
        from app.services import scholarship_discovery_extraction as extraction

        extractor = _extractor(
            groq_model="openai/gpt-oss-20b",
            groq_max_request_tokens=0,
        )
        captured = {}

        def fake_text_completion(_client, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content=_response()),
                    finish_reason="stop",
                )],
            )

        json_error = GroqProviderError(
            "malformed_request",
            400,
            {
                "type": "invalid_request_error",
                "code": "json_validate_failed",
            },
        )
        json_error._attempt_context = ("primary", Mock(), None)

        with patch.object(
            extraction,
            "generate_json_completion",
            side_effect=json_error,
        ):
            with patch.object(
                extraction,
                "generate_text_completion",
                side_effect=fake_text_completion,
            ):
                extractor.extract(_page(), _source())

        self.assertEqual(captured["reasoning_effort"], "low")

    # -- config loading ----------------------------------------------------
    def _load(self, **env):
        from app.core.config import scholarship_discovery_settings

        with patch.dict(os.environ, env):
            if "GROQ_EXTRACTION_REASONING_EFFORT" not in env:
                os.environ.pop("GROQ_EXTRACTION_REASONING_EFFORT", None)
            return scholarship_discovery_settings()

    def test_unset_env_leaves_the_setting_none(self):
        self.assertIsNone(self._load().groq_extraction_reasoning_effort)

    def test_env_accepts_the_three_levels(self):
        for level in ("low", "medium", "high"):
            with self.subTest(level=level):
                settings = self._load(GROQ_EXTRACTION_REASONING_EFFORT=level)
                self.assertEqual(
                    settings.groq_extraction_reasoning_effort,
                    level,
                )

    def test_env_is_case_insensitive(self):
        settings = self._load(GROQ_EXTRACTION_REASONING_EFFORT="LOW")
        self.assertEqual(settings.groq_extraction_reasoning_effort, "low")

    def test_invalid_env_raises_naming_the_variable(self):
        secret = "ludicrous-speed-7b2"
        with self.assertRaises(RuntimeError) as raised:
            self._load(GROQ_EXTRACTION_REASONING_EFFORT=secret)
        message = str(raised.exception)
        self.assertIn("GROQ_EXTRACTION_REASONING_EFFORT", message)
        self.assertNotIn(secret, message)

    def test_unset_env_still_yields_low_for_gpt_oss(self):
        settings = self._load()
        extractor = GroqScholarshipExtractor(
            settings,
            groq_client=Mock(),
        )
        extractor.settings = SimpleNamespace(
            groq_model="openai/gpt-oss-20b",
            groq_extraction_reasoning_effort=settings.groq_extraction_reasoning_effort,
        )
        self.assertEqual(extractor._extraction_reasoning_effort(), "low")


# ---------------------------------------------------------------------------
# P. finish_reason and token counts in diagnostics
# ---------------------------------------------------------------------------
class CompletionMetadataDiagnosticsTests(unittest.TestCase):
    def _requests(self, extractor):
        return [
            request
            for chunk in extractor.last_provider_diagnostics["chunk_diagnostics"]
            for request in chunk.get("requests", [])
        ]

    def test_successful_response_metadata_is_recorded(self):
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=_response()),
                finish_reason="stop",
            )],
            usage=SimpleNamespace(
                completion_tokens=321,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=120),
            ),
        )
        extractor = GroqScholarshipExtractor(
            SimpleNamespace(
                model="offline-groq",
                groq_model="offline-groq",
                max_provider_chunk_chars=12_000,
                groq_max_completion_tokens=500,
                groq_rate_limit_retries=0,
                groq_fallback_enabled=False,
                groq_max_request_tokens=0,
            ),
            groq_client=client,
        )
        extractor.extract(_page(), _source())

        self.assertEqual(
            self._requests(extractor)[0]["completion_metadata"],
            {
                "finish_reason": "stop",
                "completion_tokens": 321,
                "reasoning_tokens": 120,
            },
        )

    def test_truncated_output_reports_finish_reason_length(self):
        extractor = _extractor(groq_max_request_tokens=0)
        error = ScholarshipExtractionError(
            "truncated",
            category="malformed_response",
            http_status=400,
        )
        error.completion_metadata = {
            "finish_reason": "length",
            "completion_tokens": 2_048,
            "reasoning_tokens": 1_900,
        }
        extractor._generate_groq = Mock(side_effect=error)

        with self.assertRaises(ScholarshipExtractionError):
            extractor.extract(_page(), _source())

        self.assertEqual(
            self._requests(extractor)[0]["completion_metadata"],
            {
                "finish_reason": "length",
                "completion_tokens": 2_048,
                "reasoning_tokens": 1_900,
            },
        )

    def test_provider_error_body_metadata_reaches_the_error(self):
        from app.services.groq_provider import (
            completion_metadata_from_error,
            completion_metadata_from_response,
        )

        class Failure(Exception):
            status_code = 400
            body = {
                "error": {
                    "code": "json_validate_failed",
                    "message": "provider text that must not be kept",
                },
                "finish_reason": "length",
                "usage": {"completion_tokens": 2_048},
            }

        self.assertEqual(
            completion_metadata_from_error(Failure()),
            {"finish_reason": "length", "completion_tokens": 2_048},
        )
        self.assertEqual(
            completion_metadata_from_response(
                SimpleNamespace(
                    choices=[SimpleNamespace(finish_reason="stop")],
                    usage=SimpleNamespace(
                        completion_tokens=10,
                        completion_tokens_details=None,
                    ),
                ),
            ),
            {"finish_reason": "stop", "completion_tokens": 10},
        )

    def test_unknown_finish_reasons_and_bad_counts_are_dropped(self):
        from app.services.groq_provider import sanitize_completion_metadata

        self.assertEqual(
            sanitize_completion_metadata({
                "finish_reason": "page text leaked here",
                "completion_tokens": -5,
                "reasoning_tokens": True,
            }),
            {},
        )
        self.assertEqual(sanitize_completion_metadata(None), {})

    def test_metadata_does_not_leak_across_requests(self):
        extractor = _extractor(
            max_provider_chunk_chars=1_000,
            groq_max_request_tokens=0,
        )
        calls = {"count": 0}

        def generate(_prompt):
            calls["count"] += 1
            if calls["count"] == 1:
                extractor._last_completion_metadata = {"finish_reason": "stop"}
                return _response()
            # Second chunk returns no metadata at all.
            extractor._last_completion_metadata = {}
            return _response()

        extractor._generate_groq = Mock(side_effect=generate)
        extractor.extract(_page("official scholarship text " * 100), _source())

        requests = self._requests(extractor)
        self.assertGreaterEqual(len(requests), 2)
        self.assertEqual(
            requests[0]["completion_metadata"],
            {"finish_reason": "stop"},
        )
        self.assertNotIn("completion_metadata", requests[1])

    def test_diagnostic_report_shows_metadata_and_no_output_text(self):
        import importlib

        module = importlib.import_module("diagnose_single_source_extraction")
        extractor = _extractor(groq_max_request_tokens=0)
        error = ScholarshipExtractionError(
            "truncated",
            category="malformed_response",
            http_status=400,
        )
        error.completion_metadata = {
            "finish_reason": "length",
            "completion_tokens": 2_048,
            "reasoning_tokens": 1_900,
        }
        extractor._generate_groq = Mock(side_effect=error)
        with self.assertRaises(ScholarshipExtractionError):
            extractor.extract(_page(), _source())

        report = module._sanitize_extraction_diagnostics(
            extractor.last_provider_diagnostics,
            [len(FINLAND_TEXT)],
            [],
        )
        request = report["chunks"][0]["requests"][0]
        self.assertEqual(
            request["completion_metadata"],
            {
                "finish_reason": "length",
                "completion_tokens": 2_048,
                "reasoning_tokens": 1_900,
            },
        )
        serialized = json.dumps(report)
        for leaked in (
            FINLAND_TEXT,
            "Finland Master's Scholarship",
            "truncated",
            "provider text",
        ):
            self.assertNotIn(leaked, serialized)

    def test_diagnostic_report_filters_an_unknown_finish_reason(self):
        import importlib

        module = importlib.import_module("diagnose_single_source_extraction")
        self.assertEqual(
            module._safe_completion_metadata({
                "finish_reason": "some page sentence",
                "completion_tokens": 5,
            }),
            {"completion_tokens": 5},
        )
        self.assertEqual(module._safe_completion_metadata(None), {})

    def test_diagnostic_report_shows_the_provider_limit(self):
        import importlib

        module = importlib.import_module("diagnose_single_source_extraction")
        self.assertEqual(
            module._safe_provider_limit({
                "limit_type": "TPM",
                "limit": 8_000,
                "requested": 9_965,
            }),
            {"limit_type": "TPM", "limit": 8_000, "requested": 9_965},
        )
        self.assertEqual(
            module._safe_provider_limit({"limit_type": "GPM", "limit": 1}),
            {},
        )


# ---------------------------------------------------------------------------
# Q. Pages that never state the host country
# ---------------------------------------------------------------------------
GERMAN_PAGE_TEXT = (
    "The Helmut-Schmidt Programme is a scholarship available to Master's "
    "students. See the Current Announcement for details."
)


def _registry_source(country_or_region, source_id="offline-source"):
    return DiscoverySource(
        source_id=source_id,
        name="Offline source",
        official_domain="official.example",
        category="government_scholarship_programme",
        country_or_region=country_or_region,
        source_url="https://official.example/scholarships",
        source_classification="government_authority",
    )


def _countryless_candidate():
    """A Master's scholarship whose page never states the host country."""
    return {
        "values": {
            "name": "Helmut-Schmidt Programme",
            "degree_level": "Master",
        },
        "evidence": {
            "name": "The Helmut-Schmidt Programme",
            "degree_level": "Master's students",
        },
        "host_city": "",
        "masters_only": True,
        "masters_evidence": "Master's students",
        "scholarship_offer_evidence": (
            "The Helmut-Schmidt Programme is a scholarship available"
        ),
    }


class RegistryHostCountryTests(unittest.TestCase):
    def _extract(self, country_or_region, candidate=None, text=GERMAN_PAGE_TEXT):
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(
            return_value=_response(candidate or _countryless_candidate()),
        )
        source = _registry_source(country_or_region)
        return extractor, extractor.extract(_page(text), source)

    # -- the fallback fires ------------------------------------------------
    def test_country_is_filled_from_a_german_registry_entry(self):
        extractor, extracted = self._extract("Germany")

        self.assertEqual(len(extracted), 1)
        candidate = extracted[0]
        self.assertEqual(candidate.values["country"], "Germany")
        self.assertIn(
            "host_country_from_source_registry",
            candidate.review_reasons,
        )
        self.assertTrue(candidate.requires_review)
        # Country is no longer a missing required field.
        self.assertEqual(candidate.missing_required_fields, ())
        self.assertNotIn("missing_scholarship_identity", candidate.review_reasons)
        self.assertEqual(extractor.last_rejected_count, 0)
        self.assertEqual(extractor.last_outcome_status, "candidates_accepted")

    def test_other_single_european_registries_also_work(self):
        for country in ("Austria", "Sweden", "Italy", "Poland", "Hungary"):
            with self.subTest(country=country):
                _extractor_obj, extracted = self._extract(country)
                self.assertEqual(len(extracted), 1)
                self.assertEqual(extracted[0].values["country"], country)

    # -- the fallback does not fire ----------------------------------------
    def test_a_region_registry_entry_does_not_supply_a_country(self):
        for value in ("European Union", "Flanders, Belgium", "Europe", ""):
            with self.subTest(value=value):
                extractor, extracted = self._extract(value)
                # Behaviour unchanged: held for review without a country.
                self.assertEqual(len(extracted), 1)
                self.assertNotIn("country", extracted[0].values)
                self.assertIn(
                    "missing_host_country_evidence",
                    extracted[0].review_reasons,
                )
                self.assertNotIn(
                    "host_country_from_source_registry",
                    extracted[0].review_reasons,
                )
                self.assertEqual(
                    extracted[0].missing_required_fields,
                    ("country",),
                )

    def test_a_multi_country_registry_entry_is_refused(self):
        for value in ("Germany and Austria", "Germany/Austria", "Germany & Austria"):
            with self.subTest(value=value):
                _e, extracted = self._extract(value)
                self.assertNotIn("country", extracted[0].values)
                self.assertNotIn(
                    "host_country_from_source_registry",
                    extracted[0].review_reasons,
                )

    def test_a_transcontinental_registry_entry_is_refused(self):
        # Turkey needs positive host-city and institution evidence, which a
        # registry entry cannot supply.
        _e, extracted = self._extract("Turkey")
        self.assertNotIn("country", extracted[0].values)
        self.assertNotIn(
            "host_country_from_source_registry",
            extracted[0].review_reasons,
        )

    def test_a_non_european_registry_entry_is_refused(self):
        for value in ("Canada", "Japan", "not-a-country"):
            with self.subTest(value=value):
                _e, extracted = self._extract(value)
                self.assertNotIn("country", extracted[0].values)

    # -- the page always wins ----------------------------------------------
    def test_a_page_stated_country_beats_the_registry(self):
        text = (
            "The Nordic Award is a scholarship available to Master's students. "
            "The programme is hosted in Finland."
        )
        candidate = {
            "values": {
                "name": "Nordic Award",
                "country": "Finland",
                "degree_level": "Master",
            },
            "evidence": {
                "name": "The Nordic Award",
                "country": "Finland",
                "degree_level": "Master's students",
                "host_location": "The programme is hosted in Finland",
            },
            "host_city": "",
            "masters_only": True,
            "masters_evidence": "Master's students",
            "scholarship_offer_evidence": (
                "The Nordic Award is a scholarship available"
            ),
        }
        _e, extracted = self._extract("Germany", candidate=candidate, text=text)

        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0].values["country"], "Finland")
        self.assertNotIn(
            "host_country_from_source_registry",
            extracted[0].review_reasons,
        )

    def test_an_unevidenced_model_country_is_not_blessed_by_the_registry(self):
        # The model names a country the page never supports. It is kept for
        # review as before, without the registry reason, and the registry
        # country is NOT substituted.
        # No country quote at all: the registry must not step in, and the
        # unevidenced value must not be treated as confirmed.
        candidate = _countryless_candidate()
        candidate["values"]["country"] = "Austria"
        _e, extracted = self._extract("Germany", candidate=candidate)

        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0].values["country"], "Austria")
        self.assertNotIn(
            "host_country_from_source_registry",
            extracted[0].review_reasons,
        )
        # Held for review for the missing evidence, exactly as before.
        self.assertIn(
            "missing_host_location_evidence",
            extracted[0].review_reasons,
        )
        self.assertIn("missing_evidence:country", extracted[0].review_reasons)
        self.assertTrue(extracted[0].requires_review)

    def test_a_model_country_quote_absent_from_the_page_is_rejected(self):
        # Unchanged strictness: a quote that is not on the page rejects the
        # candidate, registry country or not.
        candidate = _countryless_candidate()
        candidate["values"]["country"] = "Austria"
        candidate["evidence"]["country"] = "Austria"
        extractor, extracted = self._extract("Germany", candidate=candidate)

        self.assertEqual(extracted, [])
        self.assertIn(
            "evidence_mismatch:country",
            extractor.last_rejection_detail_counts,
        )

    def test_an_unmatched_host_location_quote_is_dropped_under_the_registry(self):
        # The country came from the reviewed registry, so a bad host-location
        # quote is not load-bearing: drop it instead of discarding the
        # scholarship. (With a page-stated country it still rejects; see
        # OptionalEvidenceMismatchTests.)
        candidate = _countryless_candidate()
        candidate["evidence"]["host_location"] = "Hosted in Germany at all times"
        extractor, extracted = self._extract("Germany", candidate=candidate)

        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0].values["country"], "Germany")
        self.assertEqual(extractor.last_rejected_count, 0)
        self.assertEqual(extractor.last_rejection_detail_counts, {})
        self.assertIn("host_location", extracted[0].dropped_evidence_fields)
        self.assertIn(
            "evidence_mismatch_fields_dropped",
            extracted[0].review_reasons,
        )
        self.assertEqual(
            extractor.last_dropped_evidence_counts,
            {"evidence_dropped:host_location": 1},
        )

    def test_the_registry_does_not_relax_other_checks(self):
        # Master's evidence missing from the page is still rejected.
        candidate = _countryless_candidate()
        candidate["masters_evidence"] = "doctoral candidates only"
        extractor, extracted = self._extract("Germany", candidate=candidate)
        self.assertEqual(extracted, [])
        self.assertIn(
            "evidence_mismatch:masters_evidence",
            extractor.last_rejection_detail_counts,
        )

    def test_protected_fields_are_still_rejected_with_a_registry_country(self):
        candidate = _countryless_candidate()
        candidate["values"]["verification_status"] = "verified"
        extractor, extracted = self._extract("Germany", candidate=candidate)
        self.assertEqual(extracted, [])
        self.assertEqual(
            extractor.last_rejection_detail_counts,
            {"protected_field": 1},
        )

    def test_a_country_needing_a_host_city_is_flagged_for_review(self):
        # France requires a host city to tell European from overseas campuses.
        _e, extracted = self._extract("France")
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0].values["country"], "France")
        self.assertIn(
            "host_location_requires_review",
            extracted[0].review_reasons,
        )

    # -- the helper itself --------------------------------------------------
    def test_registry_host_country_helper(self):
        from app.services.scholarship_discovery_extraction import (
            _registry_host_country,
        )

        for value, expected in (
            ("Germany", "Germany"),
            ("  Germany  ", "Germany"),
            ("Sweden", "Sweden"),
            ("European Union", None),
            ("Flanders, Belgium", None),
            ("Germany and Austria", None),
            ("Turkey", None),
            ("Canada", None),
            ("", None),
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    _registry_host_country(_registry_source(value)),
                    expected,
                )

    # -- the prompt ---------------------------------------------------------
    def test_prompt_includes_registry_host_country_only_when_valid(self):
        extractor = _extractor()
        for value, expected in (
            ("Germany", True),
            ("Sweden", True),
            ("European Union", False),
            ("Flanders, Belgium", False),
            ("Turkey", False),
            ("Canada", False),
        ):
            with self.subTest(value=value):
                source = _registry_source(value)
                prompt = extractor._prompt(_page(), source, False)
                payload = _prompt_payload(prompt)
                if expected:
                    self.assertEqual(payload["registry_host_country"], value)
                else:
                    self.assertNotIn("registry_host_country", payload)

    def test_prompt_tells_the_model_to_include_a_countryless_scholarship(self):
        extractor = _extractor()
        prompt = extractor._prompt(_page(), _registry_source("Germany"), False)
        self.assertIn(
            "If the page names a scholarship for Master's study but does not "
            "state the host country, still include it: leave values.country "
            "empty and host_location evidence empty. Do not guess the country.",
            prompt,
        )


# ---------------------------------------------------------------------------
# R. Announcement and own-domain PDF links are crawled first
# ---------------------------------------------------------------------------
class AnnouncementLinkPriorityTests(unittest.TestCase):
    def _priority(self, href, label, official_domain="official.example"):
        from app.services.scholarship_discovery_fetch import _link_priority

        source = _registry_source("Germany")
        source = DiscoverySource(
            source_id="offline-source",
            name="Offline source",
            official_domain=official_domain,
            category="government_scholarship_programme",
            country_or_region="Germany",
            source_url="https://official.example/scholarships",
            source_classification="government_authority",
        )
        return _link_priority(source, urllib.parse.urlsplit(href), label)

    def test_announcement_labels_and_paths_are_strong_signals(self):
        cases = (
            ("https://official.example/files/doc.pdf", "Current Announcement"),
            ("https://official.example/announcement", "Details"),
            ("https://official.example/ausschreibung", "Mehr"),
            ("https://official.example/x", "Call for applications"),
            ("https://official.example/x", "AUSSCHREIBUNG 2026"),
        )
        for href, label in cases:
            with self.subTest(href=href, label=label):
                self.assertLessEqual(self._priority(href, label), 1)

    def test_own_domain_pdfs_are_strong_signals(self):
        self.assertEqual(
            self._priority("https://official.example/files/call.pdf", "Download"),
            1,
        )

    def test_pdfs_on_another_domain_are_not_promoted(self):
        self.assertEqual(
            self._priority("https://cdn.elsewhere.test/call.pdf", "Download"),
            3,
        )

    def test_generic_and_strong_terms_keep_their_order(self):
        self.assertEqual(
            self._priority("https://official.example/scholarship/x", "Scholarship"),
            2,
        )
        self.assertEqual(
            self._priority("https://official.example/about", "About us"),
            3,
        )

    def test_source_pattern_still_outranks_an_announcement(self):
        from app.services.scholarship_discovery_fetch import _link_priority

        daad = DiscoverySource(
            source_id="daad",
            name="DAAD",
            official_domain="official.example",
            category="government_scholarship_programme",
            country_or_region="Germany",
            source_url="https://official.example/scholarships",
            source_classification="government_authority",
        )
        database = _link_priority(
            daad,
            urllib.parse.urlsplit("https://official.example/db/x?detail=42"),
            "Entry",
        )
        announcement = _link_priority(
            daad,
            urllib.parse.urlsplit("https://official.example/a.pdf"),
            "Current Announcement",
        )
        self.assertLess(database, announcement)

    def test_announcement_links_are_fetched_before_generic_links(self):
        pages = {
            "/scholarships": (
                b"<p>Official scholarship information.</p>"
                b"<a href='/scholarships/generic'>Scholarship details</a>"
                b"<a href='/files/call.pdf'>Current Announcement</a>"
            ),
            "/scholarships/generic": b"<p>Generic scholarship page.</p>",
            "/files/call.pdf": b"<p>Announcement page.</p>",
        }
        fetcher = OfficialSourceFetcher(
            _crawl_settings(max_pages_per_source=2),
            max_crawl_depth=1,
        )
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"
        requested = []

        def fake_fetch_bytes(_src, url, allowed_types=None, *, on_request_attempt=None):
            requested.append(url)
            if on_request_attempt is not None:
                on_request_attempt()
            split = urllib.parse.urlsplit(url)
            key = split.path
            if key not in pages:
                raise DiscoveryFetchError("not found", status_code=404)
            return url, headers, pages[key]

        with patch.object(fetcher, "_robots_allowed", return_value=True):
            with patch.object(fetcher, "_fetch_bytes", side_effect=fake_fetch_bytes):
                fetcher.crawl(_registry_source("Germany"))

        # Only two pages are fetched: the root, then the announcement PDF.
        self.assertEqual(
            requested,
            [
                "https://official.example/scholarships",
                "https://official.example/files/call.pdf",
            ],
        )

    def test_an_announcement_link_bypasses_the_relevance_filter(self):
        # "/files/call.pdf" labelled "Current Announcement" contains no
        # generic relevant term, so it would otherwise be skipped.
        pages = {
            "/scholarships": (
                b"<p>Official scholarship information.</p>"
                b"<a href='/files/call.pdf'>Current Announcement</a>"
            ),
            "/files/call.pdf": b"<p>Announcement page.</p>",
        }
        fetcher = OfficialSourceFetcher(
            _crawl_settings(max_pages_per_source=5),
            max_crawl_depth=1,
        )
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"
        requested = []

        def fake_fetch_bytes(_src, url, allowed_types=None, *, on_request_attempt=None):
            requested.append(url)
            if on_request_attempt is not None:
                on_request_attempt()
            split = urllib.parse.urlsplit(url)
            if split.path not in pages:
                raise DiscoveryFetchError("not found", status_code=404)
            return url, headers, pages[split.path]

        with patch.object(fetcher, "_robots_allowed", return_value=True):
            with patch.object(fetcher, "_fetch_bytes", side_effect=fake_fetch_bytes):
                fetcher.crawl(_registry_source("Germany"))

        self.assertIn("https://official.example/files/call.pdf", requested)
        self.assertEqual(
            fetcher.last_crawl_stats["linked_pages_skipped_relevance"],
            0,
        )


# ---------------------------------------------------------------------------
# S. Typographic characters do not break quote matching
# ---------------------------------------------------------------------------
class TypographicQuoteMatchingTests(unittest.TestCase):
    """Folding is symmetric and exact: no fuzzy or partial matching."""

    CURLY_APOSTROPHE = "\u2019"
    CURLY_OPEN = "\u201c"
    CURLY_CLOSE = "\u201d"
    EN_DASH = "\u2013"
    EM_DASH = "\u2014"

    def _matches(self, page_text, quote):
        return _has_quote(_page(page_text), quote)

    def test_straight_apostrophe_matches_a_curly_page(self):
        page_text = (
            f"The Helmut-Schmidt Programme is open to Master{self.CURLY_APOSTROPHE}s "
            "students."
        )
        self.assertTrue(self._matches(page_text, "open to Master's students"))

    def test_curly_apostrophe_matches_a_straight_page(self):
        page_text = "The Programme is open to Master's students."
        quote = f"open to Master{self.CURLY_APOSTROPHE}s students"
        self.assertTrue(self._matches(page_text, quote))

    def test_curly_double_quotes_match_straight_ones_both_ways(self):
        curly = f"The award is {self.CURLY_OPEN}fully funded{self.CURLY_CLOSE} here."
        straight = 'The award is "fully funded" here.'
        self.assertTrue(self._matches(curly, 'is "fully funded" here'))
        self.assertTrue(
            self._matches(
                straight,
                f"is {self.CURLY_OPEN}fully funded{self.CURLY_CLOSE} here",
            ),
        )

    def test_en_and_em_dashes_match_a_hyphen_both_ways(self):
        for dash in (self.EN_DASH, self.EM_DASH, "\u2012", "\u2212"):
            with self.subTest(dash=dash):
                self.assertTrue(
                    self._matches(f"Funded for 2025{dash}2026 only.", "2025-2026"),
                )
                self.assertTrue(
                    self._matches("Funded for 2025-2026 only.", f"2025{dash}2026"),
                )

    def test_other_typographic_characters_are_folded(self):
        cases = (
            ("Apply by 1 Jan\u20262026.", "1 Jan...2026"),      # ellipsis
            ("Award of 1\u00a0000 euro.", "1 000 euro"),         # no-break space
            ("co\u00adfunded award", "cofunded award"),          # soft hyphen
            ("zero\u200bwidth award", "zerowidth award"),        # zero width
            ("the d\u00b4Azur grant", "the d'Azur grant"),       # acute accent
            ("a 3\u2033 margin", 'a 3" margin'),                 # double prime
        )
        for page_text, quote in cases:
            with self.subTest(quote=quote):
                self.assertTrue(self._matches(page_text, quote))

    def test_folding_is_applied_to_the_redacted_text_too(self):
        # The model is shown URL-redacted text; folding must apply there as well.
        page_text = (
            f"Master{self.CURLY_APOSTROPHE}s scholarship. See www.daad.de for more."
        )
        self.assertTrue(
            self._matches(page_text, "Master's scholarship. See [redacted URL] for more"),
        )

    # -- still strict ------------------------------------------------------
    def test_a_quote_with_different_words_is_still_rejected(self):
        page_text = f"Open to Master{self.CURLY_APOSTROPHE}s students in Germany."
        self.assertFalse(self._matches(page_text, "Open to doctoral students in Germany"))
        self.assertFalse(self._matches(page_text, "Open to Master's students in Austria"))

    def test_folding_does_not_enable_partial_or_fuzzy_matching(self):
        page_text = "The Helmut-Schmidt Programme funds Master's study."
        # A quote whose words are all present but reordered must not match.
        self.assertFalse(self._matches(page_text, "Master's study funds the Programme"))
        # A near-miss spelling must not match.
        self.assertFalse(self._matches(page_text, "The Helmut Schmidtt Programme"))
        # An absent sentence must not match.
        self.assertFalse(self._matches(page_text, "The Programme funds doctoral study"))

    def test_letters_are_not_folded_into_each_other(self):
        # Accented letters remain distinct; only punctuation and spacing fold.
        self.assertFalse(self._matches("the Zurich campus", "the Z\u00fcrich campus"))

    def test_normalize_is_idempotent_and_symmetric(self):
        from app.services.scholarship_discovery_extraction import _normalize

        raw = f"Master{self.CURLY_APOSTROPHE}s \u2013 2025\u20132026 {self.CURLY_OPEN}x{self.CURLY_CLOSE}"
        once = _normalize(raw)
        self.assertEqual(_normalize(once), once)
        self.assertEqual(once, _normalize('master\'s - 2025-2026 "x"'))


class TypographicEndToEndTests(unittest.TestCase):
    """The live failure: a curly-apostrophe page and a straight-quote model."""

    def test_curly_apostrophe_page_no_longer_rejects_the_candidate(self):
        curly = "\u2019"
        text = (
            f"The Helmut-Schmidt Programme is a scholarship available to Master{curly}s "
            f"students. Host country: Germany. Master{curly}s applicants only."
        )
        candidate = {
            "values": {
                "name": "Helmut-Schmidt Programme",
                "country": "Germany",
                "degree_level": "Master",
            },
            "evidence": {
                "name": "The Helmut-Schmidt Programme",
                "country": "Germany",
                "degree_level": "Master's students",
                "host_location": "Host country: Germany",
            },
            "host_city": "",
            "masters_only": True,
            # Straight apostrophes, as a model typically emits.
            "masters_evidence": "Master's applicants only",
            "scholarship_offer_evidence": (
                "The Helmut-Schmidt Programme is a scholarship available to Master's students"
            ),
        }
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response(candidate))

        extracted = extractor.extract(_page(text), _source())

        self.assertEqual(len(extracted), 1)
        self.assertEqual(extractor.last_rejected_count, 0)
        self.assertEqual(extractor.last_rejection_detail_counts, {})
        self.assertEqual(extracted[0].values["country"], "Germany")


# ---------------------------------------------------------------------------
# T. Optional evidence mismatches drop the field, not the candidate
# ---------------------------------------------------------------------------
class OptionalEvidenceMismatchTests(unittest.TestCase):
    PAGE_TEXT = (
        "The Finland Master's Scholarship is available to Master's students. "
        "Host country: Finland."
    )

    def _extract(self, values_extra, evidence_extra):
        candidate = _candidate()
        candidate["values"].update(values_extra)
        candidate["evidence"].update(evidence_extra)
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response(candidate))
        return extractor, extractor.extract(_page(self.PAGE_TEXT), _source())

    def test_an_optional_field_with_a_bad_quote_is_dropped_not_rejected(self):
        extractor, extracted = self._extract(
            {"provider": "DAAD"},
            {"provider": "Administered by an agency never named on this page"},
        )

        self.assertEqual(len(extracted), 1)
        candidate = extracted[0]
        self.assertNotIn("provider", candidate.values)
        self.assertNotIn("provider", candidate.evidence)
        self.assertIn("provider", candidate.dropped_evidence_fields)
        self.assertIn(
            "evidence_mismatch_fields_dropped",
            candidate.review_reasons,
        )
        self.assertTrue(candidate.requires_review)
        # Not a rejection.
        self.assertEqual(extractor.last_rejected_count, 0)
        self.assertEqual(extractor.last_rejection_detail_counts, {})
        self.assertEqual(extractor.last_outcome_status, "candidates_accepted")
        self.assertEqual(
            extractor.last_dropped_evidence_counts,
            {"evidence_dropped:provider": 1},
        )

    def test_several_optional_fields_are_each_counted(self):
        # Both are real optional ScholarshipCreate fields; an invented key
        # would be dropped earlier as unsupported instead.
        extractor, extracted = self._extract(
            {"provider": "DAAD", "funding_type": "Full"},
            {
                "provider": "never on this page at all",
                "funding_type": "also absent from the page",
            },
        )
        self.assertEqual(len(extracted), 1)
        self.assertEqual(
            extracted[0].dropped_evidence_fields,
            ("funding_type", "provider"),
        )
        self.assertEqual(
            extractor.last_dropped_evidence_counts,
            {
                "evidence_dropped:funding_type": 1,
                "evidence_dropped:provider": 1,
            },
        )
        self.assertNotIn("provider", extracted[0].values)
        self.assertNotIn("funding_type", extracted[0].values)
        self.assertEqual(extractor.last_rejected_count, 0)
        # One review reason however many fields were dropped.
        self.assertEqual(
            list(extracted[0].review_reasons).count(
                "evidence_mismatch_fields_dropped",
            ),
            1,
        )

    def test_a_matching_optional_quote_is_kept(self):
        extractor, extracted = self._extract(
            {"provider": "Finland Master's Scholarship"},
            {"provider": "The Finland Master's Scholarship is available"},
        )
        self.assertEqual(len(extracted), 1)
        self.assertEqual(
            extracted[0].values["provider"],
            "Finland Master's Scholarship",
        )
        self.assertEqual(extracted[0].dropped_evidence_fields, ())
        self.assertEqual(extractor.last_dropped_evidence_counts, {})

    # -- required items still reject ---------------------------------------
    def _reject_case(self, mutate):
        candidate = _candidate()
        mutate(candidate)
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response(candidate))
        return extractor, extractor.extract(_page(self.PAGE_TEXT), _source())

    def test_a_bad_name_quote_still_rejects(self):
        def mutate(candidate):
            candidate["evidence"]["name"] = "A scholarship name not on the page"

        extractor, extracted = self._reject_case(mutate)
        self.assertEqual(extracted, [])
        self.assertEqual(
            extractor.last_rejection_detail_counts,
            {"evidence_mismatch:name": 1},
        )
        self.assertEqual(extractor.last_dropped_evidence_counts, {})

    def test_a_bad_country_quote_still_rejects(self):
        def mutate(candidate):
            candidate["evidence"]["country"] = "Hosted somewhere else entirely"

        extractor, extracted = self._reject_case(mutate)
        self.assertEqual(extracted, [])
        self.assertEqual(
            extractor.last_rejection_detail_counts,
            {"evidence_mismatch:country": 1},
        )

    def test_a_bad_degree_level_quote_still_rejects(self):
        def mutate(candidate):
            candidate["evidence"]["degree_level"] = "Doctoral candidates welcome"

        extractor, extracted = self._reject_case(mutate)
        self.assertEqual(extracted, [])
        self.assertEqual(
            extractor.last_rejection_detail_counts,
            {"evidence_mismatch:degree_level": 1},
        )

    def test_a_bad_scholarship_offer_quote_still_rejects(self):
        def mutate(candidate):
            candidate["scholarship_offer_evidence"] = (
                "A funding offer that the page never makes"
            )

        extractor, extracted = self._reject_case(mutate)
        self.assertEqual(extracted, [])
        self.assertEqual(
            extractor.last_rejection_detail_counts,
            {"evidence_mismatch:scholarship_offer_evidence": 1},
        )

    def test_a_bad_masters_evidence_quote_still_rejects(self):
        def mutate(candidate):
            candidate["masters_evidence"] = "Master's wording absent from the page"

        extractor, extracted = self._reject_case(mutate)
        self.assertEqual(extracted, [])
        self.assertEqual(
            extractor.last_rejection_detail_counts,
            {"evidence_mismatch:masters_evidence": 1},
        )

    def test_a_bad_host_location_quote_still_rejects_without_the_registry(self):
        # _source() has country_or_region "test", so no registry fallback.
        def mutate(candidate):
            candidate["evidence"]["host_location"] = "Hosted in a place not on the page"

        extractor, extracted = self._reject_case(mutate)
        self.assertEqual(extracted, [])
        self.assertEqual(
            extractor.last_rejection_detail_counts,
            {"evidence_mismatch:host_location": 1},
        )

    def test_a_bad_host_city_quote_still_rejects(self):
        def mutate(candidate):
            candidate["host_city"] = "Helsinki"
            candidate["evidence"]["host_city"] = "Located in a city not on the page"

        extractor, extracted = self._reject_case(mutate)
        self.assertEqual(extracted, [])
        self.assertEqual(
            extractor.last_rejection_detail_counts,
            {"evidence_mismatch:host_city": 1},
        )

    def test_a_protected_field_still_rejects(self):
        def mutate(candidate):
            candidate["values"]["verification_status"] = "verified"

        extractor, extracted = self._reject_case(mutate)
        self.assertEqual(extracted, [])
        self.assertEqual(
            extractor.last_rejection_detail_counts,
            {"protected_field": 1},
        )


class DroppedEvidenceDiagnosticsTests(unittest.TestCase):
    def test_report_shows_field_names_and_no_quotes(self):
        import importlib

        module = importlib.import_module("diagnose_single_source_extraction")
        candidate = _candidate()
        candidate["values"]["provider"] = "DAAD"
        candidate["evidence"]["provider"] = "A sentence that is not on the page"
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response(candidate))
        extracted = extractor.extract(_page(), _source())

        report = module._sanitize_candidate_diagnostics(
            extractor,
            extractor.last_provider_diagnostics,
            len(extracted),
        )
        self.assertEqual(report["dropped_evidence_field_counts"], {"provider": 1})
        # Not counted as a rejection.
        self.assertEqual(report["rejected_candidate_count"], 0)
        self.assertEqual(report["rejection_detail_counts"], {})

        serialized = json.dumps(report)
        for leaked in (
            "A sentence that is not on the page",
            "Finland Master's Scholarship",
            FINLAND_TEXT,
        ):
            self.assertNotIn(leaked, serialized)

    def test_report_omits_the_key_when_nothing_was_dropped(self):
        import importlib

        module = importlib.import_module("diagnose_single_source_extraction")
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response(_candidate()))
        extracted = extractor.extract(_page(), _source())

        report = module._sanitize_candidate_diagnostics(
            extractor,
            extractor.last_provider_diagnostics,
            len(extracted),
        )
        self.assertNotIn("dropped_evidence_field_counts", report)

    def test_report_filters_malformed_field_names(self):
        import importlib

        module = importlib.import_module("diagnose_single_source_extraction")
        self.assertEqual(
            module._safe_dropped_evidence_counts({
                "evidence_dropped:provider": 2,
                "evidence_dropped:a whole page sentence": 1,
                "Bad-Name": 3,
                "evidence_dropped:ok_field": -1,
            }),
            {"provider": 2},
        )
        self.assertEqual(module._safe_dropped_evidence_counts(None), {})


# ---------------------------------------------------------------------------
# U. Non-breaking hyphen folding
# ---------------------------------------------------------------------------
class NonBreakingHyphenTests(unittest.TestCase):
    NB_HYPHEN = "\u2011"

    def test_non_breaking_hyphen_matches_an_ascii_hyphen_both_ways(self):
        page_text = (
            f"The Helmut{self.NB_HYPHEN}Schmidt Programme funds Master's study."
        )
        self.assertTrue(
            _has_quote(_page(page_text), "The Helmut-Schmidt Programme"),
        )
        plain = "The Helmut-Schmidt Programme funds Master's study."
        self.assertTrue(
            _has_quote(
                _page(plain),
                f"The Helmut{self.NB_HYPHEN}Schmidt Programme",
            ),
        )

    def test_non_breaking_hyphen_is_folded_by_normalize(self):
        from app.services.scholarship_discovery_extraction import _normalize

        self.assertEqual(
            _normalize(f"2025{self.NB_HYPHEN}2026"),
            _normalize("2025-2026"),
        )

    def test_folding_still_distinguishes_different_words(self):
        page_text = f"The Helmut{self.NB_HYPHEN}Schmidt Programme."
        self.assertFalse(_has_quote(_page(page_text), "The Helmut-Kohl Programme"))


class LoggedDaadEvidenceRegressionTests(unittest.TestCase):
    def test_logged_masters_evidence_quote_is_accepted_from_its_page_line(self):
        title = (
            "Helmut-Schmidt-Programme (Master\u00c6s Scholarships for Public Policy "
            "and Good Governance - PPGG)"
        )
        candidate = {
            "values": {"name": title, "degree_level": "Master"},
            "evidence": {"name": title, "degree_level": title},
            "host_city": "",
            "masters_only": True,
            "masters_evidence": title,
            "scholarship_offer_evidence": title,
        }

        extracted = _validate_candidate(
            candidate,
            _page(f"{title} - DAAD - Deutscher Akademischer Austauschdienst"),
            _registry_source("Germany", source_id="daad-helmut-schmidt"),
        )

        self.assertEqual(extracted.values["name"], title)


# ---------------------------------------------------------------------------
# V. Unapproved evidence URLs are dropped, never stored
# ---------------------------------------------------------------------------
class UnapprovedUrlDropTests(unittest.TestCase):
    PAGE_TEXT = (
        "The Finland Master's Scholarship is available to Master's students. "
        "Host country: Finland."
    )
    APPROVED = "https://official.example/apply"
    UNAPPROVED = "https://attacker.test/apply"

    def _extract(self, values_extra, links=()):
        candidate = _candidate()
        candidate["values"].update(values_extra)
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response(candidate))
        page = _page(self.PAGE_TEXT, links=links)
        return extractor, extractor.extract(page, _source())

    # -- official_application_url ------------------------------------------
    def test_an_unapproved_application_url_is_dropped_not_rejected(self):
        extractor, extracted = self._extract(
            {"official_application_url": self.UNAPPROVED},
            links=((self.UNAPPROVED, "Apply"),),
        )

        self.assertEqual(len(extracted), 1)
        candidate = extracted[0]
        self.assertNotIn("official_application_url", candidate.values)
        self.assertEqual(
            candidate.dropped_url_fields,
            ("official_application_url",),
        )
        self.assertIn("unapproved_urls_dropped", candidate.review_reasons)
        self.assertTrue(candidate.requires_review)
        self.assertEqual(extractor.last_rejected_count, 0)
        self.assertEqual(extractor.last_rejection_detail_counts, {})
        self.assertEqual(extractor.last_outcome_status, "candidates_accepted")
        self.assertEqual(
            extractor.last_dropped_evidence_counts,
            {"url_dropped:official_application_url": 1},
        )

    def test_an_approved_application_url_is_kept(self):
        extractor, extracted = self._extract(
            {"official_application_url": self.APPROVED},
            links=((self.APPROVED, "Apply"),),
        )

        self.assertEqual(len(extracted), 1)
        self.assertEqual(
            extracted[0].values["official_application_url"],
            self.APPROVED,
        )
        self.assertEqual(extracted[0].dropped_url_fields, ())
        self.assertNotIn(
            "unapproved_urls_dropped",
            extracted[0].review_reasons,
        )
        self.assertEqual(extractor.last_dropped_evidence_counts, {})

    def test_a_url_absent_from_the_page_links_is_dropped(self):
        # On the source's own domain, but never linked from the page.
        extractor, extracted = self._extract(
            {"official_application_url": "https://official.example/not-linked"},
            links=((self.APPROVED, "Apply"),),
        )
        self.assertEqual(len(extracted), 1)
        self.assertNotIn("official_application_url", extracted[0].values)
        self.assertEqual(
            extractor.last_dropped_evidence_counts,
            {"url_dropped:official_application_url": 1},
        )

    # -- additional_source_urls --------------------------------------------
    def test_unapproved_entries_are_dropped_and_approved_ones_kept(self):
        extractor, extracted = self._extract(
            {"additional_source_urls": [self.APPROVED, self.UNAPPROVED]},
            links=((self.APPROVED, "Apply"), (self.UNAPPROVED, "Elsewhere")),
        )

        self.assertEqual(len(extracted), 1)
        self.assertEqual(
            extracted[0].values["additional_source_urls"],
            [self.APPROVED],
        )
        self.assertEqual(
            extracted[0].dropped_url_fields,
            ("additional_source_urls",),
        )
        self.assertIn("unapproved_urls_dropped", extracted[0].review_reasons)
        self.assertEqual(extractor.last_rejected_count, 0)

    def test_the_field_is_removed_when_every_entry_is_unapproved(self):
        extractor, extracted = self._extract(
            {"additional_source_urls": [self.UNAPPROVED]},
            links=((self.UNAPPROVED, "Elsewhere"),),
        )
        self.assertEqual(len(extracted), 1)
        self.assertNotIn("additional_source_urls", extracted[0].values)
        self.assertEqual(
            extractor.last_dropped_evidence_counts,
            {"url_dropped:additional_source_urls": 1},
        )

    def test_all_approved_entries_are_kept_with_no_review_reason(self):
        second = "https://official.example/guide"
        extractor, extracted = self._extract(
            {"additional_source_urls": [self.APPROVED, second]},
            links=((self.APPROVED, "Apply"), (second, "Guide")),
        )
        self.assertEqual(
            extracted[0].values["additional_source_urls"],
            [self.APPROVED, second],
        )
        self.assertEqual(extracted[0].dropped_url_fields, ())
        self.assertEqual(extractor.last_dropped_evidence_counts, {})

    # -- nothing unapproved is ever stored ---------------------------------
    def test_an_unapproved_url_never_reaches_values_or_evidence(self):
        for deceptive in (
            "https://attacker.test/apply",
            "https://official.example.attacker.test/apply",
            "https://user:pass@official.example/apply",
        ):
            with self.subTest(url=deceptive):
                _extractor_obj, extracted = self._extract(
                    {"official_application_url": deceptive},
                    links=((deceptive, "Apply"),),
                )
                self.assertEqual(len(extracted), 1)
                kept = json.dumps(extracted[0].values) + json.dumps(
                    extracted[0].evidence,
                )
                self.assertNotIn("attacker", kept)
                self.assertNotIn("user:pass", kept)

    def test_a_safe_reason_is_logged_without_the_url(self):
        candidate = _candidate()
        candidate["values"]["official_application_url"] = self.UNAPPROVED
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response(candidate))
        page = _page(self.PAGE_TEXT, links=((self.UNAPPROVED, "Apply"),))

        with self.assertLogs(
            "app.services.scholarship_discovery_extraction",
            level="WARNING",
        ) as logs:
            extractor.extract(page, _source())

        logged = chr(10).join(logs.output)
        self.assertIn("invalid_evidence_url", logged)
        self.assertIn("field=official_application_url", logged)
        self.assertNotIn(self.UNAPPROVED, logged)
        self.assertNotIn("attacker", logged)

    # -- the strict cases stay strict --------------------------------------
    def test_an_invalid_source_url_still_rejects(self):
        # An off-domain page URL is refused outright. Checked against
        # _validate_candidate directly, because _prompt also guards it and
        # would otherwise fail the request before any candidate is validated.
        from app.services.scholarship_discovery_extraction import InvalidEvidenceURL

        page = _page(self.PAGE_TEXT, url="https://attacker.test/scholarships")
        with self.assertRaises(InvalidEvidenceURL) as raised:
            _validate_candidate(_candidate(), page, _source())
        self.assertEqual(
            raised.exception.rejection_detail,
            "invalid_evidence_url:source_url",
        )

    def test_an_off_domain_page_is_refused_before_the_provider_call(self):
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response(_candidate()))
        page = _page(self.PAGE_TEXT, url="https://attacker.test/scholarships")

        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor.extract(page, _source())
        self.assertEqual(raised.exception.category, "invalid_source_url")
        extractor._generate_groq.assert_not_called()

    def test_a_non_list_additional_source_urls_still_rejects(self):
        # A shape violation, not a failed approved-link check.
        extractor, extracted = self._extract(
            {"additional_source_urls": self.APPROVED},
            links=((self.APPROVED, "Apply"),),
        )
        self.assertEqual(extracted, [])
        self.assertEqual(
            extractor.last_rejection_detail_counts,
            {"invalid_evidence_url:not_list": 1},
        )

    def test_a_third_party_listing_still_strips_the_links(self):
        from dataclasses import replace

        candidate = _candidate()
        candidate["values"]["official_application_url"] = self.APPROVED
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response(candidate))
        listing = replace(_source(), source_classification="trusted_listing")
        page = _page(self.PAGE_TEXT, links=((self.APPROVED, "Apply"),))

        extracted = extractor.extract(page, listing)
        self.assertEqual(len(extracted), 1)
        self.assertNotIn("official_application_url", extracted[0].values)
        self.assertIn(
            "third_party_application_link_unverified",
            extracted[0].review_reasons,
        )
        # Unverified is a separate reason from unapproved.
        self.assertNotIn(
            "unapproved_urls_dropped",
            extracted[0].review_reasons,
        )

    # -- diagnostics --------------------------------------------------------
    def test_the_diagnostic_report_shows_the_dropped_url_field(self):
        import importlib

        module = importlib.import_module("diagnose_single_source_extraction")
        extractor, extracted = self._extract(
            {"official_application_url": self.UNAPPROVED},
            links=((self.UNAPPROVED, "Apply"),),
        )
        report = module._sanitize_candidate_diagnostics(
            extractor,
            extractor.last_provider_diagnostics,
            len(extracted),
        )
        self.assertEqual(
            report["dropped_evidence_field_counts"],
            {"official_application_url": 1},
        )
        self.assertEqual(report["rejected_candidate_count"], 0)
        self.assertEqual(report["rejection_detail_counts"], {})

        serialized = json.dumps(report)
        self.assertNotIn("attacker", serialized)
        self.assertNotIn(self.UNAPPROVED, serialized)

    def test_the_diagnostic_strips_both_code_prefixes(self):
        import importlib

        module = importlib.import_module("diagnose_single_source_extraction")
        self.assertEqual(
            module._safe_dropped_evidence_counts({
                "url_dropped:official_application_url": 1,
                "evidence_dropped:provider": 2,
            }),
            {"official_application_url": 1, "provider": 2},
        )


# ---------------------------------------------------------------------------
# W. Pydantic failures are reported as field + error type, never values
# ---------------------------------------------------------------------------
SECRET_VALUE = "three point five SECRETVALUE"


def _schema_failing_candidate():
    """A candidate whose typed fields cannot be parsed."""
    candidate = _candidate()
    candidate["values"]["min_gpa"] = SECRET_VALUE
    candidate["values"]["min_age"] = "twenty one SECRETAGE"
    candidate["evidence"]["min_gpa"] = "The Finland Master's Scholarship is available"
    candidate["evidence"]["min_age"] = "The Finland Master's Scholarship is available"
    return candidate


class SchemaErrorCodeTests(unittest.TestCase):
    """Codes are recorded when a candidate is REJECTED on schema grounds.

    Optional fields in an unusable format are now repaired or dropped (see
    FormatRepairTests), so a rejection needs a required field at fault.
    Required fields carry no extra schema constraints today, so the failure is
    driven with a real ValidationError that blames `name` and `country` and
    whose inputs are secrets, proving no input value is ever copied.
    """

    SECRET_INPUTS = ("SECRET_NAME_VALUE", "SECRET_COUNTRY_VALUE")

    def _blaming_error(self):
        from pydantic import BaseModel, ValidationError

        class _Probe(BaseModel):
            name: int
            country: int

        try:
            _Probe.model_validate({
                "name": self.SECRET_INPUTS[0],
                "country": self.SECRET_INPUTS[1],
            })
        except ValidationError as exc:
            return exc
        raise AssertionError("expected a ValidationError")

    def _extract(self):
        from app.services import scholarship_discovery_extraction as extraction

        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response(_candidate()))
        failing = Mock(side_effect=self._blaming_error())
        with patch.object(
            extraction.ScholarshipCreate, "model_validate", failing,
        ):
            extracted = extractor.extract(_page(), _source())
        return extractor, extracted

    def test_field_and_error_type_are_recorded(self):
        extractor, extracted = self._extract()

        self.assertEqual(extracted, [])
        self.assertEqual(
            extractor.last_rejection_detail_counts,
            {"schema_validation_failed": 1},
        )
        self.assertEqual(
            extractor.last_schema_error_counts,
            {
                "schema:name:int_parsing": 1,
                "schema:country:int_parsing": 1,
            },
        )

    def test_an_invalid_optional_field_is_dropped_instead(self):
        # The counterpart: optional fields no longer reach a rejection.
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(
            return_value=_response(_schema_failing_candidate()),
        )
        extracted = extractor.extract(_page(), _source())

        self.assertEqual(len(extracted), 1)
        self.assertEqual(extractor.last_rejected_count, 0)
        self.assertEqual(extractor.last_schema_error_counts, {})
        self.assertEqual(
            extracted[0].dropped_invalid_fields,
            ("min_age", "min_gpa"),
        )
        self.assertEqual(
            extractor.last_dropped_evidence_counts,
            {
                "invalid_dropped:min_age": 1,
                "invalid_dropped:min_gpa": 1,
            },
        )

    def test_no_input_value_or_message_is_recorded(self):
        extractor, _extracted = self._extract()
        serialized = json.dumps(extractor.last_schema_error_counts)
        for leaked in self.SECRET_INPUTS:
            self.assertNotIn(leaked, serialized)
        # Pydantic's prose message must not be kept either.
        self.assertNotIn("Input should be", serialized)
        self.assertNotIn("valid number", serialized)

    def test_codes_are_identifier_shaped_and_capped(self):
        from app.services.scholarship_discovery_extraction import (
            MAX_SCHEMA_ERROR_CODES,
            _is_safe_schema_error_code,
        )

        extractor, _extracted = self._extract()
        self.assertLessEqual(
            len(extractor.last_schema_error_counts),
            MAX_SCHEMA_ERROR_CODES,
        )
        for code in extractor.last_schema_error_counts:
            self.assertTrue(_is_safe_schema_error_code(code), code)
            self.assertRegex(
                code,
                r"\Aschema:[a-z_][a-z0-9_]{0,60}:[a-z_][a-z0-9_]{0,60}\Z",
            )

    def test_malformed_codes_are_refused(self):
        from app.services.scholarship_discovery_extraction import (
            ScholarshipExtractionError,
            _is_safe_schema_error_code,
        )

        for bad in (
            "schema:min_gpa",
            "schema:min_gpa:float parsing",
            "schema:Min_GPA:float_parsing",
            "other:min_gpa:float_parsing",
            "schema:min_gpa:float_parsing:extra",
            None,
            123,
        ):
            with self.subTest(code=bad):
                self.assertFalse(_is_safe_schema_error_code(bad))
        error = ScholarshipExtractionError(
            "x",
            schema_error_codes=("schema:ok_field:int_parsing", "garbage"),
        )
        self.assertEqual(
            error.schema_error_codes,
            ("schema:ok_field:int_parsing",),
        )

    def test_a_clean_candidate_records_no_schema_errors(self):
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response(_candidate()))
        extractor.extract(_page(), _source())
        self.assertEqual(extractor.last_schema_error_counts, {})

    def test_the_diagnostic_reports_schema_error_fields(self):
        import importlib

        module = importlib.import_module("diagnose_single_source_extraction")
        extractor, extracted = self._extract()
        report = module._sanitize_candidate_diagnostics(
            extractor,
            extractor.last_provider_diagnostics,
            len(extracted),
        )
        self.assertEqual(
            report["schema_error_fields"],
            {"country: int_parsing": 1, "name: int_parsing": 1},
        )
        serialized = json.dumps(report)
        for leaked in self.SECRET_INPUTS:
            self.assertNotIn(leaked, serialized)

    def test_the_diagnostic_omits_the_key_when_there_are_none(self):
        import importlib

        module = importlib.import_module("diagnose_single_source_extraction")
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response(_candidate()))
        extracted = extractor.extract(_page(), _source())
        report = module._sanitize_candidate_diagnostics(
            extractor,
            extractor.last_provider_diagnostics,
            len(extracted),
        )
        self.assertNotIn("schema_error_fields", report)

    def test_the_diagnostic_filters_malformed_codes(self):
        import importlib

        module = importlib.import_module("diagnose_single_source_extraction")
        self.assertEqual(
            module._safe_schema_error_counts({
                "schema:min_gpa:float_parsing": 2,
                "schema:bad field:x": 1,
                "not a code": 5,
                "schema:ok:ok": -1,
            }),
            {"min_gpa: float_parsing": 2},
        )
        self.assertEqual(module._safe_schema_error_counts(None), {})


# ---------------------------------------------------------------------------
# X. --show-evidence is opt-in, stdout only, never logged
# ---------------------------------------------------------------------------
class ShowEvidenceFlagTests(unittest.TestCase):
    PAGE_TEXT = (
        "The Finland Master's Scholarship is available to Master's students.\n"
        "Host country: Finland.\n"
        "Applications are administered by the national agency.\n"
    )
    BAD_QUOTE = "administered by some other agency entirely"

    def _module(self):
        import importlib

        return importlib.import_module("diagnose_single_source_extraction")

    def _candidate_with_bad_optional_quote(self):
        candidate = _candidate()
        candidate["values"]["provider"] = "Agency"
        candidate["evidence"]["provider"] = self.BAD_QUOTE
        return candidate

    # -- the collector ------------------------------------------------------
    def _collect(self):
        from app.services import scholarship_discovery_extraction as extraction

        module = self._module()
        collector = module.EvidenceCollector()
        restore = module._install_evidence_collector(collector, lambda: 1)
        try:
            result = extraction._validate_candidate(
                self._candidate_with_bad_optional_quote(),
                _page(self.PAGE_TEXT),
                _source(),
            )
        finally:
            restore()
        return module, collector, result

    def test_a_dropped_field_is_collected_with_the_closest_page_line(self):
        _module, collector, result = self._collect()

        self.assertEqual(result.dropped_evidence_fields, ("provider",))
        self.assertEqual(len(collector.items), 1)
        item = collector.items[0]
        self.assertEqual(item["field"], "provider")
        self.assertEqual(item["outcome"], "dropped_evidence_mismatch")
        self.assertEqual(item["model_quote"], self.BAD_QUOTE)
        self.assertEqual(
            item["closest_page_line"],
            "Applications are administered by the national agency.",
        )

    def test_the_validator_is_restored_afterwards(self):
        from app.services import scholarship_discovery_extraction as extraction

        before = extraction._validate_candidate
        self._collect()
        self.assertIs(extraction._validate_candidate, before)

    def test_a_rejected_candidate_is_collected(self):
        from app.services import scholarship_discovery_extraction as extraction

        module = self._module()
        candidate = _candidate()
        candidate["evidence"]["name"] = "A name that is nowhere on this page"
        collector = module.EvidenceCollector()
        restore = module._install_evidence_collector(collector, lambda: 2)
        try:
            with self.assertRaises(ScholarshipExtractionError):
                extraction._validate_candidate(
                    candidate,
                    _page(self.PAGE_TEXT),
                    _source(),
                )
        finally:
            restore()

        self.assertEqual(len(collector.items), 1)
        self.assertEqual(collector.items[0]["field"], "name")
        self.assertEqual(collector.items[0]["outcome"], "rejected")
        self.assertEqual(collector.items[0]["page_index"], 2)

    def test_text_is_clipped_and_items_are_capped(self):
        module = self._module()
        self.assertEqual(len(module._clip("x" * 500)), 300)
        self.assertTrue(module._clip("x" * 500).endswith("\u2026"))
        self.assertEqual(module._clip(None), "")
        collector = module.EvidenceCollector()
        for index in range(module.MAX_SHOWN_EVIDENCE_ITEMS + 10):
            collector.record(1, "provider", "q", "rejected", "page")
        self.assertEqual(
            len(collector.items),
            module.MAX_SHOWN_EVIDENCE_ITEMS,
        )

    def test_a_malformed_field_name_is_not_collected(self):
        module = self._module()
        collector = module.EvidenceCollector()
        collector.record(1, "Not A Field", "q", "rejected", "page")
        collector.record(1, "", "q", "rejected", "page")
        self.assertEqual(collector.items, [])

    def test_no_overlapping_line_is_reported_as_such(self):
        module = self._module()
        collector = module.EvidenceCollector()
        collector.record(1, "provider", "zzz qqq", "rejected", "unrelated text")
        self.assertEqual(collector.items[0]["closest_page_line"], "")
        self.assertIn("no overlap found", collector.render())

    # -- the CLI ------------------------------------------------------------
    def _run_cli(self, argv, result, collector_probe=None):
        """Run main() capturing stdout, stderr and logging separately."""
        import contextlib

        module = self._module()
        stdout, stderr = io.StringIO(), io.StringIO()
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        root = logging.getLogger()
        previous_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)

        def fake_run(source_id, *, evidence_collector=None):
            if collector_probe is not None and evidence_collector is not None:
                collector_probe(evidence_collector)
            return result

        try:
            with contextlib.redirect_stdout(stdout):
                with contextlib.redirect_stderr(stderr):
                    code = module.main(argv, run_diagnostic_fn=fake_run)
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)
        return code, stdout.getvalue(), stderr.getvalue(), log_stream.getvalue()

    def test_without_the_flag_no_quote_or_page_text_appears(self):
        module = self._module()
        result = {"status": "completed", "source_id": "offline-source"}
        code, out, _err, logged = self._run_cli(
            ["offline-source", "--confirm", module.CONFIRM_TOKEN],
            result,
        )
        self.assertEqual(code, 0)
        # Output is exactly the JSON document, nothing else.
        self.assertEqual(out.strip(), json.dumps(result, ensure_ascii=False))
        for leaked in (self.BAD_QUOTE, self.PAGE_TEXT.strip(), "WARNING:"):
            self.assertNotIn(leaked, out)
            self.assertNotIn(leaked, logged)

    def test_without_the_flag_the_collector_is_not_created(self):
        module = self._module()
        seen = []
        self._run_cli(
            ["offline-source", "--confirm", module.CONFIRM_TOKEN],
            {"status": "completed"},
            collector_probe=seen.append,
        )
        self.assertEqual(seen, [])

    def test_with_the_flag_quotes_appear_on_stdout_only(self):
        module = self._module()
        result = {"status": "completed", "source_id": "offline-source"}

        def fill(collector):
            collector.record(
                1,
                "provider",
                self.BAD_QUOTE,
                "dropped_evidence_mismatch",
                self.PAGE_TEXT,
            )

        code, out, _err, logged = self._run_cli(
            ["offline-source", "--confirm", module.CONFIRM_TOKEN, "--show-evidence"],
            result,
            collector_probe=fill,
        )
        self.assertEqual(code, 0)
        # The warning is the first line.
        self.assertEqual(out.splitlines()[0], module.SHOW_EVIDENCE_WARNING)
        self.assertIn("do not share", out.casefold())
        # The quote and the matched page line are on stdout.
        self.assertIn(self.BAD_QUOTE, out)
        self.assertIn("administered by the national agency", out)
        self.assertIn("provider", out)
        # And nowhere in logging.
        self.assertNotIn(self.BAD_QUOTE, logged)
        self.assertNotIn("administered by the national agency", logged)

    def test_with_the_flag_the_json_document_is_still_emitted(self):
        module = self._module()
        result = {"status": "completed", "source_id": "offline-source"}
        _code, out, _err, _logged = self._run_cli(
            ["offline-source", "--confirm", module.CONFIRM_TOKEN, "--show-evidence"],
            result,
        )
        self.assertIn(json.dumps(result, ensure_ascii=False), out)
        self.assertIn("No rejected or dropped evidence to show.", out)

    def test_a_bad_confirmation_token_still_shows_nothing(self):
        module = self._module()
        code, out, err, _logged = self._run_cli(
            ["offline-source", "--confirm", "wrong", "--show-evidence"],
            {"status": "completed"},
        )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("confirmation token", err)


# ---------------------------------------------------------------------------
# Y. One pair of wrapping quotation marks is stripped before matching
# ---------------------------------------------------------------------------
class WrappedQuoteStrippingTests(unittest.TestCase):
    PAGE_TEXT = (
        "The Finland Master's Scholarship is available to Master's students.\n"
        "Host country: Finland.\n"
        'The panel said "yes" to every applicant.\n'
    )

    def _strip(self, value):
        from app.services.scholarship_discovery_extraction import (
            _strip_wrapping_quotes,
        )

        return _strip_wrapping_quotes(value)

    def test_each_supported_pair_is_stripped(self):
        cases = (
            ('"Master\'s students"', "Master's students"),
            ("'Master students'", "Master students"),
            ("\u201cHost country: Finland\u201d", "Host country: Finland"),
            ("\u2018Host country: Finland\u2019", "Host country: Finland"),
            ("\u00abAwarded annually\u00bb", "Awarded annually"),
            ("\u201eBewerbung\u201c", "Bewerbung"),
            ("\u201eBewerbung\u201d", "Bewerbung"),
        )
        for wrapped, expected in cases:
            with self.subTest(wrapped=wrapped):
                self.assertEqual(self._strip(wrapped), expected)

    def test_surrounding_whitespace_is_removed(self):
        self.assertEqual(self._strip('   "  padded  "   '), "padded")

    def test_a_doubled_pair_is_left_alone(self):
        # The inner text still holds the same mark, so nothing is stripped:
        # "never strip quotes inside the text" wins over removing a pair.
        self.assertEqual(self._strip('""doubled""'), '""doubled""')

    def test_inner_quotation_marks_are_kept(self):
        for value in (
            'He said "yes" today',
            '"foo" and "bar"',
            'The panel said "yes" to every applicant.',
            "it's a Master's award",
        ):
            with self.subTest(value=value):
                self.assertEqual(self._strip(value), value.strip())

    def test_unbalanced_or_empty_values_are_left_alone(self):
        for value in ('"', '""', "'", "no quotes here", ""):
            with self.subTest(value=value):
                self.assertEqual(self._strip(value), value.strip())

    def test_non_strings_pass_through(self):
        self.assertIsNone(self._strip(None))
        self.assertEqual(self._strip(17), 17)

    # -- end to end ---------------------------------------------------------
    def _extract(self, mutate):
        candidate = _candidate()
        candidate["evidence"]["host_location"] = "Host country: Finland"
        mutate(candidate)
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response(candidate))
        return extractor, extractor.extract(_page(self.PAGE_TEXT), _source())

    def test_a_wrapped_masters_quote_now_matches(self):
        # The live failure: the exact page text, wrapped in double quotes.
        def mutate(candidate):
            candidate["masters_evidence"] = '"Master\'s students"'

        extractor, extracted = self._extract(mutate)
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extractor.last_rejected_count, 0)
        self.assertEqual(extractor.last_rejection_detail_counts, {})

    def test_a_wrapped_offer_quote_now_matches(self):
        def mutate(candidate):
            candidate["scholarship_offer_evidence"] = (
                '\u201cThe Finland Master\'s Scholarship is available\u201d'
            )

        _extractor_obj, extracted = self._extract(mutate)
        self.assertEqual(len(extracted), 1)

    def test_a_wrapped_field_quote_now_matches(self):
        def mutate(candidate):
            candidate["evidence"]["host_location"] = "'Host country: Finland'"

        extractor, extracted = self._extract(mutate)
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extractor.last_rejected_count, 0)

    def test_the_stored_evidence_is_the_unwrapped_text(self):
        def mutate(candidate):
            candidate["evidence"]["host_location"] = '"Host country: Finland"'

        _extractor_obj, extracted = self._extract(mutate)
        self.assertEqual(
            extracted[0].evidence["host_location"],
            "Host country: Finland",
        )

    def test_different_words_still_fail_when_wrapped(self):
        def mutate(candidate):
            candidate["masters_evidence"] = '"doctoral candidates only"'

        extractor, extracted = self._extract(mutate)
        self.assertEqual(extracted, [])
        self.assertIn(
            "evidence_mismatch:masters_evidence",
            extractor.last_rejection_detail_counts,
        )

    def test_a_quote_containing_inner_quotes_still_matches_the_page(self):
        def mutate(candidate):
            candidate["scholarship_offer_evidence"] = (
                'The panel said "yes" to every applicant.'
            )

        extractor, extracted = self._extract(mutate)
        # Rejected only for the offer-wording rule, never for a quote mismatch.
        self.assertNotIn(
            "evidence_mismatch:scholarship_offer_evidence",
            extractor.last_rejection_detail_counts,
        )


# ---------------------------------------------------------------------------
# Z. Prompt format rules, generated from the schema
# ---------------------------------------------------------------------------
class FieldFormatPromptTests(unittest.TestCase):
    def _prompt(self):
        extractor = _extractor()
        return extractor._prompt(_page(), _source(), False)

    def test_the_no_quotation_marks_rule_is_present(self):
        self.assertIn("without quote marks", self._prompt())

    def test_list_fields_are_named_as_arrays(self):
        from app.services.scholarship_discovery_extraction import (
            _field_format_hints,
        )

        prompt = self._prompt()
        list_fields, _enumerated = _field_format_hints()
        self.assertIn("eligible_countries", list_fields)
        self.assertIn("Arrays only:", prompt)
        for field in list_fields:
            self.assertIn(field, prompt)

    def test_allowed_enum_values_are_listed(self):
        prompt = self._prompt()
        self.assertIn("discipline_scope=all|listed|restricted|varies", prompt)
        self.assertIn("not_specified", prompt)

    def test_the_values_come_from_the_annotations_not_a_literal(self):
        from app.services.scholarship_discovery_extraction import (
            _field_format_hints,
        )

        _list_fields, enumerated = _field_format_hints()
        allowed = dict(enumerated)
        self.assertIn("discipline_scope", allowed)
        self.assertEqual(
            set(allowed["discipline_scope"]),
            {"all", "listed", "restricted", "varies", "not_specified"},
        )
        self.assertGreaterEqual(len(enumerated), 10)
        # Every advertised value really is accepted by the schema.
        from app.schemas.opportunity import ScholarshipCreate

        base = {
            "name": "X",
            "country": "Finland",
            "degree_level": "Master",
            "official_info_url": "https://official.example/",
            "source_name": "s",
        }
        for value in allowed["discipline_scope"]:
            with self.subTest(value=value):
                ScholarshipCreate.model_validate(
                    {**base, "discipline_scope": value},
                )

    def test_the_block_can_be_omitted(self):
        extractor = _extractor()
        without = extractor._prompt(
            _page(), _source(), False, include_field_formats=False,
        )
        self.assertNotIn("Arrays only:", without)
        self.assertLess(len(without), len(self._prompt()))

    def test_every_real_source_still_fits_the_token_cap(self):
        # Same guarantee as test_chunk_chars_default_fits_inside_the_token_cap,
        # asserted here with the format block present.
        from app.core.config import scholarship_discovery_settings
        from app.services.scholarship_discovery_sources import SOURCES_BY_ID

        with patch.dict(os.environ, {}):
            for name in ("GROQ_MAX_INPUT_CHARS", "GROQ_MAX_REQUEST_TOKENS"):
                os.environ.pop(name, None)
            settings = scholarship_discovery_settings()
        extractor = GroqScholarshipExtractor(settings, groq_client=Mock())
        chunk = "x" * settings.max_provider_chunk_chars
        worst = 0
        worst_source = None
        for source_id, source in SOURCES_BY_ID.items():
            page = FetchedPage(
                url=source.source_url,
                content_type="text/html",
                text=chunk,
                links=(),
                content_hash="a" * 64,
            )
            tokens = extractor._estimated_request_tokens(
                extractor._prompt(page, source, False),
            )
            if tokens > worst:
                worst, worst_source = tokens, source_id
        self.assertLessEqual(
            worst,
            settings.groq_max_request_tokens,
            f"{worst_source!r} needs {worst} tokens with the format block",
        )


# ---------------------------------------------------------------------------
# AA. Format repair for optional fields
# ---------------------------------------------------------------------------
class FormatRepairTests(unittest.TestCase):
    PAGE_TEXT = (
        "The Finland Master's Scholarship is available to Master's students. "
        "Host country: Finland. "
        "Open to applicants from Ghana, Kenya in any discipline."
    )

    def _extract(self, values_extra, evidence_extra=None):
        candidate = _candidate()
        candidate["values"].update(values_extra)
        candidate["evidence"].update(evidence_extra or {})
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(return_value=_response(candidate))
        return extractor, extractor.extract(_page(self.PAGE_TEXT), _source())

    # -- string -> list -----------------------------------------------------
    def test_a_comma_string_becomes_a_list(self):
        extractor, extracted = self._extract(
            {"eligible_countries": "Ghana, Kenya"},
            {"eligible_countries": "Open to applicants from Ghana, Kenya"},
        )
        self.assertEqual(len(extracted), 1)
        self.assertEqual(
            extracted[0].values["eligible_countries"],
            ["Ghana", "Kenya"],
        )
        # A repair is not a rejection and not a drop.
        self.assertEqual(extractor.last_rejected_count, 0)
        self.assertEqual(extracted[0].dropped_invalid_fields, ())
        self.assertNotIn(
            "invalid_values_dropped",
            extracted[0].review_reasons,
        )

    def test_semicolons_and_stray_separators_are_handled(self):
        extractor, extracted = self._extract(
            {"eligible_countries": " Ghana ; Kenya,, ;"},
            {"eligible_countries": "Open to applicants from Ghana, Kenya"},
        )
        self.assertEqual(
            extracted[0].values["eligible_countries"],
            ["Ghana", "Kenya"],
        )

    def test_a_single_value_string_becomes_a_one_item_list(self):
        _e, extracted = self._extract(
            {"eligible_countries": "Ghana"},
            {"eligible_countries": "Open to applicants from Ghana, Kenya"},
        )
        self.assertEqual(extracted[0].values["eligible_countries"], ["Ghana"])

    def test_a_proper_list_is_untouched(self):
        _e, extracted = self._extract(
            {"eligible_countries": ["Ghana", "Kenya"]},
            {"eligible_countries": "Open to applicants from Ghana, Kenya"},
        )
        self.assertEqual(
            extracted[0].values["eligible_countries"],
            ["Ghana", "Kenya"],
        )

    # -- invalid optional value -> dropped ---------------------------------
    def test_an_invalid_literal_is_dropped_not_rejected(self):
        extractor, extracted = self._extract(
            {"discipline_scope": "any discipline"},
            {"discipline_scope": "in any discipline"},
        )
        self.assertEqual(len(extracted), 1)
        candidate = extracted[0]
        self.assertNotIn("discipline_scope", candidate.values)
        self.assertNotIn("discipline_scope", candidate.evidence)
        self.assertEqual(
            candidate.dropped_invalid_fields,
            ("discipline_scope",),
        )
        self.assertIn("invalid_values_dropped", candidate.review_reasons)
        self.assertTrue(candidate.requires_review)
        self.assertEqual(extractor.last_rejected_count, 0)
        self.assertEqual(extractor.last_rejection_detail_counts, {})
        self.assertEqual(
            extractor.last_dropped_evidence_counts,
            {"invalid_dropped:discipline_scope": 1},
        )

    def test_an_unparsable_number_is_dropped(self):
        extractor, extracted = self._extract(
            {"min_gpa": "three point five"},
            {"min_gpa": "The Finland Master's Scholarship is available"},
        )
        self.assertEqual(len(extracted), 1)
        self.assertNotIn("min_gpa", extracted[0].values)
        self.assertEqual(
            extractor.last_dropped_evidence_counts,
            {"invalid_dropped:min_gpa": 1},
        )

    def test_several_invalid_fields_are_all_dropped(self):
        extractor, extracted = self._extract(
            {
                "discipline_scope": "any discipline",
                "min_age": "twenty one",
            },
            {
                "discipline_scope": "in any discipline",
                "min_age": "The Finland Master's Scholarship is available",
            },
        )
        self.assertEqual(len(extracted), 1)
        self.assertEqual(
            extracted[0].dropped_invalid_fields,
            ("discipline_scope", "min_age"),
        )
        self.assertEqual(
            extractor.last_dropped_evidence_counts,
            {
                "invalid_dropped:discipline_scope": 1,
                "invalid_dropped:min_age": 1,
            },
        )
        self.assertEqual(
            list(extracted[0].review_reasons).count("invalid_values_dropped"),
            1,
        )

    def test_a_valid_literal_is_kept(self):
        _e, extracted = self._extract(
            {"discipline_scope": "all"},
            {"discipline_scope": "in any discipline"},
        )
        self.assertEqual(extracted[0].values["discipline_scope"], "all")
        self.assertEqual(extracted[0].dropped_invalid_fields, ())

    # -- required and protected fields stay strict -------------------------
    def test_an_invalid_required_field_still_rejects(self):
        extractor, extracted = self._extract({"degree_level": 17})
        self.assertEqual(extracted, [])
        self.assertEqual(extractor.last_rejected_count, 1)
        self.assertIn(
            "invalid_value:degree_level",
            extractor.last_rejection_detail_counts,
        )
        self.assertEqual(extractor.last_dropped_evidence_counts, {})

    def test_a_required_field_blamed_by_the_schema_still_rejects(self):
        # Required fields carry no extra schema constraints today, so this
        # branch is driven with a ValidationError that blames `name`.
        from pydantic import BaseModel, ValidationError

        from app.services import scholarship_discovery_extraction as extraction

        class _Probe(BaseModel):
            name: int

        try:
            _Probe.model_validate({"name": "not an int"})
            raise AssertionError("expected a ValidationError")
        except ValidationError as exc:
            blamed = exc

        failing = Mock(side_effect=blamed)
        with patch.object(
            extraction.ScholarshipCreate, "model_validate", failing,
        ):
            with self.assertRaises(ScholarshipExtractionError) as raised:
                extraction._validate_candidate(
                    _candidate(), _page(self.PAGE_TEXT), _source(),
                )
        self.assertEqual(
            raised.exception.rejection_detail,
            "schema_validation_failed",
        )
        self.assertIn(
            "schema:name:int_parsing",
            raised.exception.schema_error_codes,
        )

    def test_a_protected_field_still_rejects(self):
        extractor, extracted = self._extract({"verification_status": "verified"})
        self.assertEqual(extracted, [])
        self.assertEqual(
            extractor.last_rejection_detail_counts,
            {"protected_field": 1},
        )

    def test_repair_passes_are_bounded(self):
        from app.services.scholarship_discovery_extraction import (
            MAX_FORMAT_REPAIR_PASSES,
        )

        self.assertGreaterEqual(MAX_FORMAT_REPAIR_PASSES, 2)
        self.assertLessEqual(MAX_FORMAT_REPAIR_PASSES, 10)

    # -- diagnostics --------------------------------------------------------
    def test_the_diagnostic_shows_the_dropped_invalid_field(self):
        import importlib

        module = importlib.import_module("diagnose_single_source_extraction")
        extractor, extracted = self._extract(
            {"discipline_scope": "any discipline"},
            {"discipline_scope": "in any discipline"},
        )
        report = module._sanitize_candidate_diagnostics(
            extractor,
            extractor.last_provider_diagnostics,
            len(extracted),
        )
        self.assertEqual(
            report["dropped_evidence_field_counts"],
            {"discipline_scope": 1},
        )
        self.assertEqual(report["rejected_candidate_count"], 0)
        serialized = json.dumps(report)
        self.assertNotIn("any discipline", serialized)

    def test_the_diagnostic_strips_the_invalid_dropped_prefix(self):
        import importlib

        module = importlib.import_module("diagnose_single_source_extraction")
        self.assertEqual(
            module._safe_dropped_evidence_counts({
                "invalid_dropped:discipline_scope": 1,
                "evidence_dropped:provider": 2,
                "url_dropped:official_application_url": 1,
            }),
            {
                "discipline_scope": 1,
                "official_application_url": 1,
                "provider": 2,
            },
        )


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main()


GERMAN_COUNTRY_PAGE_TEXT = (
    "The Helmut-Schmidt Programme is a scholarship available to Master's "
    "students. The programme is hosted in Germany at partner universities. "
    "See the Current Announcement for details."
)

# What the model actually returned in diag_run15: two page fragments joined
# with an ellipsis, plus a country name the passage never contains.
STITCHED_HOST_LOCATION_QUOTE = (
    "Helmut-Schmidt-Programme ... DAAD ... Germany"
)


def _stitched_host_location_candidate(country="Germany"):
    values = {"name": "Helmut-Schmidt Programme", "degree_level": "Master"}
    evidence = {
        "name": "The Helmut-Schmidt Programme",
        "degree_level": "Master's students",
        "host_location": STITCHED_HOST_LOCATION_QUOTE,
    }
    if country is not None:
        values["country"] = country
        evidence["country"] = "hosted in Germany"
    return {
        "values": values,
        "evidence": evidence,
        "host_city": "",
        "masters_only": True,
        "masters_evidence": "Master's students",
        "scholarship_offer_evidence": (
            "The Helmut-Schmidt Programme is a scholarship available"
        ),
    }


class StitchedHostLocationQuoteTests(unittest.TestCase):
    """A host_location quote that is not on the page no longer loses the
    candidate when the reviewed registry entry records the host country."""

    def _extract(self, registry_country, candidate=None, text=None):
        extractor = _extractor(groq_max_request_tokens=0)
        extractor._generate_groq = Mock(
            return_value=_response(
                candidate or _stitched_host_location_candidate(),
            ),
        )
        source = _registry_source(registry_country)
        page = _page(GERMAN_COUNTRY_PAGE_TEXT if text is None else text)
        return extractor, extractor.extract(page, source)

    def test_the_registry_country_rescues_an_unquotable_host_location(self):
        extractor, extracted = self._extract("Germany")

        self.assertEqual(len(extracted), 1)
        candidate = extracted[0]
        self.assertEqual(candidate.values["country"], "Germany")
        self.assertIn(
            "host_country_from_source_registry",
            candidate.review_reasons,
        )
        self.assertTrue(candidate.requires_review)
        self.assertEqual(extractor.last_rejected_count, 0)
        self.assertEqual(extractor.last_outcome_status, "candidates_accepted")

    def test_the_bad_quote_is_dropped_and_counted(self):
        extractor, extracted = self._extract("Germany")

        self.assertIn("host_location", extracted[0].dropped_evidence_fields)
        self.assertEqual(
            extractor.last_dropped_evidence_counts,
            {"evidence_dropped:host_location": 1},
        )
        self.assertEqual(extractor.last_rejection_detail_counts, {})

    def test_the_quote_itself_is_never_recorded(self):
        extractor, _extracted = self._extract("Germany")
        serialized = json.dumps({
            "dropped": extractor.last_dropped_evidence_counts,
            "details": extractor.last_rejection_detail_counts,
            "reasons": extractor.last_rejection_reasons,
        })
        for fragment in ("Helmut-Schmidt-Programme ...", "DAAD", "..."):
            self.assertNotIn(fragment, serialized)

    def test_without_a_registry_host_country_it_is_still_rejected(self):
        for value in ("European Union", "Europe", "Germany and Austria", ""):
            with self.subTest(registry=value):
                extractor, extracted = self._extract(value)

                self.assertEqual(extracted, [])
                self.assertEqual(extractor.last_rejected_count, 1)
                self.assertEqual(
                    extractor.last_rejection_detail_counts,
                    {"evidence_mismatch:host_location": 1},
                )

    def test_a_country_absent_from_the_page_is_still_rescued(self):
        # The same path when the model supplied no country at all: the
        # registry fills it and the unquotable host_location is dropped.
        extractor, extracted = self._extract(
            "Germany",
            candidate=_stitched_host_location_candidate(country=None),
        )

        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0].values["country"], "Germany")
        self.assertIn("host_location", extracted[0].dropped_evidence_fields)

    def test_other_evidence_fields_are_not_loosened(self):
        # Only host_location gets this treatment. A name quote that is not on
        # the page still rejects the candidate, registry country or not.
        candidate = _stitched_host_location_candidate()
        candidate["evidence"]["name"] = "A Programme That Is Not On The Page"
        extractor, extracted = self._extract("Germany", candidate=candidate)

        self.assertEqual(extracted, [])
        self.assertEqual(extractor.last_rejected_count, 1)
        self.assertIn(
            "evidence_mismatch:name",
            extractor.last_rejection_detail_counts,
        )


class ContinuousQuoteRuleTests(unittest.TestCase):
    def _prompt(self):
        extractor = _extractor(groq_max_request_tokens=0)
        return extractor._prompt(_page(), _source())

    def test_the_prompt_requires_one_continuous_passage(self):
        prompt = self._prompt()
        self.assertIn("ONE continuous passage copied exactly from the page", prompt)

    def test_the_prompt_forbids_joining_fragments_and_adding_words(self):
        prompt = self._prompt()
        self.assertIn("never join fragments with ...", prompt)
        self.assertIn("never add words the passage does not contain", prompt)

    def test_the_rule_is_stated_once(self):
        # It costs tokens on every request, so it is not repeated.
        self.assertEqual(
            self._prompt().count("ONE continuous passage"),
            1,
        )
