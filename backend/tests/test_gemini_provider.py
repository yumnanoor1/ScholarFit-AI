import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import httpx
import tenacity
from google import genai
from google.genai import _api_client, types

from app.core.config import (
    DEFAULT_GEMINI_MODEL,
    gemini_model,
    scholarship_discovery_settings,
)
from app.services import gemini_provider
from app.services import scholarship_discovery_extraction
from app.services.gemini_provider import (
    GeminiProviderError,
    _gemini_request_body,
    gemini_request_payload_size_bytes,
)
from app.services.groq_provider import generate_json_completion
from app.services.scholarship_discovery_budget import (
    DiscoveryRunBudget,
    DiscoveryRunLimitExceeded,
)


class FakeProviderError(Exception):
    def __init__(self, code, message="sensitive provider detail"):
        self.code = code
        super().__init__(message)


def _mocked_gemini_client(statuses):
    requests = []

    def respond(request):
        requests.append(request)
        status = statuses[min(len(requests) - 1, len(statuses) - 1)]
        return httpx.Response(
            status_code=status,
            json={
                "error": {
                    "code": status,
                    "message": "synthetic offline provider failure",
                    "status": "DEADLINE_EXCEEDED" if status == 504 else "RESOURCE_EXHAUSTED",
                },
            },
            request=request,
        )

    http_client = httpx.Client(
        transport=httpx.MockTransport(respond),
        trust_env=False,
    )
    client = genai.Client(
        api_key="offline-test-key",
        http_options=types.HttpOptions(httpx_client=http_client),
    )
    return client, http_client, requests


def _without_retry_delay():
    retry_args = _api_client.retry_args

    def retry_args_without_delay(options):
        retry_kwargs = retry_args(options)
        retry_kwargs["wait"] = tenacity.wait_none()
        retry_kwargs["sleep"] = lambda _: None
        return retry_kwargs

    # Keep the SDK retry predicate and attempt limit, but avoid wall-clock backoff.
    return patch.object(_api_client, "retry_args", new=retry_args_without_delay)


def _extractor_with_mock_groq(client):
    groq = MagicMock()
    groq.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"scholarships": []})))],
    )
    extractor = scholarship_discovery_extraction.GeminiScholarshipExtractor(
        SimpleNamespace(
            model="offline-gemini-model",
            groq_model="offline-groq-model",
            groq_fallback_enabled=True,
        ),
        client=client,
        groq_client=groq,
    )
    extractor._prompt = Mock(return_value="offline test prompt")
    page = SimpleNamespace(
        text="offline test page",
        url="https://offline.example/",
        links=(),
    )
    source = SimpleNamespace(
        source_id="offline-test-source",
        name="Offline source",
        official_domain="offline.example",
        source_classification="government_authority",
    )
    return extractor, groq, page, source


