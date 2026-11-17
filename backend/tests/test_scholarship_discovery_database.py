import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.scholarship_discovery_budget import (
    DiscoveryRunBudget,
    DiscoveryRunLimitExceeded,
)
from app.services.scholarship_discovery_database import (
    MAX_MANUAL_DB_CONNECT_TIMEOUT_SECONDS,
    MANUAL_DB_FINALIZATION_TIMEOUT_MS,
    ManualDiscoveryDatabaseDeadline,
    create_manual_discovery_engine,
)


class _FakeCursor:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)

    def close(self):
        return None


class _FakeConnection:
    def __init__(self, driver="psycopg"):
        self.dialect = SimpleNamespace(name="postgresql", driver=driver)
        self.engine = SimpleNamespace(dialect=self.dialect)
        self.connection = SimpleNamespace(
            driver_connection=SimpleNamespace(
                cancel=Mock(),
                cursor=Mock(return_value=_FakeCursor()),
            ),
        )


class DiscoveryDatabaseDeadlineTests(unittest.TestCase):
    def setUp(self):
        removal = patch(
            "app.services.scholarship_discovery_database.event.remove",
        )
        removal.start()
        self.addCleanup(removal.stop)

    def test_manual_engine_uses_bounded_unpooled_psycopg_connection(self):
        base_engine = SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql", driver="psycopg"),
            url=object(),
        )
        budget = DiscoveryRunBudget(
            duration_seconds=60,
            start_deadline_timer=False,
        )
        budget.start()
        created_engine = object()

        try:
            with patch(
                "app.services.scholarship_discovery_database.create_engine",
                return_value=created_engine,
            ) as create_engine:
                result, owned = create_manual_discovery_engine(base_engine, budget)

            self.assertIs(result, created_engine)
            self.assertTrue(owned)
            args, kwargs = create_engine.call_args
            self.assertIs(args[0], base_engine.url)
            self.assertEqual(
                kwargs["connect_args"],
                {"connect_timeout": MAX_MANUAL_DB_CONNECT_TIMEOUT_SECONDS},
            )
            self.assertEqual(kwargs["poolclass"].__name__, "NullPool")
            self.assertTrue(kwargs["hide_parameters"])
        finally:
            budget.close()

    def test_manual_engine_accepts_psycopg2(self):
        base_engine = SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql", driver="psycopg2"),
            url=object(),
        )
        budget = DiscoveryRunBudget(
            duration_seconds=60,
            start_deadline_timer=False,
        )
        budget.start()
        created_engine = object()

        try:
            with patch(
                "app.services.scholarship_discovery_database.create_engine",
                return_value=created_engine,
            ) as create_engine:
                result, owned = create_manual_discovery_engine(base_engine, budget)

            self.assertIs(result, created_engine)
            self.assertTrue(owned)
            self.assertEqual(create_engine.call_args.kwargs["connect_args"]["connect_timeout"], 15)
        finally:
            budget.close()

    def test_each_database_statement_gets_remaining_statement_and_lock_timeouts(self):
        now = [100.0]
        budget = DiscoveryRunBudget(
            clock=lambda: now[0],
            duration_seconds=10,
            start_deadline_timer=False,
        )
        budget.start()
        now[0] = 102.0
        connection = _FakeConnection()
        cursor = _FakeCursor()
        context = SimpleNamespace()
        listeners = []

        def listen(target, name, callback):
            listeners.append((target, name, callback))

        with patch(
            "app.services.scholarship_discovery_database.event.listen",
            side_effect=listen,
        ):
            deadline = ManualDiscoveryDatabaseDeadline(connection, budget)

        try:
            before_cursor_execute = next(
                callback
                for _target, name, callback in listeners
                if name == "before_cursor_execute"
            )
            before_cursor_execute(
                connection,
                cursor,
                "SELECT 1",
                (),
                context,
                False,
            )

            self.assertEqual(
                cursor.statements,
                [
                    "SET LOCAL statement_timeout = 8000",
                    "SET LOCAL lock_timeout = 5000",
                ],
            )
            self.assertTrue(hasattr(context, "_manual_discovery_cancel_token"))
            self.assertEqual(
                budget.snapshot()["http_attempts"],
                0,
            )
        finally:
            deadline.close()
            budget.close()

    def test_psycopg2_connection_receives_database_deadline_timeouts(self):
        budget = DiscoveryRunBudget(
            duration_seconds=10,
            start_deadline_timer=False,
        )
        budget.start()
        connection = _FakeConnection(driver="psycopg2")
        cursor = _FakeCursor()
        listeners = []

        with patch(
            "app.services.scholarship_discovery_database.event.listen",
            side_effect=lambda target, name, callback: listeners.append(
                (target, name, callback),
            ),
        ):
            deadline = ManualDiscoveryDatabaseDeadline(connection, budget)

        try:
            before_cursor_execute = next(
                callback
                for _target, name, callback in listeners
                if name == "before_cursor_execute"
            )
            before_cursor_execute(
                connection,
                cursor,
                "SELECT 1",
                (),
                SimpleNamespace(),
                False,
            )
            self.assertEqual(
                cursor.statements,
                [
                    "SET LOCAL statement_timeout = 10000",
                    "SET LOCAL lock_timeout = 5000",
                ],
            )
        finally:
            deadline.close()
            budget.close()

    def test_handle_error_listener_is_engine_scoped_and_connection_filtered(self):
        budget = DiscoveryRunBudget(
            duration_seconds=10,
            start_deadline_timer=False,
        )
        budget.start()
        connection = _FakeConnection()
        listeners = []
        context = SimpleNamespace()

        with patch(
            "app.services.scholarship_discovery_database.event.listen",
            side_effect=lambda target, name, callback: listeners.append(
                (target, name, callback),
            ),
        ):
            deadline = ManualDiscoveryDatabaseDeadline(connection, budget)

        try:
            handle_error_target, _name, handle_error = next(
                listener
                for listener in listeners
                if listener[1] == "handle_error"
            )
            self.assertIs(handle_error_target, connection.engine)

            deadline._track_operation(context)
            unrelated_connection = _FakeConnection()
            handle_error(SimpleNamespace(
                connection=unrelated_connection,
                execution_context=context,
            ))
            self.assertIn(context._manual_discovery_cancel_token, deadline._active_tokens)

            handle_error(SimpleNamespace(
                connection=connection,
                execution_context=context,
            ))
            self.assertEqual(deadline._active_tokens, set())
            self.assertFalse(hasattr(context, "_manual_discovery_cancel_token"))
        finally:
            deadline.close()
            budget.close()

    def test_expired_deadline_rejects_a_database_statement_before_cursor_execution(self):
        budget = DiscoveryRunBudget(
            duration_seconds=1,
            start_deadline_timer=False,
        )
        budget.start()
        budget._expire()
        connection = _FakeConnection()
        cursor = _FakeCursor()
        context = SimpleNamespace()
        listeners = []

        with patch(
            "app.services.scholarship_discovery_database.event.listen",
            side_effect=lambda target, name, callback: listeners.append(
                (target, name, callback),
            ),
        ):
            deadline = ManualDiscoveryDatabaseDeadline(connection, budget)

        try:
            before_cursor_execute = next(
                callback
                for _target, name, callback in listeners
                if name == "before_cursor_execute"
            )
            with self.assertRaises(DiscoveryRunLimitExceeded):
                before_cursor_execute(
                    connection,
                    cursor,
                    "SELECT 1",
                    (),
                    context,
                    False,
                )
            self.assertEqual(cursor.statements, [])
            connection.connection.driver_connection.cancel.assert_not_called()
        finally:
            deadline.close()
            budget.close()

    def test_finalization_has_one_bounded_timeout_window_after_run_deadline(self):
        budget = DiscoveryRunBudget(
            duration_seconds=1,
            start_deadline_timer=False,
        )
        budget.start()
        budget._expire()
        connection = _FakeConnection()
        cursor = _FakeCursor()
        context = SimpleNamespace()
        listeners = []

        with patch(
            "app.services.scholarship_discovery_database.event.listen",
            side_effect=lambda target, name, callback: listeners.append(
                (target, name, callback),
            ),
        ):
            deadline = ManualDiscoveryDatabaseDeadline(connection, budget)

        try:
            before_cursor_execute = next(
                callback
                for _target, name, callback in listeners
                if name == "before_cursor_execute"
            )
            with deadline.finalization():
                before_cursor_execute(
                    connection,
                    cursor,
                    "UPDATE discovery_run",
                    (),
                    context,
                    False,
                )

            self.assertEqual(
                cursor.statements,
                [
                    f"SET LOCAL statement_timeout = {MANUAL_DB_FINALIZATION_TIMEOUT_MS}",
                    f"SET LOCAL lock_timeout = {MANUAL_DB_FINALIZATION_TIMEOUT_MS}",
                ],
            )
            connection.connection.driver_connection.cancel.assert_not_called()
        finally:
            deadline.close()
            budget.close()


if __name__ == "__main__":
    unittest.main()
