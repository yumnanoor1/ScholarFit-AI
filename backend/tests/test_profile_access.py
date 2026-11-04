"""
The profile-first rule, through the real routers and an in-memory database.
Run from the backend folder:  python -m unittest discover -s tests -v
"""
import asyncio
import json
import re
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import issue_session_token
from app.database import Base, get_db
from app.models.user import StudentProfile, User
from app.routers import admin_scholarships, assistant, auth, eligibility, financial_feasibility, profile, recommendations, saved_scholarships, scholarships
from app.services.google_identity import GoogleIdentity
from app.services.profile_completion import REQUIRED_FIELDS, profile_completion
from app.schemas.user import GoogleCredential

GATED_ROUTERS = (eligibility.router, financial_feasibility.router, recommendations.router, saved_scholarships.router)
COMPLETE = dict(nationality="Pakistan", degree_level="Bachelor's", field_of_study="Computer Science", institution="NUST",
                academic_status="studying", graduation_date="2027-06", cgpa=3.4, cgpa_scale=4.0, preferred_countries="Germany")


def build_app(session):
    app = FastAPI()
    for module in (auth, profile, scholarships, saved_scholarships, eligibility, financial_feasibility,
                   recommendations, admin_scholarships, assistant):
        app.include_router(module.router)
    app.dependency_overrides[get_db] = lambda: session
    return app


def call(app, method, path, token=None, body=None):
    headers = [(b"content-type", b"application/json")]
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    payload = json.dumps(body).encode() if body is not None else b""
    path, _, query = path.partition("?")
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "path": path, "raw_path": path.encode(),
             "root_path": "", "scheme": "http", "query_string": query.encode(), "headers": headers, "client": ("203.0.113.10", 1), "server": ("test", 80)}
    sent = []

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    text = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
    return sent[0]["status"], json.loads(text) if text else None


