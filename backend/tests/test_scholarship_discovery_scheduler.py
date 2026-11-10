import os
import threading
import unittest
from datetime import datetime, timedelta, timezone
from inspect import Parameter, signature
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import ScholarshipDiscoverySettings, scholarship_discovery_settings
from app.database import Base
from app.models.scholarship_discovery import ScholarshipDiscoveryReviewItem, ScholarshipDiscoveryRun
from app.models.user import User
from app.routers import admin_scholarships
from app.routers.auth import get_current_user
from app.services.scholarship_discovery_scheduler import (
    DiscoveryLockLost,
    calculate_next_run,
    recover_stale_runs,
)
from run_scholarship_discovery_scheduler import (
    _recover_stale_runs_on_startup,
    run_scheduler,
)


def _settings(**changes):
    values = {
        "enabled": True,
        "request_timeout_seconds": 2,
        "max_response_bytes": 2048,
        "max_extracted_chars": 2000,
        "max_pages_per_source": 5,
        "max_retries": 1,
        "request_delay_seconds": 0,
        "user_agent": "FitScholarTest/1.0",
        "model": "test-model",
        "interval_hours": 24,
        "stale_run_timeout_hours": 12,
    }
    values.update(changes)
    return ScholarshipDiscoverySettings(**values)


def _reset_manual_discovery_state():
    with admin_scholarships._manual_discovery_state_lock:
        admin_scholarships._manual_discovery_state.clear()
        admin_scholarships._manual_discovery_state.update({
            "status": "idle",
            "run_id": None,
            "trigger_type": None,
            "submitted_at": None,
            "started_at": None,
            "finished_at": None,
            "stage": None,
            "error": None,
        })