class GeminiProviderTests(unittest.TestCase):
    def test_shared_model_setting_is_used_and_legacy_override_is_ignored(self):
        with (
            patch.dict(
                os.environ,
                {
                    "GEMINI_MODEL": "gemini-3-flash-preview",
                    "SCHOLARSHIP_DISCOVERY_MODEL": "legacy-model",
                },
                clear=True,
            ),
            patch("app.core.config._legacy_gemini_model_warning_logged", False),
            self.assertLogs("app.core.config", level="WARNING") as logs,
        ):
            model = gemini_model()
            settings = scholarship_discovery_settings()

        self.assertEqual(model, "gemini-3-flash-preview")
        self.assertEqual(settings.model, model)
        self.assertNotIn("legacy-model", "".join(logs.output))

    def test_shared_default_is_not_the_obsolete_model(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(gemini_model(), DEFAULT_GEMINI_MODEL)
            self.assertEqual(DEFAULT_GEMINI_MODEL, "gemini-3-flash-preview")

    def test_missing_api_key_is_categorized_without_client_initialization(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(scholarship_discovery_extraction, "_client_instance", None),
        ):
            with self.assertRaises(GeminiProviderError) as raised:
                scholarship_discovery_extraction._client()

        self.assertEqual(raised.exception.category, "missing_api_key")
        self.assertNotIn("=", str(raised.exception))

    def test_request_uses_bounded_timeout_and_only_transient_retries(self):
        client = Mock()
        client.models.generate_content.return_value = object()

        response = gemini_provider.generate_content(
            client,
            model="gemini-3-flash-preview",
            contents="synthetic test",
            config={"temperature": 0},
        )

        self.assertIsNotNone(response)
        client.models.generate_content.assert_called_once()
        request_config = client.models.generate_content.call_args.kwargs["config"]
        http_options = request_config["http_options"]
        retry_options = http_options.retry_options
        self.assertEqual(http_options.timeout, 60_000)
        self.assertEqual(retry_options.attempts, 2)
        self.assertEqual(retry_options.http_status_codes, [408, 500, 502, 503, 504])
        self.assertNotIn(401, retry_options.http_status_codes)
        self.assertNotIn(403, retry_options.http_status_codes)
        self.assertNotIn(404, retry_options.http_status_codes)
        self.assertNotIn(429, retry_options.http_status_codes)

    def test_controlled_gemini_retries_are_explicit_and_budgeted(self):
        budget = DiscoveryRunBudget(
            max_provider_attempts=2,
            duration_seconds=60,
            sleep=lambda _delay: None,
            start_deadline_timer=False,
        )
        client = Mock()
        client.models.generate_content.side_effect = [
            FakeProviderError(504),
            FakeProviderError(429),
        ]

        try:
            with self.assertRaises(GeminiProviderError) as raised:
                gemini_provider.generate_content(
                    client,
                    model="offline-model",
                    contents="offline test",
                    config={},
                    run_budget=budget,
                )

            self.assertEqual(raised.exception.category, "quota_error")
            self.assertEqual(client.models.generate_content.call_count, 2)
            self.assertEqual(budget.snapshot()["provider_attempts"], 2)
            first_options = client.models.generate_content.call_args_list[0].kwargs[
                "config"
            ]["http_options"]
            self.assertEqual(first_options.retry_options.attempts, 1)
            self.assertEqual(first_options.retry_options.http_status_codes, [])
        finally:
            budget.close()

    def test_gemini_call_is_not_invoked_when_cancellation_wins(self):
        budget = DiscoveryRunBudget(
            duration_seconds=60,
            start_deadline_timer=False,
        )
        client = MagicMock()
        begin_attempt = budget.begin_provider_attempt

        def cancel_after_registration(callback):
            token, remaining = begin_attempt(callback)
            budget._expire()
            return token, remaining

        try:
            with patch.object(
                budget,
                "begin_provider_attempt",
                side_effect=cancel_after_registration,
            ):
                with self.assertRaises(DiscoveryRunLimitExceeded):
                    gemini_provider.generate_content(
                        client,
                        model="offline-model",
                        contents="offline test",
                        config={},
                        run_budget=budget,
                    )

            client.models.generate_content.assert_not_called()
            client.close.assert_called_once()
            self.assertEqual(budget.snapshot()["provider_attempts"], 0)
            self.assertEqual(budget._cancellations, {})
            self.assertEqual(budget._operation_gates, {})
        finally:
            budget.close()

    def test_controlled_provider_cap_stops_before_another_request(self):
        budget = DiscoveryRunBudget(
            max_provider_attempts=1,
            duration_seconds=60,
            sleep=lambda _delay: None,
            start_deadline_timer=False,
        )
        client = Mock()
        client.models.generate_content.side_effect = FakeProviderError(504)

        try:
            with self.assertRaises(DiscoveryRunLimitExceeded) as raised:
                gemini_provider.generate_content(
                    client,
                    model="offline-model",
                    contents="offline test",
                    config={},
                    run_budget=budget,
                )

            self.assertEqual(raised.exception.resource, "provider_attempts")
            client.models.generate_content.assert_called_once()
            self.assertEqual(budget.snapshot()["provider_attempts"], 1)
        finally:
            budget.close()

    def test_controlled_provider_timeout_uses_remaining_deadline(self):
        now = [10.0]
        budget = DiscoveryRunBudget(
            clock=lambda: now[0],
            duration_seconds=3,
            start_deadline_timer=False,
        )
        client = Mock()
        client.models.generate_content.return_value = object()

        try:
            gemini_provider.generate_content(
                client,
                model="offline-model",
                contents="offline test",
                config={},
                run_budget=budget,
            )

            request_options = client.models.generate_content.call_args.kwargs[
                "config"
            ]["http_options"]
            self.assertEqual(request_options.timeout, 3000)
        finally:
            budget.close()

    def test_groq_fallback_attempt_consumes_provider_budget_and_remaining_timeout(self):
        now = [20.0]
        budget = DiscoveryRunBudget(
            clock=lambda: now[0],
            max_provider_attempts=1,
            duration_seconds=4,
            start_deadline_timer=False,
        )
        client = MagicMock()
        client.chat.completions.create.return_value = object()

        try:
            generate_json_completion(
                client,
                model="offline-groq-model",
                system_instruction="offline",
                contents="offline",
                run_budget=budget,
            )

            client.chat.completions.create.assert_called_once()
            self.assertEqual(
                client.chat.completions.create.call_args.kwargs["timeout"],
                4,
            )
            self.assertEqual(budget.snapshot()["provider_attempts"], 1)
        finally:
            budget.close()

    def test_groq_call_is_not_invoked_when_cancellation_wins(self):
        budget = DiscoveryRunBudget(
            duration_seconds=60,
            start_deadline_timer=False,
        )
        client = MagicMock()
        begin_attempt = budget.begin_provider_attempt

        def cancel_after_registration(callback):
            token, remaining = begin_attempt(callback)
            budget._expire()
            return token, remaining

        try:
            with patch.object(
                budget,
                "begin_provider_attempt",
                side_effect=cancel_after_registration,
            ):
                with self.assertRaises(DiscoveryRunLimitExceeded):
                    generate_json_completion(
                        client,
                        model="offline-groq-model",
                        system_instruction="offline",
                        contents="offline",
                        run_budget=budget,
                    )

            client.chat.completions.create.assert_not_called()
            client.close.assert_called_once()
            self.assertEqual(budget.snapshot()["provider_attempts"], 0)
            self.assertEqual(budget._cancellations, {})
            self.assertEqual(budget._operation_gates, {})
        finally:
            budget.close()

    def test_provider_statuses_are_categorized_and_messages_are_redacted(self):
        expected = {
            401: "authentication_error",
            403: "permission_error",
            404: "model_unavailable",
            408: "network_timeout",
            429: "quota_error",
            413: "payload_too_large",
            500: "provider_error",
            503: "provider_error",
            504: "network_timeout",
        }
        for status, category in expected.items():
            with self.subTest(status=status):
                client = Mock()
                client.models.generate_content.side_effect = FakeProviderError(status)
                with self.assertRaises(GeminiProviderError) as raised:
                    gemini_provider.generate_content(
                        client,
                        model="gemini-3-flash-preview",
                        contents="synthetic test",
                        config={},
                    )

                self.assertEqual(raised.exception.category, category)
                self.assertEqual(raised.exception.http_status, status)
                self.assertNotIn("sensitive provider detail", str(raised.exception))

    def test_request_budget_counts_serialized_utf8_payload_and_rejects_before_call(self):
        config = {
            "system_instruction": "System instruction",
            "temperature": 0.1,
            "response_mime_type": "application/json",
        }
        unicode_size = gemini_request_payload_size_bytes("奖" * 20, config)
        ascii_size = gemini_request_payload_size_bytes("a" * 20, config)
        self.assertGreater(unicode_size, ascii_size)

        client = Mock()
        with self.assertRaises(GeminiProviderError) as raised:
            gemini_provider.generate_content(
                client,
                model="offline-model",
                contents="奖" * 20,
                config=config,
                max_request_bytes=unicode_size - 1,
            )

        self.assertEqual(raised.exception.category, "payload_too_large")
        self.assertIsNone(raised.exception.http_status)
        client.models.generate_content.assert_not_called()

    def test_request_size_matches_offline_sdk_transport_body(self):
        requests = []

        def capture(request):
            requests.append(request)
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]},
                request=request,
            )

        http_client = httpx.Client(
            transport=httpx.MockTransport(capture),
            trust_env=False,
        )
        client = genai.Client(
            api_key="offline-test-key",
            http_options=types.HttpOptions(httpx_client=http_client),
        )
        contents = "Eligibility: Master's students; funding €24,000."
        config = {
            "system_instruction": "System instruction",
            "temperature": 0.1,
            "response_mime_type": "application/json",
        }
        expected_body = _gemini_request_body(contents, config)
        expected_size = gemini_request_payload_size_bytes(contents, config)

        try:
            gemini_provider.generate_content(
                client,
                model="offline-model",
                contents=contents,
                config=config,
                max_request_bytes=expected_size,
            )
            self.assertEqual(len(requests), 1)
            self.assertEqual(json.loads(requests[0].content), expected_body)
            self.assertEqual(
                requests[0].content,
                json.dumps(expected_body).encode("utf-8"),
            )
            self.assertEqual(len(requests[0].content), expected_size)
        finally:
            http_client.close()

    def test_timeout_and_network_errors_are_categorized(self):
        for error in (TimeoutError("private timeout detail"), ConnectionError("private network detail")):
            with self.subTest(error=type(error).__name__):
                client = Mock()
                client.models.generate_content.side_effect = error
                with self.assertRaises(GeminiProviderError) as raised:
                    gemini_provider.generate_content(
                        client,
                        model="gemini-3-flash-preview",
                        contents="synthetic test",
                        config={},
                    )
                self.assertEqual(raised.exception.category, "network_timeout")
                self.assertNotIn("private", str(raised.exception))

    def test_sdk_504_then_429_makes_two_attempts_and_triggers_groq_fallback(self):
        client, http_client, requests = _mocked_gemini_client([504, 429])
        extractor, groq, page, source = _extractor_with_mock_groq(client)

        try:
            with _without_retry_delay():
                with self.assertLogs("app.services.scholarship_discovery_extraction", level="WARNING") as logs:
                    self.assertEqual(extractor.extract(page, source), [])

            self.assertEqual(len(requests), 2)
            self.assertTrue(all(request.method == "POST" for request in requests))
            self.assertEqual(groq.chat.completions.create.call_count, 1)
            self.assertTrue(any("provider=gemini category=quota_error" in line for line in logs.output))
        finally:
            http_client.close()

    def test_controlled_gemini_retries_and_groq_fallback_share_provider_budget(self):
        client, http_client, requests = _mocked_gemini_client([504, 429])
        extractor, groq, page, source = _extractor_with_mock_groq(client)
        budget = DiscoveryRunBudget(
            max_provider_attempts=3,
            duration_seconds=60,
            sleep=lambda _delay: None,
            start_deadline_timer=False,
        )
        extractor.run_budget = budget

        try:
            self.assertEqual(extractor.extract(page, source), [])
            self.assertEqual(len(requests), 2)
            groq.chat.completions.create.assert_called_once()
            self.assertEqual(budget.snapshot()["provider_attempts"], 3)
        finally:
            budget.close()
            http_client.close()

    def test_sdk_504_twice_makes_two_attempts_and_classifies_final_timeout(self):
        client, http_client, requests = _mocked_gemini_client([504, 504])

        try:
            with _without_retry_delay():
                with self.assertRaises(GeminiProviderError) as raised:
                    gemini_provider.generate_content(
                        client,
                        model="offline-gemini-model",
                        contents="offline test prompt",
                        config={},
                    )

            self.assertEqual(len(requests), 2)
            self.assertEqual(raised.exception.category, "network_timeout")
            self.assertEqual(raised.exception.http_status, 504)
        finally:
            http_client.close()

    def test_sdk_initial_429_makes_one_attempt_and_triggers_groq_fallback(self):
        client, http_client, requests = _mocked_gemini_client([429])
        extractor, groq, page, source = _extractor_with_mock_groq(client)

        try:
            with _without_retry_delay():
                with self.assertLogs("app.services.scholarship_discovery_extraction", level="WARNING") as logs:
                    self.assertEqual(extractor.extract(page, source), [])

            self.assertEqual(len(requests), 1)
            self.assertEqual(groq.chat.completions.create.call_count, 1)
            self.assertTrue(any("provider=gemini category=quota_error" in line for line in logs.output))
        finally:
            http_client.close()

    def test_final_transient_http_errors_retry_then_fall_back_to_groq(self):
        for status in (500, 503, 504):
            with self.subTest(status=status):
                client, http_client, requests = _mocked_gemini_client([status, status])
                extractor, groq, page, source = _extractor_with_mock_groq(client)

                try:
                    with _without_retry_delay():
                        self.assertEqual(extractor.extract(page, source), [])

                    self.assertEqual(len(requests), 2)
                    self.assertEqual(groq.chat.completions.create.call_count, 1)
                finally:
                    http_client.close()

    def test_final_statusless_network_timeout_retries_then_falls_back(self):
        requests = []

        def timeout(request):
            requests.append(request)
            raise httpx.ReadTimeout("offline mocked timeout", request=request)

        http_client = httpx.Client(
            transport=httpx.MockTransport(timeout),
            trust_env=False,
        )
        client = genai.Client(
            api_key="offline-test-key",
            http_options=types.HttpOptions(httpx_client=http_client),
        )
        extractor, groq, page, source = _extractor_with_mock_groq(client)

        try:
            with _without_retry_delay():
                with self.assertLogs(
                    "app.services.scholarship_discovery_extraction",
                    level="WARNING",
                ) as logs:
                    self.assertEqual(extractor.extract(page, source), [])

            self.assertEqual(len(requests), 2)
            self.assertEqual(groq.chat.completions.create.call_count, 1)
            self.assertTrue(any("category=network_timeout" in line for line in logs.output))
        finally:
            client.close()
            http_client.close()

    def test_controlled_statusless_network_timeout_retries_and_counts_groq(self):
        client = MagicMock()
        client.models.generate_content.side_effect = [
            TimeoutError("offline mocked timeout"),
            TimeoutError("offline mocked timeout"),
        ]
        extractor, groq, page, source = _extractor_with_mock_groq(client)
        budget = DiscoveryRunBudget(
            max_provider_attempts=3,
            duration_seconds=60,
            sleep=lambda _delay: None,
            start_deadline_timer=False,
        )
        extractor.run_budget = budget

        try:
            self.assertEqual(extractor.extract(page, source), [])
            self.assertEqual(client.models.generate_content.call_count, 2)
            self.assertEqual(groq.chat.completions.create.call_count, 1)
            self.assertEqual(budget.snapshot()["provider_attempts"], 3)
        finally:
            budget.close()

    def test_groq_fallback_reports_shared_budget_exhaustion(self):
        client = MagicMock()
        client.models.generate_content.side_effect = FakeProviderError(429)
        extractor, groq, page, source = _extractor_with_mock_groq(client)
        budget = DiscoveryRunBudget(
            max_provider_attempts=1,
            duration_seconds=60,
            sleep=lambda _delay: None,
            start_deadline_timer=False,
        )
        extractor.run_budget = budget

        try:
            with self.assertLogs(
                "app.services.scholarship_discovery_extraction",
                level="WARNING",
            ) as logs:
                with self.assertRaises(DiscoveryRunLimitExceeded) as raised:
                    extractor.extract(page, source)

            self.assertEqual(raised.exception.resource, "provider_attempts")
            self.assertEqual(budget.snapshot()["provider_attempts"], 1)
            groq.chat.completions.create.assert_not_called()
            self.assertTrue(any("category=budget_exhausted" in line for line in logs.output))
        finally:
            budget.close()

    def test_missing_groq_key_is_classified_without_disclosure(self):
        client = MagicMock()
        client.models.generate_content.side_effect = FakeProviderError(429)
        extractor, groq, page, source = _extractor_with_mock_groq(client)
        extractor._provided_groq_client = None

        with (
            patch.dict(os.environ, {"GROQ_API_KEY": ""}),
            patch.object(scholarship_discovery_extraction, "_groq_client_instance", None),
        ):
            with self.assertLogs(
                "app.services.scholarship_discovery_extraction",
                level="WARNING",
            ) as logs:
                with self.assertRaises(
                    scholarship_discovery_extraction.ScholarshipExtractionError
                ) as raised:
                    extractor.extract(page, source)

        self.assertEqual(raised.exception.category, "missing_api_key")
        self.assertEqual(raised.exception.http_status, None)
        groq.chat.completions.create.assert_not_called()
        self.assertNotIn("offline-test-key", "\n".join(logs.output))

    def test_gemini_malformed_json_does_not_fall_back(self):
        client = MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(text="not-json")
        extractor, groq, page, source = _extractor_with_mock_groq(client)

        with self.assertRaises(
            scholarship_discovery_extraction.ScholarshipExtractionError
        ) as raised:
            extractor.extract(page, source)

        self.assertEqual(raised.exception.category, "malformed_response")
        groq.chat.completions.create.assert_not_called()

    def test_sdk_413_is_single_attempt_and_does_not_invoke_groq(self):
        client, http_client, requests = _mocked_gemini_client([413])
        extractor, groq, page, source = _extractor_with_mock_groq(client)

        try:
            with self.assertRaises(scholarship_discovery_extraction.ScholarshipExtractionError) as raised:
                extractor.extract(page, source)

            self.assertEqual(len(requests), 1)
            self.assertEqual(raised.exception.category, "payload_too_large")
            self.assertEqual(raised.exception.http_status, 413)
            groq.chat.completions.create.assert_not_called()
        finally:
            http_client.close()


if __name__ == "__main__":
    unittest.main()
