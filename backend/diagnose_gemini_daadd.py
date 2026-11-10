"""One-source, serial Gemini diagnostics for the registered DAAD page."""

import importlib.metadata
import json
import os
import re
import time
import urllib.parse
from dataclasses import replace
from unittest.mock import patch

import httpx
from google import genai
from google.genai import types

from app.core.config import scholarship_discovery_settings
from app.services import gemini_provider
from app.services.scholarship_discovery_budget import (
    DiscoveryRunBudget,
    DiscoveryRunLimitExceeded,
)
from app.services.scholarship_discovery_extraction import (
    EXTRACTION_SYSTEM_INSTRUCTION,
    GeminiScholarshipExtractor,
    ScholarshipExtractionError,
    _strict_extraction_schema,
)
from app.services.scholarship_discovery_fetch import (
    DiscoveryFetchError,
    OfficialSourceFetcher,
)
from app.services.scholarship_discovery_sources import SOURCES_BY_ID
from app.services.source_url_safety import safe_source_url

SOURCE_ID = "daad-helmut-schmidt"
REQUEST_TIMEOUT_MS = 60_000
DIAGNOSTIC_PROVIDER_ATTEMPT_LIMIT = 20
DIAGNOSTIC_DEADLINE_SECONDS = 30 * 60


def _safe_url(value):
    return safe_source_url(value) or "[redacted unsafe URL]"


def _error_details(exc):
    category = getattr(exc, "category", None)
    status = getattr(exc, "http_status", None) or getattr(exc, "code", None)
    if category is None:
        category, classified_status = gemini_provider.classify_gemini_error(exc)
        status = status or classified_status
    return {
        "exception_type": type(exc).__name__,
        "classification": category,
        "http_status": status,
    }


class _ReportingFetcher(OfficialSourceFetcher):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.http_events = []
        self.robots_allowed = None
        self.raw_html = None

    def _request(self, source, url, *, on_request_attempt=None):
        status, headers, body = super()._request(
            source,
            url,
            on_request_attempt=on_request_attempt,
        )
        event = {
            "url": _safe_url(url),
            "status": status,
            "content_type": headers.get_content_type(),
            "response_bytes": len(body),
        }
        location = headers.get("Location")
        if location:
            event["redirect_to"] = _safe_url(urllib.parse.urljoin(url, location))
        self.http_events.append(event)
        if (
            not urllib.parse.urlsplit(url).path.rstrip("/").endswith("robots.txt")
            and headers.get_content_type().lower() in {"text/html", "application/xhtml+xml"}
        ):
            charset = headers.get_content_charset() or "utf-8"
            try:
                self.raw_html = body.decode(charset, errors="replace")
            except LookupError:
                self.raw_html = body.decode("utf-8", errors="replace")
        return status, headers, body

    def _robots_allowed(self, source, url):
        self.robots_allowed = super()._robots_allowed(source, url)
        return self.robots_allowed