class SchedulerTimingTests(unittest.TestCase):
    def test_default_and_configured_intervals(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(scholarship_discovery_settings().interval_hours, 24)
        with patch.dict(os.environ, {"SCHOLARSHIP_DISCOVERY_INTERVAL_HOURS": "6"}):
            self.assertEqual(scholarship_discovery_settings().interval_hours, 6)

    def test_next_run_uses_the_configured_interval(self):
        now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        last_run = now - timedelta(hours=4)
        next_run, trigger = calculate_next_run(last_run, now, 6)
        self.assertEqual(next_run, now + timedelta(hours=2))
        self.assertEqual(trigger, "scheduled")

    def test_restart_schedules_only_the_most_recent_missed_slot_as_catch_up(self):
        now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        last_run = now - timedelta(hours=55)
        next_run, trigger = calculate_next_run(last_run, now, 24)
        self.assertEqual(next_run, now - timedelta(hours=7))
        self.assertEqual(trigger, "catch_up")

    def test_disabled_scheduler_does_not_execute(self):
        execute = Mock()
        self.assertEqual(run_scheduler(_settings(enabled=False), threading.Event(), execute=execute), 0)
        execute.assert_not_called()

    def test_graceful_shutdown_while_waiting_does_not_execute(self):
        now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        stop_event = threading.Event()
        delays = []

        def wait(delay):
            delays.append(delay)
            stop_event.set()
            return True

        execute = Mock()
        result = run_scheduler(
            _settings(interval_hours=6),
            stop_event,
            recover=Mock(return_value=0),
            get_latest_scheduled_for=lambda: now - timedelta(hours=4),
            execute=execute,
            clock=lambda: now,
            wait=wait,
        )
        self.assertEqual(result, 0)
        self.assertEqual(delays, [2 * 60 * 60])
        execute.assert_not_called()

    def test_on_time_wakeup_keeps_scheduled_trigger_type(self):
        start = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        stop_event = threading.Event()
        current_time = [start]
        executed = []

        def wait(delay):
            current_time[0] += timedelta(seconds=delay)
            return False

        def execute(*, trigger_type, scheduled_for):
            executed.append((trigger_type, scheduled_for))
            stop_event.set()
            return 0

        result = run_scheduler(
            _settings(interval_hours=6),
            stop_event,
            recover=Mock(return_value=0),
            get_latest_scheduled_for=lambda: start - timedelta(hours=4),
            execute=execute,
            clock=lambda: current_time[0],
            wait=wait,
        )
        self.assertEqual(result, 0)
        self.assertEqual(executed, [("scheduled", start + timedelta(hours=2))])

    def test_catch_up_executes_once_and_stops_cleanly(self):
        now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        last_slot = now - timedelta(hours=49)
        stop_event = threading.Event()
        executed = []

        def execute(*, trigger_type, scheduled_for):
            executed.append((trigger_type, scheduled_for))
            stop_event.set()
            return 0

        result = run_scheduler(
            _settings(),
            stop_event,
            recover=Mock(return_value=0),
            get_latest_scheduled_for=lambda: last_slot,
            execute=execute,
            clock=lambda: now,
            wait=lambda _delay: False,
        )
        self.assertEqual(result, 0)
        self.assertEqual(executed, [("catch_up", now - timedelta(hours=1))])

    def test_startup_recovery_uses_the_dedicated_recovery_trigger(self):
        with patch(
            "run_scholarship_discovery_scheduler.execute_discovery",
            return_value=0,
        ) as execute:
            self.assertEqual(_recover_stale_runs_on_startup(), 0)

        execute.assert_called_once_with(
            trigger_type="recovery",
            recovery_only=True,
        )

    def test_startup_recovery_happens_before_waiting_and_does_not_discover(self):
        now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        stop_event = threading.Event()
        engine = create_engine("sqlite://", poolclass=StaticPool)
        ScholarshipDiscoveryRun.__table__.create(engine)
        session = sessionmaker(bind=engine)()
        self.addCleanup(engine.dispose)
        self.addCleanup(session.close)
        recovered = []
        recovery_calls = []
        execute = Mock()

        def recover():
            recovery_calls.append("recovered")
            recovered.append(recover_stale_runs(
                session,
                12,
                now,
                lock_guard=Mock(check=Mock(return_value=True)),
            ))
            stop_event.set()
            return 0

        stale = ScholarshipDiscoveryRun(
            id="startup-stale",
            started_at=now - timedelta(hours=13),
            status="running",
            summary={"sources_attempted": 1},
            source_results=[],
        )
        session.add(stale)
        session.commit()

        result = run_scheduler(
            _settings(),
            stop_event,
            recover=recover,
            execute=execute,
            wait=Mock(),
        )

        self.assertEqual(result, 0)
        self.assertEqual(recovery_calls, ["recovered"])
        self.assertEqual(recovered, [1])
        session.expire_all()
        self.assertEqual(session.get(ScholarshipDiscoveryRun, "startup-stale").status, "failed")
        execute.assert_not_called()

    def test_startup_recovery_retries_lock_contention_before_scheduling(self):
        stop_event = threading.Event()
        recovery_codes = iter([3, 0])
        def recover():
            code = next(recovery_codes)
            if code == 0:
                stop_event.set()
            return code

        recovery = Mock(side_effect=recover)
        waits = []
        executed = []

        def wait(delay):
            waits.append(delay)
            if len(waits) == 1:
                return False
            stop_event.set()
            return True

        result = run_scheduler(
            _settings(),
            stop_event,
            recover=recovery,
            execute=lambda **kwargs: executed.append(kwargs),
            wait=wait,
        )

        self.assertEqual(result, 0)
        self.assertEqual(recovery.call_count, 2)
        self.assertEqual(waits, [30])
        self.assertEqual(executed, [])


class InterruptedRunRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool)
        ScholarshipDiscoveryRun.__table__.create(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)

    def test_only_stale_runs_are_failed_and_never_marked_successful(self):
        now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        stale = ScholarshipDiscoveryRun(
            id="stale",
            started_at=now - timedelta(hours=13),
            status="running",
            summary={"sources_attempted": 1},
            source_results=[],
        )
        active = ScholarshipDiscoveryRun(
            id="active",
            started_at=now - timedelta(hours=11),
            status="running",
            summary={},
            source_results=[],
        )
        self.session.add_all([stale, active])
        self.session.commit()

        self.assertEqual(
            recover_stale_runs(
                self.session,
                12,
                now,
                lock_guard=Mock(check=Mock(return_value=True)),
            ),
            1,
        )
        self.session.expire_all()
        self.assertEqual(self.session.get(ScholarshipDiscoveryRun, "stale").status, "failed")
        self.assertIn(
            "reconciled while holding the exclusive discovery advisory lock",
            self.session.get(ScholarshipDiscoveryRun, "stale").summary["error_summary"],
        )
        self.assertEqual(self.session.get(ScholarshipDiscoveryRun, "active").status, "running")

    def test_repeated_stale_recovery_is_idempotent(self):
        now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        self.session.add(ScholarshipDiscoveryRun(
            id="stale-once",
            started_at=now - timedelta(hours=13),
            status="running",
            summary={"existing": "context"},
            source_results=[],
        ))
        self.session.commit()

        lock_guard = Mock(check=Mock(return_value=True))
        self.assertEqual(recover_stale_runs(self.session, 12, now, lock_guard=lock_guard), 1)
        self.assertEqual(recover_stale_runs(self.session, 12, now, lock_guard=lock_guard), 0)
        recovered = self.session.get(ScholarshipDiscoveryRun, "stale-once")
        self.assertEqual(recovered.status, "failed")
        self.assertEqual(recovered.summary["existing"], "context")
        self.assertEqual(
            recovered.summary["recovery"]["reason"],
            "orphaned_run_reconciled_under_exclusive_lock",
        )

    def test_exclusive_advisory_lock_reconciles_stale_runs(self):
        now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        run = ScholarshipDiscoveryRun(
            id="stale-orphan",
            started_at=now - timedelta(hours=13),
            status="running",
            summary={},
            source_results=[],
        )
        self.session.add(run)
        self.session.commit()
        lock_guard = Mock(check=Mock(return_value=True))

        self.assertEqual(recover_stale_runs(self.session, 12, now, lock_guard=lock_guard), 1)
        self.session.refresh(run)
        self.assertEqual(run.status, "failed")
        self.assertEqual(
            run.summary["recovery"]["reason"],
            "orphaned_run_reconciled_under_exclusive_lock",
        )
        self.assertEqual(lock_guard.check.call_count, 2)

    def test_recovery_requires_a_verified_lock_guard(self):
        now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        parameter = signature(recover_stale_runs).parameters["lock_guard"]
        self.assertIs(parameter.default, Parameter.empty)
        with self.assertRaises(DiscoveryLockLost):
            recover_stale_runs(
                self.session,
                12,
                now,
                lock_guard=Mock(check=Mock(return_value=None)),
            )

    def test_guard_returning_false_prevents_recovery(self):
        now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        run = ScholarshipDiscoveryRun(
            id="guard-false",
            started_at=now - timedelta(hours=13),
            status="running",
            summary={},
            source_results=[],
        )
        self.session.add(run)
        self.session.commit()

        with self.assertRaises(DiscoveryLockLost):
            recover_stale_runs(self.session, 12, now, lock_guard=Mock(check=Mock(return_value=False)))

        self.session.refresh(run)
        self.assertEqual(run.status, "running")

    def test_guard_exception_prevents_recovery(self):
        now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        run = ScholarshipDiscoveryRun(
            id="guard-error",
            started_at=now - timedelta(hours=13),
            status="running",
            summary={},
            source_results=[],
        )
        self.session.add(run)
        self.session.commit()

        with self.assertRaises(DiscoveryLockLost):
            recover_stale_runs(
                self.session,
                12,
                now,
                lock_guard=Mock(check=Mock(side_effect=RuntimeError("database unavailable"))),
            )

        self.session.refresh(run)
        self.assertEqual(run.status, "running")

    def test_ownership_is_rechecked_before_recovery_commit(self):
        now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        run = ScholarshipDiscoveryRun(
            id="lost-before-commit",
            started_at=now - timedelta(hours=13),
            status="running",
            summary={},
            source_results=[],
        )
        self.session.add(run)
        self.session.commit()
        lock_guard = Mock(check=Mock(side_effect=[True, False]))

        with self.assertRaises(DiscoveryLockLost):
            recover_stale_runs(self.session, 12, now, lock_guard=lock_guard)

        self.session.refresh(run)
        self.assertEqual(run.status, "running")

    def test_verified_guard_does_not_reconcile_a_recent_run(self):
        now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        run = ScholarshipDiscoveryRun(
            id="recent-run",
            started_at=now - timedelta(minutes=5),
            status="running",
            summary={},
            source_results=[],
        )
        self.session.add(run)
        self.session.commit()

        self.assertEqual(
            recover_stale_runs(
                self.session,
                12,
                now,
                lock_guard=Mock(check=Mock(return_value=True)),
            ),
            0,
        )
        self.session.refresh(run)
        self.assertEqual(run.status, "running")

    def test_a_scheduled_slot_cannot_have_duplicate_run_records(self):
        slot = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
        self.session.add_all([
            ScholarshipDiscoveryRun(
                id="first",
                started_at=slot,
                scheduled_for=slot,
                trigger_type="scheduled",
                status="completed",
                summary={},
                source_results=[],
            ),
            ScholarshipDiscoveryRun(
                id="duplicate",
                started_at=slot,
                scheduled_for=slot,
                trigger_type="catch_up",
                status="running",
                summary={},
                source_results=[],
            ),
        ])
        with self.assertRaises(IntegrityError):
            self.session.commit()


