import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from io import StringIO
from unittest.mock import MagicMock, patch

import discover_scholarships
from app.core.config import ScholarshipDiscoverySettings
from app.services.scholarship_discovery_budget import (
    CONTROLLED_MANUAL_SOURCE_IDS,
    DiscoveryRunBudget,
    controlled_manual_settings,
)


LOCK_ID = 631287180927007781
EXPECTED_CONTROLLED_MANUAL_SOURCE_IDS = (
    "daad-helmut-schmidt",
    "daad-epos",
    "nl-scholarship",
    "leiden-excellence",
    "maastricht-nl-high-potential",
    "radboud-scholarship",
    "kth-scholarship",
    "lund-university-scholarships",
    "chalmers-scholarships",
    "eiffel-scholarship",
    "sciences-po-emile-boutmy",
    "chevening-pakistan",
    "commonwealth-masters",
    "commonwealth-shared",
    "turkiye-burslari",
)


class _QueryResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _LockConnection:
    def __init__(self, lock_state, acquire=True):
        self.lock_state = lock_state
        self.acquire = acquire
        self.fail_acquire_result = False
        self.fail_commit = False
        self.fail_backend_pid = False
        self.fail_unlock = False
        self.unlock_result = None
        self.closed = False
        self.invalidated = False
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def execute(self, statement, params=None):
        query = str(statement)
        self.calls.append((query, params))
        if "pg_backend_pid" in query:
            if self.fail_backend_pid:
                raise RuntimeError("backend PID lookup failed")
            return _QueryResult(123)
        if "pg_try_advisory_lock" in query:
            acquired = self.acquire and not self.lock_state["held"]
            if acquired:
                self.lock_state["held"] = True
            if self.fail_acquire_result:
                raise RuntimeError("acquisition response was lost")
            return _QueryResult(acquired)
        if "pg_advisory_unlock" in query:
            if self.fail_unlock:
                raise RuntimeError("unlock failed")
            if self.unlock_result is False:
                return _QueryResult(False)
            was_held = self.lock_state["held"]
            self.lock_state["held"] = False
            return _QueryResult(was_held)
        raise AssertionError(f"Unexpected query: {query}")

    def commit(self):
        if self.fail_commit:
            self.fail_commit = False
            raise RuntimeError("commit failed")

    def invalidate(self):
        self.invalidated = True
        self.lock_state["held"] = False

    def close(self):
        self.closed = True


