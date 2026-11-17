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
            "Show me my best scholarship matches": "scholarship_recommendations",
            "What are my best scholarship matches?": "scholarship_recommendations",
            "Which are the top scholarships for me?": "scholarship_recommendations",
            "Which scholarships should I prioritize?": "scholarship_recommendations",
            "Show recommended scholarships": "scholarship_recommendations",
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
            "What scholarship documents require a recommendation letter?": "documents",
            "What scholarship recommendation letters do I need?": "documents",
            "What are my chances of winning a scholarship?": "improve_chances",
            "Which scholarship requirements am I missing?": "missing_requirements",
            "What if my IELTS improves for the scholarship?": "what_if",
        }
        for message, intent in cases.items():
            self.assertEqual(detect_intent(message), intent, message)

    def test_information_questions_use_rag_intent(self):
        for message in ("What does the Alpha scholarship cover?", "How do I apply for this scholarship?",
                        "Tell me about the Alpha scholarship benefits", "Explain the Erasmus Mundus scholarship",
                        "What does the Alpha Grant cover?", "What is this scholarship about?",
                        "Describe this scholarship", "Give me an overview of the scholarship"):
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

    def test_scholarship_recommendations_reuse_ranker_and_separate_exclusions(self):
        recommendations = [
            {
                "scholarship_id": index,
                "scholarship_name": f"Match {index}",
                "recommended": True,
                "score": 80 + index,
                "category": "strong",
                "category_label": "Strong Match",
                "category_reason": "You meet the stated requirements and the score is high.",
                "country": "Germany",
                "eligibility": {"status": "eligible", "outcome": "eligible", "summary": "All stated requirements are met."},
                "funding": {"label": "Fully funded", "summary": "Tuition and stipend"},
                "deadline": {"status": "open", "date": "2026-12-01"},
                "positive": ["You meet the requirements this scholarship states."],
                "warnings": ["Confirm the deadline on the official page."],
            }
            for index in range(1, 7)
        ]
        excluded = {
            "scholarship_id": 99,
            "scholarship_name": "Excluded Grant",
            "recommended": False,
            "exclusions": [{"rule": "not_eligible", "reason": "Minimum English score not met."}],
        }
        with patch(
            "app.services.assistant.recommend_for_student",
            return_value={
                "recommendations": recommendations,
                "excluded": [excluded],
                "notes": ["The score shows suitability, not the chance of winning."],
            },
        ) as recommend:
            reply = self.ask(self.alice, "Show me my best scholarship matches")

        recommend.assert_called_once_with(self.db, self.alice_profile)
        self.assertEqual(reply["intent"], "scholarship_recommendations")
        self.assertEqual(reply["context"]["topic"], "scholarship_recommendations")
        self.assertEqual(reply["action"]["route"], "/recommendations")
        self.assertEqual(len(reply["sections"][0]["items"]), 5)
        self.assertIn("Match 1 (ID 1)", reply["sections"][0]["items"][0])
        self.assertIn("85/100", reply["sections"][0]["items"][-1])
        self.assertIn("Important warning", reply["sections"][0]["items"][0])
        self.assertNotIn("Excluded Grant", str(reply["sections"][0]["items"]))
        self.assertIn("Excluded (not recommended)", reply["sections"][1]["heading"])
        self.assertIn("Excluded Grant", reply["sections"][1]["items"][0])
        self.assertTrue(any("not your chance of receiving an award" in note for note in reply["notes"]))

    def test_scholarship_recommendations_separate_uncertain_and_excluded_eligibility(self):
        def result(scholarship_id, name, status, outcome, recommended, score, category, deadline_status="open"):
            return {
                "scholarship_id": scholarship_id,
                "scholarship_name": name,
                "recommended": recommended,
                "score": score,
                "category": category,
                "category_label": "Needs Verification" if category == "needs_verification" else "Good Match",
                "category_reason": f"{name} requires an eligibility check.",
                "country": "Germany",
                "eligibility": {
                    "status": status,
                    "outcome": outcome,
                    "summary": f"Eligibility status is {status}.",
                },
                "funding": {"label": "Funding listed", "summary": "Tuition support"},
                "deadline": {"status": deadline_status, "date": "2026-12-01"},
                "positive": [f"{name} has relevant scholarship details."],
                "warnings": [f"Verify {name} details on the official page."],
                "exclusions": [],
            }

        eligible = result(1, "Eligible Grant", "eligible", "eligible", True, 88, "good")
        missing = result(2, "Missing Information Grant", "missing_information", "verify_manually", True, 76,
                         "needs_verification")
        not_evaluated = result(3, "Unevaluated Grant", "not_evaluated", "verify_manually", True, 70,
                               "needs_verification")
        ineligible = result(4, "Hard Ineligible Grant", "not_eligible", "not_eligible", False, None, None)
        ineligible["exclusions"] = [{"rule": "not_eligible", "reason": "A required criterion is not met."}]
        closed = result(5, "Closed Grant", "eligible", "eligible", False, None, None, deadline_status="closed")
        closed["exclusions"] = [{"rule": "closed", "reason": "The application deadline has passed."}]

        with patch(
            "app.services.assistant.recommend_for_student",
            return_value={
                "recommendations": [eligible, missing, not_evaluated],
                "excluded": [ineligible, closed],
                "notes": [],
            },
        ):
            reply = self.ask(self.alice, "Show me my best scholarship matches")

        self.assertEqual(len(reply["sections"][0]["items"]), 1)
        self.assertIn("Eligible Grant", reply["sections"][0]["items"][0])
        self.assertNotIn("Missing Information Grant", str(reply["sections"][0]))
        self.assertNotIn("Unevaluated Grant", str(reply["sections"][0]))

        verification = next(section for section in reply["sections"] if section["heading"].startswith("Needs verification"))
        self.assertIn("Missing Information Grant", str(verification["items"]))
        self.assertIn("Unevaluated Grant", str(verification["items"]))
        self.assertIn("Needs verification (missing information)", verification["items"][0])
        self.assertIn("Important warning", str(verification["items"]))

        excluded = next(section for section in reply["sections"] if section["heading"].startswith("Excluded"))
        self.assertIn("Hard Ineligible Grant", str(excluded["items"]))
        self.assertIn("Closed Grant", str(excluded["items"]))
        self.assertNotIn("Hard Ineligible Grant", str(reply["sections"][:2]))
        self.assertNotIn("Closed Grant", str(reply["sections"][:2]))
        self.assertIn("not your chance of receiving an award", " ".join(reply["notes"]))

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
        self.assertEqual(reply["sections"], [
            {"heading": "Retrieved sources", "items": ["Alpha Grant: https://alpha.example/doc"]}
        ])
        self.assertEqual(reply["context"]["topic"], "scholarship_info")
        self.assertTrue({"intent", "summary", "sections", "guidance", "action", "suggestions", "notes", "context"} <= set(reply))

    def test_generated_answer_labels_sources_as_retrieved_not_claim_attributions(self):
        chunks = [
            rag_service.RetrievedChunk(1, "Alpha Grant", "https://alpha.example", f"https://source.example/{index}",
                                       "Benefits", None, None, f"Evidence {index}.")
            for index in (1, 2)
        ]
        answer = rag_service.RagAnswer(rag_service.STATUS_OK, "It covers tuition.", chunks, generated=True)
        with patch.object(rag_service, "answer_question", return_value=answer):
            reply = self.ask(self.alice, "What does the Alpha scholarship cover?")

        self.assertEqual(reply["sections"], [{
            "heading": "Retrieved sources",
            "items": ["Alpha Grant: https://source.example/1", "Alpha Grant: https://source.example/2"],
        }])

    def test_extractive_reply_lists_only_sources_for_included_excerpts(self):
        chunks = [
            rag_service.RetrievedChunk(1, "Alpha Grant", "https://alpha.example", f"https://source.example/{index}",
                                       "Benefits", None, None, f"Evidence {index}.")
            for index in range(1, 6)
        ]
        answer = rag_service.RagAnswer(
            rag_service.STATUS_OK, rag_service.extractive_answer(chunks), chunks, generated=False,
        )
        with patch.object(rag_service, "answer_question", return_value=answer):
            reply = self.ask(self.alice, "What does the Alpha scholarship cover?")

        self.assertIn("Evidence 1.", reply["summary"])
        self.assertIn("Evidence 3.", reply["summary"])
        self.assertNotIn("Evidence 4.", reply["summary"])
        self.assertEqual(reply["sections"], [{
            "heading": "Sources",
            "items": [f"Alpha Grant: https://source.example/{index}" for index in range(1, 4)],
        }])

    def test_missing_source_url_is_reported_without_using_landing_page(self):
        chunk = rag_service.RetrievedChunk(
            self.scholarship.id, self.scholarship.name, "https://alpha.example", None,
            "Benefits", None, None, "Covers tuition.",
        )
        answer = rag_service.RagAnswer(rag_service.STATUS_OK, "Covers tuition.", [chunk], generated=True)
        with patch.object(rag_service, "answer_question", return_value=answer):
            reply = self.ask(self.alice, "What does the Alpha scholarship cover?")

        self.assertEqual(reply["sections"], [{
            "heading": "Retrieved sources",
            "items": ["Alpha Grant: Source URL unavailable"],
        }])

    def test_unsafe_document_url_is_not_returned_to_student(self):
        unsafe_url = "https://student:password@alpha.example/doc?api_key=secret&lang=en#token=fragment"
        chunk = rag_service.RetrievedChunk(
            self.scholarship.id, self.scholarship.name, "https://alpha.example", unsafe_url,
            "Benefits", None, None, "Covers tuition.",
        )
        answer = rag_service.RagAnswer(rag_service.STATUS_OK, "Covers tuition.", [chunk], generated=True)
        with patch.object(rag_service, "answer_question", return_value=answer):
            reply = self.ask(self.alice, "What does the Alpha scholarship cover?")

        self.assertEqual(reply["sections"], [{
            "heading": "Retrieved sources",
            "items": ["Alpha Grant: Source URL unavailable"],
        }])
        for secret in ("student", "password", "api_key", "secret", "fragment"):
            self.assertNotIn(secret, str(reply))

    def test_conflict_source_url_is_sanitized_before_student_response(self):
        conflict = rag_service.RagConflict(
            scholarship_id=self.scholarship.id,
            scholarship_name=self.scholarship.name,
            fact_label="application deadline",
            category="deadline",
            statements=[
                rag_service.ConflictStatement(
                    "2027-03-31", "Application deadline is 31 March 2027.", 11, 21,
                    "https://student:password@alpha.example/doc?token=secret#fragment",
                    "Deadlines", "p. 2",
                ),
                rag_service.ConflictStatement(
                    "2027-04-30", "Applications close on 30 April 2027.", 12, 22,
                    "https://alpha.example/source-b", "How to apply", "p. 4",
                ),
            ],
        )
        answer = rag_service.RagAnswer(
            rag_service.STATUS_CONFLICT,
            "The retrieved official documents contain conflicting deadline information.",
            conflicts=[conflict],
        )
        with patch.object(rag_service, "answer_question", return_value=answer):
            reply = self.ask(self.alice, "Tell me about the Alpha scholarship application date.")

        self.assertIn("Source URL unavailable", str(reply["sections"]))
        for secret in ("student", "password", "token=secret", "fragment"):
            self.assertNotIn(secret, str(reply))

    def test_conflict_statement_urls_are_sanitized_without_changing_provenance(self):
        original_statement = (
            "Applications close on 31 March 2027; see http://alpha.example/details, "
            "then https://alpha.example/apply?lang=en&token=example-token!"
        )
        conflict = rag_service.RagConflict(
            scholarship_id=self.scholarship.id,
            scholarship_name=self.scholarship.name,
            fact_label="application deadline",
            category="deadline",
            statements=[
                rag_service.ConflictStatement(
                    "2027-03-31", original_statement, 11, 21,
                    "https://alpha.example/source-a?lang=en", "Deadlines", "p. 2",
                ),
                rag_service.ConflictStatement(
                    "2027-04-30", "Applications close on 30 April 2027.", 12, 22,
                    "https://alpha.example/source-b", "How to apply", "p. 4",
                ),
            ],
        )
        summary = "The retrieved official documents contain conflicting deadline information."
        answer = rag_service.RagAnswer(rag_service.STATUS_CONFLICT, summary, conflicts=[conflict])

        with patch.object(rag_service, "answer_question", return_value=answer):
            reply = self.ask(self.alice, "Tell me about the Alpha scholarship application date.")

        self.assertEqual(set(reply), {
            "intent", "summary", "context", "suggestions", "notes", "sections", "guidance", "action",
        })
        self.assertEqual(reply["intent"], "scholarship_info")
        self.assertEqual(reply["summary"], summary)
        self.assertEqual(reply["sections"], [{
            "heading": "Conflicting official statements",
            "items": [
                'Alpha Grant — application deadline: 2027-03-31. Source text: '
                '"Applications close on 31 March 2027; see http://alpha.example/details, '
                'then https://alpha.example/apply?lang=en!" '
                '(document 11, version 21, Deadlines; p. 2; source: https://alpha.example/source-a?lang=en)',
                'Alpha Grant — application deadline: 2027-04-30. Source text: '
                '"Applications close on 30 April 2027." '
                '(document 12, version 22, How to apply; p. 4; source: https://alpha.example/source-b)',
            ],
        }])
        self.assertNotIn("example-token", str(reply))
        self.assertEqual(conflict.statements[0].statement, original_statement)
        self.assertEqual(answer.status, rag_service.STATUS_CONFLICT)
        self.assertEqual(conflict.category, "deadline")

    def test_conflicting_official_statements_are_reported_without_choosing_one(self):
        conflict = rag_service.RagConflict(
            scholarship_id=self.scholarship.id,
            scholarship_name=self.scholarship.name,
            fact_label="application deadline",
            category="deadline",
            statements=[
                rag_service.ConflictStatement(
                    "2027-03-31", "Application deadline is 31 March 2027.", 11, 21,
                    "https://alpha.example/source-a", "Deadlines", "p. 2",
                ),
                rag_service.ConflictStatement(
                    "2027-04-30", "Applications close on 30 April 2027.", 12, 22,
                    "https://alpha.example/source-b", "How to apply", "p. 4",
                ),
            ],
        )
        answer = rag_service.RagAnswer(
            rag_service.STATUS_CONFLICT,
            "The retrieved official documents contain conflicting information about application deadline. "
            "I won't present either statement as definitive. Please check the cited sources.",
            conflicts=[conflict],
        )
        with patch.object(rag_service, "answer_question", return_value=answer):
            reply = self.ask(self.alice, "Tell me about the Alpha scholarship application date.")

        self.assertIn("won't present either statement as definitive", reply["summary"])
        self.assertEqual(reply["sections"][0]["heading"], "Conflicting official statements")
        statements = reply["sections"][0]["items"]
        self.assertEqual(len(statements), 2)
        self.assertIn("2027-03-31", statements[0])
        self.assertIn("https://alpha.example/source-a", statements[0])
        self.assertIn("document 11, version 21", statements[0])
        self.assertIn("2027-04-30", statements[1])
        self.assertIn("https://alpha.example/source-b", statements[1])
        self.assertIn("document 12, version 22", statements[1])

    def test_rag_without_sources_or_when_unavailable_is_honest(self):
        for status, phrase in ((rag_service.STATUS_NO_SOURCES, "approved official source"),
                               (rag_service.STATUS_WEAK_EVIDENCE, "not passages relevant enough"),
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

    def _ask_info(self, message="What is this scholarship about?", **context):
        answer = rag_service.RagAnswer(rag_service.STATUS_NO_SOURCES, "")
        with patch.object(rag_service, "answer_question", return_value=answer) as mocked:
            reply = self.ask(self.alice, message, **context)
        return reply, mocked

    def test_context_scholarship_id_is_passed_and_preserved(self):
        reply, mocked = self._ask_info(scholarship_id=self.scholarship.id)
        mocked.assert_called_once_with(self.db, "What is this scholarship about?", scholarship_id=self.scholarship.id)
        self.assertEqual(reply["context"]["scholarship_id"], self.scholarship.id)

    def test_missing_scholarship_id_does_general_search(self):
        message = "What do scholarships generally cover?"
        reply, mocked = self._ask_info(message)
        mocked.assert_called_once_with(self.db, message, scholarship_id=None)
        self.assertIsNone(reply["context"]["scholarship_id"])

    def test_named_scholarship_is_passed_to_rag_and_saved_in_context(self):
        reply, mocked = self._ask_info("What does Alpha Grant cover?")
        mocked.assert_called_once_with(self.db, "What does Alpha Grant cover?",
                                       scholarship_id=self.scholarship.id)
        self.assertEqual(reply["context"]["scholarship_id"], self.scholarship.id)

    def test_confident_partial_name_requires_multiple_distinctive_tokens(self):
        fields = {k: v for k, v in vars(make_scholarship()).items() if k != "id"}
        scholarship = Scholarship(**{**fields, "name": "Erasmus Mundus Global Award"})
        self.db.add(scholarship)
        self.db.flush()

        message = "What does the Erasmus Mundus scholarship cover?"
        reply, mocked = self._ask_info(message)
        mocked.assert_called_once_with(self.db, message, scholarship_id=scholarship.id)
        self.assertEqual(reply["context"]["scholarship_id"], scholarship.id)

    def test_single_token_partial_name_asks_for_clarification(self):
        message = "What does the scholarship called Alpha cover?"
        with patch.object(rag_service, "answer_question", side_effect=AssertionError("weak matches must not search")) as mocked:
            reply = self.ask(self.alice, message)

        mocked.assert_not_called()
        self.assertIn("clarify", reply["summary"])
        self.assertIsNone(reply["context"]["scholarship_id"])

    def test_generic_scholarship_questions_use_global_rag(self):
        for message in ("What does a grant cover?", "What does a scholarship cover?", "What do grants cover?"):
            reply, mocked = self._ask_info(message)
            mocked.assert_called_once_with(self.db, message, scholarship_id=None)
            self.assertIsNone(reply["context"]["scholarship_id"])

    def test_short_partial_name_clarifies_but_exact_short_name_resolves(self):
        fields = {k: v for k, v in vars(make_scholarship()).items() if k != "id"}
        scholarship = Scholarship(**{**fields, "name": "US Aid Grant"})
        self.db.add(scholarship)
        self.db.flush()

        message = "What does US Aid scholarship cover?"
        with patch.object(rag_service, "answer_question", side_effect=AssertionError("short partial names must clarify")) as mocked:
            reply = self.ask(self.alice, message)
        mocked.assert_not_called()
        self.assertIn("clarify", reply["summary"])
        self.assertIsNone(reply["context"]["scholarship_id"])

        exact_message = "What does US Aid Grant cover?"
        reply, mocked = self._ask_info(exact_message)
        mocked.assert_called_once_with(self.db, exact_message, scholarship_id=scholarship.id)
        self.assertEqual(reply["context"]["scholarship_id"], scholarship.id)

    def test_exact_name_wins_over_a_similar_partial_name(self):
        fields = {k: v for k, v in vars(make_scholarship()).items() if k != "id"}
        similar = Scholarship(**{**fields, "name": "Alpha Award"})
        self.db.add(similar)
        self.db.flush()

        reply, mocked = self._ask_info("Tell me about Alpha Grant")
        mocked.assert_called_once_with(self.db, "Tell me about Alpha Grant",
                                       scholarship_id=self.scholarship.id)
        self.assertEqual(reply["context"]["scholarship_id"], self.scholarship.id)

    def test_ambiguous_name_asks_for_clarification_without_calling_rag(self):
        fields = {k: v for k, v in vars(make_scholarship()).items() if k != "id"}
        similar = Scholarship(**{**fields, "name": "Alpha Award"})
        self.db.add(similar)
        self.db.flush()

        with patch.object(rag_service, "answer_question", side_effect=AssertionError("ambiguous names must not search")) as mocked:
            reply = self.ask(self.alice, "What does the Alpha scholarship cover?")

        mocked.assert_not_called()
        self.assertIn("clarify", reply["summary"])
        self.assertIsNone(reply["context"]["scholarship_id"])
        self.assertEqual(reply["sections"][0]["heading"], "Possible matches")
        self.assertEqual(len(reply["sections"][0]["items"]), 2)

    def test_named_new_scholarship_replaces_previous_context(self):
        fields = {k: v for k, v in vars(make_scholarship()).items() if k != "id"}
        other = Scholarship(**{**fields, "name": "Beta Grant"})
        self.db.add(other)
        self.db.flush()

        message = "What does Beta Grant cover?"
        reply, mocked = self._ask_info(message, scholarship_id=self.scholarship.id)
        mocked.assert_called_once_with(self.db, message, scholarship_id=other.id)
        self.assertEqual(reply["context"]["scholarship_id"], other.id)

    def test_unmatched_new_scholarship_question_clears_previous_context(self):
        message = "What does another grant cover?"
        with patch.object(rag_service, "answer_question", side_effect=AssertionError("unmatched scholarship must clarify")) as mocked:
            reply = self.ask(self.alice, message, scholarship_id=self.scholarship.id)

        mocked.assert_not_called()
        self.assertIn("clarify", reply["summary"])
        self.assertIsNone(reply["context"]["scholarship_id"])

    def test_clear_follow_up_preserves_previous_context(self):
        message = "What are its eligibility requirements?"
        reply, mocked = self._ask_info(message, scholarship_id=self.scholarship.id)
        mocked.assert_called_once_with(self.db, message, scholarship_id=self.scholarship.id)
        self.assertEqual(reply["context"]["scholarship_id"], self.scholarship.id)

    def test_unrelated_funding_question_does_not_reuse_previous_context(self):
        message = "What does funding cover?"
        reply, mocked = self._ask_info(message, scholarship_id=self.scholarship.id)
        mocked.assert_called_once_with(self.db, message, scholarship_id=None)
        self.assertIsNone(reply["context"]["scholarship_id"])

    def test_explicit_general_question_clears_previous_scholarship_scope(self):
        reply, mocked = self._ask_info(
            "What do scholarships generally cover?",
            scholarship_id=self.scholarship.id,
        )
        mocked.assert_called_once_with(self.db, "What do scholarships generally cover?", scholarship_id=None)
        self.assertIsNone(reply["context"]["scholarship_id"])

    def test_ambiguous_matches_can_be_selected_by_record_id(self):
        fields = {k: v for k, v in vars(make_scholarship()).items() if k != "id"}
        similar = Scholarship(**{**fields, "name": "Alpha Award"})
        self.db.add(similar)
        self.db.flush()

        reply, mocked = self._ask_info(f"Tell me about scholarship ID {similar.id}")
        mocked.assert_called_once_with(self.db, f"Tell me about scholarship ID {similar.id}",
                                       scholarship_id=similar.id)
        self.assertEqual(reply["context"]["scholarship_id"], similar.id)

    def test_rag_scope_cannot_return_another_scholarships_chunks(self):
        from tests.test_rag_service import RagFixture
        fixture = RagFixture()
        fixture.setUp()
        try:
            other = Scholarship(country="Finland", name="Beta Grant", official_url="https://beta.example",
                                verification_status="verified", verification_basis="official_source",
                                official_info_url="https://beta.example/info",
                                last_verified_date=fixture.scholarship.last_verified_date,
                                source_checks=[], data_flags=[], record_version=1)
            fixture.db.add(other)
            fixture.db.commit()
            fixture.indexed(text="Alpha Grant covers tuition.")
            fixture.indexed(document=fixture.source(other), text="Beta Grant covers tuition.")
            query = "What does this scholarship cover?"
            alpha = [c.text for c in fixture.retrieve(query=query, scholarship_id=fixture.scholarship.id).chunks]
            beta = [c.text for c in fixture.retrieve(query=query, scholarship_id=other.id).chunks]
            unknown = fixture.retrieve(scholarship_id=99999)
        finally:
            fixture.tearDown()
        self.assertEqual(alpha, ["Alpha Grant covers tuition."])
        self.assertEqual(beta, ["Beta Grant covers tuition."])
        self.assertEqual(unknown.status, rag_service.STATUS_NO_SOURCES)

    def test_empty_knowledge_tables_give_no_source_reply(self):
        valid = "0123456789abcdef0123456789abcdef01234567"
        with patch.dict("os.environ", {"MINILM_MODEL_REVISION": valid}), \
                patch.object(rag_service, "embed_query", return_value=[0.1] * 384):
            reply = self.ask(self.alice, "What does Alpha Grant cover?")
        self.assertIn("approved official source", reply["summary"])

    def test_invalid_context_ids_are_ignored(self):
        reply = self.ask(self.alice, "Can I afford this?", scholarship_id=9999)
        self.assertIsNone(reply["action"]["state"])

    def test_unknown_question_offers_suggestions(self):
        reply = self.ask(self.alice, "hello there")
        self.assertEqual(len(reply["suggestions"]), 6)

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
