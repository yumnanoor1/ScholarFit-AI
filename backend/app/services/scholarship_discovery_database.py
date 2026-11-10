"""PostgreSQL timeouts for controlled manual discovery database work."""

import logging
import math
import threading
import time
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool

from app.services.scholarship_discovery_budget import (
    DiscoveryRunBudget,
    DiscoveryRunLimitExceeded,
)

logger = logging.getLogger(__name__)

MAX_MANUAL_DB_CONNECT_TIMEOUT_SECONDS = 15
MAX_MANUAL_DB_LOCK_TIMEOUT_MS = 5_000
MANUAL_DB_FINALIZATION_TIMEOUT_MS = 5_000


def create_manual_discovery_engine(base_engine, budget: DiscoveryRunBudget):
    """Create an unpooled, short-connect-timeout engine for one manual run."""
    dialect = base_engine.dialect
    if dialect.name != "postgresql":
        return base_engine, False
    if dialect.driver != "psycopg":
        raise RuntimeError("Controlled manual discovery requires the psycopg driver")

    timeout = max(
        1,
        math.ceil(
            min(
                MAX_MANUAL_DB_CONNECT_TIMEOUT_SECONDS,
                budget.remaining_seconds(),
            )
        ),
    )
    return create_engine(
        base_engine.url,
        connect_args={"connect_timeout": timeout},
        poolclass=NullPool,
        pool_pre_ping=True,
        hide_parameters=True,
    ), True


class ManualDiscoveryDatabaseDeadline:
    """Apply remaining-time PostgreSQL statement and lock timeouts per operation."""

    def __init__(self, connection, budget: DiscoveryRunBudget):
        self.connection = connection
        self.budget = budget
        self._finalizing = threading.local()
        self._finalization_deadline = None
        self._active_tokens = set()
        self._lock = threading.Lock()
        self._session = None
        self._driver_connection = None
        dialect = getattr(connection, "dialect", None)
        if dialect is None:
            engine = getattr(connection, "engine", None)
            dialect = getattr(engine, "dialect", None)
        self.supported = (
            dialect is not None
            and dialect.name == "postgresql"
            and dialect.driver == "psycopg"
        )
        if not self.supported:
            logger.warning(
                "Controlled manual discovery database timeouts are unavailable "
                "for dialect=%s driver=%s",
                getattr(dialect, "name", "unknown"),
                getattr(dialect, "driver", "unknown"),
            )
            return

        proxied_connection = connection.connection
        self._driver_connection = getattr(
            proxied_connection,
            "driver_connection",
            proxied_connection,
        )
        event.listen(connection, "before_cursor_execute", self._before_cursor_execute)
        event.listen(connection, "after_cursor_execute", self._after_cursor_execute)
        event.listen(connection, "handle_error", self._handle_error)

    @classmethod
    def for_session(cls, session, budget: DiscoveryRunBudget):
        bind = session.get_bind()
        if (
            bind.dialect.name != "postgresql"
            or bind.dialect.driver != "psycopg"
        ):
            return cls(bind, budget)
        return cls(session.connection(), budget)

    def attach_session(self, session) -> None:
        if not self.supported or self._session is session:
            return
        if self._session is not None:
            raise RuntimeError("Database deadline is already attached to another session")
        self._session = session
        event.listen(session, "before_commit", self._before_commit)
        event.listen(session, "after_commit", self._after_transaction_end)
        event.listen(session, "after_rollback", self._after_transaction_end)

    def _remaining_timeout_ms(self) -> int:
        if getattr(self._finalizing, "active", False):
            try:
                return max(1, math.ceil(self.budget.remaining_seconds() * 1000))
            except DiscoveryRunLimitExceeded:
                if self._finalization_deadline is None:
                    self._finalization_deadline = (
                        time.monotonic()
                        + MANUAL_DB_FINALIZATION_TIMEOUT_MS / 1000
                    )
                remaining = self._finalization_deadline - time.monotonic()
                if remaining <= 0:
                    raise
                return max(1, math.ceil(remaining * 1000))
        return max(1, math.ceil(self.budget.remaining_seconds() * 1000))

    def _set_local_timeouts(self, cursor, timeout_ms: int) -> None:
        lock_timeout_ms = min(timeout_ms, MAX_MANUAL_DB_LOCK_TIMEOUT_MS)
        cursor.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
        cursor.execute(f"SET LOCAL lock_timeout = {lock_timeout_ms}")

    def _track_operation(self, context) -> None:
        if (
            getattr(self._finalizing, "active", False)
            and self._finalization_deadline is not None
        ):
            return
        token = self.budget.register_cancellation(self._driver_connection.cancel)
        with self._lock:
            self._active_tokens.add(token)
        if context is not None:
            context._manual_discovery_cancel_token = token

    def _release_operation(self, context) -> None:
        token = getattr(context, "_manual_discovery_cancel_token", None)
        if token is None:
            return
        with self._lock:
            self._active_tokens.discard(token)
        self.budget.unregister_cancellation(token)
        del context._manual_discovery_cancel_token

    def _before_cursor_execute(
        self,
        _connection,
        cursor,
        _statement,
        _parameters,
        context,
        _executemany,
    ) -> None:
        if not self.supported:
            return
        timeout_ms = self._remaining_timeout_ms()
        self._track_operation(context)
        try:
            self._set_local_timeouts(cursor, timeout_ms)
            if not getattr(self._finalizing, "active", False):
                self.budget.ensure_active()
        except Exception:
            self._release_operation(context)
            raise

    def _after_cursor_execute(
        self,
        _connection,
        _cursor,
        _statement,
        _parameters,
        context,
        _executemany,
    ) -> None:
        self._release_operation(context)

    def _handle_error(self, exception_context) -> None:
        self._release_operation(exception_context.execution_context)

    def _before_commit(self, _session) -> None:
        if not self.supported:
            return
        cursor = self._driver_connection.cursor()
        try:
            timeout_ms = self._remaining_timeout_ms()
            self._set_local_timeouts(cursor, timeout_ms)
        finally:
            cursor.close()
        self._track_operation(None)

    def _after_transaction_end(self, _session) -> None:
        with self._lock:
            tokens = tuple(self._active_tokens)
            self._active_tokens.clear()
        for token in tokens:
            self.budget.unregister_cancellation(token)

    @contextmanager
    def finalization(self):
        previous = getattr(self._finalizing, "active", False)
        self._finalizing.active = True
        if self._finalization_deadline is None:
            try:
                self.budget.ensure_active()
            except DiscoveryRunLimitExceeded:
                self._finalization_deadline = (
                    time.monotonic()
                    + MANUAL_DB_FINALIZATION_TIMEOUT_MS / 1000
                )
        try:
            yield
        finally:
            self._finalizing.active = previous

    def close(self) -> None:
        if not self.supported:
            return
        self._after_transaction_end(self._session)
        event.remove(self.connection, "before_cursor_execute", self._before_cursor_execute)
        event.remove(self.connection, "after_cursor_execute", self._after_cursor_execute)
        event.remove(self.connection, "handle_error", self._handle_error)
        if self._session is not None:
            event.remove(self._session, "before_commit", self._before_commit)
            event.remove(self._session, "after_commit", self._after_transaction_end)
            event.remove(self._session, "after_rollback", self._after_transaction_end)
