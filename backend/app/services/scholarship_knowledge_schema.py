import hashlib
import re
from typing import Optional

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.models.scholarship_knowledge import (
    EMBEDDING_DIMENSIONS,
    SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES,
)

EXPECTED_PGVECTOR_VERSION = "0.8.7"
EXPECTED_UNIQUE_CONSTRAINTS = {
    "scholarship_document_versions": (
        "uq_scholarship_document_version_content_hash",
    ),
    "scholarship_document_chunks": (
        "uq_scholarship_document_chunk_ordinal",
        "uq_scholarship_document_chunk_version",
    ),
    "scholarship_document_version_approvals": (
        "uq_scholarship_document_version_approval_version",
    ),
    "scholarship_chunk_embeddings": ("uq_scholarship_chunk_embedding_model_revision",),
}
EXPECTED_PRIMARY_KEYS = {
    "scholarship_source_documents": "pk_scholarship_source_documents",
    "scholarship_document_versions": "pk_scholarship_document_versions",
    "scholarship_document_chunks": "pk_scholarship_document_chunks",
    "scholarship_document_version_approvals": "pk_scholarship_document_version_approvals",
    "scholarship_chunk_embeddings": "pk_scholarship_chunk_embeddings",
}
EXPECTED_FOREIGN_KEYS = {
    "scholarship_source_documents": ("fk_scholarship_source_documents_scholarship",),
    "scholarship_document_versions": ("fk_scholarship_document_versions_source_document",),
    "scholarship_document_chunks": ("fk_scholarship_document_chunks_document_version",),
    "scholarship_document_version_approvals": (
        "fk_scholarship_document_version_approvals_version",
    ),
    "scholarship_chunk_embeddings": (
        "fk_scholarship_chunk_embeddings_chunk_version",
        "fk_scholarship_chunk_embeddings_approval",
    ),
}
EXPECTED_CHECK_CONSTRAINTS = {
    "scholarship_source_documents": ("ck_scholarship_source_role",),
    "scholarship_document_versions": (
        "ck_scholarship_document_version_sha256",
        "ck_scholarship_document_version_verification_status",
        "ck_scholarship_document_version_review_status",
        "ck_scholarship_document_version_indexing_status",
    ),
    "scholarship_document_version_approvals": (
        "ck_scholarship_document_version_approval_decision",
        "ck_scholarship_document_version_approval_verification",
        "ck_scholarship_document_version_approval_review",
        "ck_scholarship_document_version_approval_indexing",
        "ck_scholarship_document_version_approval_scholarship",
    ),
    "scholarship_document_chunks": (
        "ck_scholarship_document_chunk_sha256",
        "ck_scholarship_document_chunk_ordinal",
        "ck_scholarship_document_chunk_page_start",
        "ck_scholarship_document_chunk_page_end",
        "ck_scholarship_document_chunk_start_offset",
        "ck_scholarship_document_chunk_end_offset",
    ),
    "scholarship_chunk_embeddings": (
        "ck_scholarship_chunk_embedding_dimensions",
    ),
}
EXPECTED_BTREE_INDEXES = {
    "scholarship_source_documents": (
        "ix_scholarship_source_documents_scholarship_id",
        "uq_scholarship_source_normalized_url",
    ),
    "scholarship_document_versions": ("ix_scholarship_document_versions_source_document_id",),
    "scholarship_document_chunks": ("ix_scholarship_document_chunks_document_version_id",),
    "scholarship_document_version_approvals": (
        "ix_scholarship_document_version_approvals_document_version_id",
    ),
    "scholarship_chunk_embeddings": ("ix_scholarship_chunk_embeddings_chunk_id",),
}
EXPECTED_HNSW_INDEX = "ix_scholarship_chunk_embedding_hnsw"
EXPECTED_PARTIAL_UNIQUE_INDEXES = {
    "scholarship_source_documents": {
        "name": "uq_scholarship_source_normalized_url",
        "columns": ("scholarship_id", "normalized_url"),
        "predicate": "is_active",
    },
}
EXPECTED_TRIGGER_SPECS = {
    "trg_scholarship_document_version_approvals_validate": {
        "table": "scholarship_document_version_approvals",
        "function": "scholarship_knowledge_validate_approval",
        "timing": "BEFORE",
        "events": frozenset({"INSERT"}),
    },
    "trg_scholarship_document_version_approvals_serialize": {
        "table": "scholarship_document_version_approvals",
        "function": "scholarship_knowledge_serialize_integrity_writes",
        "timing": "BEFORE",
        "events": frozenset({"INSERT"}),
        "row_level": False,
    },
    "trg_scholarship_document_version_approvals_immutable_update": {
        "table": "scholarship_document_version_approvals",
        "function": "scholarship_knowledge_reject_history_mutation",
        "timing": "BEFORE",
        "events": frozenset({"UPDATE"}),
    },
    "trg_scholarship_document_version_approvals_immutable_delete": {
        "table": "scholarship_document_version_approvals",
        "function": "scholarship_knowledge_reject_history_mutation",
        "timing": "BEFORE",
        "events": frozenset({"DELETE"}),
    },
    "trg_scholarship_document_versions_revoke_approval": {
        "table": "scholarship_document_versions",
        "function": "scholarship_knowledge_revoke_approval",
        "timing": "AFTER",
        "events": frozenset({"UPDATE"}),
    },
    "trg_scholarship_document_versions_serialize": {
        "table": "scholarship_document_versions",
        "function": "scholarship_knowledge_serialize_integrity_writes",
        "timing": "BEFORE",
        "events": frozenset({"UPDATE"}),
        "row_level": False,
    },
    "trg_scholarships_revoke_approval": {
        "table": "scholarships",
        "function": "scholarship_knowledge_revoke_scholarship_approval",
        "timing": "AFTER",
        "events": frozenset({"UPDATE"}),
    },
    "trg_scholarships_serialize": {
        "table": "scholarships",
        "function": "scholarship_knowledge_serialize_integrity_writes",
        "timing": "BEFORE",
        "events": frozenset({"UPDATE"}),
        "row_level": False,
    },
    "trg_scholarship_source_documents_revoke_approval": {
        "table": "scholarship_source_documents",
        "function": "scholarship_knowledge_revoke_source_approval",
        "timing": "AFTER",
        "events": frozenset({"UPDATE"}),
    },
    "trg_scholarship_source_documents_serialize": {
        "table": "scholarship_source_documents",
        "function": "scholarship_knowledge_serialize_integrity_writes",
        "timing": "BEFORE",
        "events": frozenset({"UPDATE"}),
        "row_level": False,
    },
    "trg_scholarship_source_documents_protect_identity": {
        "table": "scholarship_source_documents",
        "function": "scholarship_knowledge_protect_source_identity",
        "timing": "BEFORE",
        "events": frozenset({"UPDATE"}),
    },
    "trg_scholarship_source_documents_protect_delete": {
        "table": "scholarship_source_documents",
        "function": "scholarship_knowledge_protect_source_identity",
        "timing": "BEFORE",
        "events": frozenset({"DELETE"}),
    },
    "trg_scholarship_document_versions_immutable_update": {
        "table": "scholarship_document_versions",
        "function": "scholarship_knowledge_protect_document_version",
        "timing": "BEFORE",
        "events": frozenset({"UPDATE"}),
    },
    "trg_scholarship_document_versions_immutable_delete": {
        "table": "scholarship_document_versions",
        "function": "scholarship_knowledge_protect_document_version",
        "timing": "BEFORE",
        "events": frozenset({"DELETE"}),
    },
    "trg_scholarship_document_chunks_immutable_update": {
        "table": "scholarship_document_chunks",
        "function": "scholarship_knowledge_reject_history_mutation",
        "timing": "BEFORE",
        "events": frozenset({"UPDATE"}),
    },
    "trg_scholarship_document_chunks_immutable_delete": {
        "table": "scholarship_document_chunks",
        "function": "scholarship_knowledge_reject_history_mutation",
        "timing": "BEFORE",
        "events": frozenset({"DELETE"}),
    },
    "trg_scholarship_source_documents_reject_truncate": {
        "table": "scholarship_source_documents",
        "function": "scholarship_knowledge_reject_history_truncate",
        "timing": "BEFORE",
        "events": frozenset({"TRUNCATE"}),
        "row_level": False,
    },
    "trg_scholarship_document_versions_reject_truncate": {
        "table": "scholarship_document_versions",
        "function": "scholarship_knowledge_reject_history_truncate",
        "timing": "BEFORE",
        "events": frozenset({"TRUNCATE"}),
        "row_level": False,
    },
    "trg_scholarship_document_chunks_reject_truncate": {
        "table": "scholarship_document_chunks",
        "function": "scholarship_knowledge_reject_history_truncate",
        "timing": "BEFORE",
        "events": frozenset({"TRUNCATE"}),
        "row_level": False,
    },
    "trg_scholarship_document_version_approvals_reject_truncate": {
        "table": "scholarship_document_version_approvals",
        "function": "scholarship_knowledge_reject_history_truncate",
        "timing": "BEFORE",
        "events": frozenset({"TRUNCATE"}),
        "row_level": False,
    },
    "trg_scholarship_chunk_embeddings_validate_approval": {
        "table": "scholarship_chunk_embeddings",
        "function": "scholarship_knowledge_validate_embedding",
        "timing": "BEFORE",
        "events": frozenset({"INSERT"}),
    },
    "trg_scholarship_chunk_embeddings_serialize": {
        "table": "scholarship_chunk_embeddings",
        "function": "scholarship_knowledge_serialize_integrity_writes",
        "timing": "BEFORE",
        "events": frozenset({"INSERT"}),
        "row_level": False,
    },
    "trg_scholarship_chunk_embeddings_reject_truncate": {
        "table": "scholarship_chunk_embeddings",
        "function": "scholarship_knowledge_reject_history_truncate",
        "timing": "BEFORE",
        "events": frozenset({"TRUNCATE"}),
        "row_level": False,
    },
    "trg_scholarship_chunk_embeddings_immutable_update": {
        "table": "scholarship_chunk_embeddings",
        "function": "scholarship_knowledge_reject_history_mutation",
        "timing": "BEFORE",
        "events": frozenset({"UPDATE"}),
    },
    "trg_scholarship_chunk_embeddings_immutable_delete": {
        "table": "scholarship_chunk_embeddings",
        "function": "scholarship_knowledge_reject_history_mutation",
        "timing": "BEFORE",
        "events": frozenset({"DELETE"}),
    },
}
EXPECTED_FUNCTIONS = {
    "scholarship_knowledge_validate_approval",
    "scholarship_knowledge_reject_history_mutation",
    "scholarship_knowledge_protect_source_identity",
    "scholarship_knowledge_serialize_integrity_writes",
    "scholarship_knowledge_reject_history_truncate",
    "scholarship_knowledge_protect_document_version",
    "scholarship_knowledge_revoke_approval",
    "scholarship_knowledge_revoke_scholarship_approval",
    "scholarship_knowledge_revoke_source_approval",
    "scholarship_knowledge_validate_embedding",
}
EXPECTED_FUNCTION_SIGNATURES = {
    name: {"argument_count": 0, "return_type": "trigger", "kind": "f"}
    for name in EXPECTED_FUNCTIONS
}
EXPECTED_FUNCTION_SOURCE_HASHES = {
    "scholarship_knowledge_validate_approval": "122bc2a9bb8aad1165abe1943ed97959283a3ce18946be86d007ff500a91f62a",
    "scholarship_knowledge_reject_history_mutation": "01d29ca2f0e05de9c94759d0d42155e82d630379bf0cd2baa3a46bf6441ca0a1",
    "scholarship_knowledge_protect_source_identity": "5bc9cbcefa7affbfae90aa9a733f8e1185e2cfbf281d5bd89ce5f3c663e1f299",
    "scholarship_knowledge_serialize_integrity_writes": "eb588655fb444adcceb7866a25b2a5b48644d041104c0556fae42d7a62a0732d",
    "scholarship_knowledge_reject_history_truncate": "e302bf9894358975e9682423add196279a64c8db296584d72d990b5f96ab040f",
    "scholarship_knowledge_revoke_approval": "f20d544b3bee43a838cfec7951c4847ea88dbd9c77bb14945e48eb359c6138ac",
    "scholarship_knowledge_revoke_scholarship_approval": "6f214b91711618ee20f56ab30159028c0e08def9ad42e7b251d801c6ec0f3884",
    "scholarship_knowledge_revoke_source_approval": "23bcec58104828fb745a8426b78dee1b40d1c35ef205d5d77448cac7966e0e9d",
    "scholarship_knowledge_protect_document_version": "4b1482a556c85d5faa17f4fe89369c0e4a2531cdb6e8bdc5a1f67e7a14e59e06",
    "scholarship_knowledge_validate_embedding": "af9a4c9b9caa56fd22303e63b74a2c133138e5ed35ca83da5ca310327a4c6577",
}


