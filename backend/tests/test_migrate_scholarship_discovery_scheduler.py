import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import migrate_scholarship_discovery_scheduler as migration


class FakeConnection:
    def __init__(self, events):
        self.events = events
        self.tables = {"scholarship_discovery_runs"}
        self.columns = {"id", "status"}
        self.checks = set()
        self.indexes = set()

    def execute(self, statement, parameters=None):
        query = str(statement)
        self.events.append(("execute", query, parameters))
        if "ADD COLUMN trigger_type" in query:
            self.columns.add("trigger_type")
        elif "ADD COLUMN scheduled_for" in query:
            self.columns.add("scheduled_for")
        elif "ADD CONSTRAINT" in query:
            self.checks.add(migration.TRIGGER_CONSTRAINT)
        elif "CREATE UNIQUE INDEX" in query:
            self.indexes.add(migration.SCHEDULED_SLOT_INDEX)


class FakeEngine:
    def __init__(self):
        self.events = []
        self.connection = FakeConnection(self.events)
        self.dialect = SimpleNamespace(name="postgresql")
        self.url = SimpleNamespace(database="fitscholar_phase3b_test")

    @contextlib.contextmanager
    def begin(self):
        self.events.append(("begin",))
        try:
            yield self.connection
        except Exception:
            self.events.append(("rollback",))
            raise
        else:
            self.events.append(("commit",))


def _inspect(connection):
    connection.events.append(("inspect",))
    return SimpleNamespace(
        get_table_names=lambda: list(connection.tables),
        get_columns=lambda _table: [{"name": name} for name in connection.columns],
        get_check_constraints=lambda _table: [
            {"name": name} for name in connection.checks
        ],
        get_indexes=lambda _table: [{"name": name} for name in connection.indexes],
    )


class ScholarshipDiscoverySchedulerMigrationTests(unittest.TestCase):
    def test_acquires_transaction_lock_before_catalog_inspection_and_schema_changes(self):
        engine = FakeEngine()

        with patch.object(migration, "inspect", side_effect=_inspect):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(migration.main(
                    engine=engine,
                    target_database="fitscholar_phase3b_test",
                    apply=True,
                ))

        labels = [event[0] for event in engine.events]
        self.assertEqual(labels[0:3], ["begin", "execute", "inspect"])
        lock_call = engine.events[1]
        self.assertIn("pg_advisory_xact_lock", lock_call[1])
        self.assertEqual(lock_call[2], {"lock_id": migration.MIGRATION_LOCK_ID})
        first_schema_change = next(
            index for index, event in enumerate(engine.events)
            if event[0] == "execute" and "ALTER TABLE" in event[1]
        )
        self.assertLess(1, first_schema_change)
        self.assertLess(1, labels.index("inspect"))
        self.assertEqual(labels[-1], "commit")

    def test_sequential_rerun_is_idempotent(self):
        engine = FakeEngine()

        with patch.object(migration, "inspect", side_effect=_inspect):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(migration.main(
                    engine=engine,
                    target_database="fitscholar_phase3b_test",
                    apply=True,
                ))
                self.assertTrue(migration.main(
                    engine=engine,
                    target_database="fitscholar_phase3b_test",
                    apply=True,
                ))

        schema_changes = [
            event for event in engine.events
            if event[0] == "execute" and (
                "ALTER TABLE" in event[1] or "CREATE UNIQUE INDEX" in event[1]
            )
        ]
        lock_calls = [
            event for event in engine.events
            if event[0] == "execute" and "pg_advisory_xact_lock" in event[1]
        ]
        self.assertEqual(len(schema_changes), 4)
        self.assertEqual(len(lock_calls), 2)


if __name__ == "__main__":
    unittest.main()