class ProfileAccessCase(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.app = build_app(self.db)
        self.incomplete = self.add_user("new@example.com")
        self.partial = self.add_user("partial@example.com", degree_level="Bachelor's", cgpa=3.1, field_of_study="Computer Science")
        self.complete = self.add_user("done@example.com", **COMPLETE)
        self.admin = self.add_user("admin@example.com", role="admin")

    def add_user(self, email, role="student", **profile_fields):
        user = User(email=email, hashed_password="hash", full_name="A Student", role=role)
        self.db.add(user)
        self.db.commit()
        if profile_fields:
            self.db.add(StudentProfile(user_id=user.id, **profile_fields))
            self.db.commit()
        return user

    def token(self, user):
        return issue_session_token(user)

    def status_of(self, user):
        return profile_completion(self.db, user)

    def gated_routes(self):
        for router in GATED_ROUTERS:
            for route in router.routes:
                if isinstance(route, APIRoute):
                    for method in route.methods:
                        yield method, re.sub(r"{[^}]+}", "1", route.path)


class CompletionRuleTests(ProfileAccessCase):
    def test_every_required_field_is_needed(self):
        for label, field_values in (("Nationality", {"nationality": ""}), ("Current or highest degree", {"degree_level": None}),
                                    ("Field of study", {"field_of_study": " "}), ("University", {"institution": None}),
                                    ("Study status", {"academic_status": None}), ("Graduation date", {"graduation_date": ""}),
                                    ("CGPA and grading scale", {"cgpa": None}), ("Preferred study destination", {"preferred_countries": " , "})):
            with self.subTest(label):
                user = self.add_user(f"{label.split()[0].lower()}-{len(label)}@example.com", **{**COMPLETE, **field_values})
                self.assertEqual(self.status_of(user).missing, [label])

    def test_the_forms_fallback_values_are_not_answers(self):
        self.assertTrue(self.status_of(self.add_user("zero@example.com", **{**COMPLETE, "cgpa": 0.0})).complete)
        self.assertIn("Field of study", self.status_of(self.add_user("general@example.com", **{**COMPLETE, "field_of_study": "General"})).missing)

    def test_an_unknown_study_status_or_impossible_grade_is_not_complete(self):
        self.assertFalse(self.status_of(self.add_user("odd@example.com", **{**COMPLETE, "academic_status": "maybe"})).complete)
        self.assertFalse(self.status_of(self.add_user("high@example.com", **{**COMPLETE, "cgpa": 5.0})).complete)

    def test_optional_fields_are_not_required(self):
        status = self.status_of(self.complete)
        self.assertTrue(status.complete)
        self.assertEqual((status.percent, status.missing), (100, []))

    def test_a_blank_account_name_counts_against_completion(self):
        self.complete.full_name = " "
        self.assertEqual(self.status_of(self.complete).missing, ["Full name"])

    def test_percent_reflects_real_progress(self):
        total = len(REQUIRED_FIELDS) + 1
        self.assertEqual(self.status_of(self.incomplete).percent, round(100 / total))
        self.assertGreater(self.status_of(self.partial).percent, self.status_of(self.incomplete).percent)
        self.assertLess(self.status_of(self.partial).percent, 100)


class StatusEndpointTests(ProfileAccessCase):
    def test_works_before_a_profile_exists(self):
        status, body = call(self.app, "GET", "/profile/status", self.token(self.incomplete))
        self.assertEqual(status, 200)
        self.assertEqual((body["required"], body["complete"]), (True, False))
        self.assertIn("University", body["missing"])

    def test_a_finished_profile_reports_complete(self):
        self.assertTrue(call(self.app, "GET", "/profile/status", self.token(self.complete))[1]["complete"])

    def test_needs_a_sign_in(self):
        self.assertEqual(call(self.app, "GET", "/profile/status")[0], 401)

    def test_administrators_do_not_need_a_profile(self):
        self.assertFalse(call(self.app, "GET", "/profile/status", self.token(self.admin))[1]["required"])


class GateTests(ProfileAccessCase):
    def test_every_gated_route_refuses_an_incomplete_student(self):
        token = self.token(self.incomplete)
        routes = list(self.gated_routes())
        self.assertGreaterEqual(len(routes), 8)
        for method, path in routes:
            with self.subTest(f"{method} {path}"):
                status, body = call(self.app, method, path, token, body={})
                self.assertEqual(status, 403)
                self.assertEqual(body["detail"]["code"], "profile_incomplete")

    def test_a_partial_profile_is_refused_and_told_what_is_missing(self):
        status, body = call(self.app, "GET", "/saved-scholarships/", self.token(self.partial))
        self.assertEqual(status, 403)
        self.assertIn("University", body["detail"]["missing"])

    def test_every_gated_route_still_needs_a_sign_in(self):
        for method, path in self.gated_routes():
            with self.subTest(f"{method} {path}"):
                self.assertEqual(call(self.app, method, path, body={})[0], 401)

    def test_a_complete_student_gets_through(self):
        token = self.token(self.complete)
        for path in ("/saved-scholarships/", "/recommendations/scholarships", "/eligibility/scholarships", "/financial-feasibility/plan"):
            with self.subTest(path):
                self.assertEqual(call(self.app, "GET", path, token)[0], 200)

    def test_university_and_program_routers_are_not_active(self):
        paths = {route.path for route in self.app.routes}
        self.assertFalse(any(path.startswith(("/universities", "/programs")) for path in paths))

    def test_finishing_the_profile_unlocks_straight_away(self):
        token = self.token(self.partial)
        self.assertEqual(call(self.app, "GET", "/saved-scholarships/", token)[0], 403)
        self.assertEqual(call(self.app, "PUT", "/profile/", token, COMPLETE)[0], 200)
        self.assertEqual(call(self.app, "GET", "/saved-scholarships/", token)[0], 200)

    def test_clearing_a_required_field_locks_it_again(self):
        token = self.token(self.complete)
        self.assertEqual(call(self.app, "PUT", "/profile/", token, {"institution": ""})[0], 200)
        self.assertEqual(call(self.app, "GET", "/saved-scholarships/", token)[0], 403)

    def test_an_ordinary_edit_keeps_the_profile_complete(self):
        token = self.token(self.complete)
        self.assertEqual(call(self.app, "PUT", "/profile/", token, {"cgpa": 3.2, "skills": None})[0], 200)
        self.assertTrue(self.status_of(self.complete).complete)
        self.assertEqual(call(self.app, "GET", "/saved-scholarships/", token)[0], 200)

    def test_a_cleared_field_is_named_and_restoring_it_unlocks_again(self):
        token = self.token(self.complete)
        call(self.app, "PUT", "/profile/", token, {"institution": None})
        status_code, body = call(self.app, "GET", "/profile/status", token)
        self.assertEqual(status_code, 200)
        self.assertEqual((body["complete"], body["missing"]), (False, ["University"]))
        self.assertEqual(call(self.app, "PUT", "/profile/", token, {"institution": "NUST"})[0], 200)
        self.assertEqual(call(self.app, "GET", "/saved-scholarships/", token)[0], 200)

    def test_an_edit_cannot_claim_completion(self):
        token = self.token(self.complete)
        call(self.app, "PUT", "/profile/", token, {"institution": "", "profile_completed": True})
        self.assertFalse(self.status_of(self.complete).complete)

    def test_an_administrator_is_not_gated(self):
        self.assertEqual(call(self.app, "GET", "/saved-scholarships/", self.token(self.admin))[0], 200)

    def test_the_client_cannot_claim_completion(self):
        token = self.token(self.partial)
        for claim in ({"profile_completed": True}, {"profile_complete": True, "complete": True, "percent": 100}):
            self.assertEqual(call(self.app, "PUT", "/profile/", token, claim)[0], 200)
        self.assertEqual(call(self.app, "GET", "/saved-scholarships/", token)[0], 403)


class OpenRouteTests(ProfileAccessCase):
    def test_profile_routes_stay_open_to_an_incomplete_student(self):
        token = self.token(self.incomplete)
        self.assertEqual(call(self.app, "GET", "/profile/", token)[0], 404)
        created = {"degree_level": "Bachelor's", "field_of_study": "Computer Science", "cgpa": 3.0, "cgpa_scale": 4.0}
        self.assertEqual(call(self.app, "POST", "/profile/", token, created)[0], 201)
        self.assertEqual(call(self.app, "PUT", "/profile/", token, {"nationality": "Pakistan"})[0], 200)

    def test_profile_fields_round_trip_and_partial_updates_merge(self):
        token = self.token(self.incomplete)
        payload = {
            "degree_level": "Bachelor's",
            "field_of_study": "Computer Science",
            "cgpa": 0,
            "cgpa_scale": 4,
            "preferred_fields": ["Data Science"],
            "preferred_degree_levels": ["Master's"],
            "preferred_funding_types": ["Tuition waivers"],
            "funding_preference": "Fully funded only",
            "language_test": {
                "test_type": "TOEFL iBT",
                "overall_score": 105,
                "listening": 28,
                "reading": 27,
                "writing": 25,
                "speaking": 26,
                "test_date": "2024-06-15",
                "test_status": "Completed",
            },
            "tuition_budget_amount": 1250,
            "tuition_budget_currency": "EUR",
            "living_budget_amount": 700,
            "living_budget_currency": "EUR",
            "budget_usd": None,
            "form_details": {
                "academicBackground": {"major": "Computer Science", "workExperience": "Research assistant"},
                "studyPreferences": {"currency": "EUR"},
            },
        }
        status_code, created = call(self.app, "POST", "/profile/", token, payload)
        self.assertEqual(status_code, 201)
        self.assertEqual(created["cgpa"], 0)
        self.assertEqual(created["field_of_study"], "Computer Science")
        self.assertEqual(created["preferred_fields"], ["Data Science"])
        self.assertEqual(created["preferred_degree_levels"], ["Master's"])
        self.assertEqual(created["preferred_funding_types"], ["Tuition waivers"])
        self.assertEqual(created["language_test"]["listening"], 28)
        self.assertEqual(created["language_test"]["test_date"], "2024-06-15")
        self.assertEqual(created["toefl_score"], 105)
        self.assertEqual(created["tuition_budget_currency"], "EUR")
        self.assertIsNone(created["budget_usd"])

        updated_status, updated = call(
            self.app,
            "PUT",
            "/profile/",
            token,
            {
                "tuition_budget_amount": 1500,
                "language_test": {
                    "test_type": "TOEFL iBT",
                    "overall_score": 106,
                    "test_date": "2024-06-15",
                    "test_status": "Completed",
                },
                "form_details": {"academicBackground": {"workExperience": "Teaching assistant"}},
            },
        )
        self.assertEqual(updated_status, 200)
        self.assertEqual(updated["tuition_budget_amount"], 1500)
        self.assertEqual(updated["tuition_budget_currency"], "EUR")
        self.assertEqual(updated["language_test"]["overall_score"], 106)
        self.assertEqual(updated["toefl_score"], 106)
        self.assertEqual(updated["form_details"]["academicBackground"]["major"], "Computer Science")
        self.assertEqual(updated["form_details"]["academicBackground"]["workExperience"], "Teaching assistant")
        self.assertEqual(updated["preferred_fields"], ["Data Science"])

    def test_a_complete_profile_persists_and_unlocks_after_reload(self):
        token = self.token(self.incomplete)
        details = {
            "personalInfo": {"fullName": "A Student", "email": "new@example.com"},
            "academicBackground": {"major": "Computer Science"},
            "englishProficiency": {"willingToTest": "Yes"},
            "studyPreferences": {"countries": ["Germany"]},
            "documentAvailability": {"transcript": "Available"},
        }
        status_code, _ = call(
            self.app,
            "POST",
            "/profile/",
            token,
            {
                **COMPLETE,
                "preferred_fields": ["Data Science"],
                "preferred_degree_levels": ["Master's"],
                "preferred_funding_types": ["Tuition waivers"],
                "form_details": details,
            },
        )
        self.assertEqual(status_code, 201)

        status_code, completion = call(self.app, "GET", "/profile/status", token)
        self.assertEqual(status_code, 200)
        self.assertTrue(completion["complete"])

        status_code, restored = call(self.app, "GET", "/profile/", token)
        self.assertEqual(status_code, 200)
        self.assertEqual(restored["form_details"], details)
        self.assertEqual(restored["preferred_fields"], ["Data Science"])

    def test_profile_validation_rejects_missing_scale_and_unpaired_budgets(self):
        token = self.token(self.incomplete)
        missing_scale = {"degree_level": "Bachelor's", "field_of_study": "Computer Science", "cgpa": 3.0}
        self.assertEqual(call(self.app, "POST", "/profile/", token, missing_scale)[0], 422)

        unpaired_budget = {
            "degree_level": "Bachelor's",
            "field_of_study": "Computer Science",
            "tuition_budget_amount": 1000,
        }
        self.assertEqual(call(self.app, "POST", "/profile/", token, unpaired_budget)[0], 422)

    def test_profile_validation_rejects_language_scores_outside_test_scale(self):
        token = self.token(self.incomplete)
        payload = {
            "degree_level": "Bachelor's",
            "field_of_study": "Computer Science",
            "language_test": {
                "test_type": "IELTS",
                "overall_score": 9.5,
                "test_status": "Completed",
            },
        }
        self.assertEqual(call(self.app, "POST", "/profile/", token, payload)[0], 422)

    def test_profile_updates_reject_blank_academic_fields_and_invalid_status(self):
        token = self.token(self.complete)
        for payload in (
            {"field_of_study": " "},
            {"degree_level": ""},
            {"academic_status": "on leave"},
            {"graduation_date": "2027-13"},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(call(self.app, "PUT", "/profile/", token, payload)[0], 422)

    def test_profile_reads_are_scoped_to_the_authenticated_user(self):
        first = self.add_user("profile-one@example.com", degree_level="Bachelor's", field_of_study="Chemistry")
        second = self.add_user("profile-two@example.com", degree_level="Master's", field_of_study="Physics")
        first_body = call(self.app, "GET", "/profile/", self.token(first))[1]
        second_body = call(self.app, "GET", "/profile/", self.token(second))[1]
        self.assertEqual(first_body["user_id"], first.id)
        self.assertEqual(first_body["field_of_study"], "Chemistry")
        self.assertEqual(second_body["user_id"], second.id)
        self.assertEqual(second_body["field_of_study"], "Physics")

    def test_account_details_stay_open(self):
        self.assertEqual(call(self.app, "GET", "/auth/me", self.token(self.incomplete))[0], 200)

    def test_sign_in_is_not_gated(self):
        with mock.patch.object(auth, "verify_password", return_value=True):
            reply = auth.login(SimpleNamespace(client=SimpleNamespace(host="203.0.113.11")), SimpleNamespace(username=self.incomplete.email, password="x"), self.db)
        self.assertIn("access_token", reply)

    def test_a_new_google_account_is_not_treated_as_complete(self):
        identity = GoogleIdentity(sub="sub-1", email="google@gmail.com", name="Google Student")
        with mock.patch.object(auth, "verify_google_credential", return_value=identity):
            reply = auth.google_sign_in(GoogleCredential(credential="c" * 40), SimpleNamespace(client=SimpleNamespace(host="203.0.113.12")), self.db)
        status, body = call(self.app, "GET", "/profile/status", reply["access_token"])
        self.assertEqual((status, body["complete"]), (200, False))
        self.assertEqual(call(self.app, "GET", "/saved-scholarships/", reply["access_token"])[0], 403)

    def test_an_existing_google_login_with_a_finished_profile_gets_through(self):
        self.complete.google_sub = "sub-done"
        self.db.commit()
        identity = GoogleIdentity(sub="sub-done", email=self.complete.email, name="Done")
        with mock.patch.object(auth, "verify_google_credential", return_value=identity):
            reply = auth.google_sign_in(GoogleCredential(credential="c" * 40), SimpleNamespace(client=SimpleNamespace(host="203.0.113.13")), self.db)
        self.assertEqual(call(self.app, "GET", "/saved-scholarships/", reply["access_token"])[0], 200)

    def test_browsing_stays_open_with_no_personal_results(self):
        token = self.token(self.incomplete)
        status, body = call(self.app, "GET", "/scholarships/search", token)
        self.assertEqual(status, 200)
        self.assertIn("items", body)
        self.assertEqual(call(self.app, "GET", "/universities/", token)[0], 200)

    def test_personal_search_needs_a_finished_profile(self):
        path = "/scholarships/search?sort=recommendation"
        self.assertEqual(call(self.app, "GET", path)[0], 401)
        status, body = call(self.app, "GET", path, self.token(self.incomplete))
        self.assertEqual((status, body["detail"]["code"]), (403, "profile_incomplete"))
        self.assertEqual(call(self.app, "GET", path, self.token(self.complete))[0], 200)


class AdminTests(ProfileAccessCase):
    def test_admin_routes_still_accept_only_admins(self):
        self.assertEqual(call(self.app, "GET", "/admin/scholarships/summary", self.token(self.admin))[0], 200)
        self.assertEqual(call(self.app, "GET", "/admin/scholarships/summary", self.token(self.complete))[0], 403)
        self.assertEqual(call(self.app, "GET", "/admin/scholarships/summary")[0], 401)

    def test_the_admin_refusal_message_is_unchanged(self):
        self.assertEqual(call(self.app, "GET", "/admin/scholarships/summary", self.token(self.incomplete))[1]["detail"], "Only an admin can perform this action")

    def test_a_role_is_never_changed_by_the_check(self):
        self.status_of(self.admin)
        self.db.refresh(self.admin)
        self.assertEqual(self.admin.role, "admin")


if __name__ == "__main__":
    unittest.main()
