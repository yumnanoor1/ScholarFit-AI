import json
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.scholarship_discovery_extraction import (
    ExtractedScholarship,
    GroqScholarshipExtractor,
    ScholarshipExtractionError,
    MAX_413_RECOVERY_LEVELS,
    MAX_413_RECOVERY_SUB_CHUNKS,
    MIN_PROVIDER_CHUNK_CHARS,
    _strict_extraction_schema,
    _deduplicate_extracted,
    _parse_extraction_response,
    _split_text_into_chunks,
)
from app.services.groq_provider import GroqProviderError, generate_json_completion
from app.services.scholarship_discovery_budget import (
    DiscoveryRunBudget,
    DiscoveryRunLimitExceeded,
)
from app.services.scholarship_discovery_fetch import FetchedPage
from app.services.scholarship_discovery_sources import DiscoverySource


def _page(text="Official scholarship information.", links=()):
    return FetchedPage(
        url="https://official.example/scholarships",
        content_type="text/html",
        text=text,
        links=links,
        content_hash="a" * 64,
    )


def _source():
    return DiscoverySource(
        source_id="offline-source",
        name="Offline source",
        official_domain="official.example",
        category="government_scholarship_programme",
        country_or_region="test",
        source_url="https://official.example/scholarships",
        source_classification="government_authority",
    )


def _extractor(max_chunk_chars=12_000):
    return GroqScholarshipExtractor(
        SimpleNamespace(
            model="offline-groq",
            groq_model="offline-groq",
            max_provider_chunk_chars=max_chunk_chars,
            groq_max_completion_tokens=2_048,
            groq_rate_limit_retries=0,
        ),
        client=Mock(),
        groq_client=Mock(),
    )


class _ProviderBodyFailure(Exception):
    def __init__(
        self,
        status,
        param,
        code="invalid_json_schema",
        failed_generation=None,
        usage=None,
        finish_reason=None,
        error_type="invalid_request_error",
    ):
        self.status_code = status
        self.body = {
            "error": {
                "type": error_type,
                "code": code,
                "param": param,
                "message": "Synthetic provider rejection.",
            },
        }
        if failed_generation is not None:
            self.body["error"]["failed_generation"] = failed_generation
        if usage is not None:
            self.body["usage"] = usage
        if finish_reason is not None:
            self.body["finish_reason"] = finish_reason


class _TrackingLimiter:
    def __init__(self):
        self.reservations = []
        self.releases = []

    def try_acquire(self, request_tokens=0):
        reservation = object()
        self.reservations.append(reservation)
        return reservation, 0.0

    def release(self, reservation, *, cancel=False):
        self.releases.append((reservation, cancel))