def _trigger_timing_events(trigger_type: int):
    timing = "INSTEAD OF" if trigger_type & 64 else "BEFORE" if trigger_type & 2 else "AFTER"
    events = frozenset(
        name
        for bit, name in ((4, "INSERT"), (8, "DELETE"), (16, "UPDATE"), (32, "TRUNCATE"))
        if trigger_type & bit
    )
    return timing, events, bool(trigger_type & 1)


def _triggers_are_ready(connection, schema: str) -> bool:
    trigger_rows = connection.execute(
        text(
            "SELECT trigger_row.tgname, table_class.relname, trigger_row.tgenabled, "
            "trigger_row.tgtype, "
            "routine.proname, routine_schema.nspname "
            "FROM pg_catalog.pg_trigger AS trigger_row "
            "JOIN pg_catalog.pg_class AS table_class ON table_class.oid = trigger_row.tgrelid "
            "JOIN pg_catalog.pg_namespace AS table_schema ON table_schema.oid = table_class.relnamespace "
            "JOIN pg_catalog.pg_proc AS routine ON routine.oid = trigger_row.tgfoid "
            "JOIN pg_catalog.pg_namespace AS routine_schema ON routine_schema.oid = routine.pronamespace "
            "WHERE table_schema.nspname = :schema AND NOT trigger_row.tgisinternal"
        ),
        {"schema": schema},
    ).all()
    triggers = {}
    for row in trigger_rows:
        triggers.setdefault(row[0], []).append(row[1:])
    for name, spec in EXPECTED_TRIGGER_SPECS.items():
        matching = triggers.get(name, [])
        if len(matching) != 1:
            return False
        table_name, enabled, trigger_type, function_name, function_schema = matching[0]
        timing, events, row_level = _trigger_timing_events(trigger_type)
        if (
            table_name != spec["table"]
            or enabled not in ("O", "A")
            or timing != spec["timing"]
            or events != spec["events"]
            or row_level != spec.get("row_level", True)
            or function_name != spec["function"]
            or function_schema != schema
        ):
            return False
    return True