class DiscoveryRunnerTests(unittest.TestCase):
    def setUp(self):
        self.settings = ScholarshipDiscoverySettings(
            enabled=True,
            request_timeout_seconds=120,
            max_response_bytes=50_000_000,
            max_extracted_chars=100_000,
            max_pages_per_source=200,
            max_retries=5,
            request_delay_seconds=0,
            user_agent="FitScholarTest/1.0",
            model="offline-model",
            stale_run_timeout_hours=12,
            max_linked_urls=1000,
            max_linked_url_chars=8192,
            max_linked_urls_bytes=65_536,
            max_provider_request_bytes=10_000_000,
        )
        self.lock_state = {"held": False}
        self.connection = _LockConnection(self.lock_state)
        self.engine = MagicMock()
        self.engine.connect.return_value = self.connection
        self.session = MagicMock()
        self.session_factory = MagicMock()
        self.session_factory.return_value.__enter__.return_value = self.session
        self.stdout = StringIO()
        self.stderr = StringIO()
        self.patches = [
            patch.object(discover_scholarships, "engine", self.engine),
            patch.object(discover_scholarships, "SessionLocal", self.session_factory),
            patch.object(discover_scholarships, "scholarship_discovery_settings", return_value=self.settings),
            patch.object(
                discover_scholarships,
                "inspect",
                return_value=MagicMock(
                    get_table_names=lambda: [
                        "scholarship_discovery_runs",
                        "scholarship_discovery_review_items",
                    ],
                    get_columns=lambda _table: [
                        {"name": "trigger_type"},
                        {"name": "scheduled_for"},
                    ],
                ),
            ),
        ]
        for mocked in self.patches:
            mocked.start()
            self.addCleanup(mocked.stop)
        self.session.query.return_value.filter.return_value.all.return_value = []
        self.session.query.return_value.filter.return_value.first.return_value = None
        self.lock_guard = MagicMock()
        self.lock_guard.check.return_value = True
        self.patches.append(patch.object(
            discover_scholarships,
            "DiscoveryAdvisoryLockGuard",
            return_value=self.lock_guard,
        ))
        self.patches[-1].start()
        self.addCleanup(self.patches[-1].stop)

    def _run(self, discovery, **options):
        with patch.object(discover_scholarships, "run_discovery", side_effect=discovery):
            with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
                code = discover_scholarships.main(**options)
        return code

    def _json_output(self, stream):
        return json.loads(stream.getvalue().strip())

    def test_controlled_allowlist_matches_exactly_the_approved_fifteen_ids(self):
        self.assertEqual(len(CONTROLLED_MANUAL_SOURCE_IDS), 15)
        self.assertEqual(
            CONTROLLED_MANUAL_SOURCE_IDS,
            EXPECTED_CONTROLLED_MANUAL_SOURCE_IDS,
        )

    def _assert_manual_source_preflight_fails(self, sources):
        self.engine.connect.reset_mock()
        self.stdout = StringIO()
        self.stderr = StringIO()
        with patch.object(discover_scholarships, "SOURCES", tuple(sources)):
            with patch.object(discover_scholarships, "run_discovery") as discovery:
                with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
                    code = discover_scholarships.main()

        self.assertEqual(code, 1)
        self.engine.connect.assert_not_called()
        discovery.assert_not_called()
        self.assertEqual(
            self._json_output(self.stderr),
            {
                "status": "failed",
                "error": "controlled manual source validation failed",
            },
        )

    def test_manual_source_preflight_rejects_missing_duplicate_and_unsafe_entries(self):
        selected = discover_scholarships.controlled_manual_sources()
        self._assert_manual_source_preflight_fails(
            tuple(source for source in discover_scholarships.SOURCES
                  if source.source_id != selected[0].source_id)
        )
        self._assert_manual_source_preflight_fails(
            (*discover_scholarships.SOURCES, selected[0])
        )
        for field_changes in (
            {"crawl_enabled": False},
            {"trust_reviewed": False},
            {"trust_basis": "  "},
            {"discovery_only": True},
        ):
            with self.subTest(field_changes=field_changes):
                changed = replace(selected[0], **field_changes)
                self._assert_manual_source_preflight_fails(
                    tuple(
                        changed if source.source_id == changed.source_id else source
                        for source in discover_scholarships.SOURCES
                    )
                )

    def test_lock_and_discovery_share_the_same_connection(self):
        expected = {"status": "completed", "summary": {}}
        observed = {}

        def discovery(session, **options):
            observed["session"] = session
            observed.update(options)
            session.commit()
            self.assertTrue(self.lock_state["held"])
            return expected

        self.assertEqual(self._run(discovery), 0)
        self.engine.connect.assert_called_once_with()
        self.session_factory.assert_called_once_with(bind=self.connection)
        self.assertIs(observed["session"], self.session)
        self.assertIsNot(observed["session"], self.connection)
        self.assertIs(observed["lock_guard"], self.lock_guard)
        self.lock_guard.check.assert_called()
        self.assertEqual(observed["settings"], controlled_manual_settings(self.settings))
        self.assertEqual(observed["trigger_type"], "manual")
        self.assertEqual(
            tuple(source.source_id for source in observed["sources"]),
            CONTROLLED_MANUAL_SOURCE_IDS,
        )
        self.assertIsInstance(observed["run_budget"], DiscoveryRunBudget)
        self.assertEqual(observed["settings"].request_timeout_seconds, 15)
        self.assertEqual(observed["settings"].max_response_bytes, 10_000_000)
        self.assertEqual(observed["settings"].max_pages_per_source, 3)
        self.assertEqual(observed["settings"].max_retries, 2)
        self.assertTrue(self.connection.closed)
        self.assertFalse(self.lock_state["held"])
        self.assertEqual(self._json_output(self.stdout), expected)

    def test_manual_run_uses_pipeline_when_automatic_scheduler_is_disabled(self):
        self.settings = replace(self.settings, enabled=False)
        discover_scholarships.scholarship_discovery_settings.return_value = self.settings
        started = []
        observed = {}

        def discovery(_session, **options):
            observed.update(options)
            options["on_run_started"]("manual-run-id")
            return {"status": "completed", "summary": {}}

        self.assertEqual(
            self._run(
                discovery,
                run_id="manual-run-id",
                on_run_started=started.append,
            ),
            0,
        )
        self.assertEqual(observed["trigger_type"], "manual")
        self.assertEqual(observed["run_id"], "manual-run-id")
        self.assertIsNone(observed.get("scheduled_for"))
        self.assertEqual(
            tuple(source.source_id for source in observed["sources"]),
            CONTROLLED_MANUAL_SOURCE_IDS,
        )
        self.assertEqual(started, ["manual-run-id"])
        self.assertEqual(self._json_output(self.stdout)["status"], "completed")

    def test_admin_manual_worker_uses_the_same_exact_source_allowlist(self):
        from app.routers.admin_scholarships import _execute_manual_discovery

        observed = {}

        def discovery(session, **options):
            self.assertIs(session, self.session)
            observed.update(options)
            options["on_run_started"]("admin-run-id")
            return {"status": "completed", "summary": {}}

        with patch.object(discover_scholarships, "run_discovery", side_effect=discovery):
            with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
                code = _execute_manual_discovery(
                    "admin-run-id",
                    lambda run_id: self.assertEqual(run_id, "admin-run-id"),
                    lambda stage: self.assertTrue(stage),
                )

        self.assertEqual(code, 0)
        self.assertEqual(observed["trigger_type"], "manual")
        self.assertEqual(observed["run_id"], "admin-run-id")
        self.assertEqual(
            tuple(source.source_id for source in observed["sources"]),
            CONTROLLED_MANUAL_SOURCE_IDS,
        )

    def test_scheduled_run_uses_the_same_discovery_pipeline(self):
        scheduled_for = "2026-11-08T12:00:00+00:00"
        observed = {}

        def discovery(_session, **options):
            observed.update(options)
            return {"status": "completed", "summary": {}}

        self.assertEqual(
            self._run(
                discovery,
                trigger_type="scheduled",
                scheduled_for=scheduled_for,
            ),
            0,
        )
        self.assertEqual(observed["trigger_type"], "scheduled")
        self.assertEqual(observed["scheduled_for"], scheduled_for)
        self.assertIs(observed["lock_guard"], self.lock_guard)
        self.assertNotIn("sources", observed)
        self.assertNotIn("run_budget", observed)
        self.assertEqual(self._json_output(self.stdout)["status"], "completed")

    def test_catch_up_run_keeps_existing_source_selection(self):
        scheduled_for = "2026-11-08T12:00:00+00:00"
        observed = {}

        def discovery(_session, **options):
            observed.update(options)
            return {"status": "completed", "summary": {}}

        self.assertEqual(
            self._run(
                discovery,
                trigger_type="catch_up",
                scheduled_for=scheduled_for,
            ),
            0,
        )
        self.assertEqual(observed["trigger_type"], "catch_up")
        self.assertEqual(observed["scheduled_for"], scheduled_for)
        self.assertNotIn("sources", observed)
        self.assertNotIn("run_budget", observed)

    def test_worker_stage_callback_reports_startup_and_source_progress(self):
        stages = []

        def discovery(_session, **options):
            options["on_run_started"]("manual-run-id")
            options["on_stage"]("source:test-source")
            return {"status": "completed", "summary": {}}

        self.assertEqual(
            self._run(
                discovery,
                run_id="manual-run-id",
                on_run_started=lambda _run_id: None,
                on_stage=stages.append,
            ),
            0,
        )
        self.assertEqual(
            stages,
            [
                "waiting_for_advisory_lock",
                "recovering_interrupted_runs",
                "starting_discovery",
                "source:test-source",
            ],
        )

    def test_scheduled_run_remains_disabled_when_automatic_scheduler_is_off(self):
        self.settings = replace(self.settings, enabled=False)
        discover_scholarships.scholarship_discovery_settings.return_value = self.settings
        with patch.object(discover_scholarships, "run_discovery") as discovery:
            with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
                code = discover_scholarships.main(
                    trigger_type="scheduled",
                    scheduled_for="2026-11-08T12:00:00+00:00",
                )

        self.assertEqual(code, 2)
        discovery.assert_not_called()
        self.engine.connect.assert_not_called()
        self.assertEqual(self._json_output(self.stdout)["status"], "disabled")

    def test_second_connection_cannot_acquire_during_discovery_and_can_afterward(self):
        second_connection = _LockConnection(self.lock_state)

        def discovery(_session, **_kwargs):
            self.session.commit()
            self.assertFalse(second_connection.execute(
                "SELECT pg_try_advisory_lock(:lock_id)", {"lock_id": LOCK_ID}
            ).scalar_one())
            self.assertTrue(self.lock_state["held"])
            return {"status": "completed"}

        self.assertEqual(self._run(discovery), 0)
        self.assertTrue(second_connection.execute(
            "SELECT pg_try_advisory_lock(:lock_id)", {"lock_id": LOCK_ID}
        ).scalar_one())

    def test_lock_is_released_after_discovery_exception(self):
        def fail(*_args, **_kwargs):
            raise ValueError("discovery failure")

        self.assertEqual(self._run(fail), 1)
        self.assertFalse(self.lock_state["held"])
        self.assertTrue(self.connection.closed)
        self.assertEqual(self._json_output(self.stderr), {"status": "failed", "error": "ValueError"})

    def test_lock_is_released_when_commit_fails_immediately_after_acquisition(self):
        self.connection.fail_commit = True

        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            code = discover_scholarships.main()

        self.assertEqual(code, 1)
        self.assertFalse(self.lock_state["held"])
        self.assertTrue(self.connection.closed)
        self.assertEqual(self._json_output(self.stderr), {"status": "failed", "error": "RuntimeError"})

    def test_lock_is_released_when_backend_pid_lookup_fails(self):
        self.connection.fail_backend_pid = True

        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            code = discover_scholarships.main()

        self.assertEqual(code, 1)
        self.assertFalse(self.lock_state["held"])
        self.assertTrue(self.connection.closed)
        self.assertEqual(self._json_output(self.stderr), {"status": "failed", "error": "RuntimeError"})

    def test_uncertain_acquisition_invalidates_connection(self):
        self.connection.fail_acquire_result = True

        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            with self.assertRaisesRegex(RuntimeError, "response was lost"):
                discover_scholarships.main()

        self.assertTrue(self.connection.invalidated)
        self.assertTrue(self.connection.closed)
        self.assertFalse(self.lock_state["held"])

    def test_failed_lock_acquisition_does_not_start_discovery(self):
        self.connection.acquire = False
        with patch.object(discover_scholarships, "run_discovery") as discovery:
            with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
                code = discover_scholarships.main()

        self.assertEqual(code, 3)
        discovery.assert_not_called()
        self.session_factory.assert_not_called()
        self.assertEqual(
            self._json_output(self.stdout),
            {"status": "skipped", "reason": "another discovery run is active"},
        )

    def test_startup_recovery_waits_for_the_shared_lock(self):
        self.connection.acquire = False

        with patch.object(discover_scholarships, "recover_stale_runs") as recovery:
            with patch.object(discover_scholarships, "run_discovery") as discovery:
                with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
                    code = discover_scholarships.main(recovery_only=True)

        self.assertEqual(code, 3)
        self.session_factory.assert_not_called()
        recovery.assert_not_called()
        discovery.assert_not_called()

    def test_recovery_only_does_not_start_discovery_or_create_a_run(self):
        with patch.object(discover_scholarships, "recover_stale_runs", return_value=2) as recovery:
            with patch.object(discover_scholarships, "DiscoveryRunBudget") as budget:
                with patch.object(discover_scholarships, "controlled_manual_sources") as sources:
                    with patch.object(
                        discover_scholarships,
                        "create_manual_discovery_engine",
                    ) as manual_engine:
                        with patch.object(
                            discover_scholarships,
                            "run_discovery",
                        ) as discovery:
                            with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
                                code = discover_scholarships.main(recovery_only=True)

        self.assertEqual(code, 0)
        recovery.assert_called_once_with(
            self.session,
            self.settings.stale_run_timeout_hours,
            lock_guard=self.lock_guard,
        )
        budget.assert_not_called()
        sources.assert_not_called()
        manual_engine.assert_not_called()
        discovery.assert_not_called()
        self.session.add.assert_not_called()
        self.assertEqual(
            self._json_output(self.stdout),
            {"status": "recovered", "recovered_runs": 2},
        )

    def test_missing_migration_does_not_start_discovery(self):
        with patch.object(
            discover_scholarships,
            "inspect",
            return_value=MagicMock(get_table_names=lambda: []),
        ):
            with patch.object(discover_scholarships, "run_discovery") as discovery:
                with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
                    code = discover_scholarships.main()

        self.assertEqual(code, 1)
        discovery.assert_not_called()
        self.assertEqual(
            self._json_output(self.stderr),
            {"status": "failed", "error": "discovery run-history migration is required"},
        )

    def test_missing_scheduler_migration_does_not_start_discovery(self):
        with patch.object(
            discover_scholarships,
            "inspect",
            return_value=MagicMock(
                get_table_names=lambda: [
                    "scholarship_discovery_runs",
                    "scholarship_discovery_review_items",
                ],
                get_columns=lambda _table: [{"name": "id"}],
            ),
        ):
            with patch.object(discover_scholarships, "run_discovery") as discovery:
                with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
                    code = discover_scholarships.main()

        self.assertEqual(code, 1)
        discovery.assert_not_called()
        self.assertEqual(
            self._json_output(self.stderr),
            {"status": "failed", "error": "discovery run-history migration is required"},
        )

    def test_failed_unlock_invalidates_connection_to_release_lock(self):
        self.connection.fail_unlock = True

        self.assertEqual(
            self._run(lambda *_args, **_kwargs: {"status": "completed"}),
            1,
        )
        self.assertTrue(self.connection.invalidated)
        self.assertTrue(self.connection.closed)
        self.assertFalse(self.lock_state["held"])
        self.assertEqual(self._json_output(self.stderr), {"status": "failed", "error": "RuntimeError"})

    def test_unlock_returning_false_invalidates_connection(self):
        self.connection.unlock_result = False

        self.assertEqual(
            self._run(lambda *_args, **_kwargs: {"status": "completed"}),
            1,
        )
        self.assertTrue(self.connection.invalidated)
        self.assertTrue(self.connection.closed)
        self.assertFalse(self.lock_state["held"])
        self.assertEqual(self._json_output(self.stderr), {"status": "failed", "error": "RuntimeError"})

    def test_invalid_configuration_returns_json_without_traceback(self):
        with patch.object(
            discover_scholarships,
            "scholarship_discovery_settings",
            side_effect=RuntimeError("invalid setting"),
        ):
            with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
                code = discover_scholarships.main()

        self.assertEqual(code, 1)
        self.assertEqual(self._json_output(self.stderr), {"status": "failed", "error": "RuntimeError"})
        self.assertNotIn("Traceback", self.stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
