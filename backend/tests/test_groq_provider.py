import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.core.config import scholarship_discovery_settings
from app.services.scholarship_discovery_extraction import (
    _groq_client,
    _groq_fallback_client,
)
from app.services.groq_provider import (
    DEFAULT_GROQ_MAX_COMPLETION_TOKENS,
    _GroqRequestLimiter,
    _rate_limiter_for,
    _provider_error_summary_for_log,
    _safe_model_identifier,
    GroqProviderError,
    generate_json_completion,
    generate_text_completion,
)
from app.services.scholarship_discovery_budget import (
    DiscoveryRunBudget,
    DiscoveryRunLimitExceeded,
)


def _response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
    )


class _ProviderFailure(Exception):
    def __init__(self, status, message="token=private-value"):
        self.status_code = status
        super().__init__(message)


class _ProviderBodyFailure(Exception):
    status_code = 400

    def __init__(self, body, headers=None):
        self.body = body
        self.response = SimpleNamespace(headers=headers or {})
        super().__init__("raw provider exception")


class GroqFallbackTests(unittest.TestCase):
    def test_environment_key_slots_fallback_after_401_without_logging_key_values(self):
        primary_key = "test-only-primary-key"
        fallback_key = "test-only-fallback-key"
        primary = Mock()
        primary.chat.completions.create.side_effect = _ProviderFailure(
            401,
            message=primary_key,
        )
        secondary = Mock()
        secondary.chat.completions.create.return_value = _response('{"ok":true}')

        with (
            patch.dict(
                "os.environ",
                {
                    "GROQ_API_KEY": primary_key,
                    "GROQ_API_KEY_2": fallback_key,
                },
                clear=True,
            ),
            patch(
                "app.services.scholarship_discovery_extraction._groq_client_instance",
                None,
            ),
            patch(
                "app.services.scholarship_discovery_extraction._groq_fallback_client_instance",
                None,
            ),
            patch("app.services.groq_provider._UNAVAILABLE_KEY_SLOTS", set()),
            patch(
                "app.services.scholarship_discovery_extraction.create_groq_client",
                side_effect=[primary, secondary],
            ) as client_factory,
        ):
            primary_client = _groq_client()
            fallback_client = _groq_fallback_client()
            self.assertEqual(
                client_factory.call_args_list[0].args,
                (primary_key,),
            )
            self.assertEqual(
                client_factory.call_args_list[1].args,
                (fallback_key,),
            )

            with self.assertLogs("app.services.groq_provider", level="WARNING") as logs:
                result = generate_json_completion(
                    primary_client,
                    fallback_client=fallback_client,
                    model="offline-env-key-model",
                    system_instruction="Extract facts.",
                    contents="Synthetic evidence.",
                )

        self.assertEqual(result.choices[0].message.content, '{"ok":true}')
        self.assertNotIn(primary_key, "\n".join(logs.output))
        self.assertNotIn(fallback_key, "\n".join(logs.output))
        primary.chat.completions.create.assert_called_once()
        secondary.chat.completions.create.assert_called_once()

    def test_429_does_not_use_unverified_secondary_key(self):
        primary = Mock()
        primary.chat.completions.create.side_effect = _ProviderFailure(429)
        secondary = Mock()

        with self.assertRaises(GroqProviderError) as raised:
            generate_json_completion(
                primary,
                fallback_client=secondary,
                model="offline-model",
                system_instruction="Extract facts.",
                contents="Synthetic scholarship evidence.",
            )

        self.assertEqual(raised.exception.http_status, 429)
        primary.chat.completions.create.assert_called_once()
        secondary.chat.completions.create.assert_not_called()

    def test_primary_success_does_not_call_secondary_key(self):
        primary = Mock()
        primary.chat.completions.create.return_value = _response('{"ok":true}')
        secondary = Mock()

        generate_json_completion(
            primary,
            fallback_client=secondary,
            model="offline-model",
            system_instruction="Extract facts.",
            contents="Synthetic scholarship evidence.",
        )

        primary.chat.completions.create.assert_called_once()
        secondary.chat.completions.create.assert_not_called()

    def test_secondary_key_can_be_used_when_primary_is_not_configured(self):
        secondary = Mock()
        secondary.chat.completions.create.return_value = _response('{"ok":true}')

        result = generate_json_completion(
            None,
            fallback_client=secondary,
            model="offline-model",
            system_instruction="Extract facts.",
            contents="Synthetic scholarship evidence.",
        )

        self.assertEqual(result.choices[0].message.content, '{"ok":true}')
        secondary.chat.completions.create.assert_called_once()

    def test_primary_and_secondary_json_requests_have_identical_kwargs(self):
        primary = Mock()
        primary.chat.completions.create.return_value = _response('{"ok":true}')
        secondary = Mock()
        secondary.chat.completions.create.return_value = _response('{"ok":true}')
        model = "offline-json-request-parity-model"
        system_instruction = 'Return only this JSON: {"ok":true}'
        contents = 'Return exactly {"ok":true} as JSON.'

        with patch("app.services.groq_provider._UNAVAILABLE_KEY_SLOTS", set()):
            generate_json_completion(
                primary,
                fallback_client=secondary,
                model=model,
                system_instruction=system_instruction,
                contents=contents,
                max_completion_tokens=64,
            )
            primary_kwargs = primary.chat.completions.create.call_args.kwargs
            primary.chat.completions.create.assert_called_once()
            secondary.chat.completions.create.assert_not_called()

            generate_json_completion(
                None,
                fallback_client=secondary,
                model=model,
                system_instruction=system_instruction,
                contents=contents,
                max_completion_tokens=64,
            )
            secondary_kwargs = secondary.chat.completions.create.call_args.kwargs

        self.assertEqual(primary_kwargs, secondary_kwargs)
        self.assertEqual(
            primary_kwargs,
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": contents},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
                "max_completion_tokens": 64,
            },
        )
        primary.chat.completions.create.assert_called_once()
        secondary.chat.completions.create.assert_called_once()

    def test_text_completion_falls_back_and_preserves_generation_parameters(self):
        primary = Mock()
        primary.chat.completions.create.side_effect = _ProviderFailure(503)
        secondary = Mock()
        secondary.chat.completions.create.return_value = _response("Grounded answer.")

        result = generate_text_completion(
            primary,
            fallback_client=secondary,
            model="offline-model",
            system_instruction="Use only supplied evidence.",
            contents="Synthetic evidence and question.",
            temperature=0.2,
        )

        self.assertEqual(result.choices[0].message.content, "Grounded answer.")
        self.assertEqual(
            secondary.chat.completions.create.call_args.kwargs["temperature"],
            0.2,
        )
        self.assertEqual(
            secondary.chat.completions.create.call_args.kwargs["messages"],
            primary.chat.completions.create.call_args.kwargs["messages"],
        )

    def test_fallback_failure_is_sanitized_and_preserves_provider_category(self):
        primary = Mock()
        primary.chat.completions.create.side_effect = _ProviderFailure(503)
        secondary = Mock()
        secondary.chat.completions.create.side_effect = _ProviderFailure(403)

        with self.assertRaises(GroqProviderError) as raised:
            generate_text_completion(
                primary,
                fallback_client=secondary,
                model="offline-model",
                system_instruction="Private prompt.",
                contents="Private scholarship evidence.",
                temperature=0.2,
            )

        self.assertEqual(raised.exception.category, "permission_error")
        self.assertEqual(raised.exception.http_status, 403)
        self.assertNotIn("private-value", str(raised.exception))

    def test_http_400_logs_only_allowlisted_metadata(self):
        client = Mock()
        sensitive_message_markers = (
            "PRIVATE_PROVIDER_MESSAGE_MARKER",
            "private-auth-marker",
            "gsk_private-provider-marker",
        )
        client.chat.completions.create.side_effect = _ProviderBodyFailure(
            {
                "error": {
                    "type": "invalid_request_error",
                    "code": "json_validate_failed",
                    "param": "response_format",
                    "message": (
                        "Failed to validate JSON for synthetic prompt. "
                        + " ".join(sensitive_message_markers)
                        + " " + ("long-provider-message " * 500)
                    ),
                    "failed_generation": (
                        "Synthetic evidence: https://example.test/?token=private-token"
                    ),
                },
            },
            {"x-request-id": "offline-request-123"},
        )

        with self.assertLogs("app.services.groq_provider", level="WARNING") as logs:
            with self.assertRaises(GroqProviderError) as raised:
                generate_json_completion(
                    client,
                    model="offline-model",
                    system_instruction="Synthetic system instruction.",
                    contents="Synthetic prompt.",
                )

        self.assertEqual(raised.exception.category, "malformed_request")
        self.assertEqual(raised.exception.http_status, 400)
        output = "\n".join(logs.output)
        for field in (
            "provider_error_type=invalid_request_error",
            "provider_error_code=json_validate_failed",
            "provider_error_param=response_format",
            "provider_model=offline-model",
            "provider_error_summary=Provider JSON output validation failed.",
        ):
            self.assertIn(field, output)
        self.assertNotIn("private-token", output)
        self.assertNotIn("Synthetic prompt.", output)
        self.assertNotIn("request_id=", output)
        self.assertNotIn("failed_generation", output)
        self.assertNotIn("Failed to validate JSON", output)
        self.assertNotIn("long-provider-message", output)
        for marker in sensitive_message_markers:
            self.assertNotIn(marker, output)

    def test_unknown_provider_error_code_uses_omitted_summary(self):
        client = Mock()
        client.chat.completions.create.side_effect = _ProviderBodyFailure(
            {
                "error": {
                    "type": "invalid_request_error",
                    "code": "private_unknown_code",
                    "message": "PRIVATE_UNKNOWN_PROVIDER_MESSAGE",
                },
            },
        )

        with self.assertLogs("app.services.groq_provider", level="WARNING") as logs:
            with self.assertRaises(GroqProviderError):
                generate_json_completion(
                    client,
                    model="offline-model",
                    system_instruction="Synthetic system instruction.",
                    contents="Synthetic prompt.",
                )

        output = "\n".join(logs.output)
        self.assertIn("provider_error_code=unknown", output)
        self.assertIn("provider_error_summary=[provider message omitted]", output)
        self.assertNotIn("PRIVATE_UNKNOWN_PROVIDER_MESSAGE", output)
        self.assertNotIn("private_unknown_code", output)

    def test_provider_error_summaries_are_fixed_and_allowlisted(self):
        self.assertEqual(
            _provider_error_summary_for_log("json_validate_failed"),
            "Provider JSON output validation failed.",
        )
        self.assertEqual(
            _provider_error_summary_for_log("private_unknown_code"),
            "[provider message omitted]",
        )
        self.assertEqual(
            _provider_error_summary_for_log(None),
            "[provider message omitted]",
        )

    def test_model_identifier_logging_validation_and_length_limit(self):
        self.assertEqual(
            _safe_model_identifier("namespace/model-name.v2"),
            "namespace/model-name.v2",
        )
        for invalid_model in (
            "model name with spaces",
            "gsk_private-model-marker",
            "x" * 81,
            None,
        ):
            with self.subTest(model=invalid_model):
                self.assertIsNone(_safe_model_identifier(invalid_model))

    def test_malformed_provider_error_body_does_not_expose_exception_text(self):
        client = Mock()
        client.chat.completions.create.side_effect = _ProviderBodyFailure(
            "not-json",
        )

        with self.assertLogs("app.services.groq_provider", level="WARNING") as logs:
            with self.assertRaises(GroqProviderError) as raised:
                generate_json_completion(
                    client,
                    model="offline-model",
                    system_instruction="Synthetic instruction.",
                    contents="Synthetic content.",
                )

        self.assertEqual(raised.exception.category, "malformed_request")
        self.assertEqual(raised.exception.http_status, 400)
        self.assertNotIn("raw provider exception", "\n".join(logs.output))

    def test_provider_budget_counts_secondary_key_attempt(self):
        class QuotaError(Exception):
            status_code = 503

        primary = Mock()
        primary.chat.completions.create.side_effect = QuotaError()
        secondary = Mock()
        budget = DiscoveryRunBudget(max_provider_attempts=1, start_deadline_timer=False)
        budget.start()

        try:
            with self.assertRaises(DiscoveryRunLimitExceeded) as raised:
                generate_json_completion(
                    primary,
                    fallback_client=secondary,
                    model="offline-model",
                    system_instruction="Extract facts.",
                    contents="Synthetic evidence.",
                    run_budget=budget,
                )
        finally:
            budget.close()

        self.assertEqual(raised.exception.resource, "provider_attempts")
        primary.chat.completions.create.assert_called_once()
        secondary.chat.completions.create.assert_not_called()


