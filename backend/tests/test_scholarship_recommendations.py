"""
Scholarship recommendation scoring. Service tests need no database; API tests use in-memory SQLite.
Run from the backend folder:  python -m unittest discover -s tests -v
"""
import unittest
from datetime import date
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.opportunity import Program, Scholarship, ScholarshipProgramLink, University
from app.models.user import StudentProfile, User
from app.routers import recommendations as api
from app.routers.auth import get_current_user
from app.schemas.recommendation import RecommendationList, ScholarshipRecommendation
from app.services import scholarship_recommendations as engine
from app.services.scholarship_recommendations import funding_summary, recommend_scholarship
from test_scholarship_eligibility import TODAY, make_profile, make_scholarship

CLEAR = dict(
    structured_data_version=1, nationality_scope="all", eligible_degree_levels=["Master's"], required_previous_degree="Bachelor's",
    discipline_scope="all", eligible_disciplines=None, academic_condition="numeric", min_gpa=3.0, min_gpa_scale=4.0,
    min_academic_requirement="Minimum CGPA 3.0/4.0", english_requirement_type="test_required", min_ielts=6.5,
    deadline_type="fixed", application_deadline_date=date(2027, 1, 15), verification_basis="official_source",
    funding_level="full", tuition_coverage_type="full", tuition_percent_min=None, tuition_percent_max=None, tuition_amount=None,
    tuition_currency=None, stipend_status="provided", stipend_amount=1000.0, stipend_currency="EUR", stipend_period="monthly",
    stipend_is_approximate=False, accommodation_status="covered", health_insurance_status="not_specified", travel_status="not_specified",
    funding_duration_months=24, costs_not_covered=None, institution_scope="national", host_institution=None, host_university_id=None,
    duplicate_of_id=None,
)


def record(**overrides):
    return make_scholarship(**{**CLEAR, **overrides})


def program(**overrides):
    data = dict(id=7, name="MSc Computer Science", university_id=3, degree_level="Master", field_of_study="Computer Science",
                university=SimpleNamespace(name="TU Example", country="Germany"))
    return SimpleNamespace(**{**data, **overrides})


def link(outcome):
    return SimpleNamespace(outcome=outcome, relationship_type="unconfirmed", evidence="Evidence", source_url="https://example.org",
                           verification_status="verified" if outcome == "confirmed" else "unverified", last_verified=None, notes=None)


def recommend(scholarship=None, profile=None, selected=None, stored=None):
    return recommend_scholarship(scholarship or record(), profile or make_profile(), selected, stored, today=TODAY)


class ModelTests(unittest.TestCase):
    def test_weights_add_up_to_100(self):
        self.assertEqual(sum(engine.WEIGHTS.values()), 100)

    def test_breakdown_adds_up_to_the_score(self):
        for selected, stored in ((None, None), (program(), link("confirmed"))):
            result = recommend(selected=selected, stored=stored)
            self.assertAlmostEqual(sum(item["points"] for item in result["breakdown"]), result["score"], delta=1)
            self.assertTrue(0 <= result["score"] <= 100)

    def test_best_case_scores_100(self):
        result = recommend(selected=program(), stored=link("confirmed"))
        self.assertEqual(result["score"], 100)
        self.assertEqual((result["category"], result["category_label"]), ("strong", "Strong Match"))

    def test_identical_inputs_give_identical_results(self):
        self.assertEqual(recommend(), recommend())

    def test_each_requirement_counts_once(self):
        manual = record(applicant_restrictions=["fee_paying_only"])
        with_grade = evaluate_values(manual, make_profile())
        without_grade = evaluate_values(manual, make_profile(cgpa=None))
        self.assertEqual(with_grade["eligibility"], without_grade["eligibility"])  # grades belong to the academic dimension
        self.assertLess(without_grade["academic"], with_grade["academic"])

    def test_program_weight_is_left_out_without_a_program(self):
        result = recommend()
        self.assertNotIn("program", [item["dimension"] for item in result["breakdown"]])
        self.assertIsNone(result["program_match"])
        self.assertTrue(any("hasn't been evaluated" in item for item in result["warnings"]))