class DiscoveryMonitoringRouteTests(unittest.TestCase):
    def setUp(self):
        _reset_manual_discovery_state()
        self.addCleanup(_reset_manual_discovery_state)
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)
        self.admin = User(
            email="admin@example.com",
            hashed_password="test-hash",
            full_name="Admin",
            role="admin",
        )
        self.student = User(
            email="student@example.com",
            hashed_password="test-hash",
            full_name="Student",
            role="student",
        )
        self.session.add_all([self.admin, self.student])
        self.session.commit()

    def _client(self, user):
        app = FastAPI()
        app.include_router(admin_scholarships.router)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[admin_scholarships.get_db] = lambda: self.session
        return TestClient(app)

    def test_monitoring_is_admin_only_and_returns_run_and_queue_history(self):
        now = datetime.now(timezone.utc)
        successful = ScholarshipDiscoveryRun(
            id="successful",
            started_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=2),
            scheduled_for=now - timedelta(hours=3),
            trigger_type="scheduled",
            status="completed",
            summary={
                "sources_attempted": 2,
                "sources_successfully_fetched": 2,
                "sources_failed": 0,
                "scholarships_discovered": 3,
                "new_records_created": 1,
                "review_candidates_queued": 2,
                "duplicates_skipped": 1,
            },
            source_results=[],
        )
        failed = ScholarshipDiscoveryRun(
            id="failed",
            started_at=now - timedelta(hours=1),
            finished_at=now - timedelta(minutes=50),
            trigger_type="manual",
            status="failed",
            summary={"sources_failed": 1, "error_summary": "TimeoutError"},
            source_results=[{
                "source_id": "test-source",
                "source_name": "Test source",
                "status": "failed",
                "error": "private exception text token=do-not-return",
                "error_category": "http_status",
                "failure_stage": "robots",
                "page_stage": "root_fetch",
                "http_status": 503,
                "attempt_count": 2,
                "attempt_limit": 3,
                "cause_type": "TimeoutError",
                "source_url": "https://official.example/?token=do-not-return",
                "response_body": "private response body",
            }],
        )
        legacy = ScholarshipDiscoveryRun(
            id="legacy",
            started_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=1, minutes=50),
            trigger_type="manual",
            status="failed",
            summary={"sources_failed": 1},
            source_results=[{
                "source_id": "legacy-source",
                "source_name": "Legacy source",
                "status": "failed",
                "error": "DiscoveryFetchError",
            }],
        )
        current = ScholarshipDiscoveryRun(
            id="current",
            started_at=now,
            trigger_type="manual",
            status="running",
            summary={},
            source_results=[],
        )
        self.session.add_all([successful, failed, legacy, current])
        self.session.flush()
        self.session.add(ScholarshipDiscoveryReviewItem(
            candidate_fingerprint="a" * 64,
            candidate_name="Review candidate",
            host_country="Finland",
            source_id="test-source",
            source_name="Test source",
            source_classification="official_provider",
            source_url="https://example.org/scholarship",
            review_reason="Incomplete candidate",
            discovery_run_id=successful.id,
        ))
        self.session.add(ScholarshipDiscoveryReviewItem(
            candidate_fingerprint="b" * 64,
            candidate_name="Resolved candidate",
            host_country="Finland",
            source_id="test-source",
            source_name="Test source",
            source_classification="official_provider",
            source_url="https://example.org/resolved-scholarship",
            review_reason="Already resolved",
            discovery_run_id=successful.id,
            review_status="rejected",
        ))
        self.session.commit()

        with patch.dict(os.environ, {
            "SCHOLARSHIP_DISCOVERY_ENABLED": "true",
            "SCHOLARSHIP_DISCOVERY_INTERVAL_HOURS": "6",
        }):
            with self._client(self.student) as client:
                denied = client.get("/admin/scholarships/discovery-monitoring")
            self.assertEqual(denied.status_code, 403)

            with patch.object(admin_scholarships, "discovery_advisory_lock_is_held", return_value=True):
                with self._client(self.admin) as client:
                    response = client.get("/admin/scholarships/discovery-monitoring")

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["enabled"])
        self.assertEqual(data["interval_hours"], 6)
        self.assertEqual(data["current_run_status"], "running")
        self.assertEqual(data["current_run"]["run_id"], "current")
        self.assertEqual(data["worker_status"], "running")
        self.assertEqual(data["worker_run_id"], "current")
        self.assertEqual(data["current_manual_run"]["run_id"], "current")
        self.assertEqual(data["last_scheduled_run"]["run_id"], "successful")
        self.assertEqual(data["last_successful_run"]["run_id"], "successful")
        self.assertEqual(data["last_completed_run"]["run_id"], "successful")
        self.assertEqual(data["last_failed_run"]["run_id"], "failed")
        self.assertEqual(data["candidates_total"], 2)
        self.assertEqual(data["review_queue_pending"], 1)
        failed_history = next(run for run in data["recent_runs"] if run["run_id"] == "failed")
        self.assertEqual(failed_history["error_summary"], "TimeoutError")
        failed_source = failed_history["failed_sources"][0]
        self.assertIsNone(failed_source["error"])
        self.assertEqual(failed_source["error_category"], "http_status")
        self.assertEqual(failed_source["failure_stage"], "robots")
        self.assertEqual(failed_source["page_stage"], "root_fetch")
        self.assertEqual(failed_source["http_status"], 503)
        self.assertEqual(failed_source["attempt_count"], 2)
        self.assertEqual(failed_source["attempt_limit"], 3)
        self.assertEqual(failed_source["cause_type"], "TimeoutError")
        self.assertNotIn("source_url", failed_source)
        self.assertNotIn("response_body", failed_source)
        response_text = response.text
        self.assertNotIn("do-not-return", response_text)
        self.assertNotIn("private response body", response_text)

        legacy_history = next(run for run in data["recent_runs"] if run["run_id"] == "legacy")
        legacy_source = legacy_history["failed_sources"][0]
        self.assertEqual(legacy_source["error"], "DiscoveryFetchError")
        self.assertIsNone(legacy_source["error_category"])
        self.assertIsNone(legacy_source["http_status"])

    def test_monitoring_and_history_sanitize_run_level_error_summaries(self):
        now = datetime.now(timezone.utc)
        generic = "Discovery run failed. See source-level diagnostics for details."
        summaries = {
            "safe": "TimeoutError",
            "unsafe": "RuntimeError: https://private.example/?token=do-not-return",
            "empty": "",
            "malformed": {"message": "private exception details"},
            "approved": (
                "Interrupted run reconciled while holding the exclusive discovery advisory lock"
            ),
            "too-long": "TimeoutError " + ("x" * 200),
        }
        runs = []
        for index, (run_id, error_summary) in enumerate(summaries.items()):
            started_at = now - timedelta(minutes=len(summaries) - index)
            runs.append(ScholarshipDiscoveryRun(
                id=f"error-{run_id}",
                started_at=started_at,
                finished_at=started_at + timedelta(seconds=1),
                trigger_type="manual",
                status="failed",
                summary={"sources_failed": 1, "error_summary": error_summary},
                source_results=[],
            ))
        self.session.add_all(runs)
        self.session.commit()

        with patch.object(admin_scholarships, "discovery_advisory_lock_is_held", return_value=False):
            with self._client(self.admin) as client:
                monitoring_response = client.get("/admin/scholarships/discovery-monitoring")
                history_response = client.get("/admin/scholarships/discovery-history?days=0")

        self.assertEqual(monitoring_response.status_code, 200, monitoring_response.text)
        self.assertEqual(history_response.status_code, 200, history_response.text)
        monitoring = monitoring_response.json()
        history = {
            run["run_id"]: run["error_summary"]
            for run in history_response.json()["items"]
        }
        expected = {
            "error-safe": "TimeoutError",
            "error-unsafe": generic,
            "error-empty": generic,
            "error-malformed": generic,
            "error-too-long": generic,
            "error-approved": (
                "Interrupted run reconciled while holding the exclusive discovery advisory lock"
            ),
        }
        for run in monitoring["recent_runs"]:
            if run["run_id"] in expected:
                self.assertEqual(run["error_summary"], expected[run["run_id"]])
        self.assertEqual(history, expected)
        self.assertEqual(monitoring["worker_error"], generic)
        self.assertNotIn("do-not-return", monitoring_response.text)
        self.assertNotIn("private exception details", monitoring_response.text)

    def test_manual_trigger_is_admin_only_and_works_when_scheduler_is_disabled(self):
        started = []

        def execute(run_id, on_run_started, on_stage):
            started.append(run_id)
            on_stage("waiting_for_advisory_lock")
            on_run_started(run_id)
            return 0

        with patch.dict(os.environ, {"SCHOLARSHIP_DISCOVERY_ENABLED": "false"}):
            with patch.object(admin_scholarships, "_execute_manual_discovery", side_effect=execute):
                with self._client(self.student) as client:
                    denied = client.post("/admin/scholarships/discovery-runs/manual")
                self.assertEqual(denied.status_code, 403)

                with self._client(self.admin) as client:
                    response = client.post("/admin/scholarships/discovery-runs/manual")

        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json(), {"run_id": started[0], "status": "running"})
        self.assertTrue(admin_scholarships._manual_discovery_submission_lock.acquire(timeout=2))
        admin_scholarships._manual_discovery_submission_lock.release()
        self.assertEqual(admin_scholarships._manual_discovery_state_snapshot()["status"], "completed")

    def test_manual_trigger_conflicts_with_an_existing_active_run(self):
        self.session.add(ScholarshipDiscoveryRun(
            id="active-run",
            started_at=datetime.now(timezone.utc),
            trigger_type="scheduled",
            status="running",
            summary={},
            source_results=[],
        ))
        self.session.commit()

        with patch.object(admin_scholarships, "_execute_manual_discovery") as execute:
            with self._client(self.admin) as client:
                response = client.post("/admin/scholarships/discovery-runs/manual")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "DISCOVERY_DATABASE_RUN_ACTIVE")
        execute.assert_not_called()

    def test_repeated_manual_submissions_conflict_while_first_run_is_active(self):
        release_worker = threading.Event()
        worker_finished = threading.Event()

        def execute(run_id, on_run_started, _on_stage):
            on_run_started(run_id)
            release_worker.wait(timeout=5)
            worker_finished.set()
            return 0

        with patch.object(admin_scholarships, "_execute_manual_discovery", side_effect=execute):
            with self._client(self.admin) as client:
                first = client.post("/admin/scholarships/discovery-runs/manual")
                second = client.post("/admin/scholarships/discovery-runs/manual")
        try:
            self.assertEqual(first.status_code, 202, first.text)
            self.assertEqual(second.status_code, 409)
            self.assertEqual(
                second.json()["detail"]["code"],
                "MANUAL_SUBMISSION_IN_PROGRESS",
            )
        finally:
            release_worker.set()
            self.assertTrue(worker_finished.wait(timeout=2))
            self.assertTrue(admin_scholarships._manual_discovery_submission_lock.acquire(timeout=2))
            admin_scholarships._manual_discovery_submission_lock.release()

    def test_advisory_lock_conflict_has_distinct_code_and_releases_submission_lock(self):
        with patch.object(admin_scholarships, "discovery_advisory_lock_is_held", return_value=True):
            with patch.object(admin_scholarships, "_execute_manual_discovery", return_value=3):
                with self._client(self.admin) as client:
                    response = client.post("/admin/scholarships/discovery-runs/manual")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "DISCOVERY_ADVISORY_LOCK_ACTIVE")
        self.assertIn("advisory lock", response.json()["detail"]["message"])
        self.assertTrue(admin_scholarships._manual_discovery_submission_lock.acquire(timeout=2))
        admin_scholarships._manual_discovery_submission_lock.release()
        self.assertEqual(admin_scholarships._manual_discovery_state_snapshot()["status"], "failed")

    def test_worker_exception_is_reported_and_submission_lock_is_released(self):
        with patch.object(admin_scholarships, "_execute_manual_discovery", side_effect=RuntimeError("test")):
            with self._client(self.admin) as client:
                response = client.post("/admin/scholarships/discovery-runs/manual")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(admin_scholarships._manual_discovery_state_snapshot()["status"], "failed")
        self.assertEqual(admin_scholarships._manual_discovery_state_snapshot()["error"], "RuntimeError")
        self.assertTrue(admin_scholarships._manual_discovery_submission_lock.acquire(timeout=2))
        admin_scholarships._manual_discovery_submission_lock.release()

    def test_monitoring_reports_submission_before_a_run_record_exists(self):
        with admin_scholarships._manual_discovery_state_lock:
            admin_scholarships._manual_discovery_state.update({
                "status": "submitting",
                "run_id": "pending-run",
                "trigger_type": "manual",
                "submitted_at": datetime.now(timezone.utc),
                "started_at": None,
                "finished_at": None,
                "stage": "checking_active_run",
                "error": None,
            })
        with patch.object(admin_scholarships, "discovery_advisory_lock_is_held", return_value=False):
            with self._client(self.admin) as client:
                response = client.get("/admin/scholarships/discovery-monitoring")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["worker_status"], "submitting")
        self.assertEqual(response.json()["worker_run_id"], "pending-run")
        self.assertEqual(response.json()["current_run_status"], "idle")
        self.assertIsNone(response.json()["current_run"])

    def test_submission_lock_without_a_run_record_is_not_reported_as_running(self):
        self.assertTrue(admin_scholarships._manual_discovery_submission_lock.acquire(blocking=False))
        with admin_scholarships._manual_discovery_state_lock:
            admin_scholarships._manual_discovery_state.update({
                "status": "starting",
                "run_id": "starting-run",
                "trigger_type": "manual",
                "submitted_at": datetime.now(timezone.utc),
                "started_at": None,
                "finished_at": None,
                "stage": "waiting_for_worker_start",
                "error": None,
            })
        try:
            with patch.object(admin_scholarships, "discovery_advisory_lock_is_held", return_value=True):
                with self._client(self.admin) as client:
                    response = client.get("/admin/scholarships/discovery-monitoring")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["worker_status"], "starting")
            self.assertEqual(response.json()["current_run_status"], "idle")
            self.assertIsNone(response.json()["current_run"])
        finally:
            admin_scholarships._manual_discovery_submission_lock.release()

    def test_monitoring_marks_unlocked_running_record_interrupted_without_mutating_it(self):
        interrupted = ScholarshipDiscoveryRun(
            id="interrupted-run",
            started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            trigger_type="manual",
            status="running",
            summary={},
            source_results=[],
        )
        self.session.add(interrupted)
        self.session.commit()

        with patch.object(admin_scholarships, "discovery_advisory_lock_is_held", return_value=False):
            with self._client(self.admin) as client:
                response = client.get("/admin/scholarships/discovery-monitoring")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["worker_status"], "interrupted_unknown")
        self.assertEqual(response.json()["worker_run_id"], "interrupted-run")
        self.assertEqual(response.json()["current_run_status"], "idle")
        self.assertTrue(response.json()["worker_recoverable"])
        self.session.refresh(interrupted)
        self.assertEqual(interrupted.status, "running")

    def test_monitoring_does_not_claim_a_run_when_lock_state_is_unavailable(self):
        self.session.add(ScholarshipDiscoveryRun(
            id="unverified-run",
            started_at=datetime.now(timezone.utc),
            trigger_type="manual",
            status="running",
            summary={},
            source_results=[],
        ))
        self.session.commit()

        with patch.object(admin_scholarships, "discovery_advisory_lock_is_held", return_value=None):
            with self._client(self.admin) as client:
                response = client.get("/admin/scholarships/discovery-monitoring")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["worker_status"], "interrupted_unknown")
        self.assertFalse(response.json()["worker_recoverable"])
        self.assertIn("cannot be verified", response.json()["worker_error"])


if __name__ == "__main__":
    unittest.main()
