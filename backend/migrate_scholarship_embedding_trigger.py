"""Explicit corrective migration for the scholarship embedding approval trigger.

No database connection is opened unless --apply is supplied with an explicit
database and schema. The replacement body comes from the model's canonical DDL.
"""
import argparse
import hashlib

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.database import engine as configured_engine
from app.models.scholarship_knowledge import _EMBEDDING_POSTGRES_DDL

FUNCTION_NAME = "scholarship_knowledge_validate_embedding"
APPROVALS_TABLE = "scholarship_document_version_approvals"
EMBEDDINGS_TABLE = "scholarship_chunk_embeddings"
APPROVAL_TRIGGER = "trg_scholarship_chunk_embeddings_validate_approval"
LEGACY_FUNCTION_SOURCE_SHA256 = "f96ec0144e61dc3445699420bced147725abf244f10c63fb331b8fd89bbe0b57"
CORRECTED_FUNCTION_SOURCE_SHA256 = "af9a4c9b9caa56fd22303e63b74a2c133138e5ed35ca83da5ca310327a4c6577"

_TARGET_OBJECTS_SQL = text(
    """
    SELECT current_database(),
           EXISTS (
               SELECT 1
               FROM pg_catalog.pg_namespace AS n
               WHERE n.nspname = :target_schema
           ),
           EXISTS (
               SELECT 1
               FROM pg_catalog.pg_class AS c
               JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
               WHERE n.nspname = :target_schema
                 AND c.relname = 'scholarship_document_version_approvals'
                 AND c.relkind IN ('r', 'p')
           ),
           EXISTS (
               SELECT 1
               FROM pg_catalog.pg_class AS c
               JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
               WHERE n.nspname = :target_schema
                 AND c.relname = 'scholarship_chunk_embeddings'
                 AND c.relkind IN ('r', 'p')
           ),
           EXISTS (
               SELECT 1
               FROM pg_catalog.pg_proc AS p
               JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
               WHERE n.nspname = :target_schema
                 AND p.proname = :function_name
                 AND p.pronargs = 0
                 AND p.prorettype = 'trigger'::regtype
                 AND p.prokind = 'f'
           ),
           EXISTS (
               SELECT 1
               FROM pg_catalog.pg_trigger AS t
               JOIN pg_catalog.pg_class AS c ON c.oid = t.tgrelid
               JOIN pg_catalog.pg_namespace AS table_schema ON table_schema.oid = c.relnamespace
               JOIN pg_catalog.pg_proc AS p ON p.oid = t.tgfoid
               JOIN pg_catalog.pg_namespace AS function_schema ON function_schema.oid = p.pronamespace
               WHERE table_schema.nspname = :target_schema
                 AND c.relname = 'scholarship_chunk_embeddings'
                 AND t.tgname = :trigger_name
                 AND NOT t.tgisinternal
                 AND function_schema.nspname = :target_schema
                 AND p.proname = :function_name
           )
    """
)
_FUNCTION_BODY_SQL = text(
    """
    SELECT p.prosrc
    FROM pg_catalog.pg_proc AS p
    JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname = :target_schema
      AND p.proname = :function_name
      AND p.pronargs = 0
      AND p.prorettype = 'trigger'::regtype
      AND p.prokind = 'f'
    """
)


class MigrationRefused(RuntimeError):
    """Raised when the explicit target is not the expected installed schema."""


def validate_configured_target(engine: Engine, target_database: str, target_schema: str) -> None:
    if not target_database or engine.url.database != target_database:
        raise MigrationRefused("The requested database does not match DATABASE_URL.")
    if not target_schema or "\x00" in target_schema:
        raise MigrationRefused("An explicit valid target schema is required.")


def _function_definition_statement() -> str:
    marker = f"CREATE FUNCTION {FUNCTION_NAME}()"
    for statement in _EMBEDDING_POSTGRES_DDL:
        if marker in statement:
            return statement
    raise MigrationRefused("The canonical embedding validation function definition is unavailable.")


