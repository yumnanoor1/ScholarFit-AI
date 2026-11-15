"""Every discovered link is accounted for in crawl_stats.

diag_run15 fetched 1 page out of 15 discovered links while every drop counter
read zero, because several drop points were silent. These tests pin the
counters and the per-link decision list the single-source diagnostic reports.
"""

import unittest
from dataclasses import replace

from app.core.config import ScholarshipDiscoverySettings
from app.services.scholarship_discovery_fetch import (
    DiscoveryFetchError,
    FetchedPage,
    OfficialSourceFetcher,
)
from app.services.scholarship_discovery_sources import DiscoverySource

ROOT = "https://official.example/scholarships"
PAGE_TEXT = "A scholarship for Master of Science students. " * 4

ALL_DECISIONS = frozenset({
    "queued",
    "fetched",
    "failed",
    "skipped_safety",
    "skipped_relevance",
    "already_queued",
    "not_fetched_page_budget",
})


def _settings(**overrides):
    base = ScholarshipDiscoverySettings(
        enabled=True,
        request_timeout_seconds=5,
        max_response_bytes=1_000_000,
        max_extracted_chars=10_000,
        max_pages_per_source=3,
        max_retries=0,
        request_delay_seconds=0,
        user_agent="test-agent",
        model="test-model",
    )
    return replace(base, **overrides) if overrides else base


def _source():
    return DiscoverySource(
        source_id="offline-source",
        name="Offline source",
        official_domain="official.example",
        category="government_scholarship_programme",
        country_or_region="Germany",
        source_url=ROOT,
        source_classification="government_authority",
    )


LINKS = (
    ("/scholarships/detail/1", "Scholarship detail 1"),
    ("/scholarships/detail/2", "Scholarship detail 2"),
    ("/scholarships/detail/3", "Scholarship detail 3"),
    ("/scholarships/detail/1", "Scholarship detail 1 again"),  # duplicate
    (ROOT, "Home"),                                            # already queued
    ("/imprint/", "Imprint"),                                  # irrelevant
)


def _fetcher(max_pages_per_source=3, links=LINKS, failing=()):
    fetcher = OfficialSourceFetcher(
        _settings(max_pages_per_source=max_pages_per_source),
    )

    def fake_fetch(source, url):
        if url in failing:
            raise DiscoveryFetchError("offline failure", category="timeout")
        return FetchedPage(
            url=url,
            content_type="text/html",
            text=PAGE_TEXT,
            links=links if url == ROOT else (),
            content_hash="a" * 64,
        )

    fetcher.fetch = fake_fetch
    fetcher._robots_allowed = lambda source, url: True
    return fetcher


class CrawlStatsAccountForEveryLinkTests(unittest.TestCase):
    def _assert_balances(self, stats):
        discovered = stats["linked_urls_discovered"]
        accounted = (
            stats["linked_pages_skipped_relevance"]
            + stats["linked_pages_skipped_already_queued"]
            + stats["linked_pages_fetched"]
            + stats["linked_pages_failed"]
            + stats["linked_pages_not_fetched_page_budget"]
        )
        self.assertEqual(
            discovered,
            accounted,
            f"{discovered} discovered links but {accounted} accounted for",
        )
        self.assertEqual(
            stats["linked_url_references"],
            discovered
            + stats["linked_pages_skipped_duplicate"]
            + stats["linked_pages_skipped_safety"],
        )

    def test_counters_balance_at_the_default_page_budget(self):
        fetcher = _fetcher()
        pages = fetcher.crawl(_source())

        self.assertEqual(len(pages), 3)
        self._assert_balances(fetcher.last_crawl_stats)

    def test_counters_balance_when_the_page_budget_stops_the_crawl(self):
        # The diag_run15 shape: one page fetched, links discovered, and every
        # other counter zero until now.
        fetcher = _fetcher(max_pages_per_source=1)
        pages = fetcher.crawl(_source())
        stats = fetcher.last_crawl_stats

        self.assertEqual(len(pages), 1)
        self.assertEqual(stats["linked_pages_fetched"], 0)
        self.assertEqual(stats["linked_pages_failed"], 0)
        self.assertEqual(stats["linked_pages_not_fetched_page_budget"], 3)
        self._assert_balances(stats)

    def test_counters_balance_when_a_linked_page_fails(self):
        fetcher = _fetcher(
            failing={"https://official.example/scholarships/detail/1"},
        )
        fetcher.crawl(_source())
        stats = fetcher.last_crawl_stats

        self.assertEqual(stats["linked_pages_failed"], 1)
        self._assert_balances(stats)

    def test_each_silent_drop_now_has_its_own_counter(self):
        fetcher = _fetcher(max_pages_per_source=1)
        fetcher.crawl(_source())
        stats = fetcher.last_crawl_stats

        self.assertEqual(stats["linked_pages_skipped_duplicate"], 1)
        self.assertEqual(stats["linked_pages_skipped_already_queued"], 1)
        self.assertEqual(stats["linked_pages_skipped_relevance"], 1)

    def test_the_applied_limits_are_reported(self):
        fetcher = _fetcher(max_pages_per_source=2)
        fetcher.crawl(_source())
        stats = fetcher.last_crawl_stats

        self.assertEqual(stats["max_pages_per_source"], 2)
        self.assertEqual(stats["max_crawl_depth"], fetcher.max_crawl_depth)

    def test_stats_are_reset_between_crawls(self):
        fetcher = _fetcher()
        fetcher.crawl(_source())
        first = dict(fetcher.last_crawl_stats)
        fetcher.crawl(_source())

        self.assertEqual(fetcher.last_crawl_stats, first)