class ScholarshipExtractionChunkingTests(unittest.TestCase):
    def test_chunking_is_lossless_and_respects_limit(self):
        text = ("Eligibility and deadline details.\n\n" * 20) + "Final application instructions."

        chunks = _split_text_into_chunks(text, 128)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 128 for chunk in chunks))
        self.assertEqual("".join(chunks), text)

    def test_extract_combines_chunks_and_deduplicates_identical_candidates(self):
        text = "Eligibility deadline funding required documents application instructions. " * 8
        extractor = _extractor(max_chunk_chars=128)
        seen = []
        duplicate = ExtractedScholarship(
            values={"name": "Finland Master's Award", "country": "Finland"},
            evidence={"eligibility": "Applicants must be enrolled."},
        )

        def extract_chunk(_page, _source, *, page_text, chunk_index, chunk_count):
            seen.append((page_text, chunk_index, chunk_count))
            extractor.last_provider_diagnostics = {
                "request_diagnostics": [{
                    "provider": "groq",
                    "chunk_index": chunk_index,
                    "chunk_count": chunk_count,
                }],
            }
            if chunk_index == 1:
                extractor.last_rejected_count = 1
                extractor.last_rejection_reasons = ["test_rejection"]
            return [duplicate]

        with patch.object(extractor, "_extract_single_chunk", side_effect=extract_chunk):
            result = extractor.extract(_page(text), _source())

        self.assertGreater(len(seen), 1)
        self.assertEqual("".join(chunk for chunk, _index, _count in seen), text)
        self.assertTrue(all(count == len(seen) for _chunk, _index, count in seen))
        self.assertEqual(len(result), 1)
        self.assertEqual(extractor.last_rejected_count, 1)
        self.assertEqual(extractor.last_provider_diagnostics["chunk_count"], len(seen))
        self.assertEqual(
            extractor.last_provider_diagnostics["duplicate_candidates_removed"],
            len(seen) - 1,
        )

    def test_http_413_retries_with_smaller_sub_chunks(self):
        extractor = _extractor(max_chunk_chars=6_000)
        page = _page("Eligibility sentence. " * 1000)
        extractor._generate_groq = Mock(side_effect=[
            ScholarshipExtractionError("oversized", category="payload_too_large", http_status=413),
            json.dumps({"scholarships": []}),
            json.dumps({"scholarships": []}),
            json.dumps({"scholarships": []}),
            json.dumps({"scholarships": []}),
            json.dumps({"scholarships": []}),
        ])

        self.assertEqual(extractor.extract(page, _source()), [])

        prompts = [call.args[0] for call in extractor._generate_groq.call_args_list]
        self.assertLess(len(prompts[1]), len(prompts[0]))
        self.assertLess(len(prompts[2]), len(prompts[0]))
        recovery = extractor.last_provider_diagnostics["payload_recovery"]
        self.assertTrue(recovery["recovered"])
        self.assertEqual(recovery["attempts"], 1)
        self.assertEqual(recovery["sub_chunks"], 2)
        recovered = [
            item
            for item in extractor.last_provider_diagnostics["chunk_diagnostics"]
            if item.get("status") == "recovered"
        ]
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["sub_chunk_count"], 2)

    def test_recovery_diagnostics_are_unique_and_chronological(self):
        extractor = _extractor(max_chunk_chars=6_000)
        page = _page("x" * 22_000)
        extractor._generate_groq = Mock(side_effect=[
            ScholarshipExtractionError("oversized", category="payload_too_large", http_status=413),
            json.dumps({"scholarships": []}),
            json.dumps({"scholarships": []}),
            json.dumps({"scholarships": []}),
            json.dumps({"scholarships": []}),
            json.dumps({"scholarships": []}),
        ])

        self.assertEqual(extractor.extract(page, _source()), [])

        diagnostics = extractor.last_provider_diagnostics
        self.assertNotIn("request_diagnostics", diagnostics)
        all_requests = [
            request
            for item in diagnostics["chunk_diagnostics"]
            for request in item.get("requests", [])
        ]
        self.assertEqual(len(all_requests), len({id(request) for request in all_requests}))
        recovered = [
            item
            for item in diagnostics["chunk_diagnostics"]
            if item.get("status") == "recovered"
        ][0]
        statuses = [request.get("http_status") for request in recovered["requests"]]
        self.assertEqual(statuses[0], 413)
        self.assertEqual(statuses[1:3], [None, None])
        self.assertEqual(recovered["status"], "recovered")
        self.assertTrue(recovered["recovery_succeeded"])
        self.assertEqual(recovered["recovery_level"], 1)
        self.assertEqual(recovered["sub_chunk_count"], 2)
        self.assertEqual(recovered["sub_chunk_char_limit"], 3_000)
        self.assertEqual(
            recovered["original_payload_size_bytes"],
            recovered["requests"][0]["payload_size_bytes"],
        )
        self.assertEqual(recovered["provider"], "groq")
        self.assertEqual(recovered["original_provider"], "groq")
        self.assertIsInstance(recovered["requests"], list)
        self.assertIsInstance(recovered["sub_chunk_diagnostics"], list)
        self.assertEqual(diagnostics["attempts"][0]["http_status"], 413)
        self.assertEqual(len(diagnostics["attempts"]), 6)

    def test_attempts_summary_aggregates_across_chunks(self):
        extractor = _extractor(max_chunk_chars=10_000)
        # This test counts one attempt per chunk; the token preflight is off
        # so a 10,000-char chunk is not split further.
        extractor.settings.groq_max_request_tokens = 0
        page = _page("Eligibility sentence. " * 1000)
        extractor._generate_groq = Mock(
            return_value=json.dumps({"scholarships": []})
        )

        self.assertEqual(extractor.extract(page, _source()), [])

        diagnostics = extractor.last_provider_diagnostics
        self.assertEqual(len(diagnostics["attempts"]), 3)
        self.assertTrue(all(
            attempt.get("provider") == "groq"
            and attempt.get("status") == "succeeded"
            for attempt in diagnostics["attempts"]
        ))
        self.assertEqual(len(diagnostics["chunk_diagnostics"]), 3)
        self.assertEqual(
            [item.get("chunk_index") for item in diagnostics["chunk_diagnostics"]],
            [1, 2, 3],
        )
        self.assertTrue(all(
            len(item.get("requests", [])) == 1
            for item in diagnostics["chunk_diagnostics"]
        ))

    def test_local_groq_preflight_rejection_triggers_bounded_recovery(self):
        extractor = _extractor()
        extractor.settings.groq_model = "offline-groq"
        extractor.settings.max_provider_request_bytes = 512_000
        # Asserts on the local BYTE budget; keep the token preflight disabled
        # so the byte budget alone drives the recovery.
        extractor.settings.groq_max_request_tokens = 0
        page = _page("x" * 22_000)
        source = _source()
        chunks = _split_text_into_chunks(page.text, 12_000)
        first_prompt = extractor._prompt(
            page,
            source,
            page_text=chunks[0],
        )
        first_size = extractor._request_payload_size_bytes(
            "groq",
            first_prompt,
            strict_output=False,
        )
        extractor.settings.groq_max_request_bytes = first_size - 1
        extractor._generate_groq = Mock(
            return_value=json.dumps({"scholarships": []})
        )

        self.assertEqual(extractor.extract(page, source), [])

        self.assertEqual(extractor._generate_groq.call_count, 3)
        recovery = extractor.last_provider_diagnostics["payload_recovery"]
        self.assertTrue(recovery["recovered"])
        self.assertTrue(recovery["any_recovery_succeeded"])


    def test_payload_recovery_halves_page_text(self):

        extractor = _extractor(max_chunk_chars=50_000)

        extractor.settings.max_provider_request_bytes = 1_000_000

        page = _page("x" * 4_000)

        calls = 0

        def generate(_prompt, **_kwargs):

            nonlocal calls

            calls += 1

            if calls == 1:

                raise ScholarshipExtractionError(

                    "oversized", category="payload_too_large", http_status=413

                )

            return json.dumps({"scholarships": []})

        extractor._generate_groq = Mock(side_effect=generate)

        extracted = extractor.extract(page, _source())

        self.assertEqual(extracted, [])

        diagnostics = extractor.last_provider_diagnostics

        chunk = diagnostics["chunk_diagnostics"][0]

        self.assertEqual(chunk["provider"], "groq")

        self.assertEqual(chunk["status"], "recovered")

        self.assertTrue(chunk["recovery_succeeded"])

        self.assertEqual(chunk["sub_chunk_count"], 2)

        self.assertEqual(chunk["sub_chunk_char_limit"], (len(page.text) + 1) // 2)

        sub_chunks = _split_text_into_chunks(page.text, chunk["sub_chunk_char_limit"])

        self.assertEqual(len(sub_chunks), 2)

        self.assertTrue(

            all(

                len(sub_text) <= chunk["sub_chunk_char_limit"]

                for sub_text in sub_chunks

            )

        )

        self.assertEqual("".join(sub_chunks), page.text)

        self.assertEqual(diagnostics["payload_recovery"]["attempts"], 1)

        self.assertTrue(diagnostics["payload_recovery"]["recovered"])

        self.assertTrue(diagnostics["payload_recovery"]["any_recovery_succeeded"])

    def test_json_object_mode_is_used_during_payload_recovery(self):

        extractor = _extractor(max_chunk_chars=50_000)

        extractor.settings.groq_model = "openai/gpt-oss-20b"

        extractor.settings.max_provider_request_bytes = 1_000_000

        page = _page("x" * 4_000)

        observed_requests = []

        def generate(prompt, **kwargs):

            observed_requests.append((prompt, kwargs))

            if len(observed_requests) == 1:

                raise ScholarshipExtractionError(

                    "oversized", category="payload_too_large", http_status=413

                )

            return json.dumps({"scholarships": []})

        extractor._generate_groq = Mock(side_effect=generate)

        extractor.extract(page, _source())

        self.assertGreaterEqual(len(observed_requests), 2)

        self.assertTrue(

            all(

                "strict_schema" not in kwargs
                for _prompt, kwargs in observed_requests
            ),

            observed_requests,
        )
        # Extraction always sends json_object, so no schema forces every key
        # to be present: the prompt asks for omission, never null placeholders.
        self.assertTrue(all(
            "Do not infer missing values; omit unknown fields." in prompt
            for prompt, _kwargs in observed_requests
        ))
        self.assertTrue(all(
            "use null" not in prompt
            for prompt, _kwargs in observed_requests
        ))

    def test_extraction_uses_json_object_and_validates_response(self):
        extractor = _extractor()
        extractor.settings.groq_model = "openai/gpt-oss-20b"
        extractor.settings.groq_fallback_enabled = False
        page_text = (
            "The Finland Master's Scholarship is available to Master's students. "
            "Host country: Finland."
        )
        page = _page(page_text)
        candidate = {
            "values": {
                "name": "Finland Master's Scholarship",
                "country": "Finland",
                "degree_level": "Master",
            },
            "evidence": {
                "name": "Finland Master's Scholarship",
                "country": "Finland",
                "degree_level": "Master's students",
                "host_location": "Host country: Finland",
            },
            "host_city": "",
            "masters_only": True,
            "masters_evidence": "Master's students",
            "scholarship_offer_evidence": (
                "The Finland Master's Scholarship is available"
            ),
        }
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({"scholarships": [candidate]}),
                ),
            )],
        )
        extractor._provided_groq_client = client
        expected_prompt = extractor._prompt(
            page,
            _source(),
            strict_output=True,
            page_text=page.text,
        )

        result = extractor.extract(page, _source())

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].values["name"], "Finland Master's Scholarship")
        self.assertEqual(result[0].values["country"], "Finland")
        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertNotIn("json_schema", request["response_format"])
        self.assertEqual(request["messages"][1]["content"], expected_prompt)
        size = extractor.last_provider_diagnostics["chunk_diagnostics"][0][
            "requests"
        ][0]["size_diagnostics"]
        self.assertEqual(
            size["response_schema_bytes"],
            len(json.dumps({"type": "json_object"}).encode("utf-8")),
        )
        self.assertEqual(
            size["total_serialized_request_bytes"],
            extractor.last_provider_diagnostics["chunk_diagnostics"][0][
                "requests"
            ][0]["payload_size_bytes"],
        )

    def test_json_object_mode_rejects_malformed_and_invalid_candidates(self):
        extractor = _extractor()
        extractor.settings.groq_model = "openai/gpt-oss-20b"
        extractor.settings.groq_fallback_enabled = False
        client = Mock()
        client.chat.completions.create.side_effect = [
            SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content="not JSON"),
                )],
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({
                            "scholarships": [{
                                "values": {},
                                "evidence": {},
                            }],
                        }),
                    ),
                )],
            ),
        ]
        extractor._provided_groq_client = client

        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor.extract(_page(), _source())

        self.assertEqual(raised.exception.category, "malformed_response")
        self.assertEqual(extractor.extract(_page(), _source()), [])
        self.assertEqual(extractor.last_rejected_count, 1)
        self.assertEqual(extractor.last_outcome_status, "candidates_rejected")
        self.assertEqual(client.chat.completions.create.call_count, 2)
        self.assertTrue(all(
            call.kwargs["response_format"] == {"type": "json_object"}
            for call in client.chat.completions.create.call_args_list
        ))

    def test_request_size_breakdown_adds_up_for_original_and_recovery_requests(self):

        extractor = _extractor(max_chunk_chars=50_000)

        extractor.settings.groq_model = "openai/gpt-oss-20b"

        extractor.settings.max_provider_request_bytes = 1_000_000

        page = _page(

            "Eligibility: Master's students; funding \u20ac24,000. Deadline: 30 June 2027. "

            * 40

        )

        calls = 0

        def generate(_prompt, **_kwargs):

            nonlocal calls

            calls += 1

            if calls == 1:

                raise ScholarshipExtractionError(

                    "oversized", category="payload_too_large", http_status=413

                )

            return json.dumps({"scholarships": []})

        extractor._generate_groq = Mock(side_effect=generate)

        extractor.extract(page, _source())

        diagnostics = extractor.last_provider_diagnostics

        requests = [

            request

            for chunk in diagnostics["chunk_diagnostics"]

            for request in chunk.get("requests", [])

        ]

        self.assertEqual(

            [request.get("http_status") for request in requests],

            [413, None, None],

        )

        self.assertTrue(

            any(

                chunk.get("recovery_succeeded")

                for chunk in diagnostics["chunk_diagnostics"]

            )

        )

        for request in requests:

            self.assertEqual(request["request_stage"], "provider_request")

            size = request.get("size_diagnostics")

            self.assertIsInstance(size, dict)

            for field in (

                "system_instruction_bytes",

                "user_prompt_bytes",

                "response_schema_bytes",

                "total_serialized_request_bytes",

            ):

                self.assertIn(field, size)

                value = size[field]

                self.assertIsInstance(value, int)

                self.assertFalse(isinstance(value, bool))

                self.assertGreaterEqual(value, 0)

            self.assertGreater(size["total_serialized_request_bytes"], 0)

            self.assertEqual(
                size["response_schema_bytes"],
                len(json.dumps({"type": "json_object"}).encode("utf-8")),
            )

            self.assertEqual(

                size["total_serialized_request_bytes"], request["payload_size_bytes"]

            )

            self.assertEqual(

                size["total_serialized_request_bytes"],

                size["serialized_request_bytes_after_pruning"],

            )

            self.assertGreaterEqual(

                size["total_serialized_request_bytes"],

                size["system_instruction_bytes"]

                + size["user_prompt_bytes"]

                + size["response_schema_bytes"],

            )

    def test_failed_sub_chunk_aborts_and_preserves_provider_diagnostics(self):
        extractor = _extractor()
        page = _page("Eligibility sentence. " * 100)
        calls = []

        def generate(prompt, **_kwargs):
            calls.append(prompt)
            if len(calls) == 1:
                raise ScholarshipExtractionError(
                    "oversized",
                    category="payload_too_large",
                    http_status=413,
                )
            if len(calls) == 2:
                return json.dumps({"scholarships": []})
            raise ScholarshipExtractionError(
                "permanent bad request",
                category="provider_error",
                http_status=400,
            )

        extractor._generate_groq = Mock(side_effect=generate)

        with self.assertRaises(ScholarshipExtractionError):
            extractor.extract(page, _source())

        diagnostics = extractor.last_provider_diagnostics
        self.assertNotIn("request_diagnostics", diagnostics)
        flattened_requests = [
            request
            for item in diagnostics.get("chunk_diagnostics", [])
            for request in item.get("requests", [])
        ]
        self.assertEqual(
            sum(1 for request in flattened_requests if request.get("http_status") == 400),
            1,
        )
        self.assertEqual(
            [request.get("http_status") for request in flattened_requests],
            [413, None, 400],
        )
        self.assertTrue(any(attempt.get("http_status") == 400 for attempt in diagnostics["attempts"]))
        failed_entry = diagnostics["chunk_diagnostics"][-1]
        self.assertEqual(failed_entry["status"], "failed")
        self.assertFalse(failed_entry["recovery_succeeded"])
        self.assertEqual(failed_entry["recovery_level"], 1)
        self.assertEqual(failed_entry["sub_chunk_count"], 2)
        self.assertEqual(failed_entry["sub_chunk_char_limit"], 1_100)
        self.assertEqual(
            failed_entry["original_payload_size_bytes"],
            failed_entry["requests"][0]["payload_size_bytes"],
        )
        self.assertEqual(failed_entry["provider"], "groq")
        self.assertEqual(failed_entry["original_provider"], "groq")
        self.assertIsInstance(failed_entry["requests"], list)
        self.assertIsInstance(failed_entry["sub_chunk_diagnostics"], list)

    def test_failed_sub_chunk_after_success_does_not_return_partial_extraction(self):
        extractor = _extractor()
        block = (
            "The Finland Master's Scholarship is available to Master's students. "
            "Host country: Finland. Funding: EUR 24,000. Deadline: 30 June 2027. "
            "Duration: 24 months. Requirements: official transcript."
        )
        page = _page(block * 20)
        candidate = {
            "values": {
                "name": "Finland Master's Scholarship",
                "country": "Finland",
                "degree_level": "Master",
                "eligible_degree_levels": ["Master"],
                "stipend_amount": 24000,
                "stipend_currency": "EUR",
                "application_deadline_date": "2027-06-30",
                "funding_duration_months": 24,
                "required_documents_list": ["official transcript"],
            },
            "evidence": {
                "name": "Finland Master's Scholarship",
                "country": "Finland",
                "degree_level": "Master's students",
                "eligible_degree_levels": "Master's students",
                "stipend_amount": "EUR 24,000",
                "stipend_currency": "EUR 24,000",
                "application_deadline_date": "30 June 2027",
                "funding_duration_months": "24 months",
                "required_documents_list": "official transcript",
                "host_location": "Host country: Finland",
                "host_city": "",
            },
            "host_city": "",
            "masters_only": True,
            "masters_evidence": "Master's students",
            "scholarship_offer_evidence": "The Finland Master's Scholarship is available",
        }
        calls = 0

        def generate(_prompt, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ScholarshipExtractionError(
                    "oversized",
                    category="payload_too_large",
                    http_status=413,
                )
            if calls == 2:
                return json.dumps({"scholarships": [candidate]})
            raise ScholarshipExtractionError(
                "permanent bad request",
                category="provider_error",
                http_status=400,
            )

        extractor._generate_groq = Mock(side_effect=generate)

        with self.assertRaises(ScholarshipExtractionError):
            extractor.extract(page, _source())

        recovery = extractor.last_provider_diagnostics["payload_recovery"]
        self.assertFalse(recovery["recovered"])
        self.assertFalse(recovery["any_recovery_succeeded"])

    def test_mixed_recovery_outcome_reports_recovered_false(self):
        extractor = _extractor()
        extractor.settings.max_provider_chunk_chars = 2_000
        page = _page("Eligibility sentence. " * 300)
        calls = 0

        def generate(_prompt, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ScholarshipExtractionError(
                    "oversized",
                    category="payload_too_large",
                    http_status=413,
                )
            if calls in (2, 3):
                return json.dumps({"scholarships": []})
            raise ScholarshipExtractionError(
                "still oversized",
                category="payload_too_large",
                http_status=413,
            )

        extractor._generate_groq = Mock(side_effect=generate)

        with self.assertRaises(ScholarshipExtractionError):
            extractor.extract(page, _source())

        recovery = extractor.last_provider_diagnostics["payload_recovery"]
        self.assertFalse(recovery["recovered"])
        self.assertTrue(recovery["any_recovery_succeeded"])

    def test_budget_exhaustion_during_recovery_finalizes_diagnostics(self):
        extractor = _extractor()
        page = _page("x" * 2_000)
        calls = 0

        def generate(_prompt, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ScholarshipExtractionError(
                    "oversized",
                    category="payload_too_large",
                    http_status=413,
                )
            raise DiscoveryRunLimitExceeded("provider_attempts", 1)

        extractor._generate_groq = Mock(side_effect=generate)

        with self.assertRaises(DiscoveryRunLimitExceeded):
            extractor.extract(page, _source())

        diagnostics = extractor.last_provider_diagnostics
        recovery = diagnostics["payload_recovery"]
        self.assertFalse(recovery["recovered"])
        self.assertFalse(recovery["any_recovery_succeeded"])
        level = recovery["levels"][-1]
        self.assertEqual(level["reason"], "budget_exhausted")
        self.assertEqual(level["budget_resource"], "provider_attempts")
        self.assertEqual(level["budget_limit"], 1)
        self.assertNotIn("request_diagnostics", diagnostics)
        failed_entry = diagnostics["chunk_diagnostics"][-1]
        self.assertEqual(failed_entry["status"], "failed")
        self.assertFalse(failed_entry["recovery_succeeded"])
        self.assertEqual(failed_entry["provider"], "groq")
        self.assertEqual(failed_entry["original_provider"], "groq")
        self.assertEqual(failed_entry["recovery_level"], 1)
        self.assertEqual(failed_entry["sub_chunk_count"], 2)
        self.assertEqual(failed_entry["sub_chunk_char_limit"], 1_000)
        self.assertGreater(failed_entry["original_payload_size_bytes"], 0)
        self.assertEqual(
            [request["http_status"] for request in failed_entry["requests"]],
            [413, None],
        )

    def test_recursive_recovery_preserves_successful_sub_chunk_on_budget_exhaustion(self):
        extractor = _extractor()
        page = _page("Eligibility sentence. " * 100)
        calls = 0

        def generate(_prompt, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ScholarshipExtractionError(
                    "oversized",
                    category="payload_too_large",
                    http_status=413,
                )
            if calls == 2:
                return json.dumps({"scholarships": []})
            raise DiscoveryRunLimitExceeded("provider_attempts", 1)

        extractor._generate_groq = Mock(side_effect=generate)

        with self.assertRaises(DiscoveryRunLimitExceeded):
            extractor.extract(page, _source())

        diagnostics = extractor.last_provider_diagnostics
        recovery = diagnostics["payload_recovery"]
        self.assertFalse(recovery["recovered"])
        self.assertFalse(recovery["any_recovery_succeeded"])
        self.assertEqual(recovery["levels"][-1]["completed_chunk_count"], 1)
        failed_entry = diagnostics["chunk_diagnostics"][-1]
        self.assertEqual(failed_entry["status"], "failed")
        self.assertEqual(failed_entry["provider"], "groq")
        self.assertEqual(failed_entry["original_provider"], "groq")
        self.assertEqual(failed_entry["sub_chunk_count"], 2)
        self.assertEqual(failed_entry["sub_chunk_char_limit"], 1_100)
        self.assertEqual(
            [item.get("status") for item in failed_entry["sub_chunk_diagnostics"]],
            ["succeeded", "failed"],
        )
        self.assertEqual(
            [request.get("status") for request in failed_entry["requests"]],
            ["failed", "succeeded", "failed"],
        )
        self.assertTrue(any(
            attempt.get("provider") == "groq"
            and attempt.get("status") == "succeeded"
            for attempt in diagnostics["attempts"]
        ))
        self.assertTrue(any(
            attempt.get("provider") == "groq"
            and attempt.get("error_category") == "budget_exhausted"
            for attempt in diagnostics["attempts"]
        ))

    def test_later_budget_failure_after_recovery_reports_not_recovered(self):
        extractor = _extractor(max_chunk_chars=1_000)
        page = _page("x" * 2_000)
        calls = 0

        def generate(_prompt, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ScholarshipExtractionError(
                    "oversized",
                    category="payload_too_large",
                    http_status=413,
                )
            if calls in (2, 3):
                return json.dumps({"scholarships": []})
            raise DiscoveryRunLimitExceeded("provider_attempts", 1)

        extractor._generate_groq = Mock(side_effect=generate)

        with self.assertRaises(DiscoveryRunLimitExceeded):
            extractor.extract(page, _source())

        diagnostics = extractor.last_provider_diagnostics
        recovery = diagnostics["payload_recovery"]
        self.assertFalse(recovery["recovered"])
        self.assertTrue(recovery["any_recovery_succeeded"])
        recovered = [
            item
            for item in diagnostics["chunk_diagnostics"]
            if item.get("status") == "recovered"
        ]
        self.assertEqual(len(recovered), 1)
        self.assertEqual(
            [request.get("http_status") for request in recovered[0]["requests"]],
            [413, None, None],
        )
        self.assertTrue(any(
            attempt.get("status") == "succeeded"
            for attempt in diagnostics["attempts"]
        ))

    def test_multi_level_recovery_merge_is_unique_and_chronological(self):
        extractor = _extractor()
        page = _page("x" * 2_000)
        calls = 0

        def generate(_prompt, **_kwargs):
            nonlocal calls
            calls += 1
            if calls <= 2:
                raise ScholarshipExtractionError(
                    "oversized",
                    category="payload_too_large",
                    http_status=413,
                )
            if calls in (3, 4):
                return json.dumps({"scholarships": []})
            raise ScholarshipExtractionError(
                "permanent bad request",
                category="provider_error",
                http_status=400,
            )

        extractor._generate_groq = Mock(side_effect=generate)

        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor.extract(page, _source())

        self.assertEqual(raised.exception.http_status, 400)
        diagnostics = extractor.last_provider_diagnostics
        failed_entry = diagnostics["chunk_diagnostics"][-1]
        requests = failed_entry["requests"]
        self.assertEqual(
            [request.get("http_status") for request in requests],
            [413, 413, None, None, 400],
        )
        self.assertEqual(len(requests), len({id(request) for request in requests}))
        attempts = diagnostics["attempts"]
        self.assertEqual(len(attempts), len({id(attempt) for attempt in attempts}))
        self.assertEqual(
            [attempt.get("status") for attempt in attempts],
            ["failed", "failed", "succeeded", "succeeded", "failed"],
        )
        self.assertEqual(
            [item.get("status") for item in failed_entry["sub_chunk_diagnostics"]],
            ["recovered", "failed"],
        )
        self.assertFalse(diagnostics["payload_recovery"]["recovered"])
        self.assertTrue(diagnostics["payload_recovery"]["any_recovery_succeeded"])

    def test_groq_budget_exhaustion_preserves_chunk_diagnostics(self):
        extractor = _extractor()
        budget_error = DiscoveryRunLimitExceeded("provider_attempts", 1)
        budget_error.request_started = False
        extractor._generate_groq = Mock(side_effect=budget_error)

        with self.assertRaises(DiscoveryRunLimitExceeded):
            extractor.extract(_page("Eligibility sentence. " * 10), _source())

        diagnostics = extractor.last_provider_diagnostics
        self.assertEqual(diagnostics["providers_attempted"], ["groq"])
        self.assertTrue(any(
            attempt.get("provider") == "groq"
            and attempt.get("error_category") == "budget_exhausted"
            for attempt in diagnostics["attempts"]
        ))
        failed_entry = diagnostics["chunk_diagnostics"][-1]
        self.assertEqual(failed_entry["status"], "failed")
        self.assertEqual(failed_entry["provider"], "groq")
        self.assertEqual(failed_entry["original_provider"], "groq")
        self.assertEqual(len(failed_entry["requests"]), 1)
        self.assertEqual(failed_entry["requests"][0]["provider"], "groq")
        self.assertEqual(failed_entry["requests"][0]["http_status"], None)
        self.assertFalse(failed_entry["requests"][0]["request_started"])
        self.assertEqual(failed_entry["requests"][0]["retry_outcome"], "not_attempted")
        self.assertFalse(diagnostics["payload_recovery"]["recovered"])
        self.assertNotIn("request_diagnostics", diagnostics)

    def test_in_flight_cancellation_is_marked_started_and_canceled(self):
        extractor = _extractor()
        canceled = DiscoveryRunLimitExceeded("duration_seconds", 1)
        canceled.request_started = True
        extractor._generate_groq = Mock(side_effect=canceled)

        with self.assertRaises(DiscoveryRunLimitExceeded):
            extractor.extract(_page("x" * 1_000), _source())

        diagnostics = extractor.last_provider_diagnostics
        failed_entry = diagnostics["chunk_diagnostics"][-1]
        request = failed_entry["requests"][0]
        self.assertTrue(request["request_started"])
        self.assertEqual(request["retry_outcome"], "canceled")
        self.assertIsNone(request["http_status"])
        extractor._generate_groq.assert_called_once()
        self.assertTrue(any(
            attempt.get("error_category") == "budget_exhausted"
            for attempt in diagnostics["attempts"]
        ))
        self.assertFalse(diagnostics["payload_recovery"]["recovered"])

    def test_groq_primary_budget_exhaustion_preserves_diagnostics(self):
        extractor = _extractor()
        budget_error = DiscoveryRunLimitExceeded("provider_attempts", 1)
        budget_error.request_started = False
        extractor._generate_groq = Mock(side_effect=budget_error)

        with self.assertRaises(DiscoveryRunLimitExceeded):
            extractor.extract(_page("Eligibility sentence. " * 10), _source())

        diagnostics = extractor.last_provider_diagnostics
        self.assertEqual(diagnostics["providers_attempted"], ["groq"])
        self.assertEqual(len(diagnostics["attempts"]), 1)
        self.assertEqual(
            diagnostics["attempts"][0]["error_category"],
            "budget_exhausted",
        )
        failed_entry = diagnostics["chunk_diagnostics"][-1]
        self.assertEqual(failed_entry["status"], "failed")
        self.assertEqual(failed_entry["provider"], "groq")
        self.assertEqual(failed_entry["original_provider"], "groq")
        self.assertEqual(len(failed_entry["requests"]), 1)
        self.assertIsNone(failed_entry["requests"][0]["http_status"])
        self.assertFalse(failed_entry["requests"][0]["request_started"])
        self.assertEqual(failed_entry["requests"][0]["retry_outcome"], "not_attempted")
        self.assertFalse(diagnostics["payload_recovery"]["recovered"])

    def test_provider_budget_counts_secondary_groq_key_attempt(self):
        primary_client = Mock()
        primary_client.chat.completions.create.side_effect = GroqProviderError(
            "provider_error",
            503,
        )
        secondary_client = Mock()
        budget = DiscoveryRunBudget(max_provider_attempts=1, start_deadline_timer=False)
        budget.start()
        extractor = _extractor()
        extractor.settings.groq_fallback_enabled = True
        extractor._provided_groq_client = primary_client
        extractor._provided_fallback_groq_client = secondary_client
        extractor.run_budget = budget

        try:
            with self.assertRaises(DiscoveryRunLimitExceeded) as raised:
                extractor._generate_groq("synthetic prompt")
        finally:
            budget.close()

        self.assertEqual(raised.exception.resource, "provider_attempts")
        primary_client.chat.completions.create.assert_called_once()
        secondary_client.chat.completions.create.assert_not_called()

    def test_real_groq_adapter_http_413_recovery_uses_smaller_requests(self):
        class GroqHTTPError(Exception):
            def __init__(self, status, body):
                self.status_code = status
                self.body = body

        groq_client = Mock()
        request_sizes = []

        def create(**kwargs):
            size = len(json.dumps(kwargs, ensure_ascii=False).encode("utf-8"))
            request_sizes.append(size)
            # Full-size chunks trip the provider 413; smaller recovery chunks
            # fit. Tracks the prompt wrapper, including the allowed-field list.
            if size > 15_500:
                raise GroqHTTPError(
                    413,
                    {
                        "error": {
                            "code": "request_too_large",
                            "param": "messages",
                            "message": "simulated request too large",
                        }
                    },
                )
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"scholarships": []}),
                    ),
                )],
            )

        groq_client.chat.completions.create.side_effect = create
        extractor = _extractor()
        extractor.settings.groq_fallback_enabled = True
        extractor.settings.groq_max_request_bytes = 64_000
        extractor.settings.max_provider_request_bytes = 512_000
        # This test asserts on the local BYTE budget; keep the token
        # preflight and organization TPM admission disabled so the byte budget
        # alone decides.
        extractor.settings.groq_max_request_tokens = 0
        extractor.settings.groq_tpm_limit = None
        extractor.settings.groq_organization_id = "offline-byte-budget-only-org"
        extractor._provided_groq_client = groq_client

        page = _page("x" * 22_000)
        self.assertEqual(extractor.extract(page, _source()), [])

        self.assertEqual(extractor._max_request_bytes_for("groq"), 64_000)
        self.assertGreater(request_sizes[0], 13_000)
        self.assertLessEqual(max(request_sizes), 64_000)
        self.assertLess(request_sizes[1], request_sizes[0])
        self.assertLess(request_sizes[2], request_sizes[0])
        diagnostics = extractor.last_provider_diagnostics
        diagnosed_groq_requests = [
            request
            for chunk in diagnostics["chunk_diagnostics"]
            for request in chunk.get("requests", [])
            if request.get("provider") == "groq"
        ]
        self.assertGreaterEqual(len(request_sizes), 4)
        self.assertEqual(len(request_sizes), len(diagnosed_groq_requests))
        self.assertTrue(diagnostics["payload_recovery"]["recovered"])
        self.assertTrue(diagnostics["payload_recovery"]["any_recovery_succeeded"])
        recovered = [
            item
            for item in diagnostics["chunk_diagnostics"]
            if item.get("status") == "recovered"
        ][0]
        groq_requests = [
            request
            for request in recovered["requests"]
            if request.get("provider") == "groq"
        ]
        statuses = [request.get("http_status") for request in groq_requests]
        self.assertEqual(statuses, [413, None, None])
        self.assertEqual(groq_requests[0]["provider_error_code"], "request_too_large")
        self.assertEqual(groq_requests[0]["provider_error_param"], "messages")
        self.assertTrue(groq_requests[0]["request_started"])
        self.assertEqual(groq_requests[0]["retry_outcome"], "recovery_required")
        self.assertTrue(all(request.get("request_started") for request in groq_requests))
        self.assertTrue(all(
            request.get("retry_outcome") == "succeeded"
            for request in groq_requests[1:]
        ))

    def test_local_groq_preflight_recovery_has_no_duplicate_request_diagnostics(self):
        groq_client = Mock()
        request_sizes = []

        def create(**kwargs):
            request_sizes.append(
                len(json.dumps(kwargs, ensure_ascii=False).encode("utf-8"))
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"scholarships": []}),
                    ),
                )],
            )

        groq_client.chat.completions.create.side_effect = create
        extractor = _extractor(max_chunk_chars=100_000)
        extractor.settings.groq_fallback_enabled = True
        extractor.settings.groq_max_request_bytes = 64_000
        extractor.settings.max_provider_request_bytes = 512_000
        # This test asserts on the local BYTE budget; keep the token
        # preflight disabled so the byte budget alone decides.
        extractor.settings.groq_max_request_tokens = 0
        extractor._provided_groq_client = groq_client

        page = _page("x" * 100_000)
        self.assertEqual(extractor.extract(page, _source()), [])

        self.assertEqual(len(request_sizes), 2)
        self.assertTrue(all(size <= 64_000 for size in request_sizes))
        diagnostics = extractor.last_provider_diagnostics
        self.assertTrue(diagnostics["payload_recovery"]["recovered"])
        recovered = [
            item
            for item in diagnostics["chunk_diagnostics"]
            if item.get("status") == "recovered"
        ][0]
        preflight = [
            request
            for request in recovered["requests"]
            if request.get("request_stage") == "request_preflight"
        ]
        self.assertEqual(len(preflight), 1)
        self.assertFalse(preflight[0]["request_started"])
        self.assertEqual(preflight[0]["retry_outcome"], "not_attempted")
        self.assertEqual(
            len([
                request
                for request in recovered["requests"]
                if request.get("request_stage") == "provider_request"
                and request.get("provider") == "groq"
            ]),
            2,
        )

    def test_provider_error_metadata_rejects_page_derived_values(self):
        type_text = "TYPE_UNIQUE_9b2f"
        code_text = "CODE_UNIQUE_9b2f"
        param_text = "PARAM_UNIQUE_9b2f"
        message_text = "MESSAGE_UNIQUE_9b2f"
        extractor = _extractor()
        extractor._generate_groq = Mock(
            side_effect=ScholarshipExtractionError(
                "oversized",
                category="payload_too_large",
                http_status=413,
                provider_error_details={
                    "type": type_text,
                    "code": code_text,
                    "param": param_text,
                    "message": message_text,
                },
            )
        )

        with self.assertRaises(ScholarshipExtractionError):
            extractor.extract(
                _page(f"{type_text} {code_text} {param_text} {message_text}"),
                _source(),
            )

        serialized = json.dumps(extractor.last_provider_diagnostics)
        for value in (type_text, code_text, param_text, message_text):
            self.assertNotIn(value, serialized)
        groq_attempts = [
            attempt
            for attempt in extractor.last_provider_diagnostics["attempts"]
            if attempt.get("provider") == "groq"
        ]
        self.assertTrue(all(not attempt.get("provider_error_details") for attempt in groq_attempts))

        extractor = _extractor()
        extractor._generate_groq = Mock(
            side_effect=ScholarshipExtractionError(
                "malformed_request",
                category="malformed_request",
                http_status=400,
                provider_error_details={
                    "type": "invalid_request_error",
                    "code": "invalid_json_schema",
                    "param": "response_format",
                    "message": message_text,
                },
            )
        )

        with self.assertRaises(ScholarshipExtractionError):
            extractor.extract(
                _page(f"Eligibility sentence. {message_text}"),
                _source(),
            )

        groq_attempts = [
            attempt
            for attempt in extractor.last_provider_diagnostics["attempts"]
            if attempt.get("provider") == "groq"
        ]
        self.assertEqual(groq_attempts[0]["provider_error_details"], {
            "type": "invalid_request_error",
            "code": "invalid_json_schema",
            "param": "response_format",
        })
        self.assertNotIn(message_text, json.dumps(extractor.last_provider_diagnostics))

    def test_provider_error_message_is_not_persisted(self):
        unique_page_text = "UNIQUE_PAGE_TEXT_DO_NOT_PERSIST_7f4c"
        extractor = _extractor()
        extractor._generate_groq = Mock(
            side_effect=ScholarshipExtractionError(
                "oversized",
                category="payload_too_large",
                http_status=413,
                provider_error_details={
                    "code": "request_too_large",
                    "param": "messages",
                    "message": unique_page_text,
                },
            )
        )

        with self.assertRaises(ScholarshipExtractionError):
            extractor.extract(_page(unique_page_text), _source())

        serialized = json.dumps(extractor.last_provider_diagnostics)
        self.assertNotIn(unique_page_text, serialized)
        groq_attempts = [
            attempt
            for attempt in extractor.last_provider_diagnostics["attempts"]
            if attempt.get("provider") == "groq"
        ]
        self.assertTrue(any(
            attempt.get("provider_error_details", {}).get("code") == "request_too_large"
            for attempt in groq_attempts
        ))

    def test_http_422_is_not_retried_or_recovered(self):
        extractor = _extractor()
        page = _page("Eligibility sentence. " * 100)
        extractor._generate_groq = Mock(
            side_effect=ScholarshipExtractionError(
                "unprocessable",
                category="malformed_request",
                http_status=422,
            )
        )

        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor.extract(page, _source())

        self.assertEqual(raised.exception.category, "malformed_request")
        self.assertEqual(raised.exception.http_status, 422)
        self.assertEqual(extractor._generate_groq.call_count, 1)
        self.assertFalse(extractor.last_provider_diagnostics["payload_recovery"]["recovered"])
        self.assertEqual(extractor.last_provider_diagnostics["payload_recovery"]["attempts"], 0)

    def test_splitting_is_lossless_for_unicode_and_unseparated_text(self):
        unicode_text = "αβγδ" * 500
        unicode_chunks = _split_text_into_chunks(unicode_text, 128)
        self.assertEqual("".join(unicode_chunks), unicode_text)
        self.assertTrue(all(len(chunk) <= 128 for chunk in unicode_chunks))

        unseparated_text = "x" * 1_000
        unseparated_chunks = _split_text_into_chunks(unseparated_text, 128)
        self.assertEqual("".join(unseparated_chunks), unseparated_text)
        self.assertTrue(all(len(chunk) <= 128 for chunk in unseparated_chunks))

    def test_deduplication_preserves_decimal_date_and_source_attribution(self):
        values = {
            "name": "Award",
            "stipend_amount": Decimal("1.20"),
            "application_deadline_date": date(2027, 6, 30),
            "source_name": "Offline source",
            "official_info_url": "https://official.example/scholarships",
        }
        first = ExtractedScholarship(
            values=dict(values),
            evidence={"name": "Award"},
        )
        second = ExtractedScholarship(
            values=dict(values),
            evidence={"name": "Award", "country": "Finland"},
        )

        result = _deduplicate_extracted([first, second])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].values["stipend_amount"], Decimal("1.20"))
        self.assertEqual(result[0].values["application_deadline_date"], date(2027, 6, 30))
        self.assertEqual(result[0].values["source_name"], "Offline source")
        self.assertEqual(
            result[0].values["official_info_url"],
            "https://official.example/scholarships",
        )

    def test_http_413_retry_exhaustion_fails_without_partial_results(self):
        extractor = _extractor()
        page = _page("Eligibility sentence. " * 100)
        extractor._generate_groq = Mock(
            side_effect=ScholarshipExtractionError(
                "still oversized",
                category="payload_too_large",
                http_status=413,
            )
        )

        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor.extract(page, _source())

        self.assertEqual(raised.exception.http_status, 413)
        diagnostics = extractor.last_provider_diagnostics
        recovery = diagnostics["payload_recovery"]
        self.assertFalse(recovery["recovered"])
        self.assertEqual(recovery["attempts"], MAX_413_RECOVERY_LEVELS)
        self.assertLessEqual(recovery["sub_chunks"], MAX_413_RECOVERY_SUB_CHUNKS)
        self.assertLessEqual(recovery["payload_bytes"], recovery["max_payload_bytes"])
        self.assertEqual(diagnostics["completed_chunk_count"], 0)
        self.assertGreaterEqual(extractor._generate_groq.call_count, 3)
        self.assertLessEqual(extractor._generate_groq.call_count, 7)

    def test_groq_http_413_retries_with_smaller_payload(self):
        extractor = _extractor()
        # Exercises the PROVIDER 413 path, so the local token preflight must
        # not reject the request before it is sent.
        extractor.settings.groq_max_request_tokens = 0
        extractor.settings.groq_model = "openai/gpt-oss-20b"
        extractor.settings.groq_fallback_enabled = True
        page = _page("Eligibility sentence. " * 1000)
        extractor._generate_groq = Mock(
            side_effect=ScholarshipExtractionError(
                "quota",
                category="quota_error",
                http_status=429,
            )
        )
        groq_413 = ScholarshipExtractionError(
            "oversized",
            category="payload_too_large",
            http_status=413,
            provider_error_details={
                "code": "request_too_large",
                "param": "messages",
                "message": "provider echoed sensitive request content",
            },
        )
        extractor._generate_groq = Mock(side_effect=[
            groq_413,
            *([json.dumps({"scholarships": []})] * 30),
        ])

        self.assertEqual(extractor.extract(page, _source()), [])

        groq_prompts = [
            call.args[0]
            for call in extractor._generate_groq.call_args_list
        ]
        self.assertLess(len(groq_prompts[1]), len(groq_prompts[0]))
        self.assertLess(len(groq_prompts[2]), len(groq_prompts[0]))
        recovery = extractor.last_provider_diagnostics["payload_recovery"]
        self.assertTrue(recovery["recovered"])
        requests = [
            request
            for item in extractor.last_provider_diagnostics["chunk_diagnostics"]
            for request in item.get("requests", [])
            if request.get("provider") == "groq"
        ]
        self.assertEqual(requests[0]["http_status"], 413)
        self.assertTrue(requests[0]["request_started"])
        self.assertEqual(requests[0]["provider_error_code"], "request_too_large")
        self.assertEqual(requests[0]["provider_error_param"], "messages")
        self.assertNotIn("provider echoed", json.dumps(requests))
        self.assertTrue(any(request["http_status"] is None for request in requests))
        recovered = [
            item
            for item in extractor.last_provider_diagnostics["chunk_diagnostics"]
            if item.get("status") == "recovered"
        ][0]
        self.assertEqual(recovered["provider"], "groq")
        self.assertEqual(recovered["original_provider"], "groq")

    def test_groq_413_recovery_failure_still_fails_safely(self):
        extractor = _extractor()
        extractor.settings.groq_model = "openai/gpt-oss-20b"
        page = _page("Eligibility sentence. " * 1000)
        extractor._generate_groq = Mock(
            side_effect=ScholarshipExtractionError(
                "oversized",
                category="payload_too_large",
                http_status=413,
            )
        )

        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor.extract(page, _source())

        self.assertEqual(raised.exception.category, "payload_too_large")
        self.assertEqual(raised.exception.http_status, 413)
        recovery = extractor.last_provider_diagnostics["payload_recovery"]
        self.assertFalse(recovery["recovered"])
        self.assertEqual(extractor.last_outcome_status, "provider_error")
        self.assertIn("groq", extractor.last_provider_diagnostics["providers_attempted"])

    def test_http_429_does_not_trigger_413_recovery(self):
        extractor = _extractor(max_chunk_chars=6_000)
        page = _page("Eligibility sentence. " * 1000)
        extractor._generate_groq = Mock(
            side_effect=ScholarshipExtractionError(
                "quota",
                category="quota_error",
                http_status=429,
            )
        )

        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor.extract(page, _source())

        self.assertEqual(raised.exception.category, "quota_error")
        self.assertEqual(extractor._generate_groq.call_count, 1)
        self.assertFalse(extractor.last_provider_diagnostics["payload_recovery"]["recovered"])
        self.assertEqual(extractor.last_provider_diagnostics["payload_recovery"]["attempts"], 0)

    def test_chunk_results_are_merged_and_deduplicated_with_important_fields(self):
        extractor = _extractor()
        block = (
            "The Finland Master's Scholarship is available to Master's students. "
            "Host country: Finland. Funding: EUR 24,000. Deadline: 30 June 2027. "
            "Duration: 24 months. Requirements: official transcript."
        )
        page = _page(block * 300)
        candidate = {
            "values": {
                "name": "Finland Master's Scholarship",
                "country": "Finland",
                "degree_level": "Master",
                "eligible_degree_levels": ["Master"],
                "stipend_amount": 24000,
                "stipend_currency": "EUR",
                "application_deadline_date": "2027-06-30",
                "funding_duration_months": 24,
                "required_documents_list": ["official transcript"],
            },
            "evidence": {
                "name": "Finland Master's Scholarship",
                "country": "Finland",
                "degree_level": "Master's students",
                "eligible_degree_levels": "Master's students",
                "stipend_amount": "EUR 24,000",
                "stipend_currency": "EUR 24,000",
                "application_deadline_date": "30 June 2027",
                "funding_duration_months": "24 months",
                "required_documents_list": "official transcript",
                "host_location": "Host country: Finland",
                "host_city": "",
            },
            "host_city": "",
            "masters_only": True,
            "masters_evidence": "Master's students",
            "scholarship_offer_evidence": "The Finland Master's Scholarship is available",
        }
        extractor._generate_groq = Mock(
            return_value=json.dumps({"scholarships": [candidate]})
        )

        result = extractor.extract(page, _source())

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].values["stipend_amount"], 24000)
        self.assertEqual(
            str(result[0].values["application_deadline_date"]),
            "2027-06-30",
        )
        self.assertEqual(result[0].values["funding_duration_months"], 24)
        self.assertEqual(result[0].values["country"], "Finland")
        self.assertEqual(result[0].values["required_documents_list"], ["official transcript"])
        self.assertGreaterEqual(
            extractor.last_provider_diagnostics["duplicate_candidates_removed"],
            1,
        )

    def test_diagnostics_have_metadata_without_sensitive_content(self):
        extractor = _extractor()
        page_text = "Eligibility sentence. " * 1000
        page = _page(page_text)
        extractor._generate_groq = Mock(side_effect=[
            ScholarshipExtractionError(
                "oversized",
                category="payload_too_large",
                http_status=413,
                provider_error_details={
                    "code": "request_too_large",
                    "param": "messages",
                },
            ),
            *([json.dumps({"scholarships": []})] * 30),
        ])

        self.assertEqual(extractor.extract(page, _source()), [])
        diagnostics = extractor.last_provider_diagnostics
        serialized = json.dumps(diagnostics)
        self.assertNotIn(page_text[:80], serialized)
        self.assertNotIn("Source page data (JSON)", serialized)
        self.assertIn('"serialized_request_bytes_after_pruning":', serialized)
        self.assertNotIn("authorization", serialized.casefold())
        self.assertNotIn("api_key", serialized.casefold())
        requests = [
            request
            for item in diagnostics["chunk_diagnostics"]
            for request in item.get("requests", [])
        ]
        self.assertTrue(all(request["payload_size_bytes"] > 0 for request in requests))
        self.assertTrue(all("chunk_index" in request for request in requests))
        self.assertTrue(all("chunk_count" in request for request in requests))
        self.assertTrue(diagnostics["payload_recovery"]["levels"])

    def test_http_400_is_not_retried_or_recovered(self):
        """A mocked non-schema HTTP 400 is recorded once and never payload-recovered."""
        extractor = _extractor()
        extractor._prompt_within_budget = Mock(return_value="normal prompt")
        extractor._generate_groq = Mock(
            side_effect=ScholarshipExtractionError(
                "malformed request",
                category="malformed_request",
                http_status=400,
                provider_error_details={
                    "type": "invalid_request_error",
                    "code": "invalid_json_schema",
                    "param": "messages",
                    "message": "test message",
                },
            )
        )

        with self.assertRaises(ScholarshipExtractionError):
            extractor.extract(_page(), _source())
        extractor._generate_groq.assert_called_once()
        groq_attempts = [
            attempt
            for attempt in extractor.last_provider_diagnostics["attempts"]
            if attempt.get("provider") == "groq"
        ]
        self.assertEqual(len(groq_attempts), 1)
        self.assertEqual(groq_attempts[0]["provider_error_details"]["param"], "messages")
        payload_recovery = extractor.last_provider_diagnostics["payload_recovery"]
        self.assertFalse(payload_recovery["recovered"])
        self.assertEqual(payload_recovery["attempts"], 0)

        self.assertEqual(
            extractor.last_provider_diagnostics["chunk_diagnostics"][0]["requests"][0]["http_status"],
            400,
        )
        self.assertEqual(
            extractor.last_provider_diagnostics["chunk_diagnostics"][0]["requests"][0][
                "retry_outcome"
            ],
            "not_retried",
        )
        self.assertTrue(extractor.last_provider_diagnostics["chunk_diagnostics"][0]["requests"][0]["request_started"])
        self.assertEqual(extractor.last_provider_diagnostics["chunk_diagnostics"][0]["status"], "failed")
        self.assertEqual(extractor.last_provider_diagnostics["chunk_diagnostics"][0]["recovery_level"], 0)
        self.assertEqual(
            extractor.last_provider_diagnostics["chunk_diagnostics"][0]["provider"],
            "groq",
        )
        self.assertIsNone(extractor.last_provider_diagnostics["chunk_diagnostics"][0].get("sub_chunk_count"))
        self.assertIsNone(extractor.last_provider_diagnostics["chunk_diagnostics"][0].get("sub_chunk_char_limit"))
        self.assertIsNone(extractor.last_provider_diagnostics["chunk_diagnostics"][0].get("original_payload_size_bytes"))
        self.assertIsInstance(extractor.last_provider_diagnostics["chunk_diagnostics"][0]["requests"], list)
        self.assertEqual(extractor.last_provider_diagnostics["chunk_diagnostics"][0]["sub_chunk_diagnostics"], [])

    def test_groq_400_response_format_fails_without_retry(self):
        extractor = _extractor()
        extractor.settings.groq_model = "openai/gpt-oss-20b"
        client = Mock()
        client.chat.completions.create.side_effect = _ProviderBodyFailure(400, "response_format")
        extractor._provided_groq_client = client
        extractor._provided_fallback_groq_client = None

        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor._generate_groq("synthetic prompt", strict_schema={"type": "object"})

        self.assertEqual(raised.exception.category, "invalid_response_format_schema")
        self.assertIn("schema must be fixed", str(raised.exception))
        client.chat.completions.create.assert_called_once()
        self.assertEqual(
            client.chat.completions.create.call_args.kwargs["response_format"]["type"],
            "json_schema",
        )

    def test_json_validate_failure_uses_unlogged_json_object_fallback(self):
        extractor = _extractor()
        extractor.settings.groq_model = "openai/gpt-oss-20b"
        client = Mock()
        client.chat.completions.create.side_effect = [
            _ProviderBodyFailure(
                400,
                "response_format",
                code="json_validate_failed",
                failed_generation=(
                    '{"excerpt":"Official private page text",'
                    '"padding":"' + ("x" * 3_000) + '"}'
                ),
                usage={
                    "completion_tokens": 987,
                    "completion_tokens_details": {"reasoning_tokens": 654},
                },
                finish_reason="length",
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            "```json\n"
                            '{"scholarships": []}\n'
                            "```\nFallback generated extra text."
                        ),
                    ),
                    finish_reason="stop",
                )],
                usage=SimpleNamespace(
                    completion_tokens=321,
                    completion_tokens_details=SimpleNamespace(reasoning_tokens=123),
                ),
            ),
        ]
        extractor._provided_groq_client = client
        extractor._provided_fallback_groq_client = None

        with self.assertLogs(level="INFO") as logs:
            response_text = extractor._generate_groq(
                "synthetic prompt",
                strict_schema={"type": "object"},
            )

        self.assertEqual(json.loads(response_text), {"scholarships": []})
        requests = [call.kwargs for call in client.chat.completions.create.call_args_list]
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["response_format"]["type"], "json_schema")
        self.assertEqual(requests[1]["response_format"], {"type": "json_object"})
        self.assertEqual(requests[1]["max_completion_tokens"], 2_048)
        self.assertEqual(requests[1]["reasoning_effort"], "low")

        output = "\n".join(logs.output)
        self.assertIn("request_mode=json_object reason=json_validate_failed", output)
        self.assertNotIn("failed_generation", output)
        self.assertNotIn("Official private page text", output)
        self.assertNotIn("Synthetic evidence", output)
        self.assertIn("provider_finish_reason=length", output)
        self.assertIn("provider_completion_tokens=987", output)
        self.assertIn("provider_reasoning_tokens=654", output)
        self.assertIn("finish_reason=stop completion_tokens=321 reasoning_tokens=123", output)

    def test_json_object_failure_retries_once_on_same_selected_slot_and_limiter(self):
        extractor = _extractor()
        extractor.settings.groq_fallback_enabled = True
        extractor.settings.groq_organization_id = "primary-test-org"
        extractor.settings.groq_fallback_organization_id = "fallback-test-org"
        extractor.settings.groq_max_completion_tokens = 64
        extractor.settings.groq_rate_limit_retries = 3

        primary = Mock()
        primary.chat.completions.create.side_effect = _ProviderBodyFailure(
            503,
            "messages",
        )
        secondary = Mock()
        secondary.chat.completions.create.side_effect = [
            _ProviderBodyFailure(
                400,
                "response_format",
                code="json_validate_failed",
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content='{"scholarships": []}'),
                )],
            ),
        ]
        extractor._provided_groq_client = primary
        extractor._provided_fallback_groq_client = secondary

        primary_limiter = _TrackingLimiter()
        fallback_limiter = _TrackingLimiter()

        def limiter_for(_settings, organization_id, _model):
            return {
                "primary-test-org": primary_limiter,
                "fallback-test-org": fallback_limiter,
            }[organization_id]

        with (
            patch("app.services.groq_provider._rate_limiter_for", side_effect=limiter_for),
            patch("app.services.groq_provider._UNAVAILABLE_KEY_SLOTS", set()),
        ):
            result = extractor._generate_groq("Synthetic extraction prompt.")

        self.assertEqual(json.loads(result), {"scholarships": []})
        primary.chat.completions.create.assert_called_once()
        secondary.chat.completions.create.assert_has_calls([
            unittest.mock.call(
                model="offline-groq",
                messages=[
                    {"role": "system", "content": unittest.mock.ANY},
                    {"role": "user", "content": "Synthetic extraction prompt."},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
                max_completion_tokens=64,
            ),
            unittest.mock.call(
                model="offline-groq",
                messages=[
                    {"role": "system", "content": unittest.mock.ANY},
                    {"role": "user", "content": "Synthetic extraction prompt."},
                ],
                temperature=0.1,
                max_completion_tokens=64,
            ),
        ])
        self.assertEqual(secondary.chat.completions.create.call_count, 2)
        self.assertEqual(len(primary_limiter.reservations), 1)
        self.assertEqual(len(fallback_limiter.reservations), 2)
        self.assertIsNot(
            fallback_limiter.reservations[0],
            fallback_limiter.reservations[1],
        )
        self.assertEqual(len(fallback_limiter.releases), 2)

    def test_plain_text_retry_requires_exact_json_validation_error(self):
        cases = (
            (400, "invalid_json_schema", "invalid_request_error"),
            (400, "json_validate_failed", "provider_error"),
            (413, "json_validate_failed", "invalid_request_error"),
        )
        for status, code, error_type in cases:
            with self.subTest(status=status, code=code, error_type=error_type):
                extractor = _extractor()
                client = Mock()
                client.chat.completions.create.side_effect = _ProviderBodyFailure(
                    status,
                    "response_format",
                    code=code,
                    error_type=error_type,
                )
                secondary = Mock()
                extractor._provided_groq_client = client
                extractor._provided_fallback_groq_client = secondary

                with self.assertRaises(ScholarshipExtractionError):
                    extractor._generate_groq("Synthetic extraction prompt.")

                client.chat.completions.create.assert_called_once()
                secondary.chat.completions.create.assert_not_called()

    def test_json_validation_error_without_attempt_context_does_not_retry(self):
        extractor = _extractor()
        extractor._provided_groq_client = Mock()
        provider_error = GroqProviderError(
            "malformed_request",
            400,
            {
                "type": "invalid_request_error",
                "code": "json_validate_failed",
            },
        )

        with (
            patch(
                "app.services.scholarship_discovery_extraction.generate_json_completion",
                side_effect=provider_error,
            ),
            patch(
                "app.services.scholarship_discovery_extraction.generate_text_completion",
            ) as text_completion,
            self.assertRaises(ScholarshipExtractionError),
        ):
            extractor._generate_groq("Synthetic extraction prompt.")

        text_completion.assert_not_called()

    def test_rate_limit_error_does_not_trigger_json_format_fallback(self):
        extractor = _extractor()
        client = Mock()
        client.chat.completions.create.side_effect = _ProviderBodyFailure(
            429,
            "response_format",
            code="rate_limit_exceeded",
            error_type="tokens",
        )
        extractor._provided_groq_client = client
        extractor._provided_fallback_groq_client = None

        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor._generate_groq(
                "Synthetic extraction prompt.",
                strict_schema={"type": "object"},
            )

        self.assertEqual(raised.exception.category, "quota_error")
        client.chat.completions.create.assert_called_once()

    def test_plain_text_retry_is_not_retried_after_its_single_attempt(self):
        extractor = _extractor()
        extractor.settings.groq_rate_limit_retries = 3
        client = Mock()
        client.chat.completions.create.side_effect = [
            _ProviderBodyFailure(400, "response_format", code="json_validate_failed"),
            _ProviderBodyFailure(400, "messages", code="json_validate_failed"),
        ]
        extractor._provided_groq_client = client
        extractor._provided_fallback_groq_client = None

        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor._generate_groq("Synthetic extraction prompt.")

        self.assertEqual(raised.exception.category, "json_validation_failed")
        self.assertEqual(client.chat.completions.create.call_count, 2)
        self.assertEqual(
            client.chat.completions.create.call_args_list[1].kwargs.get(
                "response_format",
            ),
            None,
        )

    def test_malformed_plain_text_retry_response_is_rejected(self):
        extractor = _extractor()
        client = Mock()
        client.chat.completions.create.side_effect = [
            _ProviderBodyFailure(400, "response_format", code="json_validate_failed"),
            SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content="This is not JSON."),
                )],
            ),
        ]
        extractor._provided_groq_client = client
        extractor._provided_fallback_groq_client = None

        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor._generate_groq("Synthetic extraction prompt.")

        self.assertEqual(raised.exception.category, "malformed_response")
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_plain_text_fallback_still_rejects_invalid_extraction_evidence(self):
        extractor = _extractor()
        block = (
            "The Finland Master's Scholarship is available to Master's students. "
            "Host country: Finland. Funding: EUR 24,000. Deadline: 30 June 2027. "
            "Duration: 24 months. Requirements: official transcript."
        )
        candidate = {
            "values": {
                "name": "Finland Master's Scholarship",
                "country": "Finland",
                "degree_level": "Master",
            },
            "evidence": {
                "name": "This quote is not present on the source page.",
            },
            "host_city": "",
            "masters_only": True,
            "masters_evidence": "Master's students",
            "scholarship_offer_evidence": "The Finland Master's Scholarship is available",
        }
        client = Mock()
        client.chat.completions.create.side_effect = [
            _ProviderBodyFailure(400, "response_format", code="json_validate_failed"),
            SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"scholarships": [candidate]}),
                    ),
                )],
            ),
        ]
        extractor._provided_groq_client = client
        extractor._provided_fallback_groq_client = None

        result = extractor.extract(_page(block), _source())

        self.assertEqual(result, [])
        self.assertEqual(extractor.last_rejected_count, 1)
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_tolerant_fallback_parser_handles_fences_and_trailing_text(self):
        self.assertEqual(
            _parse_extraction_response(
                '```json\n{"scholarships": []}\n```\nextra text',
                tolerant=True,
            ),
            {"scholarships": []},
        )
        self.assertEqual(
            _parse_extraction_response(
                'Model response: {"scholarships": []} trailing explanation',
                tolerant=True,
            ),
            {"scholarships": []},
        )

    def test_tolerant_fallback_parser_reports_truncated_json(self):
        with self.assertRaises(ScholarshipExtractionError) as raised:
            _parse_extraction_response(
                '{"scholarships": [{"values":',
                tolerant=True,
            )

        self.assertEqual(raised.exception.category, "malformed_response")
        self.assertIn("truncated_json_object", str(raised.exception))

    def test_groq_400_other_reasons_no_retry(self):
        """Non-schema HTTP 400 does not retry the format or secondary key."""
        extractor = _extractor()
        extractor.settings.groq_model = "openai/gpt-oss-20b"
        primary = Mock()
        primary.chat.completions.create.side_effect = _ProviderBodyFailure(400, "messages")
        secondary = Mock()
        extractor._provided_groq_client = primary
        extractor._provided_fallback_groq_client = secondary

        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor._generate_groq("synthetic prompt")

        self.assertEqual(raised.exception.http_status, 400)
        primary.chat.completions.create.assert_called_once()
        secondary.chat.completions.create.assert_not_called()

    def test_groq_413_preserves_sanitized_provider_code_and_parameter(self):
        error = Exception("offline provider error")
        error.status_code = 413
        error.body = {
            "error": {
                "code": "request_too_large",
                "param": "messages",
                "message": "The request is too large.",
            },
        }
        client = Mock()
        client.chat.completions.create.side_effect = error

        with self.assertRaises(GroqProviderError) as raised:
            generate_json_completion(
                client,
                model="offline-groq",
                system_instruction="instruction",
                contents="content",
            )

        self.assertEqual(raised.exception.category, "payload_too_large")
        self.assertEqual(raised.exception.http_status, 413)
        self.assertEqual(raised.exception.provider_error_details["code"], "request_too_large")
        self.assertEqual(raised.exception.provider_error_details["param"], "messages")

    def test_generate_groq_uses_groq_specific_request_byte_cap(self):
        extractor = _extractor()
        extractor.settings.max_provider_request_bytes = 512_000
        extractor.settings.groq_max_request_bytes = 1_024

        with self.assertRaises(ScholarshipExtractionError) as raised:
            extractor._generate_groq("x" * 4_096)

        self.assertEqual(raised.exception.category, "payload_too_large")
        extractor._provided_groq_client.chat.completions.create.assert_not_called()

if __name__ == "__main__":
    unittest.main()
