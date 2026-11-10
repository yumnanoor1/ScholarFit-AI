"""Single-run entry point for an external daily scheduler."""
import json
import logging
import sys
from contextlib import nullcontext
from typing import Callable, Optional

from sqlalchemy import inspect, text

from app.core.config import scholarship_discovery_settings
from app.database import SessionLocal, engine
from app.models.scholarship_discovery import (
    SCHOLARSHIP_DISCOVERY_TABLE_NAMES,
    ScholarshipDiscoveryRun,
)
from app.services.scholarship_discovery import DiscoveryDisabled, run_discovery
from app.services.scholarship_discovery_budget import (
    ControlledManualSourceConfigurationError,
    DiscoveryRunBudget,
    controlled_manual_sources,
    controlled_manual_settings,
)
from app.services.scholarship_discovery_database import (
    ManualDiscoveryDatabaseDeadline,
    create_manual_discovery_engine,
)
from app.services.scholarship_discovery_scheduler import (
    DISCOVERY_LOCK_ID,
    DiscoveryAdvisoryLockGuard,
    recover_stale_runs,
)
from app.services.scholarship_discovery_sources import SOURCES


def main(
    *,
    trigger_type: str = "manual",
    scheduled_for=None,
    recovery_only: bool = False,
    run_id: Optional[str] = None,
    on_run_started: Optional[Callable[[str], None]] = None,
    on_stage: Optional[Callable[[str], None]] = None,
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    def report_stage(stage: str) -> None:
        if on_stage is not None:
            try:
                on_stage(stage)
            except Exception as exc:
                logging.error("Discovery stage notification failed: %s", type(exc).__name__)

    try:
        settings = scholarship_discovery_settings()
    except RuntimeError as exc:
        logging.error("Scholarship discovery configuration failed: %s", exc)
        print(json.dumps({"status": "failed", "error": type(exc).__name__}), file=sys.stderr)
        return 1
    if recovery_only:
        if trigger_type not in {"manual", "recovery"} or scheduled_for is not None:
            print(json.dumps({"status": "failed", "error": "invalid recovery execution"}), file=sys.stderr)
            return 1
        trigger_type = "recovery"
    elif trigger_type not in {"scheduled", "catch_up", "manual"}:
        print(json.dumps({"status": "failed", "error": "invalid trigger type"}), file=sys.stderr)
        return 1
    if (
        trigger_type in {"manual", "recovery"} and scheduled_for is not None
    ) or (
        trigger_type in {"scheduled", "catch_up"} and scheduled_for is None
    ):
        print(json.dumps({"status": "failed", "error": "invalid scheduled execution time"}), file=sys.stderr)
        return 1
    manual_sources = None
    run_settings = settings
    if trigger_type == "manual":
        try:
            manual_sources = controlled_manual_sources(SOURCES)
            run_settings = controlled_manual_settings(settings)
        except ControlledManualSourceConfigurationError:
            print(
                json.dumps({
                    "status": "failed",
                    "error": "controlled manual source validation failed",
                }),
                file=sys.stderr,
            )
            return 1
    if not settings.enabled and (trigger_type != "manual" or recovery_only):
        print(json.dumps({"status": "disabled", "reason": "Set SCHOLARSHIP_DISCOVERY_ENABLED=true"}))
        return 2

    run_budget = DiscoveryRunBudget() if trigger_type == "manual" else None
    if run_budget is not None:
        run_budget.start()
    connection_engine = engine
    owns_connection_engine = False
    database_deadline = None
    try:
        if run_budget is not None:
            connection_engine, owns_connection_engine = create_manual_discovery_engine(
                engine,
                run_budget,
            )

        report_stage("waiting_for_advisory_lock")
        with connection_engine.connect() as lock_connection:
            if run_budget is not None:
                database_deadline = ManualDiscoveryDatabaseDeadline(
                    lock_connection,
                    run_budget,
                )
            acquisition_state = "not_attempted"
            result = None
            response = None
            response_stream = sys.stdout
            exit_code = 0
            try:
                existing_tables = set(inspect(lock_connection).get_table_names())
                missing = SCHOLARSHIP_DISCOVERY_TABLE_NAMES - existing_tables
                columns = {
                    column["name"]
                    for column in inspect(lock_connection).get_columns("scholarship_discovery_runs")
                } if "scholarship_discovery_runs" in existing_tables else set()
                missing_columns = {"trigger_type", "scheduled_for"} - columns
                if missing or missing_columns:
                    print(
                        json.dumps({
                            "status": "failed",
                            "error": "discovery run-history migration is required",
                        }),
                        file=sys.stderr,
                    )
                    return 1

                acquisition_state = "uncertain"
                acquired = lock_connection.execute(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": DISCOVERY_LOCK_ID},
                ).scalar_one()
                if acquired is False:
                    acquisition_state = "not_acquired"
                    print(json.dumps({"status": "skipped", "reason": "another discovery run is active"}))
                    return 3
                if acquired is not True:
                    raise RuntimeError("advisory lock acquisition returned an unknown result")
                acquisition_state = "acquired"

                try:
                    lock_connection.commit()
                    lock_guard = DiscoveryAdvisoryLockGuard(
                        lock_connection.execute(text("SELECT pg_backend_pid()")).scalar_one(),
                    )
                    report_stage("recovering_interrupted_runs")
                    with SessionLocal(bind=lock_connection) as db:
                        if database_deadline is not None:
                            database_deadline.attach_session(db)
                        lock_guard.check(db)
                        if recovery_only:
                            recovered = recover_stale_runs(
                                db,
                                settings.stale_run_timeout_hours,
                                lock_guard=lock_guard,
                            )
                            response = {"status": "recovered", "recovered_runs": recovered}
                        else:
                            recover_stale_runs(
                                db,
                                settings.stale_run_timeout_hours,
                                lock_guard=lock_guard,
                            )
                        if not recovery_only:
                            run_options = {}
                            if run_id is not None:
                                run_options["run_id"] = run_id
                            if on_run_started is not None:
                                run_options["on_run_started"] = on_run_started
                            if on_stage is not None:
                                run_options["on_stage"] = report_stage
                            if trigger_type == "manual":
                                run_options["sources"] = manual_sources
                                run_options["run_budget"] = run_budget
                                run_options["database_deadline"] = database_deadline
                            if scheduled_for is not None:
                                existing_run = (
                                    db.query(ScholarshipDiscoveryRun)
                                    .filter(ScholarshipDiscoveryRun.scheduled_for == scheduled_for)
                                    .first()
                                )
                                if existing_run is not None:
                                    response = {
                                        "status": "skipped",
                                        "reason": "scheduled slot already has a run record",
                                    }
                                    exit_code = 0
                                else:
                                    report_stage("starting_discovery")
                                    result = run_discovery(
                                        db,
                                        settings=run_settings,
                                        trigger_type=trigger_type,
                                        scheduled_for=scheduled_for,
                                        lock_guard=lock_guard,
                                        **run_options,
                                    )
                            else:
                                report_stage("starting_discovery")
                                result = run_discovery(
                                    db,
                                    settings=run_settings,
                                    trigger_type=trigger_type,
                                    lock_guard=lock_guard,
                                    **run_options,
                                )
                except DiscoveryDisabled as exc:
                    response = {"status": "disabled", "reason": str(exc)}
                    exit_code = 2
                except Exception as exc:
                    logging.error("Scholarship discovery failed: %s", type(exc).__name__)
                    response = {"status": "failed", "error": type(exc).__name__}
                    response_stream = sys.stderr
                    exit_code = 1
            finally:
                if acquisition_state == "acquired":
                    try:
                        finalization = (
                            database_deadline.finalization()
                            if database_deadline is not None
                            else nullcontext()
                        )
                        with finalization:
                            released = lock_connection.execute(
                                text("SELECT pg_advisory_unlock(:lock_id)"),
                                {"lock_id": DISCOVERY_LOCK_ID},
                            ).scalar_one()
                            if not released:
                                raise RuntimeError("advisory lock was not held during release")
                            lock_connection.commit()
                        acquisition_state = "released"
                    except Exception as exc:
                        lock_connection.invalidate()
                        logging.error("Scholarship discovery lock release failed: %s", type(exc).__name__)
                        response = {"status": "failed", "error": type(exc).__name__}
                        response_stream = sys.stderr
                        exit_code = 1
                elif acquisition_state == "uncertain":
                    lock_connection.invalidate()

            if response is not None:
                print(json.dumps(response), file=response_stream)
                return exit_code
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["status"] == "completed" else 1
    finally:
        if database_deadline is not None:
            database_deadline.close()
        if owns_connection_engine:
            connection_engine.dispose()
        if run_budget is not None:
            run_budget.close()


if __name__ == "__main__":
    raise SystemExit(main())
