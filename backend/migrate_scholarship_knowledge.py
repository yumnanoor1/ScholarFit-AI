"""Explicit, additive schema migration for scholarship knowledge storage.

No database connection is opened unless --check or --apply is supplied. This migration
never creates the pgvector extension; it verifies the configured database first.
"""
import argparse
from pprint import pformat

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from app import models  # noqa: F401
from app.database import Base, engine as configured_engine
from app.models.scholarship_knowledge import (
    EMBEDDING_DIMENSIONS,
    SCHOLARSHIP_KNOWLEDGE_TABLES,
    SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES,
    ScholarshipChunkEmbedding,
)
from app.services.scholarship_knowledge_schema import (
    EXPECTED_FUNCTIONS,
    EXPECTED_PGVECTOR_VERSION,
    EXPECTED_TRIGGER_SPECS,
    schema_is_ready,
)

EXPECTED_POSTGRES_MAJOR = 17

SCHEMA_OBJECTS = {
    "extension_precondition": f"vector {EXPECTED_PGVECTOR_VERSION} already enabled",
    "tables": sorted(SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES),
    "unique_constraints": [
        "uq_scholarship_document_version_content_hash",
        "uq_scholarship_document_chunk_ordinal",
        "uq_scholarship_document_chunk_version",
        "uq_scholarship_document_version_approval_version",
        "uq_scholarship_chunk_embedding_model_revision",
    ],
    "primary_keys": [
        "pk_scholarship_source_documents",
        "pk_scholarship_document_versions",
        "pk_scholarship_document_chunks",
        "pk_scholarship_document_version_approvals",
        "pk_scholarship_chunk_embeddings",
    ],
    "foreign_keys": [
        "fk_scholarship_source_documents_scholarship (RESTRICT)",
        "fk_scholarship_document_versions_source_document (RESTRICT)",
        "fk_scholarship_document_chunks_document_version (RESTRICT)",
        "fk_scholarship_document_version_approvals_version (RESTRICT)",
        "fk_scholarship_chunk_embeddings_chunk_version (RESTRICT)",
        "fk_scholarship_chunk_embeddings_approval (RESTRICT)",
    ],
    "indexes": [
        "ix_scholarship_source_documents_scholarship_id",
        "uq_scholarship_source_normalized_url (unique while source is active)",
        "ix_scholarship_document_versions_source_document_id",
        "ix_scholarship_document_chunks_document_version_id",
        "ix_scholarship_document_version_approvals_document_version_id",
        "ix_scholarship_chunk_embeddings_chunk_id",
        "ix_scholarship_chunk_embedding_hnsw (HNSW, vector_cosine_ops)",
    ],
    "other_constraints": [
        "ck_scholarship_source_role",
        "ck_scholarship_document_version_sha256",
        "ck_scholarship_document_version_verification_status",
        "ck_scholarship_document_version_review_status",
        "ck_scholarship_document_version_indexing_status",
        "ck_scholarship_document_version_approval_decision",
        "ck_scholarship_document_version_approval_verification",
        "ck_scholarship_document_version_approval_review",
        "ck_scholarship_document_version_approval_indexing",
        "ck_scholarship_document_version_approval_scholarship",
        "ck_scholarship_document_chunk_sha256",
        "ck_scholarship_document_chunk_ordinal",
        "ck_scholarship_document_chunk_page_start",
        "ck_scholarship_document_chunk_page_end",
        "ck_scholarship_document_chunk_start_offset",
        "ck_scholarship_document_chunk_end_offset",
        "ck_scholarship_chunk_embedding_dimensions",
    ],
    "functions": sorted(EXPECTED_FUNCTIONS),
    "triggers": sorted(EXPECTED_TRIGGER_SPECS),
}


class MigrationRefused(RuntimeError):
    """Raised when a precondition fails, before any schema change is attempted."""


def validate_configured_target(engine: Engine, target_database: str) -> None:
    configured_database = engine.url.database
    if not target_database or configured_database != target_database:
        raise MigrationRefused("The requested database does not match DATABASE_URL.")


