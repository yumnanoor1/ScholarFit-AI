import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import MagicMock, patch

import discover_scholarships


LOCK_ID = 631287180927007781


class _QueryResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _LockConnection:
    def __init__(self, lock_state, acquire=True):
        self.lock_state = lock_state
        self.acquire = acquire
        self.fail_unlock = False
        self.unlock_result = None
        self.closed = False
        self.invalidated = False
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def execute(self, statement, params):
        query = str(statement)
        self.calls.append((query, params))
        if "pg_try_advisory_lock" in query:
            acquired = self.acquire and not self.lock_state["held"]
            if acquired:
                self.lock_state["held"] = True
            return _QueryResult(acquired)
        if "pg_advisory_unlock" in query:
            if self.fail_unlock:
                raise RuntimeError("unlock failed")
            if self.unlock_result is False:
                return _QueryResult(False)
            was_held = self.lock_state["held"]
            self.lock_state["held"] = False
            return _QueryResult(was_held)
        raise AssertionError(f"Unexpected query: {query}")

    def commit(self):
        pass

    def invalidate(self):
        self.invalidated = True
        self.lock_state["held"] = False

    def close(self):
        self.closed = True
        self.lock_state["held"] = False


class DiscoveryRunnerTests(unittest.TestCase):
    def setUp(self):
        self.settings = MagicMock(enabled=True)
        self.lock_state = {"held": False}
        self.connection = _LockConnection(self.lock_state)
        self.engine = MagicMock()
        self.engine.connect.return_value = self.connection
        self.session = MagicMock()
        self.session_factory = MagicMock()
        self.session_factory.return_value.__enter__.return_value = self.session
        self.stdout = StringIO()
        self.stderr = StringIO()
        self.patches = [
            patch.object(discover_scholarships, "engine", self.engine),
            patch.object(discover_scholarships, "SessionLocal", self.session_factory),
            patch.object(discover_scholarships, "scholarship_discovery_settings", return_value=self.settings),
            patch.object(
                discover_scholarships,
                "inspect",
                return_value=MagicMock(get_table_names=lambda: ["scholarship_discovery_runs"]),
            ),
        ]
        for mocked in self.patches:
            mocked.start()
            self.addCleanup(mocked.stop)

    def _run(self, discovery):
        with patch.object(discover_scholarships, "run_discovery", side_effect=discovery):
            with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
                code = discover_scholarships.main()
        return code

    def _json_output(self, stream):
        return json.loads(stream.getvalue().strip())

    def test_lock_uses_dedicated_connection_and_discovery_uses_separate_session(self):
        expected = {"status": "completed", "summary": {}}
        observed = {}

        def discovery(session, *, settings):
            observed["session"] = session
            observed["settings"] = settings
            session.commit()
            self.assertTrue(self.lock_state["held"])
            return expected

        self.assertEqual(self._run(discovery), 0)
        self.engine.connect.assert_called_once_with()
        self.session_factory.assert_called_once_with()
        self.assertIs(observed["session"], self.session)
        self.assertIsNot(observed["session"], self.connection)
        self.assertIs(observed["settings"], self.settings)
        self.assertTrue(self.connection.closed)
        self.assertFalse(self.lock_state["held"])
        self.assertEqual(self._json_output(self.stdout), expected)

    def test_second_connection_cannot_acquire_during_discovery_and_can_afterward(self):
        second_connection = _LockConnection(self.lock_state)

        def discovery(_session, **_kwargs):
            self.session.commit()
            self.assertFalse(second_connection.execute(
                "SELECT pg_try_advisory_lock(:lock_id)", {"lock_id": LOCK_ID}
            ).scalar_one())
            self.assertTrue(self.lock_state["held"])
            return {"status": "completed"}

        self.assertEqual(self._run(discovery), 0)
        self.assertTrue(second_connection.execute(
            "SELECT pg_try_advisory_lock(:lock_id)", {"lock_id": LOCK_ID}
        ).scalar_one())

    def test_lock_is_released_after_discovery_exception(self):
        def fail(*_args, **_kwargs):
            raise ValueError("discovery failure")

        self.assertEqual(self._run(fail), 1)
        self.assertFalse(self.lock_state["held"])
        self.assertTrue(self.connection.closed)
        self.assertEqual(self._json_output(self.stderr), {"status": "failed", "error": "ValueError"})

    def test_failed_lock_acquisition_does_not_start_discovery(self):
        self.connection.acquire = False
        with patch.object(discover_scholarships, "run_discovery") as discovery:
            with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
                code = discover_scholarships.main()

        self.assertEqual(code, 3)
        discovery.assert_not_called()
        self.session_factory.assert_not_called()
        self.assertEqual(
            self._json_output(self.stdout),
            {"status": "skipped", "reason": "another discovery run is active"},
        )

    def test_missing_migration_does_not_start_discovery(self):
        with patch.object(
            discover_scholarships,
            "inspect",
            return_value=MagicMock(get_table_names=lambda: []),
        ):
            with patch.object(discover_scholarships, "run_discovery") as discovery:
                with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
                    code = discover_scholarships.main()

        self.assertEqual(code, 1)
        discovery.assert_not_called()
        self.assertEqual(
            self._json_output(self.stderr),
            {"status": "failed", "error": "discovery run-history migration is required"},
        )

    def test_failed_unlock_invalidates_connection_to_release_lock(self):
        self.connection.fail_unlock = True

        self.assertEqual(
            self._run(lambda *_args, **_kwargs: {"status": "completed"}),
            1,
        )
        self.assertTrue(self.connection.invalidated)
        self.assertTrue(self.connection.closed)
        self.assertFalse(self.lock_state["held"])
        self.assertEqual(self._json_output(self.stderr), {"status": "failed", "error": "RuntimeError"})

    def test_unlock_returning_false_invalidates_connection(self):
        self.connection.unlock_result = False

        self.assertEqual(
            self._run(lambda *_args, **_kwargs: {"status": "completed"}),
            1,
        )
        self.assertTrue(self.connection.invalidated)
        self.assertTrue(self.connection.closed)
        self.assertFalse(self.lock_state["held"])
        self.assertEqual(self._json_output(self.stderr), {"status": "failed", "error": "RuntimeError"})

    def test_invalid_configuration_returns_json_without_traceback(self):
        with patch.object(
            discover_scholarships,
            "scholarship_discovery_settings",
            side_effect=RuntimeError("invalid setting"),
        ):
            with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
                code = discover_scholarships.main()

        self.assertEqual(code, 1)
        self.assertEqual(self._json_output(self.stderr), {"status": "failed", "error": "RuntimeError"})
        self.assertNotIn("Traceback", self.stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
