"""Small, sanitized adapter for the Groq chat-completions API."""

import json
import logging
import math
import os
import random
import re
import threading
import time
import uuid
from collections import deque
from collections.abc import Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from app.services.scholarship_discovery_budget import (
    MAX_MANUAL_PROVIDER_TIMEOUT_SECONDS,
    DiscoveryRunBudget,
    DiscoveryRunLimitExceeded,
)

logger = logging.getLogger(__name__)
DISCOVERY_FALLBACK_DELAY_SECONDS = 5.0
DEFAULT_GROQ_MAX_COMPLETION_TOKENS = 2_048
DEFAULT_GROQ_RATE_LIMIT_RETRIES = 3
GROQ_TPM_SAFETY_FACTOR = 0.9
GROQ_RATE_LIMIT_WINDOW_SECONDS = 60.0
# Without a run budget, a provider-requested wait longer than this is not worth
# blocking on; the error is raised so the caller can report it instead.
MAX_UNBUDGETED_RATE_LIMIT_WAIT_SECONDS = 120.0
# Statuses the provider returns before it runs any inference, so the request
# spends no tokens. 400 is deliberately absent: json_validate_failed is a 400
# returned after generation, and those tokens were spent.
UNPROCESSED_REQUEST_STATUSES = frozenset({401, 403})
_SAFE_ERROR_CATEGORIES = frozenset({
    "authentication_error",
    "locally_blocked",
    "missing_api_key",
    "malformed_request",
    "model_unavailable",
    "network_timeout",
    "payload_too_large",
    "permission_error",
    "provider_error",
    "quota_error",
    "quota_exhausted",
})
_SAFE_FINISH_REASONS = frozenset({
    "content_filter",
    "function_call",
    "length",
    "stop",
    "tool_calls",
})
_DIAGNOSTIC_ERROR_TYPES = frozenset({"invalid_request_error", "tokens", "requests"})
_DIAGNOSTIC_ERROR_CODES = frozenset({
    "context_length_exceeded",
    "invalid_json_schema",
    "json_validate_failed",
    "rate_limit_exceeded",
    "request_too_large",
    "unsupported_parameter",
})
_DIAGNOSTIC_ERROR_PARAMS = frozenset({"messages", "response_format", "temperature"})
_SAFE_PROVIDER_ERROR_SUMMARIES = {
    "context_length_exceeded": "Provider context length limit exceeded.",
    "invalid_json_schema": "Provider rejected the JSON schema.",
    "json_validate_failed": "Provider JSON output validation failed.",
    "rate_limit_exceeded": "Provider organization rate or token limit exceeded.",
    "request_too_large": "Provider request size limit exceeded.",
    "unsupported_parameter": "Provider rejected an unsupported parameter.",
}
_MODEL_IDENTIFIER_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)?\Z",
)
_MAX_MODEL_IDENTIFIER_LENGTH = 80
# Groq names the exhausted limit in its message, e.g.
# "... on tokens per minute (TPM): Limit 8000, Requested 9965 ...". Only the
# limit label and its integers are kept; the message itself is never retained.
_RATE_LIMIT_DETAIL_PATTERN = re.compile(
    r"\((TPM|TPD|RPM|RPD|ITPM|OTPM)\)\s*:\s*Limit\s+(\d{1,9})"
    r"(?:\s*,\s*Used\s+(\d{1,9}))?(?:\s*,\s*Requested\s+(\d{1,9}))?",
    re.IGNORECASE,
)
_RATE_LIMIT_TYPES = frozenset({"TPM", "TPD", "RPM", "RPD", "ITPM", "OTPM"})
# Per-day limits do not reset inside a run, so retrying them only wastes budget.
_DAILY_LIMIT_TYPES = frozenset({"TPD", "RPD"})

STRICT_STRUCTURED_OUTPUT_MODELS = frozenset({
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
    "meta-models/muse-spark-open",
})
_CLIENTS_BY_ENVIRONMENT: dict[str, tuple[str, object]] = {}
_CLIENTS_LOCK = threading.Lock()
_REQUEST_LIMITERS: dict[str, "_GroqRequestLimiter"] = {}
_REQUEST_LIMITERS_LOCK = threading.Lock()
_UNAVAILABLE_KEY_SLOTS: set[str] = set()
_UNAVAILABLE_KEY_SLOTS_LOCK = threading.Lock()


class GroqProviderError(RuntimeError):
    def __init__(
        self,
        category: str,
        http_status: int | None = None,
        provider_error_details: dict[str, str] | None = None,
        limit_details: dict | None = None,
        completion_metadata: dict | None = None,
    ):
        safe_category = (
            category
            if isinstance(category, str) and category in _SAFE_ERROR_CATEGORIES
            else "provider_error"
        )
        safe_status = (
            http_status
            if isinstance(http_status, int)
            and not isinstance(http_status, bool)
            and 100 <= http_status <= 599
            else None
        )
        self.category = safe_category
        self.http_status = safe_status
        self.provider_error_details = sanitize_groq_error_metadata(
            provider_error_details or {},
        )
        self.limit_details = sanitize_rate_limit_details(limit_details)
        self.completion_metadata = sanitize_completion_metadata(completion_metadata)
        self._attempt_context = None
        suffix = f" (HTTP {safe_status})" if safe_status is not None else ""
        super().__init__(f"Groq request failed: {safe_category}{suffix}")


class _GroqReservation:
    def __init__(self, timestamp: float, request_tokens: int = 0) -> None:
        self.timestamp: float = timestamp
        self.request_tokens: int = request_tokens
        self.released: bool = False