def evaluate_values(scholarship, profile):
    result = engine.evaluate_scholarship(scholarship, profile, today=TODAY)
    return {"eligibility": engine._eligibility_value(result), "academic": engine._academic_value(result)}


class EligibilityTests(unittest.TestCase):
    def test_not_eligible_is_excluded_with_no_score(self):
        result = recommend(profile=make_profile(ielts_score=5.0))
        self.assertFalse(result["recommended"])
        self.assertIsNone(result["score"])
        self.assertIsNone(result["category"])
        self.assertEqual(result["exclusions"][0]["rule"], "not_eligible")
        self.assertIn("IELTS", result["negative"][0])

    def test_verify_manually_is_visible_and_penalized(self):
        eligible = recommend()
        manual = recommend(record(applicant_restrictions=["second_masters_excluded"]))
        self.assertTrue(manual["recommended"])
        self.assertLess(manual["score"], eligible["score"])
        self.assertEqual(manual["eligibility"]["outcome"], "verify_manually")
        self.assertNotIn(manual["category"], ("strong", "good"))
        self.assertTrue(any("second Master's" in item for item in manual["warnings"]))

    def test_high_score_cant_lift_verify_manually(self):
        result = recommend(record(applicant_restrictions=["fee_paying_only"]), selected=program(), stored=link("confirmed"))
        self.assertEqual(result["category"], "possible")

    def test_missing_profile_data_earns_less(self):
        full = recommend()
        missing = recommend(profile=make_profile(cgpa=None))
        self.assertLess(missing["score"], full["score"])
        self.assertEqual(missing["category"], "needs_verification")
        self.assertTrue(any(item.startswith("Add to your profile") for item in missing["warnings"]))

    def test_no_profile_at_all(self):
        result = recommend_scholarship(record(), None, today=TODAY)
        self.assertEqual(result["eligibility"]["status"], "missing_information")
        self.assertEqual(result["category"], "needs_verification")

    def test_unverified_record_is_always_needs_verification(self):
        result = recommend(record(verification_status="unverified", verification_basis="not_verified"), selected=program(), stored=link("confirmed"))
        self.assertEqual(result["category"], "needs_verification")
        self.assertTrue(any("not verified" in item for item in result["warnings"]))


class ProgramTests(unittest.TestCase):
    def test_confirmed_beats_potential(self):
        confirmed = recommend(selected=program(), stored=link("confirmed"))
        potential = recommend(selected=program(), stored=link("potential"))
        self.assertGreater(confirmed["score"], potential["score"])
        self.assertEqual(potential["program_match"]["label"], "Potential Match")
        self.assertNotEqual(potential["category"], "strong")
        self.assertTrue(any(item.startswith("Only a potential match") for item in potential["warnings"]))

    def test_needs_verification_is_conservative(self):
        result = recommend(record(institution_scope="participating_list"), selected=program())
        self.assertEqual(result["program_match"]["outcome"], "needs_verification")
        self.assertEqual(result["category"], "needs_verification")
        self.assertTrue(any(item.startswith("Check that this supports") for item in result["warnings"]))

    def test_not_a_match_is_excluded(self):
        result = recommend(record(country="Turkey"), selected=program())
        self.assertFalse(result["recommended"])
        self.assertIsNone(result["score"])
        self.assertEqual(result["exclusions"][0]["rule"], "not_a_match")

    def test_same_country_alone_is_never_confirmed(self):
        self.assertEqual(recommend(selected=program())["program_match"]["outcome"], "potential")