class _Diagnostic:
    def __init__(
        self,
        client,
        budget,
        model,
        max_request_bytes,
        http_statuses,
        http_requests,
    ):
        self.client = client
        self.budget = budget
        self.model = model
        self.max_request_bytes = max_request_bytes
        self.http_statuses = http_statuses
        self.http_requests = http_requests
        self.rows = []
        self.token_counts = {}
        self.quota_exhausted = False

    def _count_tokens(self, contents):
        cache_key = contents
        if cache_key in self.token_counts:
            return self.token_counts[cache_key]

        method = getattr(self.client.models, "count_tokens", None)
        if not callable(method):
            result = {
                "status": "unavailable",
                "reason": "installed SDK client has no callable models.count_tokens",
                "input_tokens": None,
                "latency_seconds": None,
                "http_status": None,
            }
            self.token_counts[cache_key] = result
            return result

        status_start = len(self.http_statuses)
        started = time.perf_counter()
        cancellation_token = None
        try:
            cancellation_token, _remaining = self.budget.begin_provider_attempt(
                self.client.close,
            )

            def invoke(remaining):
                timeout_ms = max(
                    1,
                    min(REQUEST_TIMEOUT_MS, int(remaining * 1000)),
                )
                http_options = types.HttpOptions(
                    timeout=timeout_ms,
                    retry_options=types.HttpRetryOptions(
                        attempts=1,
                        http_status_codes=[],
                    ),
                )
                config = types.CountTokensConfig(http_options=http_options)
                return method(
                    model=self.model,
                    contents=contents,
                    config=config,
                )

            response = self.budget.invoke_provider_attempt(cancellation_token, invoke)
            result = {
                "status": "returned",
                "reason": None,
                "input_tokens": getattr(response, "total_tokens", None),
                "latency_seconds": round(time.perf_counter() - started, 3),
                "http_status": self.http_statuses[-1] if len(self.http_statuses) > status_start else None,
            }
        except Exception as exc:
            details = _error_details(exc)
            result = {
                "status": "failed",
                "reason": details["classification"],
                "exception_type": details["exception_type"],
                "input_tokens": None,
                "latency_seconds": round(time.perf_counter() - started, 3),
                "http_status": (
                    self.http_statuses[-1]
                    if len(self.http_statuses) > status_start
                    else details["http_status"]
                ),
            }
            if result["http_status"] == 429:
                self.quota_exhausted = True
        finally:
            if cancellation_token is not None:
                self.budget.unregister_cancellation(cancellation_token)

        self.token_counts[cache_key] = result
        return result

    def generate(self, name, contents, config, *, system_instruction=None, page_text_chars=None):
        token_result = self._count_tokens(contents)
        row = {
            "test": name,
            "input_characters": len(contents),
            "page_text_characters": page_text_chars,
            "input_tokens": token_result.get("input_tokens"),
            "count_tokens_status": token_result.get("http_status"),
            "count_tokens_latency_seconds": token_result.get("latency_seconds"),
            "count_tokens_exception": token_result.get("exception_type"),
            "output_tokens": None,
            "generation_latency_seconds": None,
            "http_status": None,
            "exception_type": None,
            "error_classification": None,
            "conclusion": None,
        }

        if self.quota_exhausted:
            row["conclusion"] = "stopped because count_tokens reported quota exhaustion"
            self.rows.append(row)
            return None, row

        status_start = len(self.http_statuses)
        started = time.perf_counter()
        try:
            response = gemini_provider.generate_content(
                self.client,
                model=self.model,
                contents=contents,
                config=config,
                max_request_bytes=self.max_request_bytes,
                run_budget=self.budget,
            )
            row["generation_latency_seconds"] = round(time.perf_counter() - started, 3)
            row["http_status"] = (
                self.http_statuses[-1]
                if len(self.http_statuses) > status_start
                else None
            )
            usage = getattr(response, "usage_metadata", None)
            row["output_tokens"] = getattr(usage, "candidates_token_count", None)
            row["thoughts_tokens"] = getattr(usage, "thoughts_token_count", None)
            row["conclusion"] = "provider returned a response"
            self.rows.append(row)
            return response, row
        except Exception as exc:
            details = _error_details(exc)
            row["generation_latency_seconds"] = round(time.perf_counter() - started, 3)
            row["http_status"] = (
                self.http_statuses[-1]
                if len(self.http_statuses) > status_start
                else details["http_status"]
            )
            row["exception_type"] = details["exception_type"]
            row["error_classification"] = details["classification"]
            row["conclusion"] = details["classification"]
            if row["http_status"] == 429:
                self.quota_exhausted = True
            self.rows.append(row)
            return None, row


