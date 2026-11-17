"""The real admin path against PostgreSQL: is anything actually committed?

The first live manual run accepted candidates for 35 minutes and left nothing
in the database. The cause was not SQLite-shaped and SQLite cannot reproduce
it: the worker binds its Session to the advisory-lock connection, and a
Session bound to a connection that is already in a transaction JOINS it, so
every db.commit() only releases a savepoint. Nothing was durable until the
connection itself committed -- and when the lock release failed and
invalidated that connection, the whole run was rolled back.

These tests drive the real path (advisory lock -> DiscoveryDatabaseDeadline ->
run_discovery -> _save_run) against PostgreSQL with fake fetch and Groq
clients, and check durability from a SECOND connection while the run is still
going.

They are skipped unless DISCOVERY_TEST_DATABASE_URL names a scratch database.
NEVER point it at the production database: these tests create and drop tables.

    set DISCOVERY_TEST_DATABASE_URL=postgresql+psycopg://user:pw@127.0.0.1:5432/fitscholar_discovery_scratch
    .venv\\Scripts\\python.exe -m pytest tests/test_discovery_postgres_integration.py -v
"""

import os
import unittest
import uuid
from dataclasses import replace
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.scholarship_discovery import (
    ScholarshipDiscoveryReviewItem,
    ScholarshipDiscoveryRun,
)
from app.services.scholarship_discovery import run_discovery
from app.services.scholarship_discovery_budget import DiscoveryRunBudget
from app.services.scholarship_discovery_database import (
    ManualDiscoveryDatabaseDeadline,
)
from app.services.scholarship_discovery_scheduler import (
    DiscoveryAdvisoryLockGuard,
)
from tests.test_scholarship_discovery import (
    _candidate,
    _page,
    _settings,
    _source,
)

TEST_DATABASE_URL = os.getenv("DISCOVERY_TEST_DATABASE_URL", "").strip()
DISCOVERY_LOCK_ID = 8_234_119_501_726_354_001
PAGE_TEXT = (
    "The Finland Master's Award scholarship is available to Master's applicants."
)