def _replacement_function_sql(target_schema: str, preparer) -> str:
    statement = _function_definition_statement()
    marker = f"CREATE FUNCTION {FUNCTION_NAME}()"
    replacement = (
        f"CREATE OR REPLACE FUNCTION "
        f"{preparer.quote_schema(target_schema)}.{preparer.quote(FUNCTION_NAME)}()"
    )
    return statement.replace(marker, replacement, 1)


def apply_migration(engine: Engine, target_database: str, target_schema: str) -> None:
    """Replace only the existing trigger function in the explicitly named schema."""
    validate_configured_target(engine, target_database, target_schema)
    with engine.begin() as connection:
        if connection.dialect.name != "postgresql":
            raise MigrationRefused("The embedding trigger correction requires PostgreSQL.")

        target_objects = connection.execute(
            _TARGET_OBJECTS_SQL,
            {
                "target_schema": target_schema,
                "function_name": FUNCTION_NAME,
                "trigger_name": APPROVAL_TRIGGER,
            },
        ).one()
        (
            connected_database,
            schema_exists,
            approvals_table_exists,
            embeddings_table_exists,
            function_exists,
            trigger_exists,
        ) = target_objects
        if connected_database != target_database:
            raise MigrationRefused("The connected database does not match the requested target.")
        if not schema_exists:
            raise MigrationRefused("The requested target schema does not exist.")
        if not approvals_table_exists or not embeddings_table_exists:
            raise MigrationRefused("The target schema is missing required scholarship knowledge tables.")
        if not function_exists or not trigger_exists:
            raise MigrationRefused("The target schema does not contain the expected installed embedding trigger.")

        function_bodies = connection.execute(
            _FUNCTION_BODY_SQL,
            {
                "target_schema": target_schema,
                "function_name": FUNCTION_NAME,
            },
        ).scalars().all()
        if len(function_bodies) != 1:
            raise MigrationRefused(
                "The target schema does not contain exactly one compatible embedding trigger function."
            )
        existing_hash = hashlib.sha256(
            function_bodies[0].strip().encode("utf-8")
        ).hexdigest()
        if existing_hash not in {
            LEGACY_FUNCTION_SOURCE_SHA256,
            CORRECTED_FUNCTION_SOURCE_SHA256,
        }:
            raise MigrationRefused(
                "The existing embedding trigger function body is unexpected; "
                "manual investigation is required."
            )

        preparer = connection.dialect.identifier_preparer
        target_schema_sql = preparer.quote_schema(target_schema)
        public_schema_sql = preparer.quote_schema("public")
        connection.exec_driver_sql(
            f"SET LOCAL search_path TO {target_schema_sql}, {public_schema_sql}"
        )
        replacement = _replacement_function_sql(target_schema, preparer)
        connection.exec_driver_sql(replacement.replace("%", "%%"))


def main(argv=None, target_engine=None) -> int:
    parser = argparse.ArgumentParser(
        description="Explicit corrective migration for scholarship embedding approval validation.",
        allow_abbrev=False,
    )
    parser.add_argument("--apply", action="store_true", help="replace the installed trigger function")
    parser.add_argument("--database", help="must match the database configured by DATABASE_URL")
    parser.add_argument("--schema", help="explicit schema containing the installed trigger")
    args = parser.parse_args(argv)

    if not args.apply:
        print("No database connection opened and no changes made; pass --apply explicitly.")
        return 0
    if not args.database or not args.schema:
        parser.error("--database and --schema are required with --apply")

    migration_engine = target_engine or configured_engine
    try:
        validate_configured_target(migration_engine, args.database, args.schema)
        print(
            "Applying scholarship embedding trigger correction to "
            f"database {args.database!r}, schema {args.schema!r}."
        )
        apply_migration(migration_engine, args.database, args.schema)
    except MigrationRefused as error:
        raise SystemExit(f"Migration refused: {error}") from error

    print("Scholarship embedding trigger correction applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
