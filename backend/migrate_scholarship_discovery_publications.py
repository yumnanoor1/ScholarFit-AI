"""Explicit additive migration for Admin-approved discovery publications.

No schema changes occur unless --apply is supplied for the explicitly named database.
"""
import argparse

from sqlalchemy import inspect, text
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint


MIGRATION_LOCK_ID = 728341901270420
PARENT_TABLES = {
    "scholarships",
    "users",
    "scholarship_discovery_runs",
    "scholarship_discovery_review_items",
}


def _validate_tables(connection, tables):
    inspector = inspect(connection)
    for table in tables:
        existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
        expected_columns = set(table.columns.keys())
        missing_columns = expected_columns - existing_columns
        if missing_columns:
            raise RuntimeError(
                f"Incompatible {table.name} table; missing expected columns: "
                f"{', '.join(sorted(missing_columns))}."
            )
        existing_constraints = {
            constraint.get("name")
            for constraint in inspector.get_check_constraints(table.name)
        }
        expected_constraints = {
            constraint.name
            for constraint in table.constraints
            if constraint.name and isinstance(constraint, CheckConstraint)
        }
        missing_constraints = expected_constraints - existing_constraints
        if missing_constraints:
            raise RuntimeError(
                f"Incompatible {table.name} table; missing expected checks: "
                f"{', '.join(sorted(missing_constraints))}."
            )
        existing_unique_constraints = {
            tuple(constraint.get("column_names") or ())
            for constraint in inspector.get_unique_constraints(table.name)
        }
        expected_unique_constraints = {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        missing_unique_constraints = expected_unique_constraints - existing_unique_constraints
        if missing_unique_constraints:
            missing = "; ".join(", ".join(columns) for columns in sorted(missing_unique_constraints))
            raise RuntimeError(f"Incompatible {table.name} table; missing unique constraints: {missing}.")

        existing_foreign_keys = {
            (
                tuple(foreign_key.get("constrained_columns") or ()),
                foreign_key.get("referred_table"),
                tuple(foreign_key.get("referred_columns") or ()),
            )
            for foreign_key in inspector.get_foreign_keys(table.name)
        }
        expected_foreign_keys = {
            (
                tuple(column.name for column in constraint.columns),
                next(iter(constraint.elements)).column.table.name,
                tuple(element.column.name for element in constraint.elements),
            )
            for constraint in table.constraints
            if isinstance(constraint, ForeignKeyConstraint)
        }
        missing_foreign_keys = expected_foreign_keys - existing_foreign_keys
        if missing_foreign_keys:
            raise RuntimeError(f"Incompatible {table.name} table; expected foreign keys are missing.")


def main(engine=None, target_database=None, apply=False):
    if engine is None:
        from app.database import engine as configured_engine

        engine = configured_engine
    from app.models.scholarship_discovery_publication import (
        SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLES,
        SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLE_NAMES,
    )

    tables = SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLES
    if engine.dialect.name != "postgresql":
        raise RuntimeError("The scholarship discovery publication migration requires PostgreSQL.")
    if not target_database or engine.url.database != target_database:
        raise RuntimeError("The requested database does not match DATABASE_URL.")

    with engine.begin() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": MIGRATION_LOCK_ID},
        )
        existing_tables = set(inspect(connection).get_table_names())
        missing_parents = PARENT_TABLES - existing_tables
        if missing_parents:
            raise RuntimeError(
                "Apply the scholarship discovery review migration and canonical schema first; "
                f"missing tables: {', '.join(sorted(missing_parents))}."
            )

        present = SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLE_NAMES & existing_tables
        if present and present != SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLE_NAMES:
            raise RuntimeError(
                "A partial scholarship discovery publication schema exists; no changes were made."
            )
        if not present and apply:
            from app.database import Base

            Base.metadata.create_all(bind=connection, tables=list(tables))
            existing_tables = set(inspect(connection).get_table_names())
            created = SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLE_NAMES & existing_tables
            if created != SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLE_NAMES:
                raise RuntimeError("The publication schema was not created completely.")
            present = created
        if present == SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLE_NAMES:
            _validate_tables(connection, tables)

    status = "ready" if present == SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLE_NAMES else "missing (no changes made)"
    print(f"Scholarship discovery publication schema: {status}")
    return present == SCHOLARSHIP_DISCOVERY_PUBLICATION_TABLE_NAMES


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Check or create the Admin scholarship-discovery publication schema."
    )
    parser.add_argument(
        "--target-database",
        required=True,
        help="Expected database name in DATABASE_URL.",
    )
    parser.add_argument("--apply", action="store_true", help="Create the publication tables if missing.")
    arguments = parser.parse_args()
    main(target_database=arguments.target_database, apply=arguments.apply)