class _GroqRequestLimiter:
    """Thread-safe per-organization RPM, TPM, concurrency, and cooldown limiter."""

    def __init__(
        self,
        *,
        max_concurrent_requests: int,
        rpm_limit: int | None = None,
        tpm_limit: int | None = None,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        self.rpm_limit = (
            rpm_limit
            if isinstance(rpm_limit, int)
            and not isinstance(rpm_limit, bool)
            and rpm_limit > 0
            else None
        )
        self.tpm_limit = (
            tpm_limit
            if isinstance(tpm_limit, int)
            and not isinstance(tpm_limit, bool)
            and tpm_limit > 0
            else None
        )
        self._clock = clock
        self._sleep = sleep
        self._cooldown_until = 0.0
        self._provider_usage_observed_at: float | None = None
        self._provider_used_tokens = 0
        self._lock = threading.Lock()
        self._semaphore = threading.BoundedSemaphore(max_concurrent_requests)
        self._reservations: deque[_GroqReservation] = deque()

    def _expire_locked(self, now: float) -> None:
        cutoff = now - GROQ_RATE_LIMIT_WINDOW_SECONDS
        while self._reservations and self._reservations[0].timestamp <= cutoff:
            self._reservations.popleft()

    def _request_wait_locked(self, now: float) -> float:
        if self.rpm_limit is None or len(self._reservations) < self.rpm_limit:
            return 0.0
        reservation_index = len(self._reservations) - self.rpm_limit
        reservation = self._reservations[reservation_index]
        return max(
            0.0,
            reservation.timestamp + GROQ_RATE_LIMIT_WINDOW_SECONDS - now,
        )

    def _used_tokens_locked(self, now: float) -> int:
        cutoff = now - GROQ_RATE_LIMIT_WINDOW_SECONDS
        reservations = [
            item
            for item in self._reservations
            if item.timestamp > cutoff and item.request_tokens > 0
        ]
        local_tokens = sum(item.request_tokens for item in reservations)
        observed_at = self._provider_usage_observed_at
        if (
            observed_at is None
            or now >= observed_at + GROQ_RATE_LIMIT_WINDOW_SECONDS
        ):
            return local_tokens

        observed_local_tokens = sum(
            item.request_tokens
            for item in reservations
            if item.timestamp <= observed_at
        )
        later_local_tokens = local_tokens - observed_local_tokens
        return max(self._provider_used_tokens, observed_local_tokens) + later_local_tokens

    def _token_wait_locked(self, now: float, request_tokens: int) -> float:
        if self.tpm_limit is None or request_tokens == 0:
            return 0.0
        admission_limit = max(
            1,
            int(self.tpm_limit * GROQ_TPM_SAFETY_FACTOR),
        )
        if request_tokens > admission_limit:
            return 0.0
        if self._used_tokens_locked(now) + request_tokens <= admission_limit:
            return 0.0

        expirations = {
            item.timestamp + GROQ_RATE_LIMIT_WINDOW_SECONDS
            for item in self._reservations
            if item.timestamp > now - GROQ_RATE_LIMIT_WINDOW_SECONDS
            and item.request_tokens > 0
        }
        observed_at = self._provider_usage_observed_at
        if (
            observed_at is not None
            and now < observed_at + GROQ_RATE_LIMIT_WINDOW_SECONDS
        ):
            expirations.add(observed_at + GROQ_RATE_LIMIT_WINDOW_SECONDS)

        for expires_at in sorted(expirations):
            if (
                self._used_tokens_locked(expires_at) + request_tokens
                <= admission_limit
            ):
                return max(0.0, expires_at - now)
        return 0.0

    def request_token_limit_error(
        self,
        request_tokens: int,
    ) -> GroqProviderError | None:
        with self._lock:
            if self.tpm_limit is None:
                return None
            admission_limit = max(
                1,
                int(self.tpm_limit * GROQ_TPM_SAFETY_FACTOR),
            )
            if request_tokens <= admission_limit:
                return None
            return GroqProviderError(
                "payload_too_large",
                limit_details={
                    "limit_type": "TPM",
                    "limit": self.tpm_limit,
                    "requested": request_tokens,
                },
            )

    def observe_provider_tpm(
        self,
        limit_details: Mapping,
        reservation: _GroqReservation | None = None,
    ) -> None:
        details = sanitize_rate_limit_details(limit_details)
        if details.get("limit_type") != "TPM":
            return
        with self._lock:
            now = self._clock()
            self._expire_locked(now)
            provider_limit = details.get("limit")
            if isinstance(provider_limit, int) and provider_limit > 0:
                self.tpm_limit = (
                    provider_limit
                    if self.tpm_limit is None
                    else min(self.tpm_limit, provider_limit)
                )
            if reservation is not None:
                reservation.request_tokens = 0
            provider_used = details.get("used")
            if isinstance(provider_used, int):
                self._provider_usage_observed_at = now
                self._provider_used_tokens = provider_used
                logger.info(
                    "Groq TPM usage observed: limit=%s used=%s",
                    self.tpm_limit if self.tpm_limit is not None else "unknown",
                    provider_used,
                )

    def _wait(self, seconds: float, run_budget: DiscoveryRunBudget | None) -> None:
        if run_budget is not None:
            run_budget.wait(seconds)
        elif seconds > 0:
            self._sleep(seconds)

    def try_acquire(
        self,
        request_tokens: int = 0,
    ) -> tuple[_GroqReservation | None, float]:
        """Reserve immediately, or return the wait before this limiter can admit."""
        if (
            not isinstance(request_tokens, int)
            or isinstance(request_tokens, bool)
            or request_tokens < 0
        ):
            raise GroqProviderError("malformed_request", 400)
        with self._lock:
            now = self._clock()
            self._expire_locked(now)
            token_wait = self._token_wait_locked(now, request_tokens)
            wait_seconds = max(
                self._cooldown_until - now,
                self._request_wait_locked(now),
                token_wait,
            )
            if wait_seconds > 0:
                if token_wait > 0 and token_wait >= wait_seconds:
                    logger.info(
                        "Groq token budget wait: request_tokens=%d "
                        "in_window_tokens=%d tpm_limit=%d wait_seconds=%.2f",
                        request_tokens,
                        self._used_tokens_locked(now),
                        self.tpm_limit or 0,
                        wait_seconds,
                    )
                return None, wait_seconds
            if not self._semaphore.acquire(blocking=False):
                return None, 0.1
            reservation = _GroqReservation(now, request_tokens)
            self._reservations.append(reservation)
            return reservation, 0.0

    def acquire(
        self,
        run_budget: DiscoveryRunBudget | None = None,
        request_tokens: int = 0,
    ) -> _GroqReservation:
        while True:
            if run_budget is not None:
                run_budget.ensure_active()
            reservation, wait_seconds = self.try_acquire(request_tokens)
            if reservation is not None:
                return reservation
            self._wait(wait_seconds, run_budget)

    def release(
        self,
        reservation: _GroqReservation,
        *,
        cancel: bool = False,
    ) -> None:
        with self._lock:
            if reservation.released:
                return
            if cancel:
                try:
                    self._reservations.remove(reservation)
                except ValueError:
                    pass
            reservation.released = True
        self._semaphore.release()

    def discard_reserved_tokens(self, reservation: _GroqReservation) -> None:
        """Give back a reservation's tokens, keeping its request slot.

        For a request the provider refused without running inference: it still
        counted as a request, but it spent no tokens.
        """
        with self._lock:
            reservation.request_tokens = 0

    def defer_for(self, seconds: float) -> None:
        with self._lock:
            self._cooldown_until = max(self._cooldown_until, self._clock() + seconds)

    def wait(self, seconds: float, run_budget: DiscoveryRunBudget | None = None) -> None:
        self._wait(seconds, run_budget)


def _safe_provider_error_label(value) -> str | None:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    label = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value).strip())[:80]
    return label or None