class GroqRateLimitTests(unittest.TestCase):
    def test_large_prompt_is_not_blocked_by_local_token_estimate(self):
        client = Mock()
        client.chat.completions.create.return_value = _response('{"ok":true}')
        contents = "x" * 100_000
        settings = SimpleNamespace(
            groq_rate_limit_retries=0,
            groq_organization_id="large-prompt-test-org",
            groq_rpm_limit=None,
        )

        result = generate_json_completion(
            client,
            model="offline-large-prompt-model",
            system_instruction="Extract facts.",
            contents=contents,
            rate_limit_settings=settings,
        )

        self.assertEqual(result.choices[0].message.content, '{"ok":true}')
        client.chat.completions.create.assert_called_once()
        self.assertEqual(
            client.chat.completions.create.call_args.kwargs["messages"][1]["content"],
            contents,
        )

    def test_rpm_window_waits_until_old_requests_expire(self):
        class FakeClock:
            now = 0.0
            waits = []

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.waits.append(seconds)
                self.now += seconds

        clock = FakeClock()
        limiter = _GroqRequestLimiter(
            max_concurrent_requests=1,
            rpm_limit=2,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )

        for _ in range(2):
            reservation = limiter.acquire()
            limiter.release(reservation)
        reservation = limiter.acquire()
        limiter.release(reservation)

        self.assertEqual(clock.waits, [60.0])

    def test_limiter_semaphore_caps_concurrent_requests(self):
        limiter = _GroqRequestLimiter(
            max_concurrent_requests=1,
        )
        first_acquired = threading.Event()
        release_first = threading.Event()
        second_acquired = threading.Event()

        def first_request():
            reservation = limiter.acquire()
            first_acquired.set()
            release_first.wait(timeout=2)
            limiter.release(reservation)

        def second_request():
            first_acquired.wait(timeout=2)
            reservation = limiter.acquire()
            second_acquired.set()
            limiter.release(reservation)

        first = threading.Thread(target=first_request)
        second = threading.Thread(target=second_request)
        first.start()
        second.start()
        try:
            self.assertTrue(first_acquired.wait(timeout=1))
            self.assertFalse(second_acquired.wait(timeout=0.05))
        finally:
            release_first.set()
            first.join(timeout=1)
            second.join(timeout=1)

        self.assertTrue(second_acquired.is_set())

    def test_concurrent_requests_respect_rpm_limit(self):
        limiter = _GroqRequestLimiter(
            max_concurrent_requests=2,
            rpm_limit=1,
        )
        barrier = threading.Barrier(3)
        results = []
        results_lock = threading.Lock()

        def reserve():
            barrier.wait(timeout=1)
            result = limiter.try_acquire()
            with results_lock:
                results.append(result)

        threads = [threading.Thread(target=reserve) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=1)
        for thread in threads:
            thread.join(timeout=1)

        acquired = [reservation for reservation, _ in results if reservation is not None]
        waits = [wait for reservation, wait in results if reservation is None]
        self.assertEqual(len(acquired), 1)
        self.assertEqual(len(waits), 1)
        self.assertGreater(waits[0], 0)
        limiter.release(acquired[0])

    def test_tpm_window_waits_for_available_organization_capacity(self):
        class FakeClock:
            now = 0.0
            waits = []

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.waits.append(seconds)
                self.now += seconds

        clock = FakeClock()
        limiter = _GroqRequestLimiter(
            max_concurrent_requests=1,
            tpm_limit=8_000,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )
        limiter.observe_provider_tpm(
            {"limit_type": "TPM", "limit": 8_000, "used": 6_275},
        )
        client = Mock()
        client.chat.completions.create.return_value = _response('{"ok":true}')

        result = generate_json_completion(
            client,
            model="offline-tpm-window-model",
            system_instruction="Extract facts.",
            contents="Synthetic evidence.",
            rate_limit_settings=SimpleNamespace(groq_rate_limit_retries=0),
            rate_limiter=limiter,
            estimated_request_tokens=4_564,
        )

        self.assertEqual(result.choices[0].message.content, '{"ok":true}')
        self.assertEqual(clock.waits, [60.0])
        client.chat.completions.create.assert_called_once()

    def test_tpm_429_usage_delays_retry_until_the_window_has_capacity(self):
        class FakeClock:
            now = 0.0
            waits = []

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.waits.append(seconds)
                self.now += seconds

        class TpmRateLimitFailure(Exception):
            status_code = 429
            body = {
                "error": {
                    "message": (
                        "Limit reached on tokens per minute (TPM): Limit 8000, "
                        "Used 6275, Requested 4564. Please try again in 1.5s."
                    ),
                },
            }
            response = SimpleNamespace(headers={})

        clock = FakeClock()
        limiter = _GroqRequestLimiter(
            max_concurrent_requests=1,
            tpm_limit=8_000,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )
        client = Mock()
        client.chat.completions.create.side_effect = [
            TpmRateLimitFailure(),
            _response('{"ok":true}'),
        ]

        with patch("app.services.groq_provider._rate_limit_jitter", return_value=0):
            result = generate_json_completion(
                client,
                model="offline-tpm-retry-model",
                system_instruction="Extract facts.",
                contents="Synthetic evidence.",
                rate_limit_settings=SimpleNamespace(
                    groq_rate_limit_retries=1,
                    groq_organization_id="tpm-retry-org",
                    groq_tpm_limit=8_000,
                ),
                rate_limiter=limiter,
                estimated_request_tokens=4_564,
            )

        self.assertEqual(result.choices[0].message.content, '{"ok":true}')
        self.assertEqual(clock.waits, [60.0])
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_request_over_tpm_single_request_budget_is_rejected_locally(self):
        client = Mock()
        limiter = _GroqRequestLimiter(
            max_concurrent_requests=1,
            tpm_limit=8_000,
        )

        with self.assertRaises(GroqProviderError) as raised:
            generate_json_completion(
                client,
                model="offline-tpm-preflight-model",
                system_instruction="Extract facts.",
                contents="Synthetic evidence.",
                rate_limit_settings=SimpleNamespace(groq_rate_limit_retries=0),
                rate_limiter=limiter,
                estimated_request_tokens=7_500,
            )

        self.assertEqual(raised.exception.category, "payload_too_large")
        self.assertEqual(
            raised.exception.limit_details,
            {"limit_type": "TPM", "limit": 8_000, "requested": 7_500},
        )
        client.chat.completions.create.assert_not_called()

    def test_concurrent_clock_reads_cannot_append_reservations_out_of_order(self):
        slow_clock_entered = threading.Event()
        fast_call_finished = threading.Event()
        results = []
        errors = []

        class OrderedClock:
            def monotonic(self):
                if threading.current_thread().name == "slow-clock-reader":
                    slow_clock_entered.set()
                    fast_call_finished.wait(timeout=0.25)
                    return 0.0
                return 1.0

            def sleep(self, _seconds):
                return None

        clock = OrderedClock()
        limiter = _GroqRequestLimiter(
            max_concurrent_requests=2,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )
        result_lock = threading.Lock()

        def reserve(*, signal_finished=False):
            try:
                reservation, _ = limiter.try_acquire()
                with result_lock:
                    results.append(reservation)
            except Exception as exc:
                errors.append(exc)
            finally:
                if signal_finished:
                    fast_call_finished.set()

        slow = threading.Thread(
            target=reserve,
            name="slow-clock-reader",
        )
        fast = threading.Thread(
            target=reserve,
            kwargs={"signal_finished": True},
            name="fast-clock-reader",
        )
        slow.start()
        self.assertTrue(slow_clock_entered.wait(timeout=1))
        fast.start()
        slow.join(timeout=2)
        fast.join(timeout=2)

        self.assertFalse(errors)
        self.assertEqual(len(results), 2)
        timestamps = [reservation.timestamp for reservation in limiter._reservations]
        self.assertEqual(timestamps, sorted(timestamps))
        for reservation in results:
            limiter.release(reservation)

    def test_per_organization_rpm_limits_use_independent_counters(self):
        settings = SimpleNamespace(
            groq_organization_id="primary-counter-test",
            groq_fallback_organization_id="fallback-counter-test",
            groq_rpm_limit=12,
            groq_fallback_rpm_limit=24,
            groq_tpm_limit=8_000,
            groq_fallback_tpm_limit=4_000,
            groq_max_concurrent_requests=2,
        )

        primary = _rate_limiter_for(settings, "primary-counter-test", "test-model")
        same_org_other_model = _rate_limiter_for(
            settings,
            "primary-counter-test",
            "another-test-model",
        )
        fallback = _rate_limiter_for(settings, "fallback-counter-test", "test-model")

        self.assertIs(primary, same_org_other_model)
        self.assertIsNot(primary, fallback)
        self.assertEqual(primary.rpm_limit, 12)
        self.assertEqual(fallback.rpm_limit, 24)
        self.assertEqual(primary.tpm_limit, 8_000)
        self.assertEqual(fallback.tpm_limit, 4_000)
        primary_reservation = primary.acquire()
        primary.release(primary_reservation)
        fallback_reservation = fallback.try_acquire()[0]
        self.assertIsNotNone(fallback_reservation)
        fallback.release(fallback_reservation)

    def test_primary_rpm_exhaustion_uses_available_secondary(self):
        class FakeClock:
            now = 0.0
            waits = []

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.waits.append(seconds)
                self.now += seconds

        clock = FakeClock()
        limiters = {
            "quota-primary": _GroqRequestLimiter(
                max_concurrent_requests=1,
                rpm_limit=1,
                clock=clock.monotonic,
                sleep=clock.sleep,
            ),
            "quota-secondary": _GroqRequestLimiter(
                max_concurrent_requests=1,
                rpm_limit=1,
                clock=clock.monotonic,
                sleep=clock.sleep,
            ),
        }
        exhausted = limiters["quota-primary"].acquire()
        limiters["quota-primary"].release(exhausted)
        settings = SimpleNamespace(
            groq_rate_limit_retries=0,
            groq_organization_id="quota-primary",
            groq_fallback_organization_id="quota-secondary",
            groq_rpm_limit=1,
            groq_fallback_rpm_limit=1,
            groq_max_concurrent_requests=1,
        )
        primary = Mock()
        secondary = Mock()
        secondary.chat.completions.create.return_value = _response('{"ok":true}')

        with patch(
            "app.services.groq_provider._rate_limiter_for",
            side_effect=lambda _settings, organization, _model: limiters[organization],
        ):
            result = generate_json_completion(
                primary,
                fallback_client=secondary,
                model="offline-quota-selection-model",
                system_instruction="Extract facts.",
                contents="Synthetic evidence.",
                rate_limit_settings=settings,
            )

        self.assertEqual(result.choices[0].message.content, '{"ok":true}')
        primary.chat.completions.create.assert_not_called()
        secondary.chat.completions.create.assert_called_once()
        self.assertEqual(clock.waits, [])

    def test_fallback_waits_for_both_organizations_rpm_limits(self):
        class FakeClock:
            now = 0.0
            waits = []

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.waits.append(seconds)
                self.now += seconds

        class RateLimitFailure(Exception):
            status_code = 429
            body = {"error": {"message": "Please try again in 0s."}}
            response = SimpleNamespace(headers={})

        clock = FakeClock()
        primary_limiter = _GroqRequestLimiter(
            max_concurrent_requests=1,
            rpm_limit=1,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )
        fallback_limiter = _GroqRequestLimiter(
            max_concurrent_requests=1,
            rpm_limit=1,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )
        primary_reservation = primary_limiter.acquire()
        primary_limiter.release(primary_reservation)
        clock.now = 10.0
        fallback_reservation = fallback_limiter.acquire()
        fallback_limiter.release(fallback_reservation)

        settings = SimpleNamespace(
            groq_rate_limit_retries=0,
            groq_organization_id="window-primary",
            groq_fallback_organization_id="window-fallback",
        )
        primary = Mock()
        primary.chat.completions.create.side_effect = RateLimitFailure()
        secondary = Mock()
        secondary.chat.completions.create.return_value = _response('{"ok":true}')

        with patch(
            "app.services.groq_provider._rate_limiter_for",
            side_effect=lambda *args: {
                "window-primary": primary_limiter,
                "window-fallback": fallback_limiter,
            }[args[1]],
        ), patch("app.services.groq_provider._rate_limit_jitter", return_value=0):
            result = generate_json_completion(
                primary,
                fallback_client=secondary,
                model="offline-window-model",
                system_instruction="Extract facts.",
                contents="Synthetic evidence.",
                rate_limit_settings=settings,
            )

        self.assertEqual(result.choices[0].message.content, '{"ok":true}')
        self.assertEqual(clock.waits, [50.0, 10.0])
        self.assertEqual(primary.chat.completions.create.call_count, 1)
        self.assertEqual(secondary.chat.completions.create.call_count, 1)

    def test_both_organizations_429_defer_next_attempt_until_quota_recovery(self):
        class FakeClock:
            now = 0.0
            waits = []

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.waits.append(seconds)
                self.now += seconds

        class RateLimitFailure(Exception):
            status_code = 429
            response = SimpleNamespace(headers={"Retry-After": "5"})

        clock = FakeClock()
        limiters = {
            "both-429-primary": _GroqRequestLimiter(
                max_concurrent_requests=1,
                clock=clock.monotonic,
                sleep=clock.sleep,
            ),
            "both-429-fallback": _GroqRequestLimiter(
                max_concurrent_requests=1,
                clock=clock.monotonic,
                sleep=clock.sleep,
            ),
        }
        settings = SimpleNamespace(
            groq_rate_limit_retries=0,
            groq_organization_id="both-429-primary",
            groq_fallback_organization_id="both-429-fallback",
        )
        primary = Mock()
        primary.chat.completions.create.side_effect = [
            RateLimitFailure(),
            _response('{"ok":true}'),
        ]
        secondary = Mock()
        secondary.chat.completions.create.side_effect = RateLimitFailure()
        limiter_lookup = lambda *args: limiters[args[1]]

        with patch(
            "app.services.groq_provider._rate_limiter_for",
            side_effect=limiter_lookup,
        ), patch("app.services.groq_provider._rate_limit_jitter", return_value=0):
            with self.assertRaises(GroqProviderError):
                generate_json_completion(
                    primary,
                    fallback_client=secondary,
                    model="offline-both-429-model",
                    system_instruction="Extract facts.",
                    contents="Synthetic evidence.",
                    rate_limit_settings=settings,
                )
            result = generate_json_completion(
                primary,
                fallback_client=secondary,
                model="offline-both-429-model",
                system_instruction="Extract facts.",
                contents="Synthetic evidence.",
                rate_limit_settings=settings,
            )

        self.assertEqual(result.choices[0].message.content, '{"ok":true}')
        self.assertEqual(clock.waits, [5.0])
        self.assertEqual(primary.chat.completions.create.call_count, 2)
        self.assertEqual(secondary.chat.completions.create.call_count, 1)

    def test_both_429_responses_wait_for_earliest_recovery_within_retry_budget(self):
        class FakeClock:
            now = 0.0
            waits = []

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.waits.append(seconds)
                self.now += seconds

        class RateLimitFailure(Exception):
            status_code = 429
            response = SimpleNamespace(headers={"Retry-After": "5"})

        clock = FakeClock()
        limiters = {
            "wait-429-primary": _GroqRequestLimiter(
                max_concurrent_requests=1,
                clock=clock.monotonic,
                sleep=clock.sleep,
            ),
            "wait-429-fallback": _GroqRequestLimiter(
                max_concurrent_requests=1,
                clock=clock.monotonic,
                sleep=clock.sleep,
            ),
        }
        settings = SimpleNamespace(
            groq_rate_limit_retries=1,
            groq_organization_id="wait-429-primary",
            groq_fallback_organization_id="wait-429-fallback",
        )
        primary = Mock()
        primary.chat.completions.create.side_effect = [
            RateLimitFailure(),
            _response('{"ok":true}'),
        ]
        secondary = Mock()
        secondary.chat.completions.create.side_effect = RateLimitFailure()

        with patch(
            "app.services.groq_provider._rate_limiter_for",
            side_effect=lambda _settings, organization, _model: limiters[organization],
        ), patch("app.services.groq_provider._rate_limit_jitter", return_value=0):
            result = generate_json_completion(
                primary,
                fallback_client=secondary,
                model="offline-wait-429-model",
                system_instruction="Extract facts.",
                contents="Synthetic evidence.",
                rate_limit_settings=settings,
            )

        self.assertEqual(result.choices[0].message.content, '{"ok":true}')
        self.assertEqual(clock.waits, [5.0])
        self.assertEqual(primary.chat.completions.create.call_count, 2)
        self.assertEqual(secondary.chat.completions.create.call_count, 1)

    def test_rate_limit_retries_are_bounded_per_organization(self):
        class RateLimited(Exception):
            status_code = 429
            response = SimpleNamespace(headers={"Retry-After": "0"})

        limiters = {
            "bounded-primary": _GroqRequestLimiter(
                max_concurrent_requests=1,
            ),
            "bounded-fallback": _GroqRequestLimiter(
                max_concurrent_requests=1,
            ),
        }
        settings = SimpleNamespace(
            groq_rate_limit_retries=2,
            groq_organization_id="bounded-primary",
            groq_fallback_organization_id="bounded-fallback",
        )
        primary = Mock()
        primary.chat.completions.create.side_effect = RateLimited()
        secondary = Mock()
        secondary.chat.completions.create.side_effect = RateLimited()

        with patch(
            "app.services.groq_provider._rate_limiter_for",
            side_effect=lambda _settings, org, _model: limiters[org],
        ), patch("app.services.groq_provider._rate_limit_jitter", return_value=0):
            with self.assertRaises(GroqProviderError) as raised:
                generate_json_completion(
                    primary,
                    fallback_client=secondary,
                    model="offline-bounded-retry-model",
                    system_instruction="Extract facts.",
                    contents="Synthetic evidence.",
                    rate_limit_settings=settings,
                )

        self.assertEqual(raised.exception.http_status, 429)
        self.assertEqual(primary.chat.completions.create.call_count, 3)
        self.assertEqual(secondary.chat.completions.create.call_count, 3)

    def test_invalid_primary_credential_is_skipped_after_fallback_succeeds(self):
        primary = Mock()
        primary.chat.completions.create.side_effect = _ProviderFailure(401)
        secondary = Mock()
        secondary.chat.completions.create.return_value = _response('{"ok":true}')

        with patch("app.services.groq_provider._UNAVAILABLE_KEY_SLOTS", set()):
            generate_json_completion(
                primary,
                fallback_client=secondary,
                model="offline-invalid-key-model",
                system_instruction="Extract facts.",
                contents="Synthetic evidence.",
            )
            generate_json_completion(
                primary,
                fallback_client=secondary,
                model="offline-invalid-key-model",
                system_instruction="Extract facts.",
                contents="Synthetic evidence.",
            )

        primary.chat.completions.create.assert_called_once()
        self.assertEqual(secondary.chat.completions.create.call_count, 2)

    def test_secondary_401_returns_to_primary_after_primary_rpm_recovers(self):
        class FakeClock:
            now = 0.0
            waits = []

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.waits.append(seconds)
                self.now += seconds

        class InvalidKey(Exception):
            status_code = 401

        clock = FakeClock()
        limiters = {
            "secondary-401-primary": _GroqRequestLimiter(
                max_concurrent_requests=1,
                rpm_limit=1,
                clock=clock.monotonic,
                sleep=clock.sleep,
            ),
            "secondary-401-fallback": _GroqRequestLimiter(
                max_concurrent_requests=1,
                clock=clock.monotonic,
                sleep=clock.sleep,
            ),
        }
        full = limiters["secondary-401-primary"].acquire()
        limiters["secondary-401-primary"].release(full)
        settings = SimpleNamespace(
            groq_rate_limit_retries=1,
            groq_organization_id="secondary-401-primary",
            groq_fallback_organization_id="secondary-401-fallback",
        )
        primary = Mock()
        primary.chat.completions.create.return_value = _response('{"ok":true}')
        secondary = Mock()
        secondary.chat.completions.create.side_effect = InvalidKey()
        unavailable_slots = set()

        with patch(
            "app.services.groq_provider._rate_limiter_for",
            side_effect=lambda _settings, org, _model: limiters[org],
        ), patch(
            "app.services.groq_provider._UNAVAILABLE_KEY_SLOTS",
            unavailable_slots,
        ):
            result = generate_json_completion(
                primary,
                fallback_client=secondary,
                model="offline-secondary-401-recovery-model",
                system_instruction="Extract facts.",
                contents="Synthetic evidence.",
                rate_limit_settings=settings,
            )

        self.assertEqual(result.choices[0].message.content, '{"ok":true}')
        self.assertEqual(clock.waits, [60.0])
        primary.chat.completions.create.assert_called_once()
        secondary.chat.completions.create.assert_called_once()
        self.assertEqual(unavailable_slots, {"fallback"})

    def test_secondary_401_waits_for_primary_429_cooldown_then_recovers(self):
        class FakeClock:
            now = 0.0
            waits = []

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.waits.append(seconds)
                self.now += seconds

        class RateLimited(Exception):
            status_code = 429
            response = SimpleNamespace(headers={"Retry-After": "5"})

        class InvalidKey(Exception):
            status_code = 401

        clock = FakeClock()
        limiters = {
            "cooldown-401-primary": _GroqRequestLimiter(
                max_concurrent_requests=1,
                clock=clock.monotonic,
                sleep=clock.sleep,
            ),
            "cooldown-401-fallback": _GroqRequestLimiter(
                max_concurrent_requests=1,
                clock=clock.monotonic,
                sleep=clock.sleep,
            ),
        }
        settings = SimpleNamespace(
            groq_rate_limit_retries=1,
            groq_organization_id="cooldown-401-primary",
            groq_fallback_organization_id="cooldown-401-fallback",
        )
        primary = Mock()
        primary.chat.completions.create.side_effect = [
            RateLimited(),
            _response('{"ok":true}'),
        ]
        secondary = Mock()
        secondary.chat.completions.create.side_effect = InvalidKey()
        unavailable_slots = set()

        with patch(
            "app.services.groq_provider._rate_limiter_for",
            side_effect=lambda _settings, org, _model: limiters[org],
        ), patch(
            "app.services.groq_provider._UNAVAILABLE_KEY_SLOTS",
            unavailable_slots,
        ), patch("app.services.groq_provider._rate_limit_jitter", return_value=0):
            result = generate_json_completion(
                primary,
                fallback_client=secondary,
                model="offline-secondary-401-cooldown-model",
                system_instruction="Extract facts.",
                contents="Synthetic evidence.",
                rate_limit_settings=settings,
            )

        self.assertEqual(result.choices[0].message.content, '{"ok":true}')
        self.assertEqual(clock.waits, [5.0])
        self.assertEqual(primary.chat.completions.create.call_count, 2)
        secondary.chat.completions.create.assert_called_once()
        self.assertEqual(unavailable_slots, {"fallback"})

    def test_invalid_key_fallback_counts_provider_attempts_toward_rpm(self):
        class FakeClock:
            def monotonic(self):
                return 0.0

            def sleep(self, _seconds):
                return None

        clock = FakeClock()
        limiters = {
            "auth-primary": _GroqRequestLimiter(
                max_concurrent_requests=1,
                rpm_limit=10,
                clock=clock.monotonic,
                sleep=clock.sleep,
            ),
            "auth-fallback": _GroqRequestLimiter(
                max_concurrent_requests=1,
                rpm_limit=10,
                clock=clock.monotonic,
                sleep=clock.sleep,
            ),
        }
        settings = SimpleNamespace(
            groq_rate_limit_retries=0,
            groq_organization_id="auth-primary",
            groq_fallback_organization_id="auth-fallback",
        )
        primary = Mock()
        primary.chat.completions.create.side_effect = _ProviderFailure(401)
        secondary = Mock()
        secondary.chat.completions.create.return_value = _response('{"ok":true}')

        with patch(
            "app.services.groq_provider._rate_limiter_for",
            side_effect=lambda _settings, organization, _model: limiters[organization],
        ), patch("app.services.groq_provider._UNAVAILABLE_KEY_SLOTS", set()):
            generate_json_completion(
                primary,
                fallback_client=secondary,
                model="offline-auth-accounting-model",
                system_instruction="Extract facts.",
                contents="Synthetic evidence.",
                rate_limit_settings=settings,
            )

        self.assertEqual(len(limiters["auth-primary"]._reservations), 1)
        self.assertEqual(len(limiters["auth-fallback"]._reservations), 1)

    def test_http_400_and_413_do_not_rotate_to_fallback(self):
        failures = (
            ("http-400", _ProviderFailure(400)),
            ("http-413", _ProviderFailure(413)),
            ("local-malformed", GroqProviderError("malformed_request")),
        )
        for label, failure in failures:
            with self.subTest(failure=label):
                primary = Mock()
                primary.chat.completions.create.side_effect = failure
                secondary = Mock()

                with self.assertRaises(GroqProviderError):
                    generate_json_completion(
                        primary,
                        fallback_client=secondary,
                        model=f"offline-{label}-model",
                        system_instruction="Extract facts.",
                        contents="Synthetic evidence.",
                    )

                primary.chat.completions.create.assert_called_once()
                secondary.chat.completions.create.assert_not_called()

    def test_per_organization_rpm_settings_are_loaded_from_environment(self):
        with patch.dict(
            "os.environ",
            {
                "GROQ_RPM_LIMIT": "12",
                "GROQ_FALLBACK_RPM_LIMIT": "24",
                "GROQ_ORG_ID": "primary-org-test",
                "GROQ_FALLBACK_ORG_ID": "fallback-org-test",
            },
            clear=True,
        ):
            settings = scholarship_discovery_settings()

        self.assertEqual(settings.groq_organization_id, "primary-org-test")
        self.assertEqual(settings.groq_fallback_organization_id, "fallback-org-test")
        self.assertEqual(settings.groq_rpm_limit, 12)
        self.assertEqual(settings.groq_fallback_rpm_limit, 24)

    def test_missing_organization_and_rpm_settings_use_defaults(self):
        with patch.dict("os.environ", {}, clear=True):
            settings = scholarship_discovery_settings()

        self.assertIsNone(settings.groq_organization_id)
        self.assertIsNone(settings.groq_fallback_organization_id)
        self.assertIsNone(settings.groq_rpm_limit)
        self.assertIsNone(settings.groq_fallback_rpm_limit)
        self.assertEqual(settings.groq_tpm_limit, 8_000)
        self.assertEqual(settings.groq_fallback_tpm_limit, 8_000)
        self.assertEqual(settings.groq_max_concurrent_requests, 1)

    def test_tpm_settings_are_loaded_and_fallback_inherits_primary_limit(self):
        with patch.dict(
            "os.environ",
            {
                "GROQ_TPM_LIMIT": "8000",
                "GROQ_FALLBACK_TPM_LIMIT": "4000",
            },
            clear=True,
        ):
            settings = scholarship_discovery_settings()

        self.assertEqual(settings.groq_tpm_limit, 8_000)
        self.assertEqual(settings.groq_fallback_tpm_limit, 4_000)

        with patch.dict(
            "os.environ",
            {"GROQ_TPM_LIMIT": "6000"},
            clear=True,
        ):
            inherited_settings = scholarship_discovery_settings()

        self.assertEqual(inherited_settings.groq_tpm_limit, 6_000)
        self.assertEqual(inherited_settings.groq_fallback_tpm_limit, 6_000)

    def test_zero_tpm_limits_disable_token_admission_caps(self):
        with patch.dict(
            "os.environ",
            {
                "GROQ_TPM_LIMIT": "0",
                "GROQ_FALLBACK_TPM_LIMIT": "0",
            },
            clear=True,
        ):
            settings = scholarship_discovery_settings()

        self.assertIsNone(settings.groq_tpm_limit)
        self.assertIsNone(settings.groq_fallback_tpm_limit)

    def test_zero_rpm_disables_primary_cap_and_fallback_inherits_by_default(self):
        with patch.dict(
            "os.environ",
            {"GROQ_RPM_LIMIT": "0"},
            clear=True,
        ):
            settings = scholarship_discovery_settings()

        self.assertIsNone(settings.groq_rpm_limit)
        self.assertIsNone(settings.groq_fallback_rpm_limit)

    def test_zero_fallback_rpm_disables_only_fallback_cap(self):
        with patch.dict(
            "os.environ",
            {
                "GROQ_RPM_LIMIT": "12",
                "GROQ_FALLBACK_RPM_LIMIT": "0",
            },
            clear=True,
        ):
            settings = scholarship_discovery_settings()

        self.assertEqual(settings.groq_rpm_limit, 12)
        self.assertIsNone(settings.groq_fallback_rpm_limit)

    def test_invalid_rpm_limits_are_rejected(self):
        for name in ("GROQ_RPM_LIMIT", "GROQ_FALLBACK_RPM_LIMIT"):
            for value in ("-1", "1000001", "invalid"):
                with self.subTest(name=name, value=value):
                    with patch.dict("os.environ", {name: value}, clear=True):
                        with self.assertRaises(RuntimeError) as raised:
                            scholarship_discovery_settings()
                    self.assertIn(name, str(raised.exception))

    def test_429_waits_for_provider_retry_after_and_retries_same_key(self):
        class FakeClock:
            now = 0.0
            waits = []

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.waits.append(seconds)
                self.now += seconds

        class RateLimitFailure(Exception):
            status_code = 429

            def __init__(self):
                self.body = {
                    "error": {
                        "message": "Limit exceeded. Please try again in 9.8s."
                    }
                }
                self.response = SimpleNamespace(headers={})
                super().__init__("rate limited")

        clock = FakeClock()
        limiter = _GroqRequestLimiter(
            max_concurrent_requests=1,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )
        settings = SimpleNamespace(
            groq_rate_limit_retries=1,
            groq_organization_id="primary-org",
            groq_fallback_organization_id=None,
        )
        primary = Mock()
        primary.chat.completions.create.side_effect = [
            RateLimitFailure(),
            _response('{"ok":true}'),
        ]
        secondary = Mock()

        with patch("app.services.groq_provider._rate_limit_jitter", return_value=0):
            result = generate_json_completion(
                primary,
                fallback_client=secondary,
                model="offline-model",
                system_instruction="Extract facts.",
                contents="Synthetic evidence.",
                rate_limit_settings=settings,
                rate_limiter=limiter,
            )

        self.assertEqual(result.choices[0].message.content, '{"ok":true}')
        self.assertEqual(clock.waits, [9.8])
        self.assertEqual(primary.chat.completions.create.call_count, 2)
        secondary.chat.completions.create.assert_not_called()
        self.assertEqual(len(limiter._reservations), 2)

    def test_429_respects_groq_rate_limit_reset_headers(self):
        class FakeClock:
            now = 0.0
            waits = []

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.waits.append(seconds)
                self.now += seconds

        class RateLimitFailure(Exception):
            status_code = 429
            response = SimpleNamespace(headers={
                "x-ratelimit-reset-requests": "2s",
                "x-ratelimit-reset-tokens": "3s",
            })

        clock = FakeClock()
        limiter = _GroqRequestLimiter(
            max_concurrent_requests=1,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )
        client = Mock()
        client.chat.completions.create.side_effect = [
            RateLimitFailure(),
            _response('{"ok":true}'),
        ]
        settings = SimpleNamespace(
            groq_rate_limit_retries=1,
            groq_organization_id="reset-header-org",
        )

        with patch("app.services.groq_provider._rate_limit_jitter", return_value=0):
            result = generate_json_completion(
                client,
                model="offline-reset-header-model",
                system_instruction="Extract facts.",
                contents="Synthetic evidence.",
                rate_limit_settings=settings,
                rate_limiter=limiter,
            )

        self.assertEqual(result.choices[0].message.content, '{"ok":true}')
        self.assertEqual(clock.waits, [3.0])
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_nonfinite_or_invalid_rate_limit_headers_use_bounded_backoff(self):
        invalid_values = (
            "NaN",
            "Infinity",
            "-Infinity",
            "1e309",
            "not-a-number",
        )
        for header_name in (
            "Retry-After",
            "x-ratelimit-reset-requests",
            "x-ratelimit-reset-tokens",
        ):
            for value in invalid_values:
                with self.subTest(header=header_name, value=value):
                    class FakeClock:
                        now = 0.0
                        waits = []

                        def monotonic(self):
                            return self.now

                        def sleep(self, seconds):
                            self.waits.append(seconds)
                            self.now += seconds

                    class RateLimited(Exception):
                        status_code = 429

                        def __init__(self):
                            self.response = SimpleNamespace(
                                headers={header_name: value},
                            )

                    clock = FakeClock()
                    limiter = _GroqRequestLimiter(
                        max_concurrent_requests=1,
                        clock=clock.monotonic,
                        sleep=clock.sleep,
                    )
                    client = Mock()
                    client.chat.completions.create.side_effect = [
                        RateLimited(),
                        _response('{"ok":true}'),
                    ]

                    with patch(
                        "app.services.groq_provider._rate_limit_jitter",
                        return_value=0,
                    ):
                        result = generate_json_completion(
                            client,
                            model="offline-invalid-rate-header-model",
                            system_instruction="Extract facts.",
                            contents="Synthetic evidence.",
                            rate_limit_settings=SimpleNamespace(
                                groq_rate_limit_retries=1,
                            ),
                            rate_limiter=limiter,
                        )

                    self.assertEqual(result.choices[0].message.content, '{"ok":true}')
                    self.assertEqual(clock.waits, [1.0])
                    self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_pre_request_cancellation_removes_rpm_reservation(self):
        class FakeClock:
            now = 0.0
            waits = []

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.waits.append(seconds)
                self.now += seconds

        class CancelledBudget:
            def ensure_active(self):
                return None

            def begin_provider_attempt(self, _):
                raise DiscoveryRunLimitExceeded("duration_seconds", 0)

        clock = FakeClock()
        limiter = _GroqRequestLimiter(
            max_concurrent_requests=1,
            rpm_limit=1,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )
        client = Mock()

        with self.assertRaises(DiscoveryRunLimitExceeded):
            generate_json_completion(
                client,
                model="offline-cancelled-model",
                system_instruction="Extract facts.",
                contents="Synthetic evidence.",
                run_budget=CancelledBudget(),
                rate_limit_settings=SimpleNamespace(groq_rate_limit_retries=0),
                rate_limiter=limiter,
            )

        reservation = limiter.acquire()
        limiter.release(reservation)
        self.assertEqual(clock.waits, [])
        self.assertEqual(len(limiter._reservations), 1)
        client.chat.completions.create.assert_not_called()

    def test_timed_out_request_remains_in_rpm_window_until_expiry(self):
        class FakeClock:
            now = 0.0
            waits = []

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.waits.append(seconds)
                self.now += seconds

        clock = FakeClock()
        limiter = _GroqRequestLimiter(
            max_concurrent_requests=1,
            rpm_limit=1,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )
        client = Mock()
        client.chat.completions.create.side_effect = [
            TimeoutError("synthetic timeout"),
            _response('{"ok":true}'),
        ]

        with self.assertRaises(GroqProviderError):
            generate_json_completion(
                client,
                model="offline-timeout-model",
                system_instruction="Extract facts.",
                contents="Synthetic evidence.",
                rate_limiter=limiter,
            )
        result = generate_json_completion(
            client,
            model="offline-timeout-model",
            system_instruction="Extract facts.",
            contents="Synthetic evidence.",
            rate_limiter=limiter,
        )

        self.assertEqual(result.choices[0].message.content, '{"ok":true}')
        self.assertEqual(clock.waits, [60.0])

    def test_same_organization_fallback_is_not_used_for_429(self):
        class RateLimitFailure(Exception):
            status_code = 429

        class FakeClock:
            now = 0.0

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.now += seconds

        clock = FakeClock()
        limiter = _GroqRequestLimiter(
            max_concurrent_requests=1,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )
        settings = SimpleNamespace(
            groq_rate_limit_retries=0,
            groq_organization_id="same-org",
            groq_fallback_organization_id="same-org",
        )
        primary = Mock()
        primary.chat.completions.create.side_effect = RateLimitFailure()
        secondary = Mock()

        with self.assertRaises(GroqProviderError) as raised:
            generate_json_completion(
                primary,
                fallback_client=secondary,
                model="offline-model",
                system_instruction="Extract facts.",
                contents="Synthetic evidence.",
                rate_limit_settings=settings,
                rate_limiter=limiter,
            )

        self.assertEqual(raised.exception.http_status, 429)
        secondary.chat.completions.create.assert_not_called()

    def test_explicitly_separate_organization_can_use_fallback_after_429(self):
        class RateLimitFailure(Exception):
            status_code = 429
            body = {"error": {"message": "Please try again in 0s."}}
            response = SimpleNamespace(headers={})

        settings = SimpleNamespace(
            groq_rate_limit_retries=0,
            groq_max_concurrent_requests=1,
            groq_max_completion_tokens=64,
            groq_organization_id="primary-org",
            groq_fallback_organization_id="separate-org",
        )
        primary = Mock()
        primary.chat.completions.create.side_effect = RateLimitFailure()
        secondary = Mock()
        secondary.chat.completions.create.return_value = _response('{"ok":true}')

        with patch("app.services.groq_provider._rate_limit_jitter", return_value=0):
            result = generate_json_completion(
                primary,
                fallback_client=secondary,
                model="offline-separate-org-model",
                system_instruction="Extract facts.",
                contents="Synthetic evidence.",
                rate_limit_settings=settings,
            )

        self.assertEqual(result.choices[0].message.content, '{"ok":true}')
        primary.chat.completions.create.assert_called_once()
        secondary.chat.completions.create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
