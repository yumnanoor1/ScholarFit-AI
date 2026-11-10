"""Explicit additive migration for durable scholarship discovery run summaries.

No rows are modified. The new table is not created by application startup.
"""
import argparse

from sqlalchemy import inspect, text

from app import models  # noqa: F401
from app.database import engine as default_engine
from app.models.scholarship_discovery import ScholarshipDiscoveryRun


MIGRATION_LOCK_ID = 728341901270419


def main(engine=default_engine, target_database=None, apply=False):
    if engine.dialect.name != "postgresql":
        raise RuntimeError("The scholarship discovery migration requires PostgreSQL.")
    if not target_database or engine.url.database != target_database:
        raise RuntimeError("The requested database does not match DATABASE_URL.")

    table = ScholarshipDiscoveryRun.__table__
    with engine.begin() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": MIGRATION_LOCK_ID},
        )
        exists = table.name in inspect(connection).get_table_names()
        if not exists and apply:
            table.create(bind=connection)
            exists = True

    print(f"{table.name}: {'ready' if exists else 'missing (no changes made)'}")
    return exists


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check or create discovery run history storage.")
    parser.add_argument("--target-database", required=True, help="Expected database name in DATABASE_URL.")
    parser.add_argument("--apply", action="store_true", help="Create the new table if it is missing.")
    arguments = parser.parse_args()
    main(target_database=arguments.target_database, apply=arguments.apply)