def _generation_config(*, system_instruction=None, schema=None, max_output_tokens=None):
    config = {
        "automatic_continuation": False,
    }
    if system_instruction is not None:
        config["system_instruction"] = system_instruction
        config["temperature"] = 0.1
        config["response_mime_type"] = "application/json"
    if schema is not None:
        config["response_schema"] = schema
    if max_output_tokens is not None:
        config["max_output_tokens"] = max_output_tokens
    return config


def _candidate_report(candidate):
    values = candidate.values
    funding_keys = (
        "funding_type", "funding_level", "tuition_coverage_type",
        "tuition_percent_min", "tuition_percent_max", "tuition_amount",
        "tuition_amount_max", "tuition_currency", "stipend_status",
        "stipend_amount", "stipend_amount_max", "stipend_currency",
        "stipend_period", "accommodation_status", "health_insurance_status",
        "travel_status", "travel_amount", "travel_currency", "costs_not_covered",
        "living_stipend", "travel_airfare", "accommodation", "health_insurance",
        "other_benefits",
    )
    return {
        "passed_existing_validation": True,
        "requires_review": candidate.requires_review,
        "name": values.get("name"),
        "provider": values.get("provider"),
        "degree_level": values.get("degree_level"),
        "eligible_countries": values.get("eligible_countries"),
        "eligible_nationalities": values.get("eligible_nationalities"),
        "fields_of_study": {
            key: values[key]
            for key in ("eligible_fields", "eligible_disciplines")
            if values.get(key) not in (None, "", [])
        },
        "funding": {
            key: values[key]
            for key in funding_keys
            if values.get(key) not in (None, "", [])
        },
        "deadline": {
            key: values[key]
            for key in (
                "deadline", "deadline_type", "application_deadline_date",
                "application_cycle", "application_open_date",
            )
            if values.get(key) not in (None, "", [])
        },
        "duration": {
            key: values[key]
            for key in ("duration", "funding_duration_months")
            if values.get(key) not in (None, "", [])
        },
        "official_url": _safe_url(
            values.get("official_info_url") or values.get("official_url") or ""
        ),
        "missing_required_fields": list(candidate.missing_required_fields),
        "review_reasons": list(candidate.review_reasons),
        "conflicting_values": list(candidate.conflicting_values),
    }


