import threading
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.core.config import ScholarshipDiscoverySettings
from app.services import scholarship_discovery_budget as budget_module
from app.services.scholarship_discovery_budget import (
    ControlledManualSourceConfigurationError,
    DiscoveryRunBudget,
    DiscoveryRunLimitExceeded,
    controlled_manual_settings,
    controlled_manual_sources,
)
from app.services.scholarship_discovery import _persist_candidate, run_discovery
from app.services.scholarship_discovery_sources import SOURCES_BY_ID


class DiscoveryRunBudgetTests(unittest.TestCase):
    def setUp(self):
        self.settings = ScholarshipDiscoverySettings(
            enabled=True,
            request_timeout_seconds=15,
            max_response_bytes=10_000_000,
            max_extracted_chars=30_000,
            max_pages_per_source=3,
            max_retries=2,
            request_delay_seconds=1,
            user_agent="offline-test",
            model="offline-model",
        )

    def test_controlled_run_limits_match_the_approved_profile(self):
        budget = DiscoveryRunBudget(start_deadline_timer=False)
        try:
            self.assertEqual(budget.max_sources, 15)
            self.assertEqual(budget.max_pages, 45)
            self.assertEqual(budget.max_pages_per_source, 3)
            self.assertEqual(budget.max_http_attempts, 300)
            self.assertEqual(budget.max_candidates, 100)
            self.assertEqual(budget.max_provider_attempts, 100)
            self.assertEqual(budget.duration_seconds, 1800)
        finally:
            budget.close()

    def test_budgeted_manual_service_rejects_legacy_sources_before_database_access(self):
        class NoDatabaseAccess:
            def __getattr__(self, name):
                raise AssertionError(f"database access should not be reached: {name}")

        settings = ScholarshipDiscoverySettings(
            enabled=True,
            request_timeout_seconds=15,
            max_response_bytes=10_000_000,
            max_extracted_chars=30_000,
            max_pages_per_source=3,
            max_retries=2,
            request_delay_seconds=1,
            user_agent="offline-test",
            model="offline-model",
        )
        budget = DiscoveryRunBudget(
            duration_seconds=60,
            start_deadline_timer=False,
        )
        try:
            with self.assertRaises(ControlledManualSourceConfigurationError):
                run_discovery(
                    NoDatabaseAccess(),
                    settings=settings,
                    sources=(SOURCES_BY_ID["daad"],),
                    run_budget=budget,
                )
        finally:
            budget.close()

    def test_direct_manual_service_without_budget_crawls_exact_allowlist(self):
        class FakeSession:
            def __init__(self):
                self.run = None
                self.commits = 0

            def get_bind(self):
                return SimpleNamespace(
                    dialect=SimpleNamespace(name="sqlite", driver="pysqlite"),
                )

            def add(self, value):
                self.run = value

            def commit(self):
                self.commits += 1

        class FakeFetcher:
            def __init__(self):
                self.source_ids = []

            def crawl(self, source):
                self.source_ids.append(source.source_id)
                return []

        session = FakeSession()
        fetcher = FakeFetcher()

        def save_run(_db, run, summary, source_results, status, _lock_check=None):
            run.summary = dict(summary)
            run.source_results = list(source_results)
            run.status = status
            run.finished_at = run.started_at

        with patch(
            "app.services.scholarship_discovery._last_successful_fetch",
            return_value=None,
        ), patch(
            "app.services.scholarship_discovery._save_run",
            side_effect=save_run,
        ):
            result = run_discovery(
                session,
                settings=self.settings,
                fetcher=fetcher,
                extractor=object(),
            )

        expected = tuple(source.source_id for source in controlled_manual_sources())
        self.assertEqual(fetcher.source_ids, list(expected))
        self.assertEqual(result["summary"]["sources_attempted"], 15)
        self.assertEqual(session.commits, 1)

    def test_direct_manual_service_rejects_invalid_tuples_before_crawling(self):
        class NoDatabaseAccess:
            def __getattr__(self, name):
                raise AssertionError(f"database access should not be reached: {name}")

        approved = controlled_manual_sources()
        invalid_tuples = (
            approved[:-1],
            (*approved, SOURCES_BY_ID["daad"]),
            (*approved, approved[0]),
            (
                replace(approved[0], crawl_enabled=False),
                *approved[1:],
            ),
            (
                replace(approved[0], trust_reviewed=False),
                *approved[1:],
            ),
            (
                replace(approved[0], discovery_only=True),
                *approved[1:],
            ),
        )
        for with_budget in (False, True):
            for sources in invalid_tuples:
                fetcher = Mock()
                budget = (
                    DiscoveryRunBudget(start_deadline_timer=False)
                    if with_budget
                    else None
                )
                try:
                    with self.subTest(with_budget=with_budget, count=len(sources)):
                        with self.assertRaises(ControlledManualSourceConfigurationError):
                            run_discovery(
                                NoDatabaseAccess(),
                                settings=self.settings,
                                sources=sources,
                                fetcher=fetcher,
                                run_budget=budget,
                            )
                    fetcher.crawl.assert_not_called()
                finally:
                    if budget is not None:
                        budget.close()

    def test_direct_scheduled_service_keeps_explicit_source_selection(self):
        class FakeSession:
            run = None

            def add(self, value):
                self.run = value

            def commit(self):
                return None

        session = FakeSession()
        fetcher = Mock()
        fetcher.crawl.return_value = []

        def save_run(_db, run, summary, source_results, status, _lock_check=None):
            run.summary = dict(summary)
            run.source_results = list(source_results)
            run.status = status
            run.finished_at = run.started_at

        with patch(
            "app.services.scholarship_discovery._last_successful_fetch",
            return_value=None,
        ), patch(
            "app.services.scholarship_discovery._save_run",
            side_effect=save_run,
        ):
            result = run_discovery(
                session,
                settings=self.settings,
                sources=(SOURCES_BY_ID["daad"],),
                fetcher=fetcher,
                extractor=object(),
                trigger_type="scheduled",
            )

        self.assertEqual(result["summary"]["sources_attempted"], 1)
        fetcher.crawl.assert_called_once_with(SOURCES_BY_ID["daad"])

    def test_concurrent_http_attempt_reservations_cannot_exceed_limit(self):
        budget = DiscoveryRunBudget(
            max_http_attempts=10,
            duration_seconds=60,
        )
        successful_attempts = []
        rejected_attempts = []

        def reserve_attempt():
            try:
                budget.consume_http_attempt()
                successful_attempts.append(True)
            except DiscoveryRunLimitExceeded:
                rejected_attempts.append(True)

        threads = [
            threading.Thread(target=reserve_attempt)
            for _ in range(40)
        ]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(len(successful_attempts), 10)
            self.assertEqual(len(rejected_attempts), 30)
            self.assertEqual(budget.snapshot()["http_attempts"], 10)
        finally:
            budget.close()

    def test_page_and_candidate_slots_are_reserved_before_work(self):
        budget = DiscoveryRunBudget(
            max_pages=1,
            max_pages_per_source=1,
            max_candidates=1,
            duration_seconds=60,
        )
        try:
            budget.start_source("approved-source")
            budget.start_page("approved-source")
            with self.assertRaises(DiscoveryRunLimitExceeded) as page_error:
                budget.start_page("approved-source")
            self.assertEqual(page_error.exception.resource, "pages")
            self.assertEqual(budget.snapshot()["pages_started"], 1)

            budget.begin_candidate_persistence()
            with self.assertRaises(DiscoveryRunLimitExceeded) as candidate_error:
                budget.begin_candidate_persistence()
            self.assertEqual(candidate_error.exception.resource, "candidates")
            budget.finish_candidate_persistence(True)
            self.assertEqual(budget.snapshot()["candidates_persisted"], 1)
        finally:
            budget.close()

    def test_committed_candidate_counts_even_when_refresh_fails(self):
        budget = DiscoveryRunBudget(
            max_candidates=1,
            duration_seconds=60,
            start_deadline_timer=False,
        )

        def commit_then_refresh_fails(*_args, on_committed=None, **_kwargs):
            on_committed()
            raise RuntimeError("offline refresh failure")

        try:
            with patch(
                "app.services.scholarship_discovery.persist_review_candidate",
                side_effect=commit_then_refresh_fails,
            ):
                with self.assertRaisesRegex(RuntimeError, "refresh failure"):
                    _persist_candidate(
                        object(),
                        "run-id",
                        object(),
                        object(),
                        object(),
                        "review",
                        run_budget=budget,
                    )

            self.assertEqual(budget.snapshot()["candidates_persisted"], 1)
            with self.assertRaises(DiscoveryRunLimitExceeded):
                budget.begin_candidate_persistence()
        finally:
            budget.close()

    def test_candidate_persistence_failure_before_commit_is_not_counted(self):
        budget = DiscoveryRunBudget(
            max_candidates=1,
            duration_seconds=60,
            start_deadline_timer=False,
        )
        try:
            with patch(
                "app.services.scholarship_discovery.persist_review_candidate",
                side_effect=RuntimeError("offline commit failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "commit failure"):
                    _persist_candidate(
                        object(),
                        "run-id",
                        object(),
                        object(),
                        object(),
                        "review",
                        run_budget=budget,
                    )
            self.assertEqual(budget.snapshot()["candidates_persisted"], 0)
        finally:
            budget.close()

    def test_deadline_cancels_active_operations_and_has_structured_stop_reason(self):
        now = [100.0]
        cancelled = []
        budget = DiscoveryRunBudget(
            clock=lambda: now[0],
            duration_seconds=5,
            start_deadline_timer=False,
        )
        budget.start()
        budget.register_cancellation(lambda: cancelled.append(True))
        now[0] = 106.0
        try:
            with self.assertRaises(DiscoveryRunLimitExceeded) as raised:
                budget.ensure_active()

            self.assertEqual(
                raised.exception.as_dict(),
                {
                    "code": "DISCOVERY_RUN_BUDGET_EXHAUSTED",
                    "resource": "duration_seconds",
                    "limit": 5,
                },
            )
            self.assertEqual(cancelled, [True])
        finally:
            budget.close()

    def test_completed_page_is_counted_when_deadline_expires_before_recording_returns(self):
        now = [0.0]
        budget = DiscoveryRunBudget(
            clock=lambda: now[0],
            duration_seconds=5,
            start_deadline_timer=False,
        )
        budget.start()
        now[0] = 5.0
        try:
            with self.assertRaises(DiscoveryRunLimitExceeded):
                budget.record_page_fetched()
            self.assertEqual(budget.snapshot()["pages_fetched"], 1)
        finally:
            budget.close()

    def test_operation_gate_rejects_work_if_deadline_wins_the_race(self):
        budget = DiscoveryRunBudget(
            duration_seconds=5,
            start_deadline_timer=False,
        )
        budget.start()
        canceled = []
        requests_started = []
        token, _remaining = budget.begin_http_attempt(
            lambda: canceled.append(True),
        )
        try:
            budget._expire()
            with self.assertRaises(DiscoveryRunLimitExceeded) as raised:
                budget.invoke_http_attempt(
                    token,
                    lambda _remaining: requests_started.append(True),
                )
            self.assertEqual(raised.exception.resource, "duration_seconds")
            self.assertEqual(canceled, [True])
            self.assertEqual(requests_started, [])
            self.assertEqual(budget.snapshot()["http_attempts"], 0)
        finally:
            budget.unregister_cancellation(token)
            budget.close()

    def test_cancellation_racing_with_invocation_allows_only_the_gate_winner(self):
        budget = DiscoveryRunBudget(
            max_provider_attempts=1,
            duration_seconds=60,
            start_deadline_timer=False,
        )
        invocation_entered = threading.Event()
        release_invocation = threading.Event()
        cancellation_started = threading.Event()
        canceled = threading.Event()
        provider_calls = []
        original_cancel = budget_module._DiscoveryOperationGate.cancel

        def observe_cancellation(gate):
            cancellation_started.set()
            return original_cancel(gate)

        def invoke_provider():
            try:
                budget.invoke_provider_attempt(
                    token,
                    lambda _remaining: (
                        invocation_entered.set(),
                        release_invocation.wait(),
                        provider_calls.append(True),
                    ),
                )
            except Exception as error:
                provider_calls.append(type(error).__name__)

        invocation_thread = threading.Thread(target=invoke_provider)
        cancellation_thread = threading.Thread(target=budget._expire)
        with patch.object(
            budget_module._DiscoveryOperationGate,
            "cancel",
            observe_cancellation,
        ):
            token, _remaining = budget.begin_provider_attempt(canceled.set)
            try:
                invocation_thread.start()
                self.assertTrue(invocation_entered.wait(timeout=2))
                cancellation_thread.start()
                self.assertTrue(cancellation_started.wait(timeout=2))
                self.assertFalse(canceled.is_set())
                release_invocation.set()
                invocation_thread.join(timeout=2)
                cancellation_thread.join(timeout=2)

                self.assertFalse(invocation_thread.is_alive())
                self.assertFalse(cancellation_thread.is_alive())
                self.assertTrue(canceled.is_set())
                self.assertEqual(provider_calls, [True])
                self.assertEqual(budget.snapshot()["provider_attempts"], 1)
            finally:
                release_invocation.set()
                invocation_thread.join(timeout=2)
                if cancellation_thread.ident is not None:
                    cancellation_thread.join(timeout=2)
                budget.unregister_cancellation(token)
                self.assertEqual(budget._cancellations, {})
                self.assertEqual(budget._operation_gates, {})
                budget.close()

    def test_operation_exception_releases_gate_and_registration(self):
        budget = DiscoveryRunBudget(
            duration_seconds=60,
            start_deadline_timer=False,
        )
        token, _remaining = budget.begin_http_attempt(lambda: None)
        try:
            with self.assertRaisesRegex(ValueError, "offline failure"):
                budget.invoke_http_attempt(
                    token,
                    lambda _remaining: (_ for _ in ()).throw(ValueError("offline failure")),
                )
        finally:
            budget.unregister_cancellation(token)

        self.assertEqual(budget._cancellations, {})
        self.assertEqual(budget._operation_gates, {})
        next_token, _remaining = budget.begin_http_attempt(lambda: None)
        try:
            self.assertEqual(
                budget.invoke_http_attempt(next_token, lambda _remaining: "ok"),
                "ok",
            )
        finally:
            budget.unregister_cancellation(next_token)
            budget.close()

    def test_manual_profile_clamps_environment_limits_without_raising_smaller_values(self):
        settings = ScholarshipDiscoverySettings(
            enabled=True,
            request_timeout_seconds=120,
            max_response_bytes=50_000_000,
            max_extracted_chars=100_000,
            max_pages_per_source=200,
            max_retries=5,
            request_delay_seconds=1,
            user_agent="offline-test",
            model="offline-model",
            max_linked_urls=1000,
            max_linked_url_chars=8192,
            max_linked_urls_bytes=65_536,
            max_provider_request_bytes=10_000_000,
        )

        controlled = controlled_manual_settings(settings)

        self.assertEqual(controlled.request_timeout_seconds, 15)
        self.assertEqual(controlled.max_response_bytes, 10_000_000)
        self.assertEqual(controlled.max_pages_per_source, 3)
        self.assertEqual(controlled.max_retries, 2)
        self.assertEqual(controlled.max_extracted_chars, 30_000)
        self.assertEqual(controlled.max_linked_urls, 100)
        self.assertEqual(controlled.max_linked_url_chars, 2048)
        self.assertEqual(controlled.max_linked_urls_bytes, 16_384)
        self.assertEqual(controlled.max_provider_request_bytes, 512_000)

        smaller = controlled_manual_settings(
            ScholarshipDiscoverySettings(
                enabled=True,
                request_timeout_seconds=5,
                max_response_bytes=2048,
                max_extracted_chars=1000,
                max_pages_per_source=1,
                max_retries=0,
                request_delay_seconds=1,
                user_agent="offline-test",
                model="offline-model",
                max_linked_urls=5,
                max_linked_url_chars=128,
                max_linked_urls_bytes=1024,
                max_provider_request_bytes=8192,
            )
        )
        self.assertEqual(smaller.request_timeout_seconds, 5)
        self.assertEqual(smaller.max_response_bytes, 2048)
        self.assertEqual(smaller.max_pages_per_source, 1)
        self.assertEqual(smaller.max_retries, 0)
        self.assertEqual(smaller.max_provider_request_bytes, 8192)


if __name__ == "__main__":
    unittest.main()
