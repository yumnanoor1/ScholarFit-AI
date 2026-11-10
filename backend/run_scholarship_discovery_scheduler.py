"""Independent daily scheduler for scholarship discovery."""
import logging
import signal
import threading
from datetime import datetime, timezone

from app.core.config import ScholarshipDiscoverySettings, scholarship_discovery_settings
from app.database import SessionLocal
from app.models.scholarship_discovery import ScholarshipDiscoveryRun
from app.services.scholarship_discovery_scheduler import calculate_next_run
from discover_scholarships import main as execute_discovery

logger = logging.getLogger(__name__)
LOCK_CONTENTION_EXIT_CODE = 3
DISABLED_EXIT_CODE = 2
LOCK_RECHECK_SECONDS = 30


def _latest_scheduled_for():
    with SessionLocal() as db:
        run = (
            db.query(ScholarshipDiscoveryRun)
            .filter(ScholarshipDiscoveryRun.scheduled_for.is_not(None))
            .order_by(ScholarshipDiscoveryRun.scheduled_for.desc())
            .first()
        )
        return run.scheduled_for if run else None


def _slot_exists(scheduled_for):
    with SessionLocal() as db:
        return (
            db.query(ScholarshipDiscoveryRun.id)
            .filter(ScholarshipDiscoveryRun.scheduled_for == scheduled_for)
            .first()
            is not None
        )


def _recover_stale_runs_on_startup():
    return execute_discovery(trigger_type="recovery", recovery_only=True)


def run_scheduler(
    settings: ScholarshipDiscoverySettings,
    stop_event: threading.Event,
    *,
    get_latest_scheduled_for=_latest_scheduled_for,
    slot_exists=_slot_exists,
    execute=execute_discovery,
    recover=_recover_stale_runs_on_startup,
    clock=lambda: datetime.now(timezone.utc),
    wait=None,
) -> int:
    wait = wait or stop_event.wait
    if not settings.enabled:
        logger.info("Scholarship discovery scheduler is disabled")
        return 0

    while not stop_event.is_set():
        try:
            recovery_code = recover()
        except Exception as exc:
            logger.error("Scholarship discovery startup recovery failed: %s", type(exc).__name__)
            return 1
        if recovery_code == LOCK_CONTENTION_EXIT_CODE:
            if wait(min(LOCK_RECHECK_SECONDS, settings.interval_hours * 3600)):
                break
            continue
        if recovery_code == DISABLED_EXIT_CODE:
            logger.info("Scholarship discovery was disabled; stopping the scheduler")
            return 0
        if recovery_code:
            logger.error("Scholarship discovery startup recovery stopped with status %s", recovery_code)
            return recovery_code
        break

    while not stop_event.is_set():
        try:
            scheduled_for, trigger_type = calculate_next_run(
                get_latest_scheduled_for(),
                clock(),
                settings.interval_hours,
            )
        except Exception as exc:
            logger.error("Could not calculate the next scholarship discovery run: %s", type(exc).__name__)
            return 1

        delay = max(0.0, (scheduled_for - clock()).total_seconds())
        if delay:
            wait(delay)
            if stop_event.is_set():
                break
            if scheduled_for > clock():
                continue

        logger.info(
            "Starting scholarship discovery trigger=%s scheduled_for=%s",
            trigger_type,
            scheduled_for.isoformat(),
        )
        try:
            exit_code = execute(trigger_type=trigger_type, scheduled_for=scheduled_for)
        except Exception as exc:
            logger.error("Scholarship discovery execution failed: %s", type(exc).__name__)
            return 1

        if exit_code == DISABLED_EXIT_CODE:
            logger.info("Scholarship discovery was disabled; stopping the scheduler")
            return 0
        if exit_code == LOCK_CONTENTION_EXIT_CODE:
            wait(min(LOCK_RECHECK_SECONDS, settings.interval_hours * 3600))
            continue
        if exit_code:
            try:
                recorded = slot_exists(scheduled_for)
            except Exception as exc:
                logger.error("Could not verify the scheduled run record: %s", type(exc).__name__)
                return 1
            if not recorded:
                logger.error("Scholarship discovery stopped before recording its scheduled slot")
                return exit_code
            logger.warning(
                "Scholarship discovery run recorded with exit status %s; continuing on the next interval",
                exit_code,
            )

    logger.info("Scholarship discovery scheduler stopped")
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        settings = scholarship_discovery_settings()
    except RuntimeError as exc:
        logger.error("Scholarship discovery configuration failed: %s", str(exc))
        return 1

    stop_event = threading.Event()

    def request_shutdown(_signal, _frame):
        logger.info("Scholarship discovery scheduler shutdown requested")
        stop_event.set()

    signal.signal(signal.SIGINT, request_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_shutdown)
    return run_scheduler(settings, stop_event)


if __name__ == "__main__":
    raise SystemExit(main())
