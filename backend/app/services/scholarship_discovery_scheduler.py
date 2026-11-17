"""Scheduling calculations and stale-run recovery for scholarship discovery."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.models.scholarship_discovery import ScholarshipDiscoveryRun


DISCOVERY_LOCK_ID = 631287180927007781


class DiscoveryLockLost(RuntimeError):
    """Raised when the discovery connection no longer owns its advisory lock."""


class DiscoveryAdvisoryLockGuard:
    def __init__(self, backend_pid: int, lock_id: int = DISCOVERY_LOCK_ID):
        self.backend_pid = backend_pid
        self.lock_id = lock_id

    def check(self, db):
        try:
            result = db.execute(
                text(
                    "SELECT pg_backend_pid(), EXISTS ("
                    "SELECT 1 FROM pg_locks "
                    "WHERE locktype = 'advisory' "
                    "AND pid = pg_backend_pid() "
                    "AND granted "
                    "AND database = (SELECT oid FROM pg_database "
                    "WHERE datname = current_database()) "
                    "AND classid = ((CAST(:lock_id AS BIGINT) >> 32) & 4294967295)::oid "
                    "AND objid = (CAST(:lock_id AS BIGINT) & 4294967295)::oid "
                    "AND objsubid = 1)"
                ),
                {"lock_id": self.lock_id},
            ).one()
            backend_pid = int(result[0])
            owns_lock = bool(result[1])
        except Exception as exc:
            raise DiscoveryLockLost("Could not confirm discovery advisory-lock ownership") from exc
        if backend_pid != self.backend_pid or not owns_lock:
            raise DiscoveryLockLost("Discovery advisory-lock ownership was lost")
        return True


def discovery_advisory_lock_is_held(db) -> bool | None:
    if db.get_bind().dialect.name != "postgresql":
        return None
    result = db.execute(
        text(
            "SELECT EXISTS ("
            "SELECT 1 FROM pg_locks "
            "WHERE locktype = 'advisory' "
            "AND granted "
            "AND database = (SELECT oid FROM pg_database "
            "WHERE datname = current_database()) "
            "AND classid = ((CAST(:lock_id AS BIGINT) >> 32) & 4294967295)::oid "
            "AND objid = (CAST(:lock_id AS BIGINT) & 4294967295)::oid "
            "AND objsubid = 1)"
        ),
        {"lock_id": DISCOVERY_LOCK_ID},
    ).scalar_one()
    return bool(result)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def calculate_next_run(
    last_scheduled_for: datetime | None,
    now: datetime,
    interval_hours: int,
) -> tuple[datetime, str]:
    if interval_hours < 1:
        raise ValueError("interval_hours must be positive")
    now = _utc(now)
    interval = timedelta(hours=interval_hours)
    if last_scheduled_for is None:
        return now, "scheduled"

    next_run = _utc(last_scheduled_for) + interval
    if next_run > now:
        return next_run, "scheduled"

    missed_slots = (now - next_run) // interval
    return next_run + missed_slots * interval, "catch_up"


def recover_stale_runs(
    db,
    timeout_hours: int,
    now: datetime | None = None,
    *,
    lock_guard: DiscoveryAdvisoryLockGuard,
) -> int:
    """Reconcile stale running rows only while exclusive lock ownership is verified."""
    if lock_guard is None:
        raise DiscoveryLockLost("Stale-run recovery requires verified advisory-lock ownership")

    def verify_ownership() -> None:
        try:
            owns_lock = lock_guard.check(db)
        except DiscoveryLockLost:
            raise
        except Exception as exc:
            raise DiscoveryLockLost("Could not confirm discovery advisory-lock ownership") from exc
        if owns_lock is not True:
            raise DiscoveryLockLost("Discovery advisory-lock ownership was lost")

    recovered_at = _utc(now or datetime.now(timezone.utc))
    stale_before = recovered_at - timedelta(hours=timeout_hours)
    try:
        verify_ownership()
        stale_runs = (
            db.query(ScholarshipDiscoveryRun)
            .filter(
                ScholarshipDiscoveryRun.status == "running",
                ScholarshipDiscoveryRun.started_at < stale_before,
            )
            .all()
        )
        for run in stale_runs:
            summary = dict(run.summary or {})
            summary["error_summary"] = (
                "Interrupted run reconciled while holding the exclusive discovery advisory lock"
            )
            summary["recovery"] = {
                "reason": "orphaned_run_reconciled_under_exclusive_lock",
                "recovered_at": recovered_at.isoformat(),
            }
            run.summary = summary
            run.status = "failed"
            run.finished_at = recovered_at
        if stale_runs:
            verify_ownership()
            db.commit()
        return len(stale_runs)
    except Exception:
        db.rollback()
        raise
