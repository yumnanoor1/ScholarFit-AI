"""SCHOLARSHIP_DISCOVERY_MANUAL_SOURCE_IDS narrows a manual run only."""

import os
import unittest
from unittest.mock import patch

from app.core.config import MANUAL_SOURCE_IDS_ENV, manual_discovery_source_ids
from app.services.scholarship_discovery_budget import (
    CONTROLLED_MANUAL_SOURCE_IDS,
    ManualSourceSelectionError,
    configured_manual_source_ids,
    controlled_manual_sources,
    validate_controlled_manual_run_sources,
)
from app.services.scholarship_discovery_sources import SOURCES

FIVE_SOURCE_IDS = (
    "daad-epos",
    "nl-scholarship",
    "kth-scholarship",
    "eiffel-scholarship",
    "chevening-pakistan",
)


def _with_setting(value):
    environ = dict(os.environ)
    if value is None:
        environ.pop(MANUAL_SOURCE_IDS_ENV, None)
    else:
        environ[MANUAL_SOURCE_IDS_ENV] = value
    return patch.dict(os.environ, environ, clear=True)


class ManualSourceSubsetTests(unittest.TestCase):
    def test_the_setting_selects_exactly_the_listed_sources_in_order(self):
        with _with_setting(",".join(FIVE_SOURCE_IDS)):
            selected = controlled_manual_sources()
        self.assertEqual(
            tuple(source.source_id for source in selected),
            FIVE_SOURCE_IDS,
        )

    def test_the_listed_order_is_kept_even_when_it_differs_from_the_registry(self):
        reversed_ids = tuple(reversed(FIVE_SOURCE_IDS))
        with _with_setting(",".join(reversed_ids)):
            selected = controlled_manual_sources()
        self.assertEqual(
            tuple(source.source_id for source in selected),
            reversed_ids,
        )

    def test_surrounding_whitespace_is_ignored(self):
        with _with_setting("  daad-epos , nl-scholarship  "):
            self.assertEqual(
                configured_manual_source_ids(),
                ("daad-epos", "nl-scholarship"),
            )

    def test_a_subset_still_passes_manual_run_validation(self):
        with _with_setting(",".join(FIVE_SOURCE_IDS)):
            selected = controlled_manual_sources()
            validated = validate_controlled_manual_run_sources(selected)
        self.assertEqual(len(validated), 5)

    def test_an_unset_setting_leaves_all_fifteen_controlled_sources(self):
        with _with_setting(None):
            self.assertIsNone(configured_manual_source_ids())
            selected = controlled_manual_sources()
        self.assertEqual(
            tuple(source.source_id for source in selected),
            CONTROLLED_MANUAL_SOURCE_IDS,
        )
        self.assertEqual(len(selected), 15)


class ManualSourceSubsetRejectionTests(unittest.TestCase):
    def _assert_rejected(self, value):
        with _with_setting(value):
            with self.assertRaises(RuntimeError) as caught:
                controlled_manual_sources()
        message = str(caught.exception)
        self.assertIn(MANUAL_SOURCE_IDS_ENV, message)
        return message

    def test_an_unknown_id_is_rejected(self):
        with _with_setting("daad-epos,not-a-source"):
            with self.assertRaises(ManualSourceSelectionError):
                controlled_manual_sources()

    def test_an_id_outside_the_controlled_set_is_rejected(self):
        # A real registry source that manual runs do not use.
        self.assertNotIn("erasmus-mundus", CONTROLLED_MANUAL_SOURCE_IDS)
        with _with_setting("erasmus-mundus"):
            with self.assertRaises(ManualSourceSelectionError):
                controlled_manual_sources()

    def test_a_duplicate_id_is_rejected(self):
        self._assert_rejected("daad-epos,daad-epos")

    def test_an_empty_value_is_rejected(self):
        for value in ("", "   ", ",", ",,", "daad-epos,"):
            with self.subTest(value=value):
                self._assert_rejected(value)

    def test_the_message_never_repeats_the_configured_value(self):
        secret = "daad-epos,SECRETSOURCEVALUE"
        with _with_setting(secret):
            with self.assertRaises(RuntimeError) as caught:
                controlled_manual_sources()
        self.assertNotIn("SECRETSOURCEVALUE", str(caught.exception))

    def test_the_parser_rejects_values_that_are_not_source_ids(self):
        for value in ("Daad-Epos", "daad epos", "daad/epos", "-daad", "daad--epos"):
            with self.subTest(value=value):
                with _with_setting(value):
                    with self.assertRaises(RuntimeError):
                        manual_discovery_source_ids()


class RegistryIsUnchangedTests(unittest.TestCase):
    def test_the_registry_still_holds_all_thirty_two_sources(self):
        self.assertEqual(len(SOURCES), 32)
        self.assertEqual(len({source.source_id for source in SOURCES}), 32)

    def test_the_controlled_manual_list_still_holds_fifteen_ids(self):
        self.assertEqual(len(CONTROLLED_MANUAL_SOURCE_IDS), 15)

    def test_erasmus_mundus_is_still_discovery_only(self):
        erasmus = [
            source for source in SOURCES if source.source_id == "erasmus-mundus"
        ]
        self.assertEqual(len(erasmus), 1)
        self.assertIs(erasmus[0].discovery_only, True)
        self.assertEqual(
            [source.source_id for source in SOURCES if source.discovery_only],
            ["erasmus-mundus"],
        )

    def test_the_setting_does_not_change_the_registry(self):
        before = [
            (
                source.source_id,
                source.source_url,
                source.crawl_enabled,
                source.discovery_only,
                source.trust_reviewed,
                source.trust_basis,
            )
            for source in SOURCES
        ]
        with _with_setting(",".join(FIVE_SOURCE_IDS)):
            controlled_manual_sources()
        after = [
            (
                source.source_id,
                source.source_url,
                source.crawl_enabled,
                source.discovery_only,
                source.trust_reviewed,
                source.trust_basis,
            )
            for source in SOURCES
        ]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