class AcademicTests(unittest.TestCase):
    def test_met_minimum(self):
        self.assertEqual(evaluate_values(record(), make_profile())["academic"], 1)

    def test_other_grading_scale_isnt_converted(self):
        scale = record(min_gpa=5.0, min_gpa_scale=7.0, min_academic_requirement="GPA of at least 5.0/7.0")
        self.assertLess(evaluate_values(scale, make_profile())["academic"], 1)
        result = recommend(scale, make_profile(cgpa=1.0))
        self.assertTrue(result["recommended"])  # 1.0/4 isn't compared with 5/7, so it isn't a failure either
        self.assertEqual(result["eligibility"]["outcome"], "verify_manually")

    def test_same_scale_shortfall_excludes(self):
        self.assertFalse(recommend(profile=make_profile(cgpa=2.5))["recommended"])

    def test_missing_cgpa_earns_nothing_for_that_requirement(self):
        self.assertLess(evaluate_values(record(), make_profile(cgpa=None))["academic"], evaluate_values(record(), make_profile())["academic"])


class FundingTests(unittest.TestCase):
    def tier(self, **overrides):
        return funding_summary(record(**overrides))["tier"]

    def test_tiers(self):
        self.assertEqual(self.tier(), "fully_funded")
        self.assertEqual(self.tier(funding_level="mixed"), "substantially_funded")
        self.assertEqual(self.tier(funding_level="partial", stipend_status="conditional"), "substantially_funded")
        self.assertEqual(self.tier(funding_level="tuition_only", stipend_status="none"), "tuition_only")
        self.assertEqual(self.tier(funding_level="partial", tuition_coverage_type="fixed_amount", tuition_amount=5000, stipend_status="none"), "partially_funded")
        self.assertEqual(self.tier(funding_level="not_specified"), "incomplete")
        self.assertEqual(self.tier(funding_level=None), "incomplete")

    def test_secondary_evidence_isnt_called_fully_funded(self):
        self.assertEqual(self.tier(verification_basis="mixed_sources"), "substantially_funded")

    def test_full_funding_ranks_above_partial(self):
        partial = recommend(record(funding_level="partial", tuition_coverage_type="fixed_amount", tuition_amount=5000, stipend_status="none"))
        self.assertGreater(recommend()["score"], partial["score"])

    def test_missing_amount_is_a_warning_and_earns_less(self):
        result = recommend(record(stipend_amount=None))
        self.assertFalse(result["funding"]["amount_confirmed"])
        self.assertIn("amount not confirmed", result["funding"]["summary"])
        self.assertTrue(any("funding amount isn't confirmed" in item for item in result["warnings"]))
        self.assertLess(result["score"], recommend()["score"])

    def test_no_amount_is_invented(self):
        summary = funding_summary(record(stipend_amount=None, stipend_currency=None))["summary"]
        self.assertNotRegex(summary, r"\d")

    def test_uncovered_costs_are_named(self):
        self.assertTrue(any("living costs" in item for item in recommend(record(costs_not_covered=["living_costs"]))["warnings"]))


class DeadlineTests(unittest.TestCase):
    def test_closed_is_excluded_but_stays_eligible(self):
        result = recommend(record(application_deadline_date=date(2026, 2, 20), deadline="20 February 2026"))
        self.assertFalse(result["recommended"])
        self.assertEqual(result["exclusions"][0]["rule"], "closed")
        self.assertEqual(result["eligibility"]["status"], "eligible")

    def test_upcoming(self):
        result = recommend(record(application_open_date=date(2026, 11, 20)))
        self.assertEqual(result["deadline"]["status"], "upcoming")
        self.assertTrue(any("2026-11-20" in item for item in result["positive"]))
        self.assertLess(result["score"], recommend()["score"])

    def test_unknown_is_labelled_with_no_date(self):
        result = recommend(record(deadline_type="annual", application_deadline_date=None, deadline="Typically 1 February"))
        self.assertIsNone(result["deadline"]["date"])
        self.assertTrue(any("No exact deadline" in item for item in result["warnings"]))


