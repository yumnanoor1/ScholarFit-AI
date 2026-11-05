"""
FitScholar AI Assistant tests. In-memory SQLite, router called directly.
Run from the backend folder:  python -m unittest discover -s tests -p "test_assistant.py" -v
"""
import unittest
from unittest.mock import patch

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
from app.services import rag_service
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

    def test_existing_intents_win_over_scholarship_info(self):
        cases = {
            "What are the deadlines for scholarships?": "deadlines",
            "Can I afford the scholarship funding?": "financial",
            "What documents does the scholarship need?": "documents",
            "What are my chances of winning a scholarship?": "improve_chances",
            "Which scholarship requirements am I missing?": "missing_requirements",
            "What if my IELTS improves for the scholarship?": "what_if",
        }
        for message, intent in cases.items():
            self.assertEqual(detect_intent(message), intent, message)

    def test_information_questions_use_rag_intent(self):
        for message in ("What does the Alpha scholarship cover?", "How do I apply for this scholarship?",
                        "Tell me about the Alpha scholarship benefits", "Explain the Erasmus Mundus scholarship",
                        "What is this scholarship about?", "Describe this scholarship", "Give me an overview of the scholarship"):
            self.assertEqual(detect_intent(message), "scholarship_info", message)

    def test_deterministic_intents_still_win_over_new_info_terms(self):
        cases = {
            "Explain the scholarship deadlines": "deadlines",
            "Explain how much this scholarship costs": "financial",
            "Describe the documents for this scholarship": "documents",
            "Explain why I am not eligible for this scholarship": "why_not_eligible",
            "Give an overview of how to improve my profile": "improve_profile",
            "Explain how to improve my chances of a scholarship": "improve_chances",
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

    def test_rag_reply_keeps_the_response_shape(self):
        chunk = rag_service.RetrievedChunk(1, "Alpha Grant", "https://alpha.example", "https://alpha.example/doc",
                                           "Benefits", 2, 2, "Covers tuition.")
        answer = rag_service.RagAnswer(rag_service.STATUS_OK, "It covers tuition.", [chunk], generated=True)
        with patch.object(rag_service, "answer_question", return_value=answer):
            reply = self.ask(self.alice, "What does the Alpha scholarship cover?")
        self.assertEqual(reply["intent"], "scholarship_info")
        self.assertEqual(reply["summary"], "It covers tuition.")
        self.assertEqual(reply["sections"], [{"heading": "Sources", "items": ["Alpha Grant: https://alpha.example"]}])
        self.assertEqual(reply["context"]["topic"], "scholarship_info")
        self.assertTrue({"intent", "summary", "sections", "guidance", "action", "suggestions", "notes", "context"} <= set(reply))

    def test_rag_without_sources_or_when_unavailable_is_honest(self):
        for status, phrase in ((rag_service.STATUS_NO_SOURCES, "approved official source"),
                               (rag_service.STATUS_UNAVAILABLE, "can't search")):
            with patch.object(rag_service, "answer_question", return_value=rag_service.RagAnswer(status, "")):
                reply = self.ask(self.alice, "What does the Alpha scholarship cover?")
            self.assertIn(phrase, reply["summary"])
            self.assertEqual(reply["sections"], [])

    def test_rag_is_not_used_for_deterministic_intents(self):
        with patch.object(rag_service, "answer_question", side_effect=AssertionError("RAG must not run")):
            for message in ("What are my scholarship deadlines?", "Why am I not eligible for a scholarship?",
                            "How can I improve my profile?", "hello"):
                self.ask(self.alice, message)

    def _ask_info(self, **context):
        answer = rag_service.RagAnswer(rag_service.STATUS_NO_SOURCES, "")
        with patch.object(rag_service, "answer_question", return_value=answer) as mocked:
            reply = self.ask(self.alice, "What is this scholarship about?", **context)
        return reply, mocked

    def test_context_scholarship_id_is_passed_and_preserved(self):
        reply, mocked = self._ask_info(scholarship_id=self.scholarship.id)
        mocked.assert_called_once_with(self.db, "What is this scholarship about?", scholarship_id=self.scholarship.id)
        self.assertEqual(reply["context"]["scholarship_id"], self.scholarship.id)

    def test_missing_scholarship_id_does_general_search(self):
        reply, mocked = self._ask_info()
        mocked.assert_called_once_with(self.db, "What is this scholarship about?", scholarship_id=None)
        self.assertIsNone(reply["context"]["scholarship_id"])

    def test_rag_scope_cannot_return_another_scholarships_chunks(self):
        from tests.test_rag_service import RagFixture
        fixture = RagFixture()
        fixture.setUp()
        try:
            other = Scholarship(country="Finland", name="Beta Grant", official_url="https://beta.example",
                                verification_status="verified", verification_basis="official_source", record_version=1)
            fixture.db.add(other)
            fixture.db.commit()
            fixture.indexed(text="Alpha text.")
            fixture.indexed(document=fixture.source(other), text="Beta text.")
            alpha = [c.text for c in fixture.retrieve(scholarship_id=fixture.scholarship.id).chunks]
            beta = [c.text for c in fixture.retrieve(scholarship_id=other.id).chunks]
            unknown = fixture.retrieve(scholarship_id=99999)
        finally:
            fixture.tearDown()
        self.assertEqual(alpha, ["Alpha text."])
        self.assertEqual(beta, ["Beta text."])
        self.assertEqual(unknown.status, rag_service.STATUS_NO_SOURCES)

    def test_empty_knowledge_tables_give_no_source_reply(self):
        valid = "0123456789abcdef0123456789abcdef01234567"
        with patch.dict("os.environ", {"MINILM_MODEL_REVISION": valid}), \
                patch.object(rag_service, "embed_query", return_value=[0.1] * 384):
            reply = self.ask(self.alice, "What does the Alpha scholarship cover?")
        self.assertIn("approved official source", reply["summary"])

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
