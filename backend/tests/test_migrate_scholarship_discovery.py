import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import migrate_scholarship_discovery as run_history_migration
import migrate_scholarship_discovery_review as review_migration
import migrate_scholarship_discovery_scheduler as scheduler_migration


class FakeConnection:
    def __init__(self, events):
        self.events = events
        self.tables = set()

    def execute(self, statement, parameters=None):
        self.events.append(("execute", str(statement), parameters))


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


class FakeTable:
    name = "scholarship_discovery_runs"

    def __init__(self, events):
        self.events = events
        self.create_count = 0

    def create(self, bind):
        self.events.append(("create",))
        self.create_count += 1
        bind.tables.add(self.name)


def _inspect(connection):
    connection.events.append(("inspect",))
    return SimpleNamespace(get_table_names=lambda: list(connection.tables))


class ScholarshipDiscoveryRunHistoryMigrationTests(unittest.TestCase):
    def test_all_discovery_migrations_use_the_same_lock_id(self):
        self.assertEqual(
            {
                run_history_migration.MIGRATION_LOCK_ID,
                review_migration.MIGRATION_LOCK_ID,
                scheduler_migration.MIGRATION_LOCK_ID,
            },
            {728341901270419},
        )

    def test_acquires_transaction_lock_before_inspection_and_table_creation(self):
        engine = FakeEngine()
        table = FakeTable(engine.events)
        model = SimpleNamespace(__table__=table)

        with patch.object(run_history_migration, "ScholarshipDiscoveryRun", model):
            with patch.object(run_history_migration, "inspect", side_effect=_inspect):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertTrue(run_history_migration.main(
                        engine=engine,
                        target_database="fitscholar_phase3b_test",
                        apply=True,
                    ))

        labels = [event[0] for event in engine.events]
        self.assertEqual(labels, ["begin", "execute", "inspect", "create", "commit"])
        lock_call = engine.events[1]
        self.assertIn("pg_advisory_xact_lock", lock_call[1])
        self.assertEqual(
            lock_call[2],
            {"lock_id": run_history_migration.MIGRATION_LOCK_ID},
        )

    def test_sequential_rerun_does_not_create_the_table_twice(self):
        engine = FakeEngine()
        table = FakeTable(engine.events)
        model = SimpleNamespace(__table__=table)

        with patch.object(run_history_migration, "ScholarshipDiscoveryRun", model):
            with patch.object(run_history_migration, "inspect", side_effect=_inspect):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertTrue(run_history_migration.main(
                        engine=engine,
                        target_database="fitscholar_phase3b_test",
                        apply=True,
                    ))
                    self.assertTrue(run_history_migration.main(
                        engine=engine,
                        target_database="fitscholar_phase3b_test",
                        apply=True,
                    ))

        self.assertEqual(table.create_count, 1)
        lock_calls = [
            event for event in engine.events
            if event[0] == "execute" and "pg_advisory_xact_lock" in event[1]
        ]
        self.assertEqual(len(lock_calls), 2)


if __name__ == "__main__":
    unittest.main()
