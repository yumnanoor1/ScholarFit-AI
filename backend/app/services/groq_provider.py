"""Small, sanitized adapter for the Groq chat-completions API."""

import json

from app.services.scholarship_discovery_budget import (
    MAX_MANUAL_PROVIDER_TIMEOUT_SECONDS,
    DiscoveryRunBudget,
    DiscoveryRunLimitExceeded,
)

STRICT_STRUCTURED_OUTPUT_MODELS = frozenset({
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
    "meta-models/muse-spark-open",
})


class GroqProviderError(RuntimeError):
    def __init__(self, category: str, http_status: int | None = None):
        self.category = category
        self.http_status = http_status
        suffix = f" (HTTP {http_status})" if http_status is not None else ""
        super().__init__(f"Groq request failed: {category}{suffix}")


def _http_status(exc: Exception) -> int | None:
    for attribute in ("status_code", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
            return value
    return None


def classify_groq_error(exc: Exception) -> tuple[str, int | None]:
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
) -> dict:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": contents},
        ],
        "temperature": 0.1,
        "response_format": response_format,
    }


def groq_request_payload_size_bytes(
    model: str,
    system_instruction: str,
    contents: str,
    response_format: dict,
) -> int:
    return len(
        json.dumps(
            _groq_request_body(model, system_instruction, contents, response_format),
        ).encode("utf-8")
    )


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
        raise GroqProviderError(category, status) from None


def generate_json_completion(
    client,
    *,
    model: str,
    system_instruction: str,
    contents: str,
    strict_schema: dict | None = None,
    max_request_bytes: int | None = None,
    run_budget: DiscoveryRunBudget | None = None,
):
    response_format = groq_response_format(model, strict_schema)
    request_body = _groq_request_body(model, system_instruction, contents, response_format)
    if (
        max_request_bytes is not None
        and groq_request_payload_size_bytes(
            model,
            system_instruction,
            contents,
            response_format,
        ) > max_request_bytes
    ):
        raise GroqProviderError("payload_too_large")
    cancellation_token = None
    try:
        if run_budget is not None:
            cancellation_token, _remaining = run_budget.begin_provider_attempt(
                client.close,
            )
            return run_budget.invoke_provider_attempt(
                cancellation_token,
                lambda remaining: client.chat.completions.create(
                    **request_body,
                    timeout=min(MAX_MANUAL_PROVIDER_TIMEOUT_SECONDS, remaining),
                ),
            )
        return client.chat.completions.create(**request_body)
    except DiscoveryRunLimitExceeded:
        raise
    except Exception as exc:
        if run_budget is not None:
            run_budget.ensure_active()
        category, status = classify_groq_error(exc)
        raise GroqProviderError(category, status) from None
    finally:
        if run_budget is not None and cancellation_token is not None:
            run_budget.unregister_cancellation(cancellation_token)
