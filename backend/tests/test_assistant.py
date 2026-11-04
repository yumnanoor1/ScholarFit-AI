"""
FitScholar AI Assistant tests. In-memory SQLite, router called directly.
Run from the backend folder:  python -m unittest discover -s tests -p "test_assistant.py" -v
"""
import unittest

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.rate_limit import ALL_LIMITS
from app.database import Base
from app.models.opportunity import Scholarship
from app.models.user import StudentProfile, User
from app.routers import assistant as api
from app.schemas.assistant import AssistantContext, AssistantRequest
from app.services.assistant import detect_intent
from tests.test_profile_improvement import make_scholarship


class IntentTests(unittest.TestCase):
    def test_spec_questions(self):
        cases = {
            "How can I improve my profile?": "improve_profile",
            "What's my best next action?": "next_action",
            "Why am I not eligible for a scholarship?": "why_not_eligible",
            "Which requirements am I missing?": "missing_requirements",
            "How can I improve my chances of getting a scholarship?": "improve_chances",
            "What should I do first?": "next_action",
            "What if I improve my CGPA?": "what_if",
            "hello": "help",
        }
        for message, intent in cases.items():
            self.assertEqual(detect_intent(message), intent, message)


class ApiTests(unittest.TestCase):
    def setUp(self):
        for limit in ALL_LIMITS:
            limit.clear()
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        fields = {k: v for k, v in vars(make_scholarship()).items() if k != "id"}
        self.scholarship = Scholarship(**{**fields, "name": "Alpha Grant", "english_requirement": "Yes - IELTS 7.5 overall"})
        self.hidden = Scholarship(**{**fields, "name": "Hidden Grant", "verification_status": "unverified"})
        self.alice = User(email="alice@example.com", hashed_password="x", full_name="Alice")
        self.bob = User(email="bob@example.com", hashed_password="x", full_name="Bob")
        self.admin = User(email="admin@example.com", hashed_password="x", full_name="Admin", role="admin")
        self.nobody = User(email="none@example.com", hashed_password="x", full_name="None")
        self.db.add_all([self.scholarship, self.hidden, self.alice, self.bob, self.admin, self.nobody])
        self.db.flush()
        done = dict(institution="NUST", academic_status="graduated", graduation_date="2024-06", preferred_countries="Germany")
        self.alice_profile = StudentProfile(user_id=self.alice.id, degree_level="Bachelor's", field_of_study="Computer Science",
                                            cgpa=3.5, cgpa_scale=4.0, ielts_score=6.0, nationality="Pakistan", budget_usd=1000, **done)
        self.db.add_all([self.alice_profile,
                         StudentProfile(user_id=self.bob.id, degree_level="Bachelor's", field_of_study="Computer Science",
                                        cgpa=3.5, cgpa_scale=4.0, ielts_score=8.0, nationality="Pakistan", budget_usd=1000, **done),
                         StudentProfile(user_id=self.admin.id, nationality="Pakistan")])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def ask(self, user, message, **context):
        return api.chat(AssistantRequest(message=message, context=AssistantContext(**context)), db=self.db, current_user=user)

    def test_improve_profile_separates_required_from_optional(self):
        reply = self.ask(self.alice, "How can I improve my profile?")
        self.assertEqual(reply["intent"], "improve_profile")
        english = next(item for item in reply["guidance"] if item["id"] == "unmet-english")
        self.assertEqual((english["kind"], english["priority"]), ("required", "High"))
        self.assertIn("IELTS 7", english["target"])
        self.assertEqual(english["action"]["label"], "Explore Language Requirements")
        self.assertNotIn("Hidden Grant", str(reply))

    def test_data_is_per_student(self):
        alice = {item["id"] for item in self.ask(self.alice, "improve my profile")["guidance"]}
        bob = {item["id"] for item in self.ask(self.bob, "improve my profile")["guidance"]}
        self.assertIn("unmet-english", alice)
        self.assertNotIn("unmet-english", bob)

    def test_best_next_action_is_single_and_changes_with_profile(self):
        first = self.ask(self.alice, "What's my best next action?")
        self.assertTrue(first["title"].startswith("Your Best Next Action"))
        self.assertIsNotNone(first["action"])
        self.assertEqual(first["context"]["shown_actions"], [first["context"]["shown_actions"][0]])
        self.alice_profile.ielts_score = 8.5
        self.db.commit()
        second = self.ask(self.alice, "What's my best next action?")
        self.assertNotEqual(first["title"], second["title"])

    def test_follow_up_does_not_repeat_the_same_action(self):
        first = self.ask(self.alice, "What should I do first?")
        second = self.ask(self.alice, "What should I do after that?", **first["context"])
        self.assertNotEqual(first["title"], second["title"])

    def test_why_not_eligible_uses_stored_criteria(self):
        reply = self.ask(self.alice, "Why am I not eligible for Alpha Grant?")
        self.assertEqual(reply["title"], "Alpha Grant")
        text = str(reply["sections"])
        self.assertIn("IELTS 7.5", text)
        self.assertEqual(reply["context"]["scholarship_id"], self.scholarship.id)

    def test_why_not_eligible_follow_up_uses_context(self):
        reply = self.ask(self.alice, "Why am I not eligible for this scholarship?", scholarship_id=self.scholarship.id)
        self.assertEqual(reply["title"], "Alpha Grant")

    def test_unverified_scholarship_gets_no_result(self):
        reply = self.ask(self.alice, "Why am I not eligible for Hidden Grant?")
        self.assertIn("not been verified", reply["summary"])

    def test_what_if_cgpa_makes_no_promises(self):
        reply = self.ask(self.alice, "What if I improve my CGPA?")
        self.assertEqual(reply["intent"], "what_if")
        self.assertIn("not a promise", " ".join(reply["notes"]))

    def test_what_if_english_uses_stated_minimum(self):
        reply = self.ask(self.alice, "What if I improve my IELTS?")
        self.assertIn("IELTS", str(reply["sections"]))

    def test_missing_profile_information_is_not_a_failure(self):
        self.alice_profile.ielts_score = None
        self.db.commit()
        reply = self.ask(self.alice, "What if I improve my IELTS?")
        self.assertIn("isn't in your profile", reply["summary"])

    def test_documents_are_not_claimed(self):
        reply = self.ask(self.alice, "Which documents do I need to upload?")
        self.assertEqual(reply["action"]["route"], "/documents")
        self.assertIn("can't see", reply["summary"])

    def test_financial_action(self):
        reply = self.ask(self.alice, "Can I afford this?", scholarship_id=self.scholarship.id)
        self.assertEqual(reply["action"]["route"], "/financial")
        self.assertEqual(reply["action"]["state"]["scholarshipId"], self.scholarship.id)
        self.assertIsNone(self.ask(self.alice, "Can I afford this?")["action"]["state"])

    def test_invalid_context_ids_are_ignored(self):
        reply = self.ask(self.alice, "Can I afford this?", scholarship_id=9999)
        self.assertIsNone(reply["action"]["state"])

    def test_unknown_question_offers_suggestions(self):
        reply = self.ask(self.alice, "hello there")
        self.assertEqual(len(reply["suggestions"]), 5)

    def test_admin_is_refused(self):
        with self.assertRaises(HTTPException) as error:
            self.ask(self.admin, "improve my profile")
        self.assertEqual(error.exception.status_code, 403)

    def test_missing_profile_is_404(self):
        with self.assertRaises(HTTPException) as error:
            self.ask(self.nobody, "improve my profile")
        self.assertEqual(error.exception.status_code, 404)

    def test_rate_limit(self):
        with self.assertRaises(HTTPException) as error:
            for _ in range(40):
                self.ask(self.alice, "hello")
        self.assertEqual(error.exception.status_code, 429)


class ValidationTests(unittest.TestCase):
    def test_blank_and_long_messages_rejected(self):
        for message in ("   ", "x" * 501):
            with self.assertRaises(ValidationError):
                AssistantRequest(message=message)


if __name__ == "__main__":
    unittest.main()
