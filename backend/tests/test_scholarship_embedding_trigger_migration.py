import ast
import contextlib
import hashlib
import io
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.models import scholarship_knowledge as knowledge_model
from app.services import scholarship_knowledge_schema
import migrate_scholarship_embedding_trigger as migration


def _embedding_function_source():
    for statement in knowledge_model._EMBEDDING_POSTGRES_DDL:
        match = re.search(
            r"CREATE FUNCTION scholarship_knowledge_validate_embedding\(\) RETURNS trigger\s+"
            r"LANGUAGE plpgsql AS \$\$(.*?)\$\$;",
            statement,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return match.group(1).strip()
    raise AssertionError("Canonical embedding validation function definition is missing")


def _legacy_embedding_function_source():
    source = _embedding_function_source()
    corrected_query = """        SELECT a.* INTO latest_approval
        FROM scholarship_document_version_approvals AS a
        WHERE a.document_version_id = NEW.document_version_id
        ORDER BY a.id DESC
        LIMIT 1;"""
    legacy_query = """        SELECT * INTO latest_approval FROM scholarship_document_version_approvals
        WHERE document_version_id = NEW.document_version_id ORDER BY id DESC LIMIT 1;"""
    if source.count(corrected_query) != 1:
        raise AssertionError("Corrected latest-approval query is not present exactly once")
    return source.replace(corrected_query, legacy_query, 1).strip()


class _IdentifierPreparer:
    def quote_schema(self, schema):
        return f'"{schema}"'

    def quote(self, identifier):
        return f'"{identifier}"'


class _NoConnectEngine:
    url = SimpleNamespace(database="fitscholar_db")

    def connect(self):
        raise AssertionError("The default migration mode must not connect")

    def begin(self):
        raise AssertionError("The default migration mode must not begin a transaction")


class _FakeResult:
    def __init__(self, row=None, values=()):
        self.row = row
        self.values = list(values)

    def one(self):
        return self.row

    def scalars(self):
        return self

    def all(self):
        return self.values


class _FakeConnection:
    def __init__(self, *, installed_schema="phase3b_test", function_source=""):
        self.dialect = SimpleNamespace(
            name="postgresql",
            identifier_preparer=_IdentifierPreparer(),
        )
        self.installed_schema = installed_schema
        self.function_source = function_source
        self.executed_sql = []
        self.catalog_queries = []

    def execute(self, statement, params):
        query = str(statement)
        self.catalog_queries.append((query, params))
        target_schema = params["target_schema"]
        if "SELECT current_database()" in query:
            is_installed_schema = target_schema == self.installed_schema
            return _FakeResult(
                row=(
                    "fitscholar_db",
                    True,
                    True,
                    True,
                    is_installed_schema,
                    is_installed_schema,
                )
            )
        if "SELECT p.prosrc" in query:
            values = [self.function_source] if target_schema == self.installed_schema else []
            return _FakeResult(values=values)
        raise AssertionError(f"Unexpected catalog query: {query}")

    def exec_driver_sql(self, statement):
        self.executed_sql.append(statement)


class _FakeTransactionEngine:
    def __init__(self, connection):
        self.url = SimpleNamespace(database="fitscholar_db")
        self.connection = connection

    @contextlib.contextmanager
    def begin(self):
        yield self.connection


class ScholarshipEmbeddingTriggerMigrationTests(unittest.TestCase):
    def test_corrected_function_source_matches_readiness_hash(self):
        source = _embedding_function_source()
        source_hash = hashlib.sha256(source.strip().encode("utf-8")).hexdigest()

        self.assertEqual(
            source_hash,
            scholarship_knowledge_schema.EXPECTED_FUNCTION_SOURCE_HASHES[
                "scholarship_knowledge_validate_embedding"
            ],
        )
        self.assertEqual(source_hash, migration.CORRECTED_FUNCTION_SOURCE_SHA256)
        self.assertIn(
            "WHERE a.document_version_id = NEW.document_version_id",
            source,
        )
        self.assertIn("ORDER BY a.id DESC", source)

    def test_known_legacy_function_source_matches_migration_hash(self):
        source_hash = hashlib.sha256(
            _legacy_embedding_function_source().encode("utf-8")
        ).hexdigest()

        self.assertEqual(source_hash, migration.LEGACY_FUNCTION_SOURCE_SHA256)

    def test_corrective_migration_reuses_one_canonical_definition_for_target_schema(self):
        definitions = [
            statement
            for statement in knowledge_model._EMBEDDING_POSTGRES_DDL
            if "CREATE FUNCTION scholarship_knowledge_validate_embedding()" in statement
        ]
        self.assertEqual(len(definitions), 1)

        replacement = migration._replacement_function_sql(
            "phase3b_test",
            _IdentifierPreparer(),
        )
        self.assertIn(
            'CREATE OR REPLACE FUNCTION "phase3b_test"."scholarship_knowledge_validate_embedding"()',
            replacement,
        )
        self.assertIn("WHERE a.document_version_id = NEW.document_version_id", replacement)

    def test_default_migration_mode_does_not_connect_or_run_at_startup(self):
        engine = _NoConnectEngine()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = migration.main([], target_engine=engine)

        self.assertEqual(result, 0)
        self.assertIn("No database connection opened", output.getvalue())

        startup_path = Path(__file__).resolve().parents[1] / "main.py"
        startup_tree = ast.parse(startup_path.read_text(encoding="utf-8"))
        migration_imports = [
            alias.name
            for node in ast.walk(startup_tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ] + [
            node.module
            for node in ast.walk(startup_tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        self.assertNotIn("migrate_scholarship_embedding_trigger", migration_imports)

    def test_apply_requires_configured_database_and_reports_schema(self):
        wrong_target = _NoConnectEngine()
        with self.assertRaisesRegex(
            migration.MigrationRefused,
            "does not match DATABASE_URL",
        ):
            migration.validate_configured_target(
                wrong_target,
                "another_database",
                "public",
            )

        output = io.StringIO()
        with patch.object(migration, "apply_migration") as apply:
            with contextlib.redirect_stdout(output):
                result = migration.main(
                    [
                        "--apply",
                        "--database",
                        "fitscholar_db",
                        "--schema",
                        "isolated_test",
                    ],
                    target_engine=wrong_target,
                )
        self.assertEqual(result, 0)
        apply.assert_called_once_with(wrong_target, "fitscholar_db", "isolated_test")
        self.assertIn("database 'fitscholar_db', schema 'isolated_test'", output.getvalue())

    def test_known_legacy_function_body_is_accepted_for_replacement(self):
        connection = _FakeConnection(
            function_source=_legacy_embedding_function_source(),
        )
        engine = _FakeTransactionEngine(connection)

        migration.apply_migration(engine, "fitscholar_db", "phase3b_test")

        self.assertTrue(any("CREATE OR REPLACE FUNCTION" in sql for sql in connection.executed_sql))

    def test_corrected_function_body_is_accepted_for_idempotent_rerun(self):
        connection = _FakeConnection(function_source=_embedding_function_source())
        engine = _FakeTransactionEngine(connection)

        migration.apply_migration(engine, "fitscholar_db", "phase3b_test")

        self.assertTrue(any("CREATE OR REPLACE FUNCTION" in sql for sql in connection.executed_sql))

    def test_unexpected_function_body_is_rejected_before_replacement_sql(self):
        connection = _FakeConnection(function_source="BEGIN RETURN NEW; END;")
        engine = _FakeTransactionEngine(connection)

        with self.assertRaisesRegex(
            migration.MigrationRefused,
            "body is unexpected; manual investigation is required",
        ):
            migration.apply_migration(engine, "fitscholar_db", "phase3b_test")

        self.assertFalse(any("CREATE OR REPLACE FUNCTION" in sql for sql in connection.executed_sql))
        self.assertFalse(any("SET LOCAL search_path" in sql for sql in connection.executed_sql))

    def test_function_in_another_schema_is_not_accepted(self):
        connection = _FakeConnection(
            installed_schema="actual_schema",
            function_source=_legacy_embedding_function_source(),
        )
        engine = _FakeTransactionEngine(connection)

        with self.assertRaisesRegex(
            migration.MigrationRefused,
            "does not contain the expected installed embedding trigger",
        ):
            migration.apply_migration(engine, "fitscholar_db", "requested_schema")

        target_query, params = connection.catalog_queries[0]
        self.assertIn("n.nspname = :target_schema", target_query)
        self.assertEqual(params["target_schema"], "requested_schema")
        self.assertFalse(connection.executed_sql)

    def test_function_body_catalog_query_is_schema_and_signature_scoped(self):
        query = str(migration._FUNCTION_BODY_SQL)

        self.assertIn("n.nspname = :target_schema", query)
        self.assertIn("p.proname = :function_name", query)
        self.assertIn("p.pronargs = 0", query)
        self.assertIn("p.prorettype = 'trigger'::regtype", query)


if __name__ == "__main__":
    unittest.main()