class LinkDecisionListTests(unittest.TestCase):
    def _decisions(self, **kwargs):
        fetcher = _fetcher(**kwargs)
        fetcher.crawl(_source())
        return fetcher.last_link_decisions

    def test_every_decision_names_a_host_a_path_and_a_reason(self):
        decisions = self._decisions()
        self.assertTrue(decisions)
        for entry in decisions:
            with self.subTest(path=entry["path"]):
                self.assertEqual(entry["host"], "official.example")
                self.assertTrue(entry["path"].startswith("/"))
                self.assertIn(entry["decision"], ALL_DECISIONS)

    def test_the_decisions_explain_a_one_page_crawl(self):
        decisions = {
            (entry["path"], entry["decision"])
            for entry in self._decisions(max_pages_per_source=1)
        }

        self.assertIn(("/imprint/", "skipped_relevance"), decisions)
        self.assertIn(("/scholarships", "already_queued"), decisions)
        self.assertIn(
            ("/scholarships/detail/1", "not_fetched_page_budget"),
            decisions,
        )

    def test_a_fetched_link_is_marked_fetched(self):
        decisions = {
            (entry["path"], entry["decision"]) for entry in self._decisions()
        }

        self.assertIn(("/scholarships/detail/1", "fetched"), decisions)

    def test_no_query_string_or_page_text_is_recorded(self):
        links = (("/scholarships/detail/1?token=SECRETQUERY", "Detail"),)
        decisions = self._decisions(links=links)
        self.assertTrue(decisions)
        for entry in decisions:
            with self.subTest(path=entry["path"]):
                self.assertNotIn("SECRETQUERY", entry["path"])
                self.assertNotIn("?", entry["path"])
                self.assertNotIn("Master of Science", entry["path"])


class PlaywrightAttemptCounterTests(unittest.TestCase):
    def _fetcher(self):
        fetcher = OfficialSourceFetcher(
            _settings(), playwright_factory=lambda: None,
        )
        fetcher._fetch_playwright = lambda source, url: FetchedPage(
            url=url,
            content_type="text/html",
            text=PAGE_TEXT,
            links=(),
            content_hash="a" * 64,
        )
        return fetcher

    def test_a_linked_page_fetch_is_counted(self):
        fetcher = self._fetcher()
        fetcher.fetch(_source(), ROOT + "/detail/1")

        self.assertEqual(fetcher.last_crawl_stats["linked_pages_attempted"], 1)

    def test_the_root_page_is_not_counted_as_a_linked_page(self):
        fetcher = self._fetcher()
        fetcher.fetch(_source(), ROOT)

        self.assertEqual(fetcher.last_crawl_stats["linked_pages_attempted"], 0)


class DiagnosticLinkDecisionReportTests(unittest.TestCase):
    def _module(self):
        import importlib

        return importlib.import_module("diagnose_single_source_extraction")

    def _report(self, decisions):
        fetcher = type("_F", (), {"last_link_decisions": decisions})()
        return self._module()._safe_link_decisions(fetcher)

    def test_decisions_are_reported(self):
        reported = self._report([
            {"host": "official.example", "path": "/a/b", "decision": "queued"},
        ])
        self.assertEqual(
            reported,
            [{"host": "official.example", "path": "/a/b", "decision": "queued"}],
        )

    def test_an_unknown_decision_is_dropped(self):
        self.assertEqual(
            self._report([
                {"host": "official.example", "path": "/a", "decision": "weird"},
            ]),
            [],
        )

    def test_an_unsafe_host_or_path_is_replaced(self):
        reported = self._report([
            {
                "host": "official.example SECRET TEXT",
                "path": "/a b <secret>",
                "decision": "queued",
            },
        ])
        self.assertEqual(reported[0]["host"], "unavailable")
        self.assertEqual(reported[0]["path"], "unavailable")

    def test_the_list_is_capped(self):
        many = [
            {"host": "official.example", "path": f"/p/{i}", "decision": "queued"}
            for i in range(500)
        ]
        self.assertEqual(
            len(self._report(many)),
            self._module().MAX_REPORTED_LINK_DECISIONS,
        )


if __name__ == "__main__":
    unittest.main()