def _partial_unique_indexes_are_ready(inspector, schema: str) -> bool:
    for table_name, spec in EXPECTED_PARTIAL_UNIQUE_INDEXES.items():
        matching = [
            index
            for index in inspector.get_indexes(table_name, schema=schema)
            if index.get("name") == spec["name"]
        ]
        if len(matching) != 1:
            return False
        index = matching[0]
        options = index.get("dialect_options") or {}
        predicate = options.get("postgresql_where") or index.get("postgresql_where") or ""
        normalized_predicate = re.sub(r'[\s()"]', "", str(predicate).casefold())
        if (
            index.get("unique") is not True
            or tuple(index.get("column_names") or ()) != spec["columns"]
            or normalized_predicate != spec["predicate"]
        ):
            return False
    return True


def _functions_are_ready(connection, schema: str) -> bool:
    function_rows = connection.execute(
        text(
            "SELECT routine.proname, routine.pronargs, "
            "routine.prorettype::regtype::text, routine.prokind, routine.prosrc "
            "FROM pg_catalog.pg_proc AS routine "
            "JOIN pg_catalog.pg_namespace AS routine_schema ON routine_schema.oid = routine.pronamespace "
            "WHERE routine_schema.nspname = :schema"
        ),
        {"schema": schema},
    ).all()
    functions = {}
    for row in function_rows:
        functions.setdefault(row[0], []).append(row[1:])
    for name, signature in EXPECTED_FUNCTION_SIGNATURES.items():
        matches = functions.get(name, [])
        if len(matches) != 1:
            return False
        argument_count, return_type, kind, source = matches[0]
        expected_hash = EXPECTED_FUNCTION_SOURCE_HASHES.get(name)
        if (
            argument_count != signature["argument_count"]
            or return_type != signature["return_type"]
            or kind != signature["kind"]
            or not source
            or expected_hash is None
            or hashlib.sha256(source.strip().encode("utf-8")).hexdigest() != expected_hash
        ):
            return False
    return True


