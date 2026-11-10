import json
from typing import Literal, Optional

from google.genai import types

from app.services.scholarship_discovery_budget import (
    MAX_MANUAL_PROVIDER_TIMEOUT_SECONDS,
    DiscoveryRunBudget,
    DiscoveryRunLimitExceeded,
)

GeminiErrorCategory = Literal[
    "missing_api_key",
    "authentication_error",
    "permission_error",
    "quota_error",
    "model_unavailable",
    "network_timeout",
    "provider_error",
    "payload_too_large",
]

GEMINI_TIMEOUT_MS = 60_000
GEMINI_MAX_ATTEMPTS = 2
GEMINI_RETRYABLE_HTTP_STATUSES = (408, 500, 502, 503, 504)


class GeminiProviderError(RuntimeError):
    def __init__(
        self,
        category: GeminiErrorCategory,
        http_status: Optional[int] = None,
    ):
        self.category = category
        self.http_status = http_status
        suffix = f" (HTTP {http_status})" if http_status is not None else ""
        super().__init__(f"Gemini request failed: {category}{suffix}")


def _http_status(exc: Exception) -> Optional[int]:
    for attribute in ("code", "status_code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
            return value
    return None


def _gemini_request_body(contents: str, config: dict) -> dict:
    request_body = {
        "contents": [{"parts": [{"text": contents}], "role": "user"}],
    }
    system_instruction = config.get("system_instruction")
    if system_instruction is not None:
        request_body["systemInstruction"] = {
            "parts": [{"text": system_instruction}],
            "role": "user",
        }

    generation_config = {}
    for key, value in config.items():
        if key in {"system_instruction", "http_options"}:
            continue
        api_key = "".join(
            word.capitalize() if index else word
            for index, word in enumerate(key.split("_"))
        )
        generation_config[api_key] = value
    if generation_config:
        request_body["generationConfig"] = generation_config

    return request_body


def gemini_request_payload_size_bytes(contents: str, config: dict) -> int:
    return len(json.dumps(_gemini_request_body(contents, config)).encode("utf-8"))


def classify_gemini_error(exc: Exception) -> tuple[GeminiErrorCategory, Optional[int]]:
    status = _http_status(exc)
    if status == 401:
        return "authentication_error", status
    if status == 403:
        return "permission_error", status
    if status == 429:
        return "quota_error", status
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


def is_retryable_gemini_error(
    category: str,
    status: Optional[int],
) -> bool:
    return (
        status in GEMINI_RETRYABLE_HTTP_STATUSES
        or category == "network_timeout" and status is None
    )


def is_gemini_fallback_eligible(
    category: str,
    status: Optional[int],
) -> bool:
    return (
        category == "quota_error" and status == 429
        or is_retryable_gemini_error(category, status)
    )


def create_gemini_client(api_key: str):
    try:
        from google import genai

        return genai.Client(api_key=api_key)
    except Exception as exc:
        category, status = classify_gemini_error(exc)
        raise GeminiProviderError(category, status) from None


def generate_content(
    client,
    *,
    model: str,
    contents: str,
    config: dict,
    max_request_bytes: Optional[int] = None,
    run_budget: Optional[DiscoveryRunBudget] = None,
):
    if (
        max_request_bytes is not None
        and gemini_request_payload_size_bytes(contents, config) > max_request_bytes
    ):
        raise GeminiProviderError("payload_too_large")

    if run_budget is None:
        request_config = dict(config)
        request_config["http_options"] = types.HttpOptions(
            timeout=GEMINI_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(
                attempts=GEMINI_MAX_ATTEMPTS,
                http_status_codes=list(GEMINI_RETRYABLE_HTTP_STATUSES),
            ),
        )
        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=request_config,
            )
        except Exception as exc:
            category, status = classify_gemini_error(exc)
            raise GeminiProviderError(category, status) from None

    for attempt in range(GEMINI_MAX_ATTEMPTS):
        cancellation_token = None
        try:
            cancellation_token, _remaining = run_budget.begin_provider_attempt(
                client.close,
            )

            def invoke_generate_content(remaining):
                request_config = dict(config)
                request_config["http_options"] = types.HttpOptions(
                    timeout=max(
                        1,
                        min(
                            GEMINI_TIMEOUT_MS,
                            int(MAX_MANUAL_PROVIDER_TIMEOUT_SECONDS * 1000),
                            int(remaining * 1000),
                        ),
                    ),
                    retry_options=types.HttpRetryOptions(
                        attempts=1,
                        http_status_codes=[],
                    ),
                )
                return client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=request_config,
                )

            return run_budget.invoke_provider_attempt(
                cancellation_token,
                invoke_generate_content,
            )
        except DiscoveryRunLimitExceeded:
            raise
        except Exception as exc:
            run_budget.ensure_active()
            category, status = classify_gemini_error(exc)
            if (
                is_retryable_gemini_error(category, status)
                and attempt + 1 < GEMINI_MAX_ATTEMPTS
            ):
                run_budget.wait(min(2 ** attempt, 8))
                continue
            raise GeminiProviderError(category, status) from None
        finally:
            if cancellation_token is not None:
                run_budget.unregister_cancellation(cancellation_token)