def sanitize_groq_error_metadata(value) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    allowed = {
        "type": _DIAGNOSTIC_ERROR_TYPES,
        "code": _DIAGNOSTIC_ERROR_CODES,
        "param": _DIAGNOSTIC_ERROR_PARAMS,
    }
    sanitized = {}
    for field, permitted_values in allowed.items():
        label = _safe_provider_error_label(value.get(field))
        if label in permitted_values:
            sanitized[field] = label
    return sanitized


def sanitize_rate_limit_details(value) -> dict:
    """Keep only a known limit label and bounded non-negative integers."""
    if not isinstance(value, Mapping):
        return {}
    limit_type = value.get("limit_type")
    if (
        not isinstance(limit_type, str)
        or limit_type.strip().upper() not in _RATE_LIMIT_TYPES
    ):
        return {}
    details = {"limit_type": limit_type.strip().upper()}
    for field in ("limit", "used", "requested"):
        number = value.get(field)
        if (
            isinstance(number, int)
            and not isinstance(number, bool)
            and 0 <= number <= 1_000_000_000
        ):
            details[field] = number
    return details


def extract_rate_limit_details(body: Mapping | None, fallback_text: str = "") -> dict:
    """Parse which Groq limit was hit, and its integers, without keeping the message."""
    message = _nested_error_value(body, "message") if body is not None else None
    if not isinstance(message, str):
        message = fallback_text if isinstance(fallback_text, str) else ""
    match = _RATE_LIMIT_DETAIL_PATTERN.search(message[:4096])
    if match is None:
        return {}
    limit_type, limit, used, requested = match.groups()
    return sanitize_rate_limit_details({
        "limit_type": limit_type,
        "limit": int(limit),
        "used": int(used) if used is not None else None,
        "requested": int(requested) if requested is not None else None,
    })


def sanitize_provider_message_for_log(message: str | None) -> str | None:
    if not isinstance(message, str) or not message.strip():
        return None
    return "[provider message omitted]"


def _provider_error_summary_for_log(error_code: str | None) -> str:
    if not isinstance(error_code, str):
        return "[provider message omitted]"
    return _SAFE_PROVIDER_ERROR_SUMMARIES.get(
        error_code,
        "[provider message omitted]",
    )


def _safe_model_identifier(model) -> str | None:
    if not isinstance(model, str):
        return None
    identifier = model.strip()
    if (
        not identifier
        or len(identifier) > _MAX_MODEL_IDENTIFIER_LENGTH
        or not _MODEL_IDENTIFIER_PATTERN.fullmatch(identifier)
        or identifier.casefold().startswith(("gsk_", "bearer", "sk-"))
    ):
        return None
    return identifier


def _read_error_body(exc: Exception) -> Mapping | None:
    body = getattr(exc, "body", None)
    if body is None:
        return None
    if isinstance(body, str):
        if len(body) > 65_536:
            return None
        try:
            body = json.loads(body)
        except (TypeError, ValueError):
            return None
    if isinstance(body, Mapping):
        return body
    # If body is a dict-like object that isn't a Mapping subtype,
    # try to convert it to a dict for downstream compatibility.
    if isinstance(body, dict):
        return body
    # Fall back to exc.response.json() if available.
    response = getattr(exc, "response", None)
    if response is not None:
        response_json = getattr(response, "json", None)
        if callable(response_json):
            try:
                body = response_json()
                if isinstance(body, Mapping):
                    return body
                if isinstance(body, dict):
                    return body
            except (TypeError, ValueError, AttributeError):
                pass
    return None


def _error_payload_mappings(body: Mapping):
    pending = [(body, 0)]
    seen = set()
    while pending and len(seen) < 32:
        mapping, depth = pending.pop(0)
        if id(mapping) in seen:
            continue
        seen.add(id(mapping))
        yield mapping
        if depth < 5:
            for key in (
                "error",
                "details",
                "data",
                "response",
                "usage",
                "completion_tokens_details",
            ):
                nested = mapping.get(key)
                if isinstance(nested, Mapping):
                    pending.append((nested, depth + 1))


def _nested_error_value(body: Mapping | None, *names: str):
    if body is None:
        return None
    for mapping in _error_payload_mappings(body):
        for name in names:
            value = mapping.get(name)
            if value is not None:
                return value
    return None


def _fallback_has_separate_organizations(settings) -> bool:
    # API-key slots do not reveal organization ownership; only explicitly
    # configured, distinct organization IDs establish separate accounting.
    primary_org = getattr(settings, "groq_organization_id", None)
    fallback_org = getattr(settings, "groq_fallback_organization_id", None)
    return bool(
        isinstance(primary_org, str)
        and primary_org.strip()
        and isinstance(fallback_org, str)
        and fallback_org.strip()
        and primary_org.strip().casefold() != fallback_org.strip().casefold()
    )


def _rate_limiter_for(
    settings,
    organization_id: str,
    _model: str,
) -> _GroqRequestLimiter:
    is_separate_fallback_org = (
        _fallback_has_separate_organizations(settings)
        and organization_id.casefold()
        == settings.groq_fallback_organization_id.strip().casefold()
    )
    if is_separate_fallback_org and hasattr(settings, "groq_fallback_rpm_limit"):
        rpm_limit = settings.groq_fallback_rpm_limit
    else:
        rpm_limit = getattr(settings, "groq_rpm_limit", None)
    if is_separate_fallback_org and hasattr(settings, "groq_fallback_tpm_limit"):
        tpm_limit = settings.groq_fallback_tpm_limit
    else:
        tpm_limit = getattr(settings, "groq_tpm_limit", None)
    max_concurrent_requests = getattr(settings, "groq_max_concurrent_requests", 1)
    key = organization_id.strip().casefold()
    with _REQUEST_LIMITERS_LOCK:
        limiter = _REQUEST_LIMITERS.get(key)
        if limiter is None:
            limiter = _GroqRequestLimiter(
                max_concurrent_requests=max_concurrent_requests,
                rpm_limit=rpm_limit,
                tpm_limit=tpm_limit,
            )
            _REQUEST_LIMITERS[key] = limiter
        return limiter


def _organization_for_key_slot(settings, role: str) -> str:
    if role == "fallback" and _fallback_has_separate_organizations(settings):
        return settings.groq_fallback_organization_id.strip()
    organization_id = getattr(settings, "groq_organization_id", None)
    return organization_id.strip() if isinstance(organization_id, str) and organization_id.strip() else "unverified"