def _sources(count):
    base = _source()
    return tuple(
        replace(base, source_id=f"offline-source-{index}")
        for index in range(1, count + 1)
    )


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "set DISCOVERY_TEST_DATABASE_URL to a scratch PostgreSQL database",
)
class DiscoveryCommitsPerSourceOnPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
        if cls.engine.dialect.name != "postgresql":
            raise unittest.SkipTest("DISCOVERY_TEST_DATABASE_URL is not PostgreSQL")
        Base.metadata.create_all(bind=cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.run_id = str(uuid.uuid4())
        self.page = _page(PAGE_TEXT, content_hash="d" * 64)
        self.fetcher = MagicMock()
        self.fetcher.crawl.return_value = [self.page]
        self.extractor = MagicMock()
        self.extractor.last_rejected_count = 0
        self.addCleanup(self._clean_up_rows)

    def _clean_up_rows(self):
        with self.engine.connect() as conn:
            conn.execute(
                text(
                    "DELETE FROM scholarship_discovery_review_items "
                    "WHERE discovery_run_id = :run_id"
                ),
                {"run_id": self.run_id},
            )
            conn.execute(
                text("DELETE FROM scholarship_discovery_runs WHERE id = :run_id"),
                {"run_id": self.run_id},
            )
            conn.commit()

    def _observe(self, query_fn):
        """Run a query on a SEPARATE connection: only committed rows are seen."""
        session = self.Session()
        try:
            return query_fn(session)
        finally:
            session.close()

    def _runs_visible(self, session):
        return (
            session.query(ScholarshipDiscoveryRun)
            .filter(ScholarshipDiscoveryRun.id == self.run_id)
            .count()
        )

    def _items_visible(self, session):
        return [
            item.source_id
            for item in session.query(ScholarshipDiscoveryReviewItem)
            .filter(ScholarshipDiscoveryReviewItem.discovery_run_id == self.run_id)
            .all()
        ]

    def _candidate_for(self, source_id):
        candidate = _candidate(page=self.page)
        candidate.values["name"] = f"Award from {source_id}"
        return candidate

    def _real_path(self, sources, extract, budget_seconds=600):
        """Advisory lock -> deadline -> run_discovery, as the worker does it."""
        observations = []
        self.extractor.extract.side_effect = extract
        budget = DiscoveryRunBudget(
            max_sources=10,
            duration_seconds=budget_seconds,
            start_deadline_timer=False,
        )
        budget.start()
        lock_connection = self.engine.connect()
        try:
            acquired = lock_connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": DISCOVERY_LOCK_ID},
            ).scalar_one()
            self.assertTrue(acquired, "another run holds the advisory lock")
            lock_connection.commit()
            lock_guard = DiscoveryAdvisoryLockGuard(
                lock_connection.execute(
                    text("SELECT pg_backend_pid()")
                ).scalar_one(),
            )
            # The worker's own sequence, including the fix under test.
            lock_connection.commit()
            session = self.Session(
                bind=lock_connection, join_transaction_mode="control_fully",
            )
            deadline = ManualDiscoveryDatabaseDeadline.for_session(session, budget)
            deadline.attach_session(session)
            try:
                with patch(
                    "app.services.scholarship_discovery."
                    "validate_controlled_manual_run_sources",
                    side_effect=lambda items: tuple(items),
                ):
                    result = run_discovery(
                        session,
                        settings=_settings(),
                        sources=sources,
                        fetcher=self.fetcher,
                        extractor=self.extractor,
                        trigger_type="manual",
                        run_id=self.run_id,
                        run_budget=budget,
                        database_deadline=deadline,
                        lock_guard=lock_guard,
                        on_stage=lambda stage: observations.append(
                            (stage, self._observe(self._items_visible)),
                        ),
                    )
            finally:
                session.close()
                try:
                    deadline.close()
                except Exception:
                    pass
            return result, observations
        finally:
            try:
                lock_connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": DISCOVERY_LOCK_ID},
                )
                lock_connection.commit()
            finally:
                lock_connection.close()
                budget.close()

    def test_the_run_row_is_committed_before_any_source_runs(self):
        seen_at_first_source = []

        def extract(page, source):
            seen_at_first_source.append(self._observe(self._runs_visible))
            return [self._candidate_for(source.source_id)]

        self._real_path(_sources(1), extract)

        self.assertEqual(
            seen_at_first_source[0],
            1,
            "the run row must be visible from another connection while the "
            "run is still going",
        )

    def test_each_source_commits_its_candidates_independently(self):
        sources = _sources(3)

        def extract(page, source):
            return [self._candidate_for(source.source_id)]

        _result, observations = self._real_path(sources, extract)

        # on_stage fires as each source starts, so by source N the items of
        # sources 1..N-1 must already be committed and visible elsewhere.
        stages = [
            (stage, items)
            for stage, items in observations
            if stage.startswith("source:")
        ]
        self.assertGreaterEqual(len(stages), 3)
        self.assertEqual(len(stages[1][1]), 1, stages[1])
        self.assertEqual(len(stages[2][1]), 2, stages[2])
        self.assertEqual(len(self._observe(self._items_visible)), 3)

    def test_a_third_source_running_out_of_time_keeps_the_first_two(self):
        sources = _sources(3)
        budget_holder = {}

        def extract(page, source):
            if source.source_id == sources[2].source_id:
                budget_holder["budget"].expire()
            return [self._candidate_for(source.source_id)]

        self.extractor.extract.side_effect = extract

        budget = DiscoveryRunBudget(
            max_sources=10,
            duration_seconds=600,
            start_deadline_timer=False,
        )
        budget.start()
        budget_holder["budget"] = budget
        lock_connection = self.engine.connect()
        try:
            lock_connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": DISCOVERY_LOCK_ID},
            ).scalar_one()
            lock_connection.commit()
            guard = DiscoveryAdvisoryLockGuard(
                lock_connection.execute(
                    text("SELECT pg_backend_pid()")
                ).scalar_one(),
            )
            lock_connection.commit()
            session = self.Session(
                bind=lock_connection, join_transaction_mode="control_fully",
            )
            try:
                with patch(
                    "app.services.scholarship_discovery."
                    "validate_controlled_manual_run_sources",
                    side_effect=lambda items: tuple(items),
                ):
                    with self.assertRaises(Exception):
                        run_discovery(
                            session,
                            settings=_settings(),
                            sources=sources,
                            fetcher=self.fetcher,
                            extractor=self.extractor,
                            trigger_type="manual",
                            run_id=self.run_id,
                            run_budget=budget,
                            lock_guard=guard,
                        )
            finally:
                session.close()
            # What the failing lock release used to do to the whole run.
            lock_connection.invalidate()
        finally:
            lock_connection.close()
            budget.close()

        survived = self._observe(self._items_visible)
        self.assertEqual(
            sorted(survived),
            [sources[0].source_id, sources[1].source_id],
            "candidates from the sources that finished must survive both the "
            "time limit and the connection being invalidated",
        )
        self.assertEqual(self._observe(self._runs_visible), 1)


if __name__ == "__main__":
    unittest.main()