def main():
    settings = scholarship_discovery_settings()
    key = os.getenv("GEMINI_API_KEY")
    report = {
        "configuration_loaded": True,
        "gemini_api_key_status": "PRESENT" if key else "MISSING",
        "configured_model": settings.model,
        "google_genai_version": importlib.metadata.version("google-genai"),
        "groq_fallback_enabled_for_diagnostic": False,
        "provider_calls": 0,
        "candidate_extraction": None,
        "database_or_publication_action": False,
    }
    if not key:
        report["stopped_reason"] = "GEMINI_API_KEY is missing; no fetch or provider request was made"
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return

    source = SOURCES_BY_ID[SOURCE_ID]
    if not source.trust_reviewed or not source.crawl_enabled or not source.trust_basis:
        report["stopped_reason"] = "registered source trust or crawl gate is not satisfied"
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return

    settings = replace(settings, groq_fallback_enabled=False)
    budget = DiscoveryRunBudget(
        max_provider_attempts=DIAGNOSTIC_PROVIDER_ATTEMPT_LIMIT,
        duration_seconds=DIAGNOSTIC_DEADLINE_SECONDS,
    )
    http_statuses = []
    http_requests = []
    http_client = httpx.Client(
        event_hooks={
            "request": [lambda _request: http_requests.append(1)],
            "response": [lambda response: http_statuses.append(response.status_code)],
        },
    )
    client = genai.Client(
        api_key=key,
        http_options=types.HttpOptions(httpx_client=http_client),
    )
    key = None
    extractor = None
    page = None
    try:
        budget.start()
        budget.start_source(SOURCE_ID)
        budget.start_page(SOURCE_ID)
        fetcher = _ReportingFetcher(settings, run_budget=budget)
        registered_url = fetcher._safe_fetch_url(source, source.source_url)
        if registered_url != source.source_url:
            raise RuntimeError("registered URL changed during safety normalization")
        page = fetcher.fetch(source, registered_url)
        budget.record_page_fetched()
        report["fetch"] = {
            "succeeded": True,
            "source_id": SOURCE_ID,
            "final_url": _safe_url(page.url),
            "http_status": next(
                (event["status"] for event in reversed(fetcher.http_events)
                 if not urllib.parse.urlsplit(event["url"]).path.rstrip("/").endswith("robots.txt")),
                None,
            ),
            "content_type": page.content_type,
            "response_bytes": next(
                (event["response_bytes"] for event in reversed(fetcher.http_events)
                 if not urllib.parse.urlsplit(event["url"]).path.rstrip("/").endswith("robots.txt")),
                None,
            ),
            "cleaned_text_characters": len(page.text),
            "raw_html_characters": len(fetcher.raw_html) if fetcher.raw_html is not None else None,
            "robots_decision": "allowed" if fetcher.robots_allowed else "blocked_or_unavailable",
            "http_events": fetcher.http_events,
            "redirects": [
                {"status": event["status"], "from": event["url"], "to": event["redirect_to"]}
                for event in fetcher.http_events if event.get("redirect_to")
            ],
        }

        extractor = GeminiScholarshipExtractor(
            settings,
            client=client,
            run_budget=budget,
        )
        diagnostic = _Diagnostic(
            client,
            budget,
            settings.model,
            settings.max_provider_request_bytes,
            http_statuses,
            http_requests,
        )
        linked_urls, links_limited, _priority_count = extractor._bounded_linked_urls(page, source)
        system_instruction = EXTRACTION_SYSTEM_INSTRUCTION
        production_prompt = extractor._prompt_within_budget(
            page,
            source,
            provider="gemini",
        )
        common_config = _generation_config(system_instruction=system_instruction)

        with patch.object(
            gemini_provider,
            "GEMINI_MAX_ATTEMPTS",
            1,
        ):
            tiny_response, tiny_row = diagnostic.generate(
                "tiny prompt: Say hello",
                "Say hello",
                _generation_config(max_output_tokens=32),
            )
            if tiny_response is None:
                report["payload_matrix_stopped"] = True
                report["tiny_prompt_failure"] = tiny_row
            else:
                short_text = page.text[:2000]
                short_prompt = extractor._prompt(
                    page,
                    source,
                    linked_urls=linked_urls,
                    linked_urls_limited=links_limited,
                    page_text=short_text,
                )
                diagnostic.generate(
                    "DAAD cleaned text: first 2,000 characters",
                    short_prompt,
                    common_config,
                    system_instruction=system_instruction,
                    page_text_chars=len(short_text),
                )

                if not diagnostic.quota_exhausted:
                    baseline_response = None
                    baseline_error = None

                    def measured_extraction_call(prompt):
                        nonlocal baseline_response, baseline_error
                        baseline_response, row = diagnostic.generate(
                            "DAAD cleaned text: full 3,385 characters "
                            "(also serves 5k/10k/20k/40k caps)",
                            prompt,
                            common_config,
                            system_instruction=system_instruction,
                            page_text_chars=len(page.text),
                        )
                        if baseline_response is None:
                            baseline_error = row
                            raise ScholarshipExtractionError(
                                "Diagnostic Gemini request failed.",
                                category=row["error_classification"] or "provider_error",
                                http_status=row["http_status"],
                            )
                        return baseline_response.text or ""

                    candidates = []
                    extraction_error = None
                    with patch.object(
                        extractor,
                        "_generate_gemini",
                        side_effect=measured_extraction_call,
                    ):
                        try:
                            candidates = extractor.extract(page, source)
                        except ScholarshipExtractionError as exc:
                            extraction_error = {
                                "category": exc.category,
                                "http_status": exc.http_status,
                            }
                    report["candidate_extraction"] = {
                        "outcome": extractor.last_outcome_status,
                        "provider_failure": extraction_error,
                        "valid_structured_candidate": bool(candidates),
                        "candidates": [_candidate_report(candidate) for candidate in candidates],
                        "rejected_count": extractor.last_rejected_count,
                        "rejection_reasons": list(extractor.last_rejection_reasons),
                        "note": (
                            "5k/10k/20k/40k text thresholds all cap to the same "
                            "available 3,385 cleaned characters; no duplicate calls were made."
                        ),
                    }

                    if not diagnostic.quota_exhausted:
                        raw_prompt = extractor._prompt(
                            page,
                            source,
                            linked_urls=linked_urls,
                            linked_urls_limited=links_limited,
                            page_text=fetcher.raw_html or "",
                        )
                        diagnostic.generate(
                            "Full raw HTML diagnostic-only comparison",
                            raw_prompt,
                            common_config,
                            system_instruction=system_instruction,
                            page_text_chars=len(fetcher.raw_html or ""),
                        )

                    if not diagnostic.quota_exhausted:
                        schema = _strict_extraction_schema()
                        diagnostic.generate(
                            "Same full cleaned input with structured response schema",
                            production_prompt,
                            _generation_config(
                                system_instruction=system_instruction,
                                schema=schema,
                            ),
                            system_instruction=system_instruction,
                            page_text_chars=len(page.text),
                        )

                    if not diagnostic.quota_exhausted:
                        for output_limit in (256, 1024):
                            diagnostic.generate(
                                f"Full cleaned input, max_output_tokens={output_limit}",
                                production_prompt,
                                _generation_config(
                                    system_instruction=system_instruction,
                                    max_output_tokens=output_limit,
                                ),
                                system_instruction=system_instruction,
                                page_text_chars=len(page.text),
                            )

        report["measurements"] = diagnostic.rows
        report["sdk_count_tokens_method_available"] = callable(
            getattr(client.models, "count_tokens", None)
        )
        report["sdk_count_tokens_note"] = (
            "Gemini Developer API count_tokens does not support system_instruction in CountTokensConfig; "
            "the SDK raises ValueError before HTTP. Counts cover input contents only, not the separate "
            "system instruction or response-schema overhead."
        )
        report["alternate_model_comparison"] = (
            "not run; availability on this Free-tier project was not verified"
        )
        report["thinking_setting_comparison"] = (
            "not run; SDK types exist, but configured-model/account support was not verified"
        )
        report["provider_operations_budgeted"] = budget.snapshot()["provider_attempts"]
        report["provider_calls"] = len(http_requests)
        report["http_requests_started"] = len(http_requests)
        report["http_responses_observed"] = len(http_statuses)
        report["budget"] = budget.snapshot()
        if diagnostic.quota_exhausted:
            report["payload_matrix_stopped"] = True
            report["stop_reason"] = "HTTP 429 quota response; no further provider calls were made"
            if report["candidate_extraction"] is None:
                report["candidate_extraction"] = {
                    "status": "not_attempted_due_to_quota",
                    "valid_structured_candidate": False,
                }
        else:
            report["payload_matrix_stopped"] = report.get("payload_matrix_stopped", False)
    except (DiscoveryFetchError, DiscoveryRunLimitExceeded, RuntimeError) as exc:
        report["diagnostic_failure"] = {
            "exception_type": type(exc).__name__,
            "category": getattr(exc, "category", None),
            "resource": getattr(exc, "resource", None),
            "http_status": getattr(exc, "status_code", None),
        }
        report["provider_operations_budgeted"] = budget.snapshot()["provider_attempts"]
        report["provider_calls"] = len(http_requests)
        report["http_requests_started"] = len(http_requests)
    finally:
        if extractor is not None:
            extractor.close()
        client.close()
        http_client.close()
        report["database_or_publication_action"] = False
        budget.close()

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