def _key_slot_is_unavailable(role: str) -> bool:
    with _UNAVAILABLE_KEY_SLOTS_LOCK:
        return role in _UNAVAILABLE_KEY_SLOTS


def _mark_key_slot_unavailable(role: str) -> None:
    with _UNAVAILABLE_KEY_SLOTS_LOCK:
        _UNAVAILABLE_KEY_SLOTS.add(role)


def _retry_after_seconds(exc: Exception) -> tuple[float | None, str]:
    cause = exc.__cause__ if isinstance(exc, GroqProviderError) else None
    source = cause or exc
    response = getattr(source, "response", None)
    headers = getattr(response, "headers", None)
    if isinstance(headers, Mapping):
        for name, value in headers.items():
            if not isinstance(name, str) or name.casefold() != "retry-after":
                continue
            try:
                delay = float(value)
            except (TypeError, ValueError):
                try:
                    retry_at = parsedate_to_datetime(str(value))
                except (TypeError, ValueError, OverflowError):
                    break
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
            if math.isfinite(delay) and delay >= 0:
                return delay, "retry_after_header"
        reset_delays = []
        for name, value in headers.items():
            if not isinstance(name, str) or name.casefold() not in {
                "x-ratelimit-reset-requests",
                "x-ratelimit-reset-tokens",
            }:
                continue
            text = str(value).strip().casefold()
            try:
                delay = float(text)
            except ValueError:
                duration = re.fullmatch(
                    r"(?:(\d+(?:\.\d+)?)m)?(\d+(?:\.\d+)?)s",
                    text,
                )
                if duration is None:
                    continue
                delay = (
                    float(duration.group(1) or 0) * 60
                    + float(duration.group(2))
                )
            if math.isfinite(delay) and delay >= 0:
                reset_delays.append(delay)
        if reset_delays:
            return max(reset_delays), "rate_limit_reset_header"

    body = _read_error_body(source)
    message = _nested_error_value(body, "message")
    if not isinstance(message, str):
        message = str(source)
    match = re.search(
        r"\btry\s+again\s+in\s+(\d+(?:\.\d+)?)\s*(?:s|sec(?:ond)?s?)\b",
        message,
        re.IGNORECASE,
    )
    if match:
        return float(match.group(1)), "provider_message"
    return None, "exponential_backoff"


def _rate_limit_jitter() -> float:
    return random.uniform(0.1, 0.5)


def _nonnegative_int(value) -> int | None:
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 1_000_000
    ):
        return value
    return None


def _safe_finish_reason(value) -> str | None:
    label = _safe_provider_error_label(value)
    if label is None:
        return None
    label = label.casefold()
    return label if label in _SAFE_FINISH_REASONS else None


def _log_provider_diagnostic_event(event: str, **fields) -> None:
    logger.info(
        "Groq provider diagnostic event: event=%s",
        event,
        extra={"groq_diagnostic": {"event": event, **fields}},
    )


def completion_metadata_from_response(response) -> dict:
    """Sanitized finish reason and token counts from a successful response."""
    choices = getattr(response, "choices", None)
    choice = choices[0] if isinstance(choices, (list, tuple)) and choices else None
    usage = getattr(response, "usage", None)
    completion_details = getattr(usage, "completion_tokens_details", None)
    return _completion_metadata(
        _safe_finish_reason(getattr(choice, "finish_reason", None)),
        _nonnegative_int(getattr(usage, "completion_tokens", None)),
        _nonnegative_int(getattr(completion_details, "reasoning_tokens", None)),
    )


def completion_metadata_from_error(exc: Exception) -> dict:
    """Sanitized finish reason and token counts carried by an error body."""
    cause = exc.__cause__ if isinstance(exc, GroqProviderError) else None
    body = _read_error_body(cause or exc)
    if body is None:
        return {}
    return _completion_metadata(
        _safe_finish_reason(_nested_error_value(body, "finish_reason")),
        _nonnegative_int(_nested_error_value(body, "completion_tokens")),
        _nonnegative_int(_nested_error_value(body, "reasoning_tokens")),
    )


def _completion_metadata(finish_reason, completion_tokens, reasoning_tokens) -> dict:
    metadata = {}
    if finish_reason is not None:
        metadata["finish_reason"] = finish_reason
    if completion_tokens is not None:
        metadata["completion_tokens"] = completion_tokens
    if reasoning_tokens is not None:
        metadata["reasoning_tokens"] = reasoning_tokens
    return metadata


def sanitize_completion_metadata(value) -> dict:
    """Re-validate metadata from an untrusted caller or a test double."""
    if not isinstance(value, Mapping):
        return {}
    return _completion_metadata(
        _safe_finish_reason(value.get("finish_reason")),
        _nonnegative_int(value.get("completion_tokens")),
        _nonnegative_int(value.get("reasoning_tokens")),
    )


def _log_completion_metadata(
    response,
    key_slot: str,
    request_mode: str,
    *,
    request_id: str,
    attempt_id: str,
    attempt: int,
    retry_count: int,
) -> None:
    choices = getattr(response, "choices", None)
    choice = choices[0] if isinstance(choices, (list, tuple)) and choices else None
    finish_reason = _safe_finish_reason(
        getattr(choice, "finish_reason", None),
    )
    usage = getattr(response, "usage", None)
    completion_tokens = _nonnegative_int(getattr(usage, "completion_tokens", None))
    completion_details = getattr(usage, "completion_tokens_details", None)
    reasoning_tokens = _nonnegative_int(
        getattr(completion_details, "reasoning_tokens", None),
    )
    logger.info(
        "Groq completion received: key_slot=%s request_mode=%s finish_reason=%s "
        "completion_tokens=%s reasoning_tokens=%s",
        key_slot,
        request_mode,
        finish_reason or "not_returned",
        completion_tokens if completion_tokens is not None else "not_returned",
        reasoning_tokens if reasoning_tokens is not None else "not_returned",
    )
    _log_provider_diagnostic_event(
        "attempt_completed",
        request_id=request_id,
        attempt_id=attempt_id,
        key_slot=key_slot,
        request_mode=request_mode,
        http_status=None,
        outcome="succeeded",
        attempt=attempt,
        retry_count=retry_count,
        error_category=None,
        completion_tokens=completion_tokens,
    )


