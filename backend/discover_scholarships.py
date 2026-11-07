"""Single-run entry point for an external daily scheduler."""
import json
import logging
import sys

from sqlalchemy import inspect, text

from app.core.config import scholarship_discovery_settings
from app.database import SessionLocal, engine
from app.models.scholarship_discovery import SCHOLARSHIP_DISCOVERY_TABLE_NAMES
from app.services.scholarship_discovery import DiscoveryDisabled, run_discovery


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        settings = scholarship_discovery_settings()
    except RuntimeError as exc:
        logging.error("Scholarship discovery configuration failed: %s", exc)
        print(json.dumps({"status": "failed", "error": type(exc).__name__}), file=sys.stderr)
        return 1
    if not settings.enabled:
        print(json.dumps({"status": "disabled", "reason": "Set SCHOLARSHIP_DISCOVERY_ENABLED=true"}))
        return 2

    with engine.connect() as lock_connection:
        existing_tables = set(inspect(lock_connection).get_table_names())
        missing = SCHOLARSHIP_DISCOVERY_TABLE_NAMES - existing_tables
        if missing:
            print(json.dumps({"status": "failed", "error": "discovery run-history migration is required"}), file=sys.stderr)
            return 1
        lock_id = 631287180927007781
        acquired = lock_connection.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": lock_id},
        ).scalar_one()
        if not acquired:
            print(json.dumps({"status": "skipped", "reason": "another discovery run is active"}))
            return 3
        lock_connection.commit()

        result = None
        response = None
        response_stream = sys.stdout
        exit_code = 0
        try:
            try:
                with SessionLocal() as db:
                    result = run_discovery(db, settings=settings)
            except DiscoveryDisabled as exc:
                response = {"status": "disabled", "reason": str(exc)}
                exit_code = 2
            except Exception as exc:
                logging.error("Scholarship discovery failed: %s", type(exc).__name__)
                response = {"status": "failed", "error": type(exc).__name__}
                response_stream = sys.stderr
                exit_code = 1
        finally:
            try:
                released = lock_connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": lock_id},
                ).scalar_one()
                if not released:
                    raise RuntimeError("advisory lock was not held during release")
                lock_connection.commit()
            except Exception as exc:
                lock_connection.invalidate()
                logging.error("Scholarship discovery lock release failed: %s", type(exc).__name__)
                response = {"status": "failed", "error": type(exc).__name__}
                response_stream = sys.stderr
                exit_code = 1

        if response is not None:
            print(json.dumps(response), file=response_stream)
            return exit_code
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
