"""A run that stops early keeps what it already saved.

The first live manual run hit the duration budget mid-source, crashed through
the failure handler and left the review queue looking empty. These tests pin
the two guarantees that were missing: candidates are committed per source, and
running out of time ends the run as a partial run with a clear status.
"""

import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.scholarship_discovery import (
    ScholarshipDiscoveryReviewItem,
    ScholarshipDiscoveryRun,
)
from app.services.scholarship_discovery import run_discovery
from app.services.scholarship_discovery_budget import DiscoveryRunBudget
from app.services.scholarship_discovery_extraction import (
    ScholarshipExtractionError,
)
from tests.test_scholarship_discovery import (
    _candidate,
    _page,
    _settings,
    _source,
)

PAGE_TEXT = (
    "The Finland Master's Award scholarship is available to Master's applicants."
)


def _sources(count):
    """Distinct sources that share the shared helper's trust settings."""
    from dataclasses import replace

    base = _source()
    return tuple(
        replace(base, source_id=f"offline-source-{index}")
        for index in range(1, count + 1)
    )


class PartialRunPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def _enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.page = _page(PAGE_TEXT, content_hash="d" * 64)
        self.fetcher = MagicMock()
        self.fetcher.crawl.return_value = [self.page]
        self.extractor = MagicMock()
        self.extractor.last_rejected_count = 0

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _candidate_for(self, source_id):
        candidate = _candidate(page=self.page)
        candidate.values["name"] = f"Award from {source_id}"
        return candidate

    def _run(self, sources, **options):
        return run_discovery(
            self.db,
            settings=_settings(),
            sources=sources,
            fetcher=self.fetcher,
            extractor=self.extractor,
            trigger_type=options.pop("trigger_type", "scheduled"),
            **options,
        )

    def test_candidates_from_earlier_sources_survive_a_later_failure(self):
        sources = _sources(3)
        failing_source_id = sources[2].source_id

        def extract(page, source):
            if source.source_id == failing_source_id:
                raise ScholarshipExtractionError(
                    "offline provider failure",
                    category="provider_error",
                )
            return [self._candidate_for(source.source_id)]

        self.extractor.extract.side_effect = extract

        result = self._run(sources, run_id="partial-run")

        queued = {
            item.source_id
            for item in self.db.query(ScholarshipDiscoveryReviewItem).all()
        }
        self.assertEqual(
            queued,
            {sources[0].source_id, sources[1].source_id},
            "candidates from the sources that finished must still be queued",
        )
        self.assertEqual(result["summary"]["sources_failed"], 1)

        # The rows are really committed, not just visible in this session.
        other = sessionmaker(bind=self.engine)()
        try:
            self.assertEqual(
                other.query(ScholarshipDiscoveryReviewItem).count(), 2,
            )
        finally:
            other.close()

    def test_a_crash_in_the_third_source_keeps_the_first_two(self):
        sources = _sources(3)

        def extract(page, source):
            if source.source_id == sources[2].source_id:
                raise RuntimeError("offline crash")
            return [self._candidate_for(source.source_id)]

        self.extractor.extract.side_effect = extract

        with self.assertRaises(RuntimeError):
            self._run(sources, run_id="crash-run")

        other = sessionmaker(bind=self.engine)()
        try:
            queued = {
                item.source_id
                for item in other.query(ScholarshipDiscoveryReviewItem).all()
            }
            self.assertEqual(
                queued, {sources[0].source_id, sources[1].source_id},
            )
            # The failure status was written even though the run's own
            # session had been rolled back (this is where ObjectDeletedError
            # used to lose it).
            run = other.get(ScholarshipDiscoveryRun, "crash-run")
            self.assertIsNotNone(run)
            self.assertEqual(run.status, "failed")
            self.assertIsNotNone(run.finished_at)
            self.assertEqual(run.summary["error_summary"], "RuntimeError")
        finally:
            other.close()


class TimeLimitEndsTheRunGracefullyTests(unittest.TestCase):
    """A run budget requires the manual trigger, and the manual trigger only
    accepts the real controlled source list. These tests are about the time
    check, so that allowlist check is stubbed out for offline sources."""

    def setUp(self):
        patcher = patch(
            "app.services.scholarship_discovery."
            "validate_controlled_manual_run_sources",
            side_effect=lambda sources: tuple(sources),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.page = _page(PAGE_TEXT, content_hash="d" * 64)
        self.fetcher = MagicMock()
        self.fetcher.crawl.return_value = [self.page]
        self.extractor = MagicMock()
        self.extractor.last_rejected_count = 0
        self.extractor.extract.return_value = []

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _budget(self, seconds):
        return DiscoveryRunBudget(
            max_sources=10,
            duration_seconds=seconds,
            start_deadline_timer=False,
        )

    def test_a_run_with_too_little_time_left_stops_before_the_next_source(self):
        # The first source always runs; with less than
        # MIN_SECONDS_TO_START_A_SOURCE left afterwards, the rest are not
        # started and are reported instead.
        budget = self._budget(10)
        budget.start()
        try:
            result = run_discovery(
                self.db,
                settings=_settings(),
                sources=_sources(3),
                fetcher=self.fetcher,
                extractor=self.extractor,
                trigger_type="manual",
                run_id="time-limit-run",
                run_budget=budget,
            )
        finally:
            budget.close()

        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            result["summary"]["run_outcome"], "stopped_time_limit",
        )
        self.assertEqual(
            result["summary"]["stop_reason"]["resource"], "duration_seconds",
        )
        self.assertEqual(
            result["summary"]["sources_not_reached"],
            ["offline-source-2", "offline-source-3"],
        )
        self.fetcher.crawl.assert_called_once()

        run = self.db.get(ScholarshipDiscoveryRun, "time-limit-run")
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.summary["run_outcome"], "stopped_time_limit")
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(
            run.summary["sources_not_reached"],
            ["offline-source-2", "offline-source-3"],
        )

    def test_a_run_with_time_left_is_unaffected(self):
        budget = self._budget(600)
        budget.start()
        try:
            result = run_discovery(
                self.db,
                settings=_settings(),
                sources=_sources(2),
                fetcher=self.fetcher,
                extractor=self.extractor,
                trigger_type="manual",
                run_id="normal-run",
                run_budget=budget,
            )
        finally:
            budget.close()

        self.assertEqual(result["status"], "completed")
        self.assertNotIn("sources_not_reached", result["summary"])
        self.assertEqual(result["summary"]["sources_attempted"], 2)


