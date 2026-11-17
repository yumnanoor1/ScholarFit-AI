"""Add scheduled-slot metadata to scholarship discovery run history."""
import argparse

from sqlalchemy import inspect, text


TABLE_NAME = "scholarship_discovery_runs"
MIGRATION_LOCK_ID = 728341901270419
TRIGGER_CONSTRAINT = "ck_scholarship_discovery_run_trigger_type"
SCHEDULED_SLOT_INDEX = "uq_scholarship_discovery_run_scheduled_for"


def _is_ready(connection):
    inspector = inspect(connection)
    if TABLE_NAME not in inspector.get_table_names():
        return False
    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}
    checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints(TABLE_NAME)
    }
    indexes = {index["name"] for index in inspector.get_indexes(TABLE_NAME)}
    return (
        {"trigger_type", "scheduled_for"} <= columns
        and TRIGGER_CONSTRAINT in checks
        and SCHEDULED_SLOT_INDEX in indexes
    )


def main(engine=None, target_database=None, apply=False):
    if engine is None:
        from app.database import engine as configured_engine

        engine = configured_engine
    if engine.dialect.name != "postgresql":
        raise RuntimeError("The scholarship discovery scheduler migration requires PostgreSQL.")
    if not target_database or engine.url.database != target_database:
        raise RuntimeError("The requested database does not match DATABASE_URL.")

    with engine.begin() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": MIGRATION_LOCK_ID},
        )
        if TABLE_NAME not in inspect(connection).get_table_names():
            raise RuntimeError("Apply the scholarship discovery run-history migration first.")
        if apply:
            columns = {
                column["name"]
                for column in inspect(connection).get_columns(TABLE_NAME)
            }
            if "trigger_type" not in columns:
                connection.execute(text(
                    "ALTER TABLE scholarship_discovery_runs "
                    "ADD COLUMN trigger_type VARCHAR(16) NOT NULL DEFAULT 'manual'"
                ))
            if "scheduled_for" not in columns:
                connection.execute(text(
                    "ALTER TABLE scholarship_discovery_runs "
                    "ADD COLUMN scheduled_for TIMESTAMP WITH TIME ZONE"
                ))

            checks = {
                constraint["name"]
                for constraint in inspect(connection).get_check_constraints(TABLE_NAME)
            }
            if TRIGGER_CONSTRAINT not in checks:
                connection.execute(text(
                    "ALTER TABLE scholarship_discovery_runs "
                    "ADD CONSTRAINT ck_scholarship_discovery_run_trigger_type "
                    "CHECK (trigger_type IN ('scheduled', 'catch_up', 'manual'))"
                ))
            indexes = {
                index["name"]
                for index in inspect(connection).get_indexes(TABLE_NAME)
            }
            if SCHEDULED_SLOT_INDEX not in indexes:
                connection.execute(text(
                    "CREATE UNIQUE INDEX uq_scholarship_discovery_run_scheduled_for "
                    "ON scholarship_discovery_runs (scheduled_for)"
                ))

        ready = _is_ready(connection)

    print(f"{TABLE_NAME}: {'ready' if ready else 'missing (no changes made)'}")
    return ready


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Add scheduled-slot metadata to discovery run history.",
    )
    parser.add_argument(
        "--target-database",
        required=True,
        help="Expected database name in DATABASE_URL.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Add the scheduler columns and slot uniqueness index.",
    )
    arguments = parser.parse_args()
    main(target_database=arguments.target_database, apply=arguments.apply)
