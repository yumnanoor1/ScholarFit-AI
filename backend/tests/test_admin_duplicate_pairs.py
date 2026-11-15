"""Possible-duplicate pairs: scoring, derived status, and dismissal.

The Duplicates page re-derives suspected pairs from the records on every
request, so "Not a duplicate" has to be stored or the pair comes straight
back. These tests pin that, the similarity the page shows instead of
"Not scored", and the four statuses the page colours.

Run from the backend folder:  python -m unittest tests.test_admin_duplicate_pairs -v
"""
import unittest
from datetime import date, datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.opportunity import (
    Scholarship,
    ScholarshipAuditLog,
    ScholarshipDuplicateDismissal,
)
from app.models.user import User
from app.routers import admin_scholarships as admin_api
from app.routers.auth import get_current_user
from app.services.scholarship_quality import (
    dismissal_key,
    duplicate_pairs,
    name_similarity,
)


def _scholarship(name, country="Germany", **overrides):
    values = {
        "name": name,
        "country": country,
        "provider": "DAAD",
        "degree_level": "Master",
        "verification_status": "verified",
        "official_info_url": "https://www.daad.de/en/award/",
        "record_version": 1,
    }
    values.update(overrides)
    return Scholarship(**values)


class DuplicatePairScoringTests(unittest.TestCase):
    """The scoring and status rules, without a database."""

    def test_similarity_is_the_overlap_the_pairing_threshold_uses(self):
        self.assertEqual(name_similarity('Helmut Schmidt Award', 'Helmut Schmidt Award'), 1.0)
        partial = name_similarity('Helmut Schmidt Award', 'Helmut Schmidt Grant')
        self.assertGreater(partial, 0)
        self.assertLess(partial, 1)
        self.assertEqual(name_similarity('Alpha', 'Beta'), 0.0)

    def test_similarity_is_zero_when_a_name_folds_away_to_nothing(self):
        # "Scholarship" and "Master" are stop words in the folding.
        self.assertEqual(name_similarity('Scholarship', 'Masters Scholarships'), 0.0)
        self.assertEqual(name_similarity('', 'Alpha'), 0.0)
        self.assertEqual(name_similarity(None, None), 0.0)

    def test_a_pair_key_does_not_depend_on_the_order_asked_for(self):
        self.assertEqual(dismissal_key(7, 3), (3, 7))
        self.assertEqual(dismissal_key(3, 7), (3, 7))


class DuplicatePairDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        event.listen(
            self.engine, "connect",
            lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.admin = User(
            email="admin@example.com", hashed_password="x", full_name="Admin", role="admin",
        )
        # Same country and nearly the same name: a suspected pair.
        self.first = _scholarship("Helmut Schmidt Award")
        self.second = _scholarship("Helmut Schmidt Award Programme")
        # A record that must never pair with the others.
        self.unrelated = _scholarship("Chevening", country="United Kingdom", provider="FCDO")
        self.db.add_all([self.admin, self.first, self.second, self.unrelated])
        self.db.commit()

        self.app = FastAPI()
        self.app.include_router(admin_api.router)
        self.app.dependency_overrides[admin_api.get_db] = lambda: self.db
        self.app.dependency_overrides[get_current_user] = lambda: self.admin
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def pairs(self):
        response = self.client.get("/admin/scholarships/duplicates")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def pair_for(self, first_id, second_id):
        wanted = dismissal_key(first_id, second_id)
        for pair in self.pairs():
            if dismissal_key(pair["first_id"], pair["second_id"]) == wanted:
                return pair
        return None

    # --- what the list shows -------------------------------------------------

    def test_a_suspected_pair_carries_a_score_and_both_records(self):
        pair = self.pair_for(self.first.id, self.second.id)
        self.assertIsNotNone(pair, "the suspected pair should be suggested")
        self.assertEqual(pair["status"], "needs_review")
        self.assertEqual(pair["kind"], "suspected")
        self.assertGreater(pair["similarity"], 0)
        self.assertLessEqual(pair["similarity"], 1)
        self.assertTrue(pair["same_country"])
        self.assertTrue(pair["same_provider"])
        # Every field the rows render, for each side.
        for side in ("first", "second"):
            record = pair[side]
            self.assertEqual(record["country"], "Germany")
            self.assertEqual(record["degree_level"], "Master")
            self.assertEqual(record["verification_status"], "verified")
            self.assertIn("daad.de", record["source_url"])
            self.assertFalse(record["archived"])

    def test_records_in_different_countries_are_never_paired(self):
        self.assertIsNone(self.pair_for(self.first.id, self.unrelated.id))

    def test_a_flagged_pair_reports_which_record_is_the_duplicate(self):
        flagged = self.client.post(
            f"/admin/scholarships/{self.second.id}/duplicate",
            json={"duplicate_of_id": self.first.id, "note": "Same award call"},
        )
        self.assertEqual(flagged.status_code, 200, flagged.text)
        pair = self.pair_for(self.first.id, self.second.id)
        self.assertEqual(pair["status"], "flagged")
        self.assertEqual(pair["kind"], "flagged")
        self.assertEqual(pair["duplicate_id"], self.second.id)
        self.assertEqual(pair["first_id"], self.first.id)

    def test_archiving_the_duplicate_moves_the_pair_to_resolved(self):
        self.client.post(
            f"/admin/scholarships/{self.second.id}/duplicate",
            json={"duplicate_of_id": self.first.id, "note": "Same award call"},
        )
        archived = self.client.post(
            f"/admin/scholarships/{self.second.id}/archive",
            json={"reason": "Duplicate of the Helmut Schmidt Award"},
        )
        self.assertEqual(archived.status_code, 200, archived.text)
        pair = self.pair_for(self.first.id, self.second.id)
        self.assertEqual(pair["status"], "resolved")
        self.assertTrue(pair["second"]["archived"])

    def test_a_flagged_pair_is_listed_once_not_twice(self):
        self.client.post(
            f"/admin/scholarships/{self.second.id}/duplicate",
            json={"duplicate_of_id": self.first.id, "note": "Same award call"},
        )
        wanted = dismissal_key(self.first.id, self.second.id)
        matching = [
            pair for pair in self.pairs()
            if dismissal_key(pair["first_id"], pair["second_id"]) == wanted
        ]
        self.assertEqual(len(matching), 1, matching)

    # --- dismissal -----------------------------------------------------------

    def test_a_dismissed_pair_is_not_suggested_again(self):
        response = self.client.post(
            "/admin/scholarships/duplicates/dismiss",
            json={
                "first_id": self.first.id,
                "second_id": self.second.id,
                "note": "Two different intakes of the same programme",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        pair = self.pair_for(self.first.id, self.second.id)
        self.assertEqual(pair["status"], "dismissed")
        # And still dismissed on a completely fresh request.
        self.assertEqual(self.pair_for(self.first.id, self.second.id)["status"], "dismissed")

    def test_dismissing_changes_neither_record(self):
        self.client.post(
            "/admin/scholarships/duplicates/dismiss",
            json={"first_id": self.first.id, "second_id": self.second.id},
        )
        self.db.expire_all()
        for record in (self.first, self.second):
            refreshed = self.db.get(Scholarship, record.id)
            self.assertIsNone(refreshed.duplicate_of_id)
            self.assertFalse(refreshed.archived)

    def test_dismissing_records_an_audit_entry_against_both_records(self):
        self.client.post(
            "/admin/scholarships/duplicates/dismiss",
            json={"first_id": self.first.id, "second_id": self.second.id, "note": "Different awards"},
        )
        entries = (
            self.db.query(ScholarshipAuditLog)
            .filter(ScholarshipAuditLog.action == "duplicate_dismissed")
            .all()
        )
        self.assertEqual(
            sorted(entry.scholarship_id for entry in entries),
            sorted([self.first.id, self.second.id]),
        )
        for entry in entries:
            self.assertEqual(entry.note, "Different awards")
            self.assertEqual(entry.actor_email, self.admin.email)

    def test_dismissing_the_same_pair_twice_is_harmless(self):
        body = {"first_id": self.first.id, "second_id": self.second.id}
        self.assertEqual(self.client.post("/admin/scholarships/duplicates/dismiss", json=body).status_code, 200)
        self.assertEqual(self.client.post("/admin/scholarships/duplicates/dismiss", json=body).status_code, 200)
        self.assertEqual(self.db.query(ScholarshipDuplicateDismissal).count(), 1)

    def test_the_pair_order_sent_does_not_matter(self):
        self.client.post(
            "/admin/scholarships/duplicates/dismiss",
            json={"first_id": self.second.id, "second_id": self.first.id},
        )
        stored = self.db.query(ScholarshipDuplicateDismissal).one()
        self.assertLess(stored.first_id, stored.second_id)
        self.assertEqual(self.pair_for(self.first.id, self.second.id)["status"], "dismissed")

    def test_an_explicit_flag_wins_over_an_earlier_dismissal(self):
        self.client.post(
            "/admin/scholarships/duplicates/dismiss",
            json={"first_id": self.first.id, "second_id": self.second.id},
        )
        self.client.post(
            f"/admin/scholarships/{self.second.id}/duplicate",
            json={"duplicate_of_id": self.first.id, "note": "Changed my mind, same award"},
        )
        self.assertEqual(self.pair_for(self.first.id, self.second.id)["status"], "flagged")

    def test_dismissing_a_pair_refuses_bad_input(self):
        self.assertEqual(
            self.client.post(
                "/admin/scholarships/duplicates/dismiss",
                json={"first_id": self.first.id, "second_id": self.first.id},
            ).status_code,
            422,
            "a record cannot be dismissed against itself",
        )
        self.assertEqual(
            self.client.post(
                "/admin/scholarships/duplicates/dismiss",
                json={"first_id": 0, "second_id": self.second.id},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(
                "/admin/scholarships/duplicates/dismiss",
                json={"first_id": self.first.id, "second_id": 99999},
            ).status_code,
            404,
            "an unknown record is not found, not silently dismissed",
        )
        self.assertEqual(
            self.client.post(
                "/admin/scholarships/duplicates/dismiss",
                json={"first_id": self.first.id, "second_id": self.second.id, "extra": "no"},
            ).status_code,
            422,
            "unexpected fields are refused",
        )

    def test_dismissal_needs_an_admin(self):
        self.app.dependency_overrides[get_current_user] = lambda: User(
            id=99, email="student@example.com", hashed_password="x",
            full_name="Student", role="student",
        )
        for method, path, body in (
            ("post", "/admin/scholarships/duplicates/dismiss",
             {"first_id": self.first.id, "second_id": self.second.id}),
            ("get", "/admin/scholarships/duplicates", None),
        ):
            with self.subTest(path=path):
                call = getattr(self.client, method)
                response = call(path, json=body) if body is not None else call(path)
                self.assertEqual(response.status_code, 403, response.text)

    def test_dismissals_do_not_leak_between_unrelated_pairs(self):
        # Folds to the same words as self.first, so it is a suspected pair
        # at the 0.8 threshold. "Helmut Schmidt Award Fellowship" would not
        # be: 3 shared words out of 4 is 0.75.
        third = _scholarship("The Helmut Schmidt Award")
        self.db.add(third)
        self.db.commit()
        self.client.post(
            "/admin/scholarships/duplicates/dismiss",
            json={"first_id": self.first.id, "second_id": self.second.id},
        )
        self.assertEqual(self.pair_for(self.first.id, self.second.id)["status"], "dismissed")
        other = self.pair_for(self.first.id, third.id)
        self.assertIsNotNone(other)
        self.assertEqual(other["status"], "needs_review")


class DuplicatePairsUnitTests(unittest.TestCase):
    """duplicate_pairs on plain objects, so the rules are readable."""

    class Row:
        def __init__(self, id, name, country="Germany", provider="DAAD",
                     duplicate_of_id=None, archived=False):
            self.id = id
            self.name = name
            self.country = country
            self.provider = provider
            self.degree_level = "Master"
            self.official_info_url = "https://example.org/a"
            self.official_url = None
            self.verification_status = "verified"
            self.duplicate_of_id = duplicate_of_id
            self.archived = archived
            self.last_verified_date = date(2026, 10, 1)
            self.created_at = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def test_dismissed_pairs_keep_their_status_and_are_not_re_suggested(self):
        rows = [self.Row(1, "Helmut Schmidt Award"), self.Row(2, "Helmut Schmidt Award Programme")]
        plain = duplicate_pairs(rows)
        self.assertEqual([pair["status"] for pair in plain], ["needs_review"])
        dismissed = duplicate_pairs(rows, dismissed={(2, 1)})
        self.assertEqual([pair["status"] for pair in dismissed], ["dismissed"])

    def test_the_default_call_still_works_for_the_records_listing(self):
        # _rows_with_issues calls duplicate_pairs(rows) with no dismissals.
        rows = [self.Row(1, "Alpha Award"), self.Row(2, "Alpha Award Programme")]
        self.assertEqual(len(duplicate_pairs(rows)), 1)

    def test_an_archived_duplicate_reads_as_resolved(self):
        rows = [
            self.Row(1, "Alpha Award"),
            self.Row(2, "Alpha Award", duplicate_of_id=1, archived=True),
        ]
        self.assertEqual(duplicate_pairs(rows)[0]["status"], "resolved")

    def test_a_duplicate_pointing_at_a_missing_record_is_ignored(self):
        rows = [self.Row(2, "Alpha Award", duplicate_of_id=404)]
        self.assertEqual(duplicate_pairs(rows), [])


if __name__ == "__main__":
    unittest.main()