def preflight_connection(
    connection: Connection,
    target_database: str,
    target_schema: str,
) -> dict:
    if connection.dialect.name != "postgresql":
        raise MigrationRefused("The scholarship knowledge migration requires PostgreSQL.")
    validate_configured_target(connection.engine, target_database)
    if not target_schema:
        raise MigrationRefused("An explicit target schema is required.")

    embedding_type = ScholarshipChunkEmbedding.__table__.c.embedding.type
    if EMBEDDING_DIMENSIONS != 384 or getattr(embedding_type, "dim", None) != 384:
        raise MigrationRefused("The model vector column must be configured for exactly 384 dimensions.")

    database, schema, version_num = connection.execute(
        text(
            "SELECT current_database(), current_schema(), "
            "current_setting('server_version_num')::integer"
        )
    ).one()
    if database != target_database or schema != target_schema:
        raise MigrationRefused("The connected database or schema does not match the explicit target.")
    if int(version_num) // 10000 != EXPECTED_POSTGRES_MAJOR:
        raise MigrationRefused(f"PostgreSQL {EXPECTED_POSTGRES_MAJOR} is required for this migration.")

    extension = connection.execute(
        text(
            "SELECT extversion, pg_catalog.to_regtype('vector') IS NOT NULL "
            "FROM pg_catalog.pg_extension WHERE extname = 'vector'"
        )
    ).one_or_none()
    if extension is None:
        raise MigrationRefused("The vector extension is not enabled in the target database.")
    if extension[0] != EXPECTED_PGVECTOR_VERSION or not extension[1]:
        raise MigrationRefused(
            f"Expected pgvector {EXPECTED_PGVECTOR_VERSION} and a visible vector type."
        )
    return {
        "database": database,
        "schema": schema,
        "postgres_major": int(version_num) // 10000,
        "pgvector_version": extension[0],
        "dimensions": EMBEDDING_DIMENSIONS,
    }


def _existing_rag_tables(connection: Connection, schema: str) -> set:
    existing = set(inspect(connection).get_table_names(schema=schema))
    return existing & SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES


def apply_migration(engine: Engine, target_database: str, target_schema: str) -> bool:
    """Create only scholarship knowledge tables; return True if schema was already ready."""
    validate_configured_target(engine, target_database)
    with engine.begin() as connection:
        preflight_connection(connection, target_database, target_schema)
        existing = _existing_rag_tables(connection, target_schema)
        if existing:
            if existing == SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES and schema_is_ready(connection, target_schema):
                return True
            raise MigrationRefused(
                "A partial or incompatible scholarship knowledge schema already exists; no objects were changed."
            )

        Base.metadata.create_all(bind=connection, tables=list(SCHOLARSHIP_KNOWLEDGE_TABLES))
        if not schema_is_ready(connection, target_schema):
            raise MigrationRefused("Post-migration schema verification failed; the transaction will be rolled back.")
    return False


def main(argv=None, target_engine=None) -> int:
    parser = argparse.ArgumentParser(
        description="Explicit additive migration for scholarship knowledge tables.",
        allow_abbrev=False,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="run read-only database preflight")
    mode.add_argument("--apply", action="store_true", help="create the new tables after preflight")
    parser.add_argument("--database", help="must match the database configured by DATABASE_URL")
    parser.add_argument("--schema", help="explicit PostgreSQL schema to check or migrate")
    args = parser.parse_args(argv)

    print("Schema objects:")
    print(pformat(SCHEMA_OBJECTS, sort_dicts=False))
    if not args.check and not args.apply:
        print("No database connection opened and no changes made; choose --check or --apply explicitly.")
        return 0
    if not args.database or not args.schema:
        parser.error("--database and --schema are required with --check or --apply")

    migration_engine = target_engine or configured_engine
    try:
        validate_configured_target(migration_engine, args.database)
        if args.check:
            with migration_engine.connect() as connection:
                details = preflight_connection(connection, args.database, args.schema)
                existing = _existing_rag_tables(connection, args.schema)
                if not existing:
                    print(f"Preflight passed: {details}")
                    print("Scholarship knowledge schema is absent; --apply can create it.")
                    return 0
                if existing != SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES:
                    raise MigrationRefused(
                        "A partial scholarship knowledge schema exists and is incompatible."
                    )
                if not schema_is_ready(connection, args.schema):
                    raise MigrationRefused(
                        "Scholarship knowledge tables exist, but the schema is incompatible or incomplete."
                    )
            print(f"Preflight passed: {details}")
            print("Scholarship knowledge schema is installed and ready.")
            return 0

        already_ready = apply_migration(migration_engine, args.database, args.schema)
    except MigrationRefused as error:
        raise SystemExit(f"Migration refused: {error}") from error
    print("Scholarship knowledge schema was already ready." if already_ready else "Scholarship knowledge schema created and verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