def _sanitize_groq_error_message(
    exc: Exception,
) -> tuple[dict[str, str | None], Mapping | None]:
    body = _read_error_body(exc)
    metadata = sanitize_groq_error_metadata({
        "type": _nested_error_value(body, "type"),
        "code": _nested_error_value(body, "code"),
        "param": _nested_error_value(body, "param"),
    })
    details = {
        "error_type": metadata.get("type", "provider_error"),
        "error_code": metadata.get("code"),
        "error_param": metadata.get("param"),
    }
    return details, body


def _http_status(exc: Exception) -> int | None:
    for attribute in ("status_code", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
            return value
    return None


class LocallyBlockedRequestError(RuntimeError):
    """Raised when a local test harness, diagnostic wrapper, or hard limit blocks a request."""
    locally_blocked = True
    category = "locally_blocked"
    http_status = None


def is_locally_blocked_error(exc: Exception) -> bool:
    if isinstance(exc, LocallyBlockedRequestError):
        return True
    if getattr(exc, "locally_blocked", False) or getattr(exc, "is_locally_blocked", False):
        return True
    if getattr(exc, "category", None) == "locally_blocked":
        return True
    msg = str(exc).casefold()
    if any(
        token in msg
        for token in (
            "hard limit",
            "locally blocked",
            "diagnostic limit",
            "harness limit",
            "mock request limit",
            "local blocker",
        )
    ):
        return True
    name = type(exc).__name__.casefold()
    if "locallyblocked" in name or "diagnosticblocked" in name:
        return True
    return False


def classify_groq_error(exc: Exception) -> tuple[str, int | None]:
    if is_locally_blocked_error(exc):
        return "locally_blocked", None
    status = _http_status(exc)
    if status == 401:
        return "authentication_error", status
    if status == 403:
        return "permission_error", status
    if status == 429:
        return "quota_error", status
    if status in (400, 422):
        return "malformed_request", status
    if status == 404:
        return "model_unavailable", status
    if status == 413:
        return "payload_too_large", status
    if status in (408, 504):
        return "network_timeout", status
    exception_name = type(exc).__name__.casefold()
    if any(token in exception_name for token in ("timeout", "connect", "network", "transport")):
        return "network_timeout", status
    return "provider_error", status


def _groq_request_body(
    model: str,
    system_instruction: str,
    contents: str,
    response_format: dict,
    *,
    max_completion_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> dict:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": contents},
        ],
        "temperature": 0.1,
        "response_format": response_format,
    }
    if max_completion_tokens is not None:
        body["max_completion_tokens"] = max_completion_tokens
    if reasoning_effort is not None:
        body["reasoning_effort"] = reasoning_effort
    return body


def _estimate_request_tokens(request_body: Mapping) -> int:
    """Conservatively estimate prompt plus reserved completion tokens."""
    messages = request_body.get("messages", ())
    characters = 0
    if isinstance(messages, (list, tuple)):
        for message in messages:
            if not isinstance(message, Mapping):
                continue
            content = message.get("content")
            if isinstance(content, str):
                characters += len(content)
            elif isinstance(content, (list, tuple)):
                characters += sum(
                    len(part["text"])
                    for part in content
                    if isinstance(part, Mapping)
                    and isinstance(part.get("text"), str)
                )
    max_completion_tokens = request_body.get(
        "max_completion_tokens",
        DEFAULT_GROQ_MAX_COMPLETION_TOKENS,
    )
    if (
        not isinstance(max_completion_tokens, int)
        or isinstance(max_completion_tokens, bool)
        or max_completion_tokens < 0
    ):
        max_completion_tokens = DEFAULT_GROQ_MAX_COMPLETION_TOKENS
    return math.ceil(characters / 3.2) + max_completion_tokens + 32


def groq_request_payload_size_bytes(
    model: str,
    system_instruction: str,
    contents: str,
    response_format: dict,
    *,
    max_completion_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> int:
    return len(
        json.dumps(
            _groq_request_body(
                model,
                system_instruction,
                contents,
                response_format,
                max_completion_tokens=max_completion_tokens,
                reasoning_effort=reasoning_effort,
            ),
        ).encode("utf-8")
    )


def groq_request_size_breakdown(
    model: str,
    system_instruction: str,
    contents: str,
    response_format: dict,
    *,
    max_completion_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, int]:
    """Return sanitized byte size breakdown of a Groq request payload."""
    system_instruction_bytes = len(system_instruction.encode("utf-8"))
    user_prompt_bytes = len(contents.encode("utf-8"))
    response_schema_bytes = (
        len(json.dumps(response_format).encode("utf-8"))
        if response_format
        else 0
    )
    total_serialized_request_bytes = groq_request_payload_size_bytes(
        model,
        system_instruction,
        contents,
        response_format,
        max_completion_tokens=max_completion_tokens,
        reasoning_effort=reasoning_effort,
    )
    return {
        "system_instruction_bytes": system_instruction_bytes,
        "user_prompt_bytes": user_prompt_bytes,
        "response_schema_bytes": response_schema_bytes,
        "total_serialized_request_bytes": total_serialized_request_bytes,
    }


def groq_response_format(model: str, strict_schema: dict | None = None) -> dict:
    if model in STRICT_STRUCTURED_OUTPUT_MODELS and strict_schema is not None:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "scholarship_extraction",
                "strict": True,
                "schema": strict_schema,
            },
        }
    return {"type": "json_object"}


def create_groq_client(api_key: str):
    if not api_key:
        raise GroqProviderError("missing_api_key")
    try:
        from groq import Groq

        return Groq(api_key=api_key, timeout=60.0, max_retries=0)
    except Exception as exc:
        category, status = classify_groq_error(exc)
        # Preserve the original exception for error-detail extraction
        raise GroqProviderError(category, status) from exc


def groq_client_for_env(environment_variable: str):
    api_key = os.getenv(environment_variable, "").strip()
    if not api_key:
        return None
    with _CLIENTS_LOCK:
        cached = _CLIENTS_BY_ENVIRONMENT.get(environment_variable)
        if cached is not None and cached[0] == api_key:
            return cached[1]
        client = create_groq_client(api_key)
        _CLIENTS_BY_ENVIRONMENT[environment_variable] = (api_key, client)
        return client


