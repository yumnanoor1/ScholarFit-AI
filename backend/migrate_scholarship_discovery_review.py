"""Explicit additive migration for the Admin scholarship-discovery review queue.

No schema changes occur unless --apply is supplied for the explicitly named database.
"""
import argparse

from sqlalchemy import inspect, text

MIGRATION_LOCK_ID = 728341901270419


def main(engine=None, target_database=None, apply=False, table=None):
    if engine is None:
        from app.database import engine as configured_engine

        engine = configured_engine
    if table is None:
        from app import models  # noqa: F401
        from app.models.scholarship_discovery import ScholarshipDiscoveryReviewItem

        table = ScholarshipDiscoveryReviewItem.__table__

    if engine.dialect.name != "postgresql":
        raise RuntimeError("The scholarship discovery review migration requires PostgreSQL.")
    if not target_database or engine.url.database != target_database:
        raise RuntimeError("The requested database does not match DATABASE_URL.")

    with engine.begin() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": MIGRATION_LOCK_ID},
        )
        tables = set(inspect(connection).get_table_names())
        if "scholarship_discovery_runs" not in tables:
            raise RuntimeError("Apply the scholarship discovery run-history migration first.")
        exists = table.name in tables
        if not exists and apply:
            table.create(bind=connection)
            exists = True

    print(f"{table.name}: {'ready' if exists else 'missing (no changes made)'}")
    return exists


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Check or create the scholarship discovery review queue."
    )
    parser.add_argument("--target-database", required=True, help="Expected database name in DATABASE_URL.")
    parser.add_argument("--apply", action="store_true", help="Create the review table if it is missing.")
    arguments = parser.parse_args()
    main(target_database=arguments.target_database, apply=arguments.apply)
