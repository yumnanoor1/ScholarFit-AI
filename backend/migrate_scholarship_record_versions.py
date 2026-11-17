"""Initialize legacy NULL scholarship versions and enforce a default positive baseline.

Run explicitly with --check or --apply and the database name. Applying is transactional
on PostgreSQL and changes only rows whose record_version is NULL.
"""
import argparse

from sqlalchemy import MetaData, Table, inspect, select, text, update
from sqlalchemy.engine import Connection, Engine

from app.database import engine as configured_engine

SCHEMA = "public"
TABLE_NAME = "scholarships"
BACKFILL_SQL = "UPDATE public.scholarships SET record_version = 1 WHERE record_version IS NULL"
VERIFY_SQL = (
    "SELECT COUNT(*) AS remaining_null_versions "
    "FROM public.scholarships WHERE record_version IS NULL"
)


class MigrationRefused(RuntimeError):
    """Raised when the target schema cannot safely accept the version backfill."""


def _scholarships_table(connection: Connection) -> Table:
    inspector = inspect(connection)
    if not inspector.has_table(TABLE_NAME, schema=SCHEMA):
        raise MigrationRefused("public.scholarships does not exist.")
    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME, schema=SCHEMA)}
    if "record_version" not in columns:
        raise MigrationRefused("public.scholarships.record_version does not exist.")
    return Table(TABLE_NAME, MetaData(), schema=SCHEMA, autoload_with=connection)


def backfill_null_versions(connection: Connection, table: Table) -> int:
    """Set only legacy NULL rows to baseline version 1."""
    result = connection.execute(
        update(table).where(table.c.record_version.is_(None)).values(record_version=1)
    )
    return result.rowcount


def count_null_versions(connection: Connection, table: Table) -> int:
    return connection.execute(
        select(text("COUNT(*)")).select_from(table).where(table.c.record_version.is_(None))
    ).scalar_one()


def apply_migration(connection: Connection) -> tuple[int, int]:
    if connection.dialect.name != "postgresql":
        raise MigrationRefused("This schema migration requires PostgreSQL.")
    table = _scholarships_table(connection)
    updated = backfill_null_versions(connection, table)
    remaining = count_null_versions(connection, table)
    if remaining:
        raise MigrationRefused(f"Backfill left {remaining} NULL record_version row(s).")

    preparer = connection.dialect.identifier_preparer
    qualified_table = preparer.format_table(table)
    version_column = preparer.quote("record_version")
    connection.exec_driver_sql(
        f"ALTER TABLE {qualified_table} ALTER COLUMN {version_column} SET DEFAULT 1"
    )
    connection.exec_driver_sql(
        f"ALTER TABLE {qualified_table} ALTER COLUMN {version_column} SET NOT NULL"
    )
    return updated, count_null_versions(connection, table)


def check_migration(connection: Connection) -> int:
    table = _scholarships_table(connection)
    return count_null_versions(connection, table)


def run(engine: Engine, database: str, apply: bool = False) -> None:
    if not database or engine.url.database != database:
        raise MigrationRefused("The requested database does not match DATABASE_URL.")
    if apply:
        with engine.begin() as connection:
            updated, remaining = apply_migration(connection)
        print(f"Initialized {updated} NULL version(s); remaining NULL versions: {remaining}")
    else:
        with engine.connect() as connection:
            remaining = check_migration(connection)
        print(f"Remaining NULL versions: {remaining}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill legacy scholarship record versions.")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true", help="Count NULL record versions without changing data.")
    modes.add_argument("--apply", action="store_true", help="Backfill NULL versions and enforce the schema default.")
    parser.add_argument("--database", required=True, help="Must match the configured DATABASE_URL database.")
    args = parser.parse_args()
    try:
        run(configured_engine, args.database, apply=args.apply)
    except MigrationRefused as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