def generate_json_completion(
    client,
    *,
    model: str,
    system_instruction: str,
    contents: str,
    strict_schema: dict | None = None,
    max_request_bytes: int | None = None,
    run_budget: DiscoveryRunBudget | None = None,
    fallback_client=None,
    max_completion_tokens: int | None = None,
    reasoning_effort: str | None = None,
    rate_limit_settings=None,
    rate_limiter: _GroqRequestLimiter | None = None,
    estimated_request_tokens: int | None = None,
):
    response_format = groq_response_format(model, strict_schema)
    request_body = _groq_request_body(
        model,
        system_instruction,
        contents,
        response_format,
        max_completion_tokens=max_completion_tokens,
        reasoning_effort=reasoning_effort,
    )
    if (
        max_request_bytes is not None
        and groq_request_payload_size_bytes(
            model,
            system_instruction,
            contents,
            response_format,
            max_completion_tokens=max_completion_tokens,
            reasoning_effort=reasoning_effort,
        ) > max_request_bytes
    ):
        raise GroqProviderError("payload_too_large")
    if estimated_request_tokens is None:
        estimated_request_tokens = _estimate_request_tokens(request_body)
    return _generate_with_fallback(
        client,
        fallback_client,
        request_body,
        run_budget=run_budget,
        rate_limit_settings=rate_limit_settings,
        rate_limiter=rate_limiter,
        estimated_request_tokens=estimated_request_tokens,
    )


def generate_text_completion(
    client,
    *,
    model: str,
    system_instruction: str,
    contents: str,
    temperature: float,
    fallback_client=None,
    rate_limit_settings=None,
    rate_limiter: _GroqRequestLimiter | None = None,
    run_budget: DiscoveryRunBudget | None = None,
    max_completion_tokens: int | None = None,
    reasoning_effort: str | None = None,
    pinned_attempt: tuple[str, object, _GroqRequestLimiter | None] | None = None,
    estimated_request_tokens: int | None = None,
):
    if max_completion_tokens is None:
        max_completion_tokens = getattr(
            rate_limit_settings,
            "groq_max_completion_tokens",
            DEFAULT_GROQ_MAX_COMPLETION_TOKENS,
        )
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": contents},
        ],
        "temperature": temperature,
        "max_completion_tokens": max_completion_tokens,
    }
    if reasoning_effort is not None:
        request_body["reasoning_effort"] = reasoning_effort
    if estimated_request_tokens is None:
        estimated_request_tokens = _estimate_request_tokens(request_body)
    return _generate_with_fallback(
        client,
        fallback_client,
        request_body,
        run_budget=run_budget,
        rate_limit_settings=rate_limit_settings,
        rate_limiter=rate_limiter,
        pinned_attempt=pinned_attempt,
        estimated_request_tokens=estimated_request_tokens,
    )


def _reserve_for_next_attempt(
    attempts: list[tuple[str, object, _GroqRequestLimiter | None]],
    run_budget: DiscoveryRunBudget | None,
    estimated_request_tokens: int,
):
    while True:
        if run_budget is not None:
            run_budget.ensure_active()

        waits = []
        oversized_errors = []
        for role, attempt_client, limiter in attempts:
            if limiter is None:
                return role, attempt_client, None, None
            if isinstance(limiter, _GroqRequestLimiter):
                token_limit_error = limiter.request_token_limit_error(
                    estimated_request_tokens,
                )
                if token_limit_error is not None:
                    oversized_errors.append(token_limit_error)
                    continue
            reservation, wait_seconds = limiter.try_acquire(
                estimated_request_tokens,
            )
            if reservation is not None:
                return role, attempt_client, limiter, reservation
            waits.append((wait_seconds, limiter))

        if not waits and oversized_errors:
            raise oversized_errors[0]
        wait_seconds, wait_limiter = min(waits, key=lambda item: item[0])
        wait_limiter.wait(wait_seconds, run_budget)