class EvidenceTests(unittest.TestCase):
    def test_conflict_stops_a_good_category(self):
        result = recommend(record(min_academic_requirement="Minimum CGPA 3.5/4.0"))
        self.assertEqual(result["category"], "needs_verification")

    def test_weaker_source_scores_lower(self):
        self.assertLess(recommend(record(verification_basis="secondary_only"))["score"], recommend()["score"])

    def test_explanations_use_the_record(self):
        result = recommend(record(stipend_amount=1234))
        self.assertTrue(any("EUR 1,234 per month" in item for item in result["positive"]))
        self.assertTrue(any("IELTS 7" in item for item in result["positive"]))


class ApiTests(unittest.TestCase):
    def setUp(self):
        db_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=db_engine)
        self.db = sessionmaker(bind=db_engine)()
        fields = {key: value for key, value in vars(record(duration="2 years")).items() if key != "id"}
        self.university = University(name="TU Example", country="Germany")
        self.db.add(self.university)
        self.db.flush()
        self.program = Program(name="MSc", university_id=self.university.id, degree_level="Master", field_of_study="Computer Science",
                               duration_months=24, tuition_amount=10000, tuition_currency="EUR")
        self.first = Scholarship(**{**fields, "name": "Full"})
        self.partial = Scholarship(**{**fields, "name": "Partial", "funding_level": "partial", "tuition_coverage_type": "fixed_amount",
                                      "tuition_amount": 5000, "tuition_currency": "EUR", "stipend_status": "none"})
        self.original = Scholarship(**{**fields, "name": "Original", "funding_level": "tuition_only"})
        self.copy = Scholarship(**{**fields, "name": "Copy"})
        self.hidden = Scholarship(**{**fields, "name": "Hidden", "verification_status": "unverified"})
        self.closed = Scholarship(**{**fields, "name": "Closed", "application_deadline_date": date(2020, 1, 1), "deadline": "1 January 2020"})
        self.turkey = Scholarship(**{**fields, "name": "Elsewhere", "country": "Turkey"})
        self.alice = User(email="alice@example.com", hashed_password="x", full_name="Alice")
        self.bob = User(email="bob@example.com", hashed_password="x", full_name="Bob")
        self.carol = User(email="carol@example.com", hashed_password="x", full_name="Carol")  # no profile
        self.db.add_all([self.program, self.first, self.partial, self.original, self.copy, self.hidden, self.closed, self.turkey,
                         self.alice, self.bob, self.carol])
        self.db.flush()
        self.copy.duplicate_of_id = self.original.id
        self.db.add_all([
            StudentProfile(user_id=self.alice.id, nationality="Pakistan", degree_level="Bachelor's", cgpa=3.4, cgpa_scale=4.0,
                           ielts_score=7.0, field_of_study="Computer Science", date_of_birth=date(2001, 5, 1)),
            StudentProfile(user_id=self.bob.id, nationality="Pakistan", degree_level="Bachelor's", cgpa=3.4, cgpa_scale=4.0,
                           ielts_score=5.0, field_of_study="Computer Science"),
            ScholarshipProgramLink(scholarship_id=self.first.id, program_id=self.program.id, outcome="confirmed",
                                   relationship_type="named_program", evidence="Evidence", source_url="https://example.org",
                                   verification_status="verified", last_verified=date(2026, 10, 31)),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def listing(self, user, program_id=None, include_unverified=False):
        result = api.scholarship_recommendations(program_id=program_id, include_unverified=include_unverified, db=self.db, current_user=user)
        return RecommendationList.model_validate(result).model_dump()

    def names(self, rows):
        return [item["scholarship_name"] for item in rows]

    def test_ranking_order(self):
        rows = self.listing(self.alice)["recommendations"]
        self.assertEqual(self.names(rows), ["Elsewhere", "Full", "Original", "Partial"])  # equal scores sort by name
        self.assertEqual([item["rank"] for item in rows], [1, 2, 3, 4])
        self.assertEqual(sorted(rows, key=lambda item: -item["score"]), rows)

    def test_duplicate_appears_once(self):
        result = self.listing(self.alice)
        self.assertNotIn("Copy", self.names(result["recommendations"] + result["excluded"]))

    def test_hidden_records_need_the_flag(self):
        self.assertNotIn("Hidden", self.names(self.listing(self.alice)["recommendations"]))
        rows = self.listing(self.alice, include_unverified=True)["recommendations"]
        self.assertEqual(next(item for item in rows if item["scholarship_name"] == "Hidden")["category"], "needs_verification")

    def test_closed_is_listed_apart(self):
        result = self.listing(self.alice)
        self.assertIn("Closed", self.names(result["excluded"]))
        self.assertNotIn("Closed", self.names(result["recommendations"]))

    def test_program_excludes_non_matches(self):
        result = self.listing(self.alice, self.program.id)
        self.assertEqual(result["program"]["id"], self.program.id)
        self.assertEqual(result["recommendations"][0]["scholarship_name"], "Full")
        self.assertEqual(result["recommendations"][0]["program_match"]["outcome"], "confirmed")
        self.assertIn("Elsewhere", self.names(result["excluded"]))

    def test_financial_amounts_come_with_a_program(self):
        rows = self.listing(self.alice, self.program.id)["recommendations"]
        self.assertGreater(rows[0]["funding"]["for_program"]["confirmed_funding"], 0)
        potential = next(item for item in rows if item["scholarship_name"] == "Original")
        self.assertIsNone(potential["program_match"]["relationship_verification_status"])

    def test_different_students_get_different_results(self):
        alice = self.listing(self.alice)
        bob = self.listing(self.bob)
        self.assertEqual(len(bob["recommendations"]), 0)   # Bob's IELTS is below every minimum here
        self.assertGreater(len(alice["recommendations"]), 0)

    def test_student_comes_from_the_token_only(self):
        for route in api.router.routes:
            self.assertNotIn("user_id", [item.name for item in route.dependant.query_params])
            self.assertIn(get_current_user, [item.call for item in route.dependant.dependencies])

    def test_invalid_token(self):
        with self.assertRaises(HTTPException) as error:
            get_current_user(token="not-a-real-token", db=self.db)
        self.assertEqual(error.exception.status_code, 401)

    def test_unknown_program(self):
        with self.assertRaises(HTTPException) as error:
            self.listing(self.alice, 99999)
        self.assertEqual((error.exception.status_code, error.exception.detail), (404, "Program not found"))

    def test_unknown_scholarship(self):
        with self.assertRaises(HTTPException) as error:
            api.scholarship_recommendation(99999, program_id=None, db=self.db, current_user=self.alice)
        self.assertEqual(error.exception.status_code, 404)

    def test_no_profile_is_handled(self):
        result = self.listing(self.carol)
        self.assertFalse(result["profile_complete"])
        self.assertEqual(result["summary"]["eligible"], 0)
        self.assertIn("nationality", [gap["field"] for gap in result["profile_gaps"]])

    def test_one_scholarship_matches_the_list(self):
        one = api.scholarship_recommendation(self.first.id, program_id=None, db=self.db, current_user=self.alice)
        ScholarshipRecommendation.model_validate(one)
        listed = self.listing(self.alice)["recommendations"][0]
        self.assertEqual((one["score"], one["category"]), (listed["score"], listed["category"]))

    def test_nothing_is_written(self):
        before = (self.db.query(ScholarshipProgramLink).count(), self.db.query(Scholarship).count())
        self.listing(self.alice, self.program.id)
        self.assertEqual((self.db.query(ScholarshipProgramLink).count(), self.db.query(Scholarship).count()), before)


if __name__ == "__main__":
    unittest.main()