def schema_is_ready(connection: Connection, schema: Optional[str] = None) -> bool:
    """Read-only check used by startup and future RAG routes; never creates schema objects."""
    if connection.dialect.name != "postgresql":
        return False

    inspector = inspect(connection)
    target_schema = schema
    if target_schema is None:
        target_schema = connection.execute(text("SELECT current_schema()")).scalar_one_or_none()
    if not target_schema:
        return False

    tables = set(inspector.get_table_names(schema=target_schema))
    if not SCHOLARSHIP_KNOWLEDGE_TABLE_NAMES.issubset(tables):
        return False

    for table_name, constraint_name in EXPECTED_UNIQUE_CONSTRAINTS.items():
        constraints = inspector.get_unique_constraints(table_name, schema=target_schema)
        found = {item.get("name") for item in constraints}
        if not set(constraint_name).issubset(found):
            return False
    for table_name, constraint_name in EXPECTED_PRIMARY_KEYS.items():
        primary_key = inspector.get_pk_constraint(table_name, schema=target_schema)
        if primary_key.get("name") != constraint_name:
            return False
    for table_name, constraint_name in EXPECTED_FOREIGN_KEYS.items():
        foreign_keys = inspector.get_foreign_keys(table_name, schema=target_schema)
        found = {item.get("name"): item for item in foreign_keys}
        if not set(constraint_name).issubset(found):
            return False
        if any(
            (found[name].get("options") or {}).get("ondelete", "").upper() != "RESTRICT"
            for name in constraint_name
        ):
            return False
    for table_name, constraint_names in EXPECTED_CHECK_CONSTRAINTS.items():
        checks = inspector.get_check_constraints(table_name, schema=target_schema)
        found = {item.get("name") for item in checks}
        if not set(constraint_names).issubset(found):
            return False
    for table_name, index_names in EXPECTED_BTREE_INDEXES.items():
        indexes = inspector.get_indexes(table_name, schema=target_schema)
        found = {item.get("name") for item in indexes}
        if not set(index_names).issubset(found):
            return False
    if not _partial_unique_indexes_are_ready(inspector, target_schema):
        return False
    if not _functions_are_ready(connection, target_schema):
        return False
    if not _triggers_are_ready(connection, target_schema):
        return False

    extension = connection.execute(
        text(
            "SELECT extversion, pg_catalog.to_regtype('vector') IS NOT NULL "
            "FROM pg_catalog.pg_extension WHERE extname = 'vector'"
        )
    ).one_or_none()
    if extension is None or extension[0] != EXPECTED_PGVECTOR_VERSION or not extension[1]:
        return False

    vector_type = connection.execute(
        text(
            "SELECT pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) "
            "FROM pg_catalog.pg_attribute AS attribute "
            "JOIN pg_catalog.pg_class AS table_class ON table_class.oid = attribute.attrelid "
            "JOIN pg_catalog.pg_namespace AS table_schema ON table_schema.oid = table_class.relnamespace "
            "WHERE table_schema.nspname = :schema "
            "AND table_class.relname = 'scholarship_chunk_embeddings' "
            "AND attribute.attname = 'embedding' AND NOT attribute.attisdropped"
        ),
        {"schema": target_schema},
    ).scalar_one_or_none()
    if vector_type != f"vector({EMBEDDING_DIMENSIONS})":
        return False

    index_definition = connection.execute(
        text(
            "SELECT indexdef FROM pg_catalog.pg_indexes "
            "WHERE schemaname = :schema "
            "AND tablename = 'scholarship_chunk_embeddings' "
            "AND indexname = :index_name"
        ),
        {"schema": target_schema, "index_name": EXPECTED_HNSW_INDEX},
    ).scalar_one_or_none()
    if not index_definition:
        return False
    normalized_index = index_definition.casefold()
    return "using hnsw" in normalized_index and "vector_cosine_ops" in normalized_index