def _generate_with_fallback(
    client,
    fallback_client,
    request_body: dict,
    *,
    run_budget: DiscoveryRunBudget | None = None,
    rate_limit_settings=None,
    rate_limiter: _GroqRequestLimiter | None = None,
    pinned_attempt: tuple[str, object, _GroqRequestLimiter | None] | None = None,
    estimated_request_tokens: int = 0,
):
    if pinned_attempt is None:
        configured_attempts = [("primary", client)]
        if fallback_client is not None and fallback_client is not client:
            configured_attempts.append(("fallback", fallback_client))
    else:
        pinned_role, pinned_client, _ = pinned_attempt
        if pinned_role not in {"primary", "fallback"} or pinned_client is None:
            raise GroqProviderError("malformed_request", 400)
        configured_attempts = [(pinned_role, pinned_client)]
    request_id = uuid.uuid4().hex
    unavailable_attempts = [
        role
        for role, attempt_client in configured_attempts
        if attempt_client is not None and _key_slot_is_unavailable(role)
    ]
    attempts = []
    separate_organizations = (
        rate_limit_settings is not None
        and _fallback_has_separate_organizations(rate_limit_settings)
    )
    if pinned_attempt is not None:
        role, attempt_client, limiter = pinned_attempt
        if attempt_client is not None and not _key_slot_is_unavailable(role):
            attempts.append((role, attempt_client, limiter))
    else:
        for role, attempt_client in configured_attempts:
            if attempt_client is None or _key_slot_is_unavailable(role):
                continue
            if rate_limiter is not None and (
                role == "primary" or not separate_organizations
            ):
                limiter = rate_limiter
            elif rate_limit_settings is not None:
                organization = _organization_for_key_slot(rate_limit_settings, role)
                limiter = _rate_limiter_for(
                    rate_limit_settings,
                    organization,
                    request_body["model"],
                )
            else:
                limiter = rate_limiter
            attempts.append((role, attempt_client, limiter))

    if not attempts:
        if unavailable_attempts:
            raise GroqProviderError("authentication_error", 401)
        raise GroqProviderError("missing_api_key")

    request_mode = (
        request_body.get("response_format", {}).get("type", "completion")
        if isinstance(request_body.get("response_format"), Mapping)
        else "completion"
    )
    retry_limit = 0 if pinned_attempt is not None else (
        getattr(
            rate_limit_settings,
            "groq_rate_limit_retries",
            DEFAULT_GROQ_RATE_LIMIT_RETRIES,
        )
        if rate_limit_settings is not None
        else 0
    )
    attempt_counts = {role: 0 for role, _, _ in attempts}
    previous_error = None
    last_error = None
    last_error_cause = None
    preferred_role = None
    retry_only_role = None
    fallback_delay_applied = False
    request_attempt_count = 0

    while True:
        eligible_attempts = [
            attempt
            for attempt in attempts
            if attempt_counts[attempt[0]] < retry_limit + 1
            and not _key_slot_is_unavailable(attempt[0])
            and (retry_only_role is None or attempt[0] == retry_only_role)
        ]
        if not eligible_attempts:
            if retry_only_role is not None and last_error is not None:
                raise last_error from last_error_cause
            if last_error is not None:
                if previous_error is not None and last_error is not previous_error:
                    raise last_error from previous_error
                if last_error_cause is not None:
                    raise last_error from last_error_cause
                raise last_error
            raise GroqProviderError("missing_api_key")

        if preferred_role is not None:
            eligible_attempts.sort(
                key=lambda attempt: attempt[0] != preferred_role,
            )
        if (
            previous_error is not None
            and previous_error.http_status != 429
            and run_budget is not None
            and not fallback_delay_applied
            and eligible_attempts[0][0] == "fallback"
        ):
            run_budget.ensure_active()
            run_budget.wait(DISCOVERY_FALLBACK_DELAY_SECONDS)
            fallback_delay_applied = True

        role, attempt_client, limiter, reservation = _reserve_for_next_attempt(
            eligible_attempts,
            run_budget,
            estimated_request_tokens,
        )
        preferred_role = None
        attempt_counts[role] += 1
        attempt_id = uuid.uuid4().hex
        if role == "fallback":
            if previous_error is not None:
                fallback_reason = (
                    "rate_limit_retry_exhausted_separate_org"
                    if previous_error.http_status == 429
                    else "primary_transient_error"
                )
            elif _key_slot_is_unavailable("primary"):
                fallback_reason = "primary_credential_unavailable"
            else:
                fallback_reason = "primary_request_limit_unavailable"
            logger.info(
                "Groq fallback selected: key_slot=fallback request_mode=%s "
                "reason=%s primary_error_category=%s",
                request_mode,
                fallback_reason,
                previous_error.category if previous_error is not None else "none",
            )
            _log_provider_diagnostic_event(
                "fallback_selected",
                request_id=request_id,
                attempt_id=attempt_id,
                key_slot=role,
                request_mode=request_mode,
                attempt=request_attempt_count + 1,
                retry_count=request_attempt_count,
            )

        cancellation_token = None
        request_started = False
        attempt_number = None
        provider_error = None
        provider_cause = None
        rate_limit_wait = None
        rate_limit_wait_source = None
        response = None
        try:
            if run_budget is not None:
                cancellation_token, _ = run_budget.begin_provider_attempt(
                    attempt_client.close,
                )

                def invoke_provider(remaining):
                    nonlocal request_started, request_attempt_count, attempt_number
                    request_started = True
                    request_attempt_count += 1
                    attempt_number = request_attempt_count
                    _log_provider_diagnostic_event(
                        "attempt_started",
                        request_id=request_id,
                        attempt_id=attempt_id,
                        key_slot=role,
                        request_mode=request_mode,
                        attempt=attempt_number,
                        retry_count=attempt_number - 1,
                    )
                    return attempt_client.chat.completions.create(
                        **request_body,
                        timeout=min(MAX_MANUAL_PROVIDER_TIMEOUT_SECONDS, remaining),
                    )

                response = run_budget.invoke_provider_attempt(
                    cancellation_token,
                    invoke_provider,
                )
            else:
                request_started = True
                request_attempt_count += 1
                attempt_number = request_attempt_count
                _log_provider_diagnostic_event(
                    "attempt_started",
                    request_id=request_id,
                    attempt_id=attempt_id,
                    key_slot=role,
                    request_mode=request_mode,
                    attempt=attempt_number,
                    retry_count=attempt_number - 1,
                )
                response = attempt_client.chat.completions.create(**request_body)
        except DiscoveryRunLimitExceeded:
            if request_started:
                _log_provider_diagnostic_event(
                    "attempt_completed",
                    request_id=request_id,
                    attempt_id=attempt_id,
                    key_slot=role,
                    request_mode=request_mode,
                    http_status=None,
                    outcome="cancelled",
                    attempt=attempt_number,
                    retry_count=attempt_number - 1,
                    error_category="budget_exhausted",
                    completion_tokens=None,
                )
            raise
        except GroqProviderError as exc:
            provider_error = exc
            provider_cause = exc.__cause__
        except Exception as exc:
            if run_budget is not None:
                run_budget.ensure_active()
            category, status = classify_groq_error(exc)
            details, body = _sanitize_groq_error_message(exc)
            safe_details = {
                field: details[key]
                for field, key in (
                    ("type", "error_type"),
                    ("code", "error_code"),
                    ("param", "error_param"),
                )
                if details.get(key) is not None
            }
            finish_reason = _safe_finish_reason(
                _nested_error_value(body, "finish_reason"),
            )
            completion_tokens = _nonnegative_int(
                _nested_error_value(body, "completion_tokens"),
            )
            reasoning_tokens = _nonnegative_int(
                _nested_error_value(body, "reasoning_tokens"),
            )
            model_identifier = _safe_model_identifier(request_body.get("model"))
            error_summary = _provider_error_summary_for_log(
                details.get("error_code"),
            )
            limit_details = extract_rate_limit_details(body, str(exc))
            if (
                status == 429
                and limit_details.get("limit_type") in _DAILY_LIMIT_TYPES
            ):
                # A per-day limit will not reset inside this run.
                category = "quota_exhausted"
            if category == "locally_blocked":
                logger.warning(
                    "Groq request locally blocked: key_slot=%s category=%s",
                    role,
                    category,
                )
            else:
                logger.warning(
                    "Groq provider request failed: key_slot=%s category=%s "
                    "http_status=%s provider_error_type=%s provider_error_code=%s "
                    "provider_error_param=%s provider_finish_reason=%s "
                    "provider_completion_tokens=%s provider_reasoning_tokens=%s "
                    "provider_model=%s provider_error_summary=%s "
                    "limit_type=%s limit=%s used=%s requested=%s",
                    role,
                    category,
                    status,
                    details["error_type"],
                    details.get("error_code") or "unknown",
                    details.get("error_param") or "unknown",
                    finish_reason or "not_returned",
                    completion_tokens if completion_tokens is not None else "not_returned",
                    reasoning_tokens if reasoning_tokens is not None else "not_returned",
                    model_identifier or "omitted",
                    error_summary,
                    limit_details.get("limit_type", "not_returned"),
                    limit_details.get("limit", "not_returned"),
                    limit_details.get("used", "not_returned"),
                    limit_details.get("requested", "not_returned"),
                )
            provider_error = GroqProviderError(
                category,
                status,
                safe_details,
                limit_details,
                _completion_metadata(
                    finish_reason,
                    completion_tokens,
                    reasoning_tokens,
                ),
            )
            provider_cause = exc
        finally:
            if (
                provider_error is not None
                and provider_error.http_status == 429
                and provider_error.limit_details.get("limit_type") == "TPM"
                and limiter is not None
            ):
                limiter.observe_provider_tpm(
                    provider_error.limit_details,
                    reservation,
                )
            if provider_error is not None and provider_error.http_status == 429:
                delay, rate_limit_wait_source = _retry_after_seconds(
                    provider_cause or provider_error,
                )
                if delay is None:
                    delay = min(2 ** (attempt_counts[role] - 1), 30)
                    rate_limit_wait_source = "exponential_backoff"
                rate_limit_wait = delay + _rate_limit_jitter()
                if limiter is not None:
                    # Never park the shared limiter past the point where this run
                    # could still use it; a per-day limit would otherwise stall
                    # every later source until the run deadline.
                    limiter.defer_for(min(
                        rate_limit_wait,
                        run_budget.remaining_seconds()
                        if run_budget is not None
                        else MAX_UNBUDGETED_RATE_LIMIT_WAIT_SECONDS,
                    ))
            if (
                reservation is not None
                and limiter is not None
                and provider_error is not None
                and provider_error.http_status in UNPROCESSED_REQUEST_STATUSES
            ):
                # The provider refused this request before running any
                # inference, so it spent no tokens. The attempt still counts
                # toward the request-per-minute budget, so the reservation
                # stays; only its token share is given back. Holding those
                # tokens would block the next request for a whole TPM window.
                limiter.discard_reserved_tokens(reservation)
            if reservation is not None:
                limiter.release(
                    reservation,
                    cancel=not request_started,
                )
            if run_budget is not None and cancellation_token is not None:
                run_budget.unregister_cancellation(cancellation_token)

        if provider_error is None:
            _log_completion_metadata(
                response,
                role,
                request_mode,
                request_id=request_id,
                attempt_id=attempt_id,
                attempt=attempt_number,
                retry_count=attempt_number - 1,
            )
            return response

        if provider_error.category == "locally_blocked":
            logger.warning(
                "Groq request locally blocked: key_slot=%s category=%s",
                role,
                provider_error.category,
            )
        else:
            logger.warning(
                "Groq provider request failed: key_slot=%s category=%s http_status=%s",
                role,
                provider_error.category,
                provider_error.http_status,
            )
        _log_provider_diagnostic_event(
            "attempt_completed",
            request_id=request_id,
            attempt_id=attempt_id,
            key_slot=role,
            request_mode=request_mode,
            http_status=provider_error.http_status,
            outcome=(
                "locally_blocked"
                if provider_error.category == "locally_blocked"
                else "failed"
            ),
            attempt=attempt_number,
            retry_count=attempt_number - 1,
            error_category=provider_error.category,
            completion_tokens=None,
        )
        provider_error._attempt_context = (role, attempt_client, limiter)
        status = provider_error.http_status
        if status == 401 or provider_error.category == "authentication_error":
            _mark_key_slot_unavailable(role)
        last_error = provider_error
        last_error_cause = provider_cause

        if provider_error.category == "locally_blocked":
            if previous_error is not None and provider_error is not previous_error:
                raise provider_error from previous_error
            if provider_cause is not None:
                raise provider_error from provider_cause
            raise provider_error

        other_role = "fallback" if role == "primary" else "primary"
        other_is_configured = any(
            candidate_role == other_role
            for candidate_role, _, _ in attempts
        )
        can_switch_on_429 = (
            status == 429
            and separate_organizations
            and other_is_configured
            and not _key_slot_is_unavailable(other_role)
        )
        if status == 429:
            logger.warning(
                "Groq rate-limit retry scheduled: key_slot=%s request_mode=%s "
                "attempt=%s max_attempts=%s wait_seconds=%.2f wait_source=%s",
                role,
                request_mode,
                attempt_counts[role],
                retry_limit + 1,
                rate_limit_wait,
                rate_limit_wait_source,
            )
            _log_provider_diagnostic_event(
                "rate_limit_retry",
                request_id=request_id,
                attempt_id=attempt_id,
                key_slot=role,
                request_mode=request_mode,
                http_status=status,
                outcome="retry_scheduled",
                attempt=attempt_number,
                retry_count=attempt_number - 1,
                max_attempts=retry_limit + 1,
                wait_source=rate_limit_wait_source,
            )
            if can_switch_on_429:
                if role == "primary":
                    previous_error = provider_error
                retry_only_role = None
                preferred_role = other_role
                continue
            daily_quota_exhausted = (
                provider_error.category == "quota_exhausted"
                or provider_error.limit_details.get("limit_type")
                in _DAILY_LIMIT_TYPES
            )
            wait_exceeds_budget = (
                rate_limit_wait is not None
                and (
                    rate_limit_wait > run_budget.remaining_seconds()
                    if run_budget is not None
                    else rate_limit_wait > MAX_UNBUDGETED_RATE_LIMIT_WAIT_SECONDS
                )
            )
            if daily_quota_exhausted or wait_exceeds_budget:
                logger.warning(
                    "Groq rate-limit retry abandoned: key_slot=%s reason=%s "
                    "limit_type=%s wait_seconds=%.2f",
                    role,
                    (
                        "daily_quota_exhausted"
                        if daily_quota_exhausted
                        else "wait_exceeds_budget"
                    ),
                    provider_error.limit_details.get("limit_type", "not_returned"),
                    rate_limit_wait or 0.0,
                )
                if previous_error is not None and provider_error is not previous_error:
                    raise provider_error from previous_error
                if provider_cause is not None:
                    raise provider_error from provider_cause
                raise provider_error
            if attempt_counts[role] < retry_limit + 1:
                retry_only_role = role
                preferred_role = None
                continue
            if previous_error is not None and provider_error is not previous_error:
                raise provider_error from previous_error
            if provider_cause is not None:
                raise provider_error from provider_cause
            raise provider_error

        can_return_to_primary = (
            role == "fallback"
            and (
                status == 401
                or provider_error.category == "authentication_error"
            )
            and "primary" in attempt_counts
            and attempt_counts["primary"] < retry_limit + 1
            and not _key_slot_is_unavailable("primary")
        )
        if can_return_to_primary:
            retry_only_role = None
            preferred_role = "primary"
            continue

        can_use_fallback = (
            role == "primary"
            and other_is_configured
            and status not in (400, 413, 422)
            and provider_error.category not in {
                "malformed_request",
                "payload_too_large",
                "locally_blocked",
            }
        )
        if can_use_fallback:
            previous_error = provider_error
            attempt_counts[role] = retry_limit + 1
            retry_only_role = None
            preferred_role = "fallback"
            continue
        if previous_error is not None and provider_error is not previous_error:
            raise provider_error from previous_error
        if provider_cause is not None:
            raise provider_error from provider_cause
        raise provider_error
