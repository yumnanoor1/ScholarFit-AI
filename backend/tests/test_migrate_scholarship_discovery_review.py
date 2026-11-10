import contextlib
import io
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import migrate_scholarship_discovery_review as migration


class FakeConnection:
    def __init__(self, events, tables):
        self.events = events
        self.tables = tables

    def execute(self, statement, parameters):
        self.events.append(("execute", str(statement), parameters))


class FakeEngine:
    def __init__(self, tables):
        self.events = []
        self.connection = FakeConnection(self.events, set(tables))
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
    name = "scholarship_discovery_review_items"

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


class ScholarshipDiscoveryReviewMigrationTests(unittest.TestCase):
    def test_acquires_transaction_lock_before_catalog_inspection_and_creation(self):
        engine = FakeEngine({"scholarship_discovery_runs"})
        table = FakeTable(engine.events)
        output = io.StringIO()

        with patch.object(migration, "inspect", side_effect=_inspect):
            with contextlib.redirect_stdout(output):
                result = migration.main(
                    engine=engine,
                    target_database="fitscholar_phase3b_test",
                    apply=True,
                    table=table,
                )

        labels = [event[0] for event in engine.events]
        self.assertEqual(labels, ["begin", "execute", "inspect", "create", "commit"])
        lock_call = engine.events[1]
        self.assertIn("pg_advisory_xact_lock", lock_call[1])
        self.assertEqual(lock_call[2], {"lock_id": migration.MIGRATION_LOCK_ID})
        self.assertTrue(result)

    def test_sequential_rerun_does_not_create_the_table_twice(self):
        engine = FakeEngine({"scholarship_discovery_runs"})
        table = FakeTable(engine.events)

        with patch.object(migration, "inspect", side_effect=_inspect):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(migration.main(
                    engine=engine,
                    target_database="fitscholar_phase3b_test",
                    apply=True,
                    table=table,
                ))
                self.assertTrue(migration.main(
                    engine=engine,
                    target_database="fitscholar_phase3b_test",
                    apply=True,
                    table=table,
                ))

        self.assertEqual(table.create_count, 1)
        self.assertEqual(sum(event[0] == "execute" for event in engine.events), 2)

