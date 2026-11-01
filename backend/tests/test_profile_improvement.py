"""
Profile improvement guidance tests. Records come from the real services; API tests use in-memory SQLite.
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
from app.models.opportunity import Program, Scholarship, University
from app.models.user import StudentProfile, User
from app.routers import eligibility as api
from app.services.profile_improvement import CATEGORIES, build_guidance

TODAY = date(2026, 10, 31)


def make_profile(**overrides):
    data = dict(nationality="Pakistan", date_of_birth=date(2001, 5, 1), degree_level="Bachelor's",
                field_of_study="Computer Science", cgpa=3.5, cgpa_scale=4.0, ielts_score=7.5, toefl_score=None,
                skills="Python", research_interests="NLP", institution="NUST", academic_status="graduated",
                graduation_date="2024-06", work_experience="Intern", budget_usd=1000.0)
    data.update(overrides)
    return SimpleNamespace(**data)


def make_program(**overrides):
    data = dict(id=1, name="MSc Test", degree_level="Master", field_of_study="Computer Science", min_cgpa=3.0,
                min_ielts=7.0, min_toefl=95, required_degree=None, source_url="https://example.edu",
                last_verified=date(2026, 10, 25), university=SimpleNamespace(name="Test University", country="Germany"))
    data.update(overrides)
    return SimpleNamespace(**data)


def make_scholarship(**overrides):
    data = dict(id=5, name="Test Scholarship", provider="Provider", country="Germany", degree_level="Master's",
                verification_status="verified", eligible_nationalities="Open to students of all nationalities",
                pakistan_eligible="Yes - open to all", eligible_fields="All fields", min_academic_requirement="Minimum CGPA 3.0",
                bachelors_requirement="Yes - required for Master's admission", english_requirement="Yes - IELTS 6.5 overall",
                work_experience="Not specified", age_requirement="Not specified", deadline="2027-01-15",
                funding_type="Fully Funded", tuition_coverage="Full tuition", living_stipend="No", other_benefits=None,
                last_verified="2026-09-30", official_url="https://example.org", source_name="Official")
    data.update(overrides)
    return SimpleNamespace(**data)


def guidance(profile=None, programs=None, scholarships=None, has_budget=True):
    return build_guidance(profile or make_profile(), [make_program()] if programs is None else programs,
                          [make_scholarship()] if scholarships is None else scholarships, has_budget=has_budget, today=TODAY)


def find(result, recommendation_id):
    return next((item for item in result["recommendations"] if item["id"] == recommendation_id), None)


class GapTests(unittest.TestCase):
    def test_strong_complete_profile_has_no_gaps(self):
        self.assertEqual(guidance()["recommendations"], [])

    def test_unmet_english_program(self):
        item = find(guidance(make_profile(ielts_score=6.0)), "unmet-english")
        self.assertEqual((item["priority"], item["actionability"], item["result_type"]), ("High", "achievable", "unmet"))
        self.assertIn("IELTS 7", item["related"][0]["requirement_text"])

    def test_missing_score_is_not_a_failure(self):
        result = guidance(make_profile(ielts_score=None))
        self.assertIsNotNone(find(result, "missing-information-english"))
        self.assertIsNone(find(result, "unmet-english"))
        self.assertEqual(result["summary"]["not_eligible"], 0)

    def test_completed_cgpa_is_not_changeable(self):
        item = find(guidance(make_profile(cgpa=2.5)), "unmet-academic")
        self.assertEqual((item["priority"], item["actionability"]), ("Medium", "not_changeable"))
        self.assertIn("can't be changed", item["suggested_action"])

    def test_student_still_studying_can_improve_cgpa(self):
        item = find(guidance(make_profile(cgpa=2.5, academic_status="studying")), "unmet-academic")
        self.assertEqual((item["priority"], item["actionability"]), ("High", "achievable"))

    def test_unmet_nationality_is_not_changeable(self):
        scholarship = make_scholarship(pakistan_eligible="No - not listed")
        item = find(guidance(scholarships=[scholarship]), "unmet-nationality")
        self.assertEqual(item["actionability"], "not_changeable")

    def test_missing_nationality(self):
        self.assertEqual(find(guidance(make_profile(nationality=None)), "missing-information-nationality")["priority"], "High")

    def test_free_text_needs_manual_verification(self):
        scholarship = make_scholarship(eligible_fields="STEM courses only")
        item = find(guidance(scholarships=[scholarship]), "manual-verification-field")
        self.assertEqual(item["actionability"], "manual_verification")
        self.assertEqual(item["related"][0]["requirement_text"], "STEM courses only")

    def test_stated_conditions_need_manual_verification(self):
        text = "Not awarded for a second Master's programme at UvA."
        item = find(guidance(scholarships=[make_scholarship(notes=text)]), "manual-verification-restrictions")
        self.assertEqual(item["actionability"], "manual_verification")
        self.assertEqual(item["related"][0]["requirement_text"], text)

    def test_program_background_kept_as_written(self):
        program = make_program(required_degree="Bachelor's in informatics")
        item = find(guidance(programs=[program]), "manual-verification-program-background")
        self.assertEqual(item["related"][0]["requirement_text"], "Bachelor's in informatics")

    def test_unverified_scholarship_gets_no_gap_analysis(self):
        scholarship = make_scholarship(verification_status="unverified", pakistan_eligible="No")
        result = guidance(scholarships=[scholarship], programs=[])
        self.assertIsNone(find(result, "unmet-nationality"))
        self.assertIsNotNone(find(result, "manual-verification-unverified"))

    def test_program_without_minimums(self):
        program = make_program(min_cgpa=None, min_ielts=None, min_toefl=None)
        self.assertIsNotNone(find(guidance(programs=[program]), "manual-verification-no-published-minimum"))


class StructureTests(unittest.TestCase):
    def test_shared_gap_is_not_repeated(self):
        programs = [make_program(id=1), make_program(id=2, name="MSc Two")]
        result = guidance(make_profile(ielts_score=None), programs=programs)
        matches = [item for item in result["recommendations"] if item["id"] == "missing-information-english"]
        self.assertEqual(len(matches), 1)
        self.assertEqual({(r["kind"], r["id"]) for r in matches[0]["related"]},
                         {("program", 1), ("program", 2), ("scholarship", 5)})

    def test_priorities_are_sorted(self):
        profile = make_profile(ielts_score=None, skills=None)
        program = make_program(required_degree="Bachelor's")
        order = [item["priority"] for item in guidance(profile, programs=[program])["recommendations"]]
        self.assertEqual(order, sorted(order, key=["High", "Medium", "Low"].index))

    def test_only_categories_in_use_are_listed(self):
        result = guidance(make_profile(ielts_score=None))
        self.assertEqual([item["name"] for item in result["categories"]], ["English Language Preparation"])
        self.assertTrue(set(item["category"] for item in result["recommendations"]) <= set(CATEGORIES))

    def test_every_recommendation_is_traceable(self):
        profile = make_profile(ielts_score=None, cgpa=0, skills=None, nationality=None)
        for item in guidance(profile, has_budget=False)["recommendations"]:
            for field in ("gap", "why_it_matters", "suggested_action", "profile_information", "comparison"):
                self.assertTrue(item[field], (item["id"], field))
            if item["result_type"] != "optional":
                self.assertTrue(item["related"] and item["requirement"])

    def test_optional_gaps_are_low(self):
        item = find(guidance(make_profile(skills=None)), "optional-skills")
        self.assertEqual((item["priority"], item["result_type"]), ("Low", "optional"))

    def test_budget_in_plan_counts(self):
        profile = make_profile(budget_usd=None)
        self.assertIsNone(find(guidance(profile, has_budget=True), "optional-budget"))
        self.assertIsNotNone(find(guidance(profile, has_budget=False), "optional-budget"))

    def test_changes_when_profile_changes(self):
        before = {item["id"] for item in guidance(make_profile(ielts_score=6.0))["recommendations"]}
        after = {item["id"] for item in guidance(make_profile(ielts_score=7.5))["recommendations"]}
        self.assertIn("unmet-english", before - after)

    def test_never_promises_an_outcome(self):
        result = guidance(make_profile(ielts_score=None))
        self.assertTrue(any("does not guarantee" in note for note in result["notes"]))
        self.assertNotIn("guarantee", " ".join(item["expected_benefit"] or "" for item in result["recommendations"]))

    def test_opportunity_results_separate_each_outcome(self):
        entry = guidance(make_profile(cgpa=2.5, ielts_score=None))["opportunities"][0]
        self.assertEqual(entry["unmet"][0]["requirement"], "Minimum CGPA")
        self.assertEqual(entry["missing_information"][0]["requirement"], "English language")
        self.assertEqual(entry["satisfied"][0]["requirement"], "Degree level")


class ApiTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        germany = University(name="German University", country="Germany")
        sweden = University(name="Swedish University", country="Sweden")
        self.db.add_all([germany, sweden])
        self.db.flush()
        self.german = Program(university_id=germany.id, name="German MSc", degree_level="Master", min_ielts=7.0)
        self.swedish = Program(university_id=sweden.id, name="Swedish MSc", degree_level="Master", min_ielts=7.0)
        fields = {k: v for k, v in vars(make_scholarship()).items() if k != "id"}
        self.scholarship = Scholarship(**fields)
        self.unverified = Scholarship(**{**fields, "name": "Hidden", "verification_status": "unverified"})
        self.alice = User(email="alice@example.com", hashed_password="x", full_name="Alice")
        self.bob = User(email="bob@example.com", hashed_password="x", full_name="Bob")
        self.carol = User(email="carol@example.com", hashed_password="x", full_name="Carol")
        self.db.add_all([self.german, self.swedish, self.scholarship, self.unverified, self.alice, self.bob, self.carol])
        self.db.flush()
        self.db.add_all([
            StudentProfile(user_id=self.alice.id, degree_level="Bachelor's", cgpa=3.5, cgpa_scale=4.0, ielts_score=6.0,
                           nationality="Pakistan", preferred_countries="Germany"),
            StudentProfile(user_id=self.bob.id, degree_level="Bachelor's", cgpa=3.5, cgpa_scale=4.0, ielts_score=8.0,
                           nationality="Pakistan"),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def call(self, user, program_id=None, scholarship_id=None):
        return api.profile_improvements(program_id=program_id, scholarship_id=scholarship_id, db=self.db, current_user=user)

    def test_scope_uses_preferred_countries(self):
        result = self.call(self.alice)
        self.assertEqual(result["scope"]["type"], "preferred_countries")
        self.assertEqual([item["name"] for item in result["opportunities"] if item["kind"] == "program"], ["German MSc"])

    def test_without_preferences_covers_all_verified(self):
        result = self.call(self.bob)
        self.assertEqual(result["scope"]["type"], "all")
        self.assertEqual(result["summary"]["programs_evaluated"], 2)
        self.assertEqual(result["summary"]["scholarships_evaluated"], 1)

    def test_students_get_their_own_guidance(self):
        alice = {item["id"] for item in self.call(self.alice)["recommendations"]}
        bob = {item["id"] for item in self.call(self.bob)["recommendations"]}
        self.assertIn("unmet-english", alice)
        self.assertNotIn("unmet-english", bob)

    def test_selected_opportunity(self):
        result = self.call(self.alice, program_id=self.swedish.id)
        self.assertEqual(result["scope"]["type"], "selected")
        self.assertEqual(result["summary"]["opportunities_evaluated"], 1)

    def test_unknown_ids(self):
        for kwargs in ({"program_id": 9999}, {"scholarship_id": 9999}):
            with self.assertRaises(HTTPException) as error:
                self.call(self.alice, **kwargs)
            self.assertEqual(error.exception.status_code, 404)

    def test_missing_profile(self):
        with self.assertRaises(HTTPException) as error:
            self.call(self.carol)
        self.assertEqual(error.exception.status_code, 404)
        self.assertIn("Profile", error.exception.detail)


if __name__ == "__main__":
    unittest.main()
