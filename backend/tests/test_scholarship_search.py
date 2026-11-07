"""
Scholarship search and filters. Uses in-memory SQLite.
Run from the backend folder:  python -m unittest discover -s tests -v
"""
import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.opportunity import Scholarship
from app.models.user import StudentProfile, User
from app.routers import scholarships as api
from app.core.security import issue_session_token
from app.routers.auth import get_optional_user
from app.schemas.search import ScholarshipFilterOptions, ScholarshipSearchResult
from app.services.scholarship_search import filter_options, match_search, search_scholarships, search_terms, short_country
from test_scholarship_eligibility import TODAY, make_scholarship
from test_scholarship_recommendations import CLEAR

FIELDS = {key: value for key, value in vars(make_scholarship(**CLEAR)).items() if key != "id"}


def add(session, **overrides):
    row = Scholarship(**{**FIELDS, **overrides})
    session.add(row)
    return row


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=cls.engine)
        db = sessionmaker(bind=cls.engine)()
        cls.db = db
        cls.german = add(db, name="Alpha Stipend", provider="DAAD Agency", country="Germany", last_verified_date=date(2026, 9, 1),
                         eligible_disciplines=["Engineering"], discipline_scope="listed", nationality_scope="all", eligible_fields="Engineering only",
                         pakistan_eligible="Yes", accommodation_status="covered", travel_status="covered",
                         institution_scope="national")
        cls.partial = add(db, name="Beta Grant", provider="Lund University", country="Sweden", last_verified_date=date(2026, 10, 1),
                          funding_level="partial", tuition_coverage_type="fixed_amount", tuition_amount=5000, tuition_currency="EUR",
                          stipend_status="none", accommodation_status="not_specified", eligible_nationalities="Citizens of Kenya only",
                          nationality_scope="listed", eligible_countries=["Kenya"], pakistan_eligible="", min_academic_requirement="Minimum CGPA 3.0/4.0",
                          application_deadline_date=date(2026, 12, 1), deadline="1 December 2026")
        cls.pakistan = add(db, name="Gamma Award", provider="Berlin Fund", country="Germany", eligible_countries=["Pakistan"], nationality_scope="listed",
                           pakistan_eligible="Yes - listed", funding_level="not_specified", deadline_type="annual", application_deadline_date=None,
                           deadline="Typically in March", last_verified_date=date(2026, 7, 1), eligible_nationalities="Citizens of Pakistan")
        cls.closed = add(db, name="Delta Türkiye Bursu", provider="Ankara Office", country="Turkey", application_deadline_date=date(2020, 1, 1),
                         deadline="1 January 2020", last_verified_date=date(2026, 8, 1))
        cls.hidden = add(db, name="Epsilon Hidden", provider="Unknown", country="Germany", verification_status="unverified")
        cls.conflict = add(db, name="Zeta Conflict", provider="Paris House", country="European Union (multi-country, incl. France)",
                           min_academic_requirement="Minimum CGPA 3.5/4.0", eligible_degree_levels=["Master's (Research)"],
                           last_verified_date=date(2026, 8, 1))
        cls.original = add(db, name="Eta Original", provider="Rome", country="Italy", last_verified_date=date(2026, 8, 1))
        cls.copy = add(db, name="Eta Copy", provider="Rome", country="Italy", last_verified_date=date(2026, 8, 1))
        cls.alice = User(email="alice@example.com", hashed_password="x", full_name="Alice")
        cls.bob = User(email="bob@example.com", hashed_password="x", full_name="Bob")
        cls.carol = User(email="carol@example.com", hashed_password="x", full_name="Carol")
        db.add_all([cls.alice, cls.bob, cls.carol])
        db.flush()
        cls.copy.duplicate_of_id = cls.original.id
        cls.alice_profile = StudentProfile(user_id=cls.alice.id, nationality="Pakistan", degree_level="Bachelor's", cgpa=3.4, cgpa_scale=4.0,
                                           ielts_score=7.0, field_of_study="Computer Science", preferred_fields=["Engineering"],
                                           date_of_birth=date(2001, 5, 1))
        cls.bob_profile = StudentProfile(user_id=cls.bob.id, nationality="Pakistan", degree_level="Bachelor's", cgpa=3.4, cgpa_scale=4.0,
                                         ielts_score=5.0, field_of_study="Computer Science")
        db.add_all([cls.alice_profile, cls.bob_profile])
        db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def search(self, profile=None, signed_in=False, sort=None, skip=0, limit=20, **filters):
        result = search_scholarships(self.db, filters, profile, signed_in, sort=sort, skip=skip, limit=limit, today=TODAY)
        return ScholarshipSearchResult.model_validate(result).model_dump()

    def names(self, **options):
        return [item["scholarship"]["name"] for item in self.search(**options)["items"]]

    # ---- Search ----

    def test_case_and_spaces_dont_matter(self):
        self.assertEqual(self.names(q="  aLPHA    stipend "), ["Alpha Stipend"])

    def test_word_start_partial(self):
        self.assertEqual(self.names(q="stip"), ["Alpha Stipend"])

    def test_inside_a_word_isnt_a_match(self):
        self.assertEqual(self.names(q="ipend"), [])

    def test_empty_search_returns_everything_visible(self):
        self.assertEqual(self.search(q="   ")["total"], self.search()["total"])
        self.assertEqual(search_terms(None), [])

    def test_accents_are_ignored(self):
        self.assertEqual(self.names(q="turkiye"), ["Delta Türkiye Bursu"])

    def test_search_fields(self):
        for query, expected in (("beta", "Beta Grant"), ("Lund", "Beta Grant"), ("sweden", "Beta Grant"), ("Engineering", "Alpha Stipend")):
            self.assertIn(expected, self.names(q=query), query)

    def test_every_word_must_match(self):
        self.assertEqual(self.names(q="alpha sweden"), [])

    def test_reports_where_it_was_found(self):
        german = self.search(q="germany")["items"]
        self.assertTrue(all("Host country" in item["matched_fields"] for item in german))
        kenya = self.search(q="kenya", verification=["verified"])["items"]
        self.assertIn("Eligible nationalities", kenya[0]["matched_fields"])
        self.assertNotIn("Host country", kenya[0]["matched_fields"])

    def test_structured_hits_come_first(self):
        record = make_scholarship(**{**CLEAR, "host_institution": None, "eligible_disciplines": ["Law"], "eligible_fields": "Law", "name": "X", "provider": "Y", "country": "Z",
                                     "eligible_countries": None, "study_type": None})
        self.assertEqual(match_search(record, ["law"]), (["Disciplines"], True))
        record.eligible_disciplines = None
        self.assertEqual(match_search(record, ["law"]), (["Disciplines"], False))

    def test_a_stated_exclusion_isnt_a_match(self):
        record = make_scholarship(**{**CLEAR, "host_institution": None, "eligible_countries": None, "eligible_fields": None, "name": "X", "provider": "Y",
                                     "country": "Z", "study_type": "Full-time Master's at Radboud (Erasmus Mundus programmes excluded)"})
        self.assertIsNone(match_search(record, ["erasmus"])[0])
        self.assertEqual(match_search(record, ["radboud"])[0], ["Description"])

    def test_regular_expression_characters_are_safe(self):
        self.assertEqual(self.names(q="(.*"), [])

    # ---- Filters ----

    def test_host_country_ignores_nationality(self):
        self.assertEqual(sorted(self.names(host_country=["Germany"])), ["Alpha Stipend", "Gamma Award"])
        self.assertEqual(self.names(host_country=["Pakistan"]), [])

    def test_host_country_groups_long_names(self):
        self.assertEqual(self.names(host_country=["European Union"]), ["Zeta Conflict"])
        self.assertEqual(short_country("European Union (multi-country, incl. France)"), "European Union")

    def test_nationality_ignores_host_country(self):
        result = self.names(nationality="Kenya")
        self.assertIn("Beta Grant", result)
        self.assertNotIn("Gamma Award", result)   # listed for Pakistan only
        self.assertNotIn("Beta Grant", self.names(nationality="Pakistan"))
        self.assertIn("Gamma Award", self.names(nationality="pakistan"))

    def test_nationality_status_is_reported(self):
        items = self.search(nationality="Kenya")["items"]
        self.assertEqual(next(item for item in items if item["scholarship"]["name"] == "Beta Grant")["nationality_status"], "satisfied")

    def test_degree(self):
        self.assertEqual(self.names(degree=["Master's (Research)"]), ["Zeta Conflict"])

    def test_discipline(self):
        self.assertIn("Alpha Stipend", self.names(discipline=["Engineering"]))
        self.assertIn("Beta Grant", self.names(discipline=["Engineering"]))     # open to all fields
        self.assertNotIn("Alpha Stipend", self.names(discipline=["Law"]))
        self.assertNotIn("Alpha Stipend", self.names(discipline=["all_fields"]))

    def test_funding_tier(self):
        self.assertEqual(self.names(funding=["partially_funded"]), ["Beta Grant"])
        self.assertEqual(self.names(funding=["incomplete"]), ["Gamma Award"])

    def test_every_benefit_must_be_offered(self):
        self.assertEqual(self.names(benefit=["travel", "accommodation"]), ["Alpha Stipend"])
        self.assertNotIn("Beta Grant", self.names(benefit=["stipend"]))

    def test_deadline(self):
        self.assertEqual(self.names(deadline=["closed"]), ["Delta Türkiye Bursu"])
        self.assertEqual(self.names(deadline=["unknown"]), ["Gamma Award"])
        self.assertEqual(self.names(deadline=["upcoming", "rolling"]), [])

    def test_unverified_needs_asking_for(self):
        self.assertNotIn("Epsilon Hidden", self.names())
        self.assertEqual(self.names(verification=["unverified"]), ["Epsilon Hidden"])

    def test_conflicting(self):
        self.assertEqual(self.names(verification=["conflicting"]), ["Zeta Conflict"])
        self.assertTrue(self.search(verification=["conflicting"])["items"][0]["has_conflict"])

    def test_duplicate_shows_once(self):
        self.assertEqual(self.names(q="Eta"), ["Eta Original"])

    def test_combined_filters(self):
        result = self.names(q="alpha", host_country=["Germany"], degree=["Master's"], funding=["fully_funded"], deadline=["open", "upcoming"])
        self.assertEqual(result, ["Alpha Stipend"])
        self.assertEqual(self.names(q="alpha", host_country=["Sweden"]), [])

    def test_empty_results(self):
        result = self.search(q="zzzz")
        self.assertEqual((result["total"], result["items"]), (0, []))

    def test_empty_catalogue_returns_no_records(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        empty_db = sessionmaker(bind=engine)()
        try:
            result = search_scholarships(empty_db, {}, None, False, today=TODAY)
            self.assertEqual((result["total"], result["items"]), (0, []))
            self.assertEqual(filter_options(empty_db, today=TODAY)["verification"], [])
        finally:
            empty_db.close()
            engine.dispose()

    def test_stale_record_is_not_in_verified_search(self):
        stale = add(self.db, name="Stale Award", last_verified_date=date(2026, 1, 1))
        self.db.add(stale)
        self.db.flush()
        try:
            self.assertNotIn("Stale Award", self.names())
            self.assertIn("Stale Award", self.names(verification=["unverified"]))
        finally:
            self.db.delete(stale)
            self.db.commit()

    # ---- Eligibility and isolation ----

    def test_eligibility_filter(self):
        rows = self.search(profile=self.alice_profile, signed_in=True, eligibility=["eligible"])["items"]
        self.assertIn("Eta Original", [item["scholarship"]["name"] for item in rows])
        self.assertTrue(all(item["eligibility"]["outcome"] == "eligible" for item in rows))

    def test_different_students_get_their_own_results(self):
        alice = self.search(profile=self.alice_profile, signed_in=True, eligibility=["not_eligible"])["items"]
        bob = self.search(profile=self.bob_profile, signed_in=True, eligibility=["not_eligible"])["items"]
        self.assertGreater(len(bob), len(alice))

    def test_incomplete_profile_is_stated(self):
        result = self.search(profile=None, signed_in=True)
        self.assertTrue(result["profile_incomplete"])
        self.assertIn("nationality", [gap["field"] for gap in result["profile_gaps"]])
        self.assertFalse(self.search(profile=self.alice_profile, signed_in=True)["profile_incomplete"])

    def test_visitors_get_no_personal_results(self):
        item = self.search()["items"][0]
        self.assertIsNone(item["eligibility"])
        self.assertIsNone(item["score"])
        self.assertEqual(item["exclusions"], [])

    def route(self, user=None, **options):
        defaults = dict(q=None, host_country=[], nationality=None, nationality_scope=[], degree=[], discipline=[], academic_condition=[],
                        funding=[], benefit=[], deadline=[], verification=[], eligibility=[], sort=None, skip=0, limit=20)
        return api.search(**{**defaults, **options}, db=self.db, current_user=user)

    def test_route_uses_the_token_user(self):
        names = lambda user: [item["scholarship"].name for item in self.route(user, eligibility=["eligible"])["items"]]  # noqa: E731
        # These fixtures only hold what eligibility reads. test_profile_access covers the completion rule
        finished = SimpleNamespace(required=True, complete=True, missing=[])
        with mock.patch.object(api, "profile_completion", return_value=finished):
            self.assertIn("Eta Original", names(self.alice))
            self.assertNotIn("Eta Original", names(self.bob))

    def test_route_has_no_user_parameter(self):
        route = next(item for item in api.router.routes if item.path == "/scholarships/search")
        self.assertNotIn("user_id", [item.name for item in route.dependant.query_params])

    def test_personal_filters_need_a_login(self):
        for options in (dict(eligibility=["eligible"]), dict(sort="recommendation")):
            with self.assertRaises(HTTPException) as error:
                self.route(None, **options)
            self.assertEqual(error.exception.status_code, 401)

    def test_route_has_no_program_search_controls(self):
        route = next(item for item in api.router.routes if item.path == "/scholarships/search")
        query_names = [item.name for item in route.dependant.query_params]
        self.assertNotIn("program_id", query_names)
        self.assertNotIn("match", query_names)

    def test_optional_user(self):
        self.assertIsNone(get_optional_user(None, self.db))
        self.assertEqual(get_optional_user(issue_session_token(self.alice), self.db).id, self.alice.id)
        with self.assertRaises(HTTPException) as error:
            get_optional_user("not-a-real-token", self.db)
        self.assertEqual(error.exception.status_code, 401)

    # ---- Sorting ----

    def visible(self, sort, **options):
        return self.names(sort=sort, profile=self.alice_profile, signed_in=True, **options)

    def test_sort_by_name(self):
        names = self.visible("name")
        self.assertEqual(names, sorted(names))

    def test_sort_by_deadline(self):
        names = self.visible("deadline")
        self.assertEqual(names[0], "Beta Grant")             # the earliest date still ahead
        self.assertEqual(names[-1], "Gamma Award")           # no exact date goes last
        self.assertLess(names.index("Alpha Stipend"), names.index("Delta Türkiye Bursu"))   # past dates follow future ones

    def test_sort_by_funding(self):
        names = self.visible("funding")
        self.assertEqual(names[-1], "Gamma Award")
        self.assertEqual(names[-2], "Beta Grant")

    def test_sort_by_country(self):
        rows = self.search(sort="country")["items"]
        countries = [short_country(item["scholarship"]["country"]) for item in rows]
        self.assertEqual(countries, sorted(countries))

    def test_sort_by_verified(self):
        names = self.visible("verified")
        self.assertEqual(names[0], "Beta Grant")
        self.assertEqual(names[:3], ["Beta Grant", "Alpha Stipend", "Delta Türkiye Bursu"])   # newest verified review first

    def test_sort_by_verified_does_not_promote_unverified_dates(self):
        names = self.names(sort="verified", verification=["verified", "unverified"])
        self.assertGreater(names.index("Epsilon Hidden"), names.index("Delta Türkiye Bursu"))

    def test_sort_by_score_puts_excluded_last(self):
        rows = self.search(profile=self.alice_profile, signed_in=True, sort="recommendation")["items"]
        scores = [item["score"] for item in rows]
        known = [score for score in scores if score is not None]
        self.assertEqual(known, sorted(known, reverse=True))
        self.assertEqual(scores[:len(known)], known)

    def test_sort_applies_after_filters(self):
        self.assertEqual(self.names(sort="name", host_country=["Germany"]), ["Alpha Stipend", "Gamma Award"])

    def test_default_sort(self):
        self.assertEqual(self.search()["sort"], "name")
        self.assertEqual(self.search(q="alpha")["sort"], "relevance")
        self.assertEqual(self.search(profile=self.alice_profile, signed_in=True)["sort"], "recommendation")

    # ---- Pagination ----

    def test_pages_cover_every_result_once(self):
        total = self.search(sort="name")["total"]
        seen = [name for start in range(0, total, 2) for name in self.names(sort="name", skip=start, limit=2)]
        self.assertEqual(len(seen), total)
        self.assertEqual(len(set(seen)), total)

    def test_total_ignores_the_page(self):
        result = self.search(limit=1)
        self.assertEqual(len(result["items"]), 1)
        self.assertGreater(result["total"], 1)

    def test_past_the_end(self):
        self.assertEqual(self.search(skip=500)["items"], [])

    # ---- Efficiency and options ----

    def test_query_count_doesnt_grow_with_results(self):
        statements = []
        listener = lambda conn, cursor, statement, *rest: statements.append(statement)  # noqa: E731
        event.listen(self.engine, "before_cursor_execute", listener)
        try:
            self.search(profile=self.alice_profile, signed_in=True, sort="name")
        finally:
            event.remove(self.engine, "before_cursor_execute", listener)
        self.assertLessEqual(len(statements), 3, statements)

    def test_options_only_offer_what_exists(self):
        options = ScholarshipFilterOptions.model_validate(filter_options(self.db, today=TODAY)).model_dump()
        self.assertIn("European Union", [item["value"] for item in options["host_countries"]])
        self.assertIn("all_fields", [item["value"] for item in options["disciplines"]])
        self.assertNotIn("Veterinary Science", [item["value"] for item in options["disciplines"]])
        self.assertNotIn("rolling", [item["value"] for item in options["deadlines"]])
        self.assertTrue(all(item["count"] > 0 for item in options["funding"]))
        self.assertNotIn("programs", options)

    def test_old_listing_is_unchanged(self):
        rows = api.list_scholarships(country=None, funding_type=None, degree_level=None, pakistan_eligible_only=False,
                                     include_unverified=False, search=None, skip=0, limit=100, db=self.db)
        self.assertEqual(len(rows), self.db.query(Scholarship).filter(Scholarship.verification_status == "verified").count())


if __name__ == "__main__":
    unittest.main()