if __name__ == "__main__":
    unittest.main()


class EveryCandidateGoesToReviewTests(unittest.TestCase):
    """Discovery never publishes. It queues; an admin decides."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.page = _page(PAGE_TEXT, content_hash="d" * 64)
        self.fetcher = MagicMock()
        self.fetcher.crawl.return_value = [self.page]
        self.extractor = MagicMock()
        self.extractor.last_rejected_count = 0
        self.extractor.extract.return_value = [_candidate(page=self.page)]

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_a_brand_new_candidate_creates_no_scholarship(self):
        from app.models.opportunity import Scholarship

        result = run_discovery(
            self.db,
            settings=_settings(),
            sources=_sources(1),
            fetcher=self.fetcher,
            extractor=self.extractor,
            trigger_type="scheduled",
            run_id="review-only-run",
        )

        self.assertEqual(self.db.query(Scholarship).count(), 0)
        self.assertEqual(result["summary"]["new_records_created"], 0)

    def test_it_is_queued_as_pending(self):
        run_discovery(
            self.db,
            settings=_settings(),
            sources=_sources(1),
            fetcher=self.fetcher,
            extractor=self.extractor,
            trigger_type="scheduled",
            run_id="review-only-run-2",
        )

        items = self.db.query(ScholarshipDiscoveryReviewItem).all()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].review_status, "pending")
        self.assertIsNone(items[0].accepted_scholarship_id)


class RunClosesWhatItOpenedTests(unittest.TestCase):
    """A run must not leave a Playwright browser behind.

    run_discovery builds its own fetcher when the caller does not pass one, and
    that fetcher owns a Playwright process, a Chromium browser and a context.
    Nothing closed it, so every run on the long-lived API process leaked one --
    the sockets and handles behind WinError 10055 on a small Windows host.
    """

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.page = _page(PAGE_TEXT, content_hash="d" * 64)
        self.extractor = MagicMock()
        self.extractor.last_rejected_count = 0
        self.extractor.extract.return_value = []

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _run(self, fetcher=None, run_id="cleanup-run", **options):
        return run_discovery(
            self.db,
            settings=_settings(),
            sources=_sources(1),
            fetcher=fetcher,
            extractor=self.extractor,
            trigger_type="scheduled",
            run_id=run_id,
            **options,
        )

    def test_a_fetcher_the_run_created_is_closed(self):
        page = self.page

        class _RecordingFetcher:
            # A real class: the service checks isinstance against this name.
            instances = []

            def __init__(self, *args, **kwargs):
                self.closed = 0
                self.last_crawl_stats = {}
                self.lock_check = None
                self.run_budget = None
                type(self).instances.append(self)

            def crawl(self, source):
                return [page]

            def close(self):
                self.closed += 1

        with patch(
            "app.services.scholarship_discovery.OfficialSourceFetcher",
            _RecordingFetcher,
        ):
            self._run()

        self.assertEqual(len(_RecordingFetcher.instances), 1)
        self.assertEqual(_RecordingFetcher.instances[0].closed, 1)

    def test_the_fetcher_is_closed_even_when_the_run_fails(self):
        class _FailingFetcher:
            instances = []

            def __init__(self, *args, **kwargs):
                self.closed = 0
                self.last_crawl_stats = {}
                self.lock_check = None
                self.run_budget = None
                type(self).instances.append(self)

            def crawl(self, source):
                raise RuntimeError("offline failure")

            def close(self):
                self.closed += 1

        with patch(
            "app.services.scholarship_discovery.OfficialSourceFetcher",
            _FailingFetcher,
        ):
            # A source failure is recorded, not raised; a crawl that raises
            # RuntimeError is re-raised after cleanup.
            with self.assertRaises(RuntimeError):
                self._run(run_id="cleanup-run-failed")

        self.assertEqual(_FailingFetcher.instances[0].closed, 1)

    def test_a_fetcher_the_caller_owns_is_left_open(self):
        # The caller (and the tests that reuse one fetcher) keeps control.
        fetcher = MagicMock()
        fetcher.crawl.return_value = [self.page]
        fetcher.last_crawl_stats = {}

        self._run(fetcher=fetcher, run_id="cleanup-run-caller")

        fetcher.close.assert_not_called()
