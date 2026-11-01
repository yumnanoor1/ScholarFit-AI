"""
Google sign-in. Google's verifier is mocked, and everything runs on an in-memory database.
Run from the backend folder:  python -m unittest discover -s tests -v
"""
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi import BackgroundTasks, HTTPException
from google.auth import exceptions as google_errors
from passlib.context import CryptContext
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import rate_limit as limits
from app.core import security
from app.core.config import validate_settings
from app.core.permissions import require_admin
from app.core.security import decode_access_token, hash_password, verify_password
from app.database import Base
from app.models.user import User
from app.routers import auth as api
from app.schemas.user import ForgotPasswordRequest, GoogleCredential, GoogleLinkRequest, ResetPasswordRequest, UserCreate, UserResponse
from app.services import google_identity
from app.services.google_identity import GoogleIdentity, GoogleTokenRejected, GoogleUnavailable, verify_google_credential

PASSWORD = "Original-1"
CREDENTIAL = "google-id-token-" + "x" * 40
CLIENT_ID = "test-client.apps.googleusercontent.com"
NEW_PERSON = GoogleIdentity(sub="sub-new", email="new@gmail.com", name="New Person")
STUDENT = GoogleIdentity(sub="sub-student", email="student@example.com", name="Name From Google")
ADMIN = GoogleIdentity(sub="sub-admin", email="admin@example.com", name="Admin From Google")


def visitor(ip="203.0.113.10"):
    return SimpleNamespace(client=SimpleNamespace(host=ip))


class GoogleCase(unittest.TestCase):
    def setUp(self):
        for limit in limits.ALL_LIMITS:
            limit.clear()
        fast_hashing = mock.patch.object(security, "pwd_context", CryptContext(schemes=["bcrypt"], bcrypt__rounds=4))
        fast_hashing.start()
        self.addCleanup(fast_hashing.stop)
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        self.sessions = sessionmaker(bind=engine)
        self.db = self.sessions()
        self.addCleanup(self.db.close)
        self.student = User(email="student@example.com", hashed_password=hash_password(PASSWORD), full_name="Student", role="student")
        self.admin = User(email="admin@example.com", hashed_password=hash_password(PASSWORD), full_name="Admin", role="admin")
        self.db.add_all([self.student, self.admin])
        self.db.commit()

    def sign_in(self, identity, ip="203.0.113.10"):
        with mock.patch.object(api, "verify_google_credential", return_value=identity):
            return api.google_sign_in(GoogleCredential(credential=CREDENTIAL), visitor(ip), self.db)

    def link(self, identity, password=PASSWORD, ip="203.0.113.10"):
        with mock.patch.object(api, "verify_google_credential", return_value=identity):
            return api.link_google_account(GoogleLinkRequest(credential=CREDENTIAL, password=password), visitor(ip), self.db)

    def refused(self, call):
        with self.assertRaises(HTTPException) as refused:
            call()
        return refused.exception

    def account_of(self, reply):
        return api.get_current_user(reply["access_token"], self.db)

    def users(self):
        return self.db.query(User).count()


class GoogleLoginTests(GoogleCase):
    def test_a_new_person_gets_a_student_account(self):
        user = self.account_of(self.sign_in(NEW_PERSON))
        self.assertEqual((user.email, user.full_name, user.role, user.google_sub), ("new@gmail.com", "New Person", "student", "sub-new"))

    def test_the_session_is_the_normal_session(self):
        reply = self.sign_in(NEW_PERSON)
        self.assertEqual(reply["token_type"], "bearer")
        self.assertEqual(set(decode_access_token(reply["access_token"])), {"sub", "email", "pwd", "exp"})

    def test_a_linked_account_signs_in_without_creating_another(self):
        first = self.account_of(self.sign_in(NEW_PERSON))
        count = self.users()
        self.assertEqual(self.account_of(self.sign_in(NEW_PERSON)).id, first.id)
        self.assertEqual(self.users(), count)

    def test_the_stable_sub_identifies_the_person_when_their_email_changes(self):
        first = self.account_of(self.sign_in(NEW_PERSON))
        renamed = GoogleIdentity(sub=NEW_PERSON.sub, email="renamed@gmail.com", name="New Person")
        self.assertEqual(self.account_of(self.sign_in(renamed)).id, first.id)

    def test_an_unlinked_existing_email_needs_the_password(self):
        refused = self.refused(lambda: self.sign_in(STUDENT))
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.detail["code"], "link_required")
        self.db.refresh(self.student)
        self.assertIsNone(self.student.google_sub)

    def test_email_capitals_do_not_get_around_linking(self):
        self.student.email = "Student@Example.com"
        self.db.commit()
        self.assertEqual(self.refused(lambda: self.sign_in(STUDENT)).detail["code"], "link_required")
        self.assertEqual(self.users(), 2)

    def test_a_different_google_identity_cannot_use_a_linked_email(self):
        self.link(STUDENT)
        other = GoogleIdentity(sub="sub-other", email=STUDENT.email, name="Other")
        self.assertEqual(self.refused(lambda: self.sign_in(other)).status_code, 409)

    def test_two_first_sign_ins_at_once_make_one_account(self):
        real_commit = self.db.commit

        def loses_the_race():
            self.db.rollback()
            with self.sessions() as other:
                other.add(User(email=NEW_PERSON.email, hashed_password="x", full_name="Winner", role="student", google_sub=NEW_PERSON.sub))
                other.commit()
            self.db.commit = real_commit
            raise IntegrityError("insert", {}, Exception("duplicate"))

        with mock.patch.object(self.db, "commit", side_effect=loses_the_race):
            reply = self.sign_in(NEW_PERSON)
        self.assertEqual(self.account_of(reply).full_name, "Winner")
        self.assertEqual(self.db.query(User).filter(User.google_sub == NEW_PERSON.sub).count(), 1)

    def test_an_email_taken_during_sign_up_falls_back_to_linking(self):
        def loses_the_race():
            self.db.rollback()
            raise IntegrityError("insert", {}, Exception("duplicate"))

        with mock.patch.object(self.db, "commit", side_effect=loses_the_race):
            refused = self.refused(lambda: self.sign_in(NEW_PERSON))
        self.assertEqual(refused.detail["code"], "link_required")


class GoogleLinkTests(GoogleCase):
    def test_the_right_password_links_and_signs_in(self):
        self.assertEqual(self.account_of(self.link(STUDENT)).id, self.student.id)
        self.db.refresh(self.student)
        self.assertEqual(self.student.google_sub, STUDENT.sub)
        self.assertEqual(self.account_of(self.sign_in(STUDENT)).id, self.student.id)

    def test_a_wrong_password_links_nothing(self):
        refused = self.refused(lambda: self.link(STUDENT, password="Wrong-Pass-1"))
        self.assertEqual(refused.status_code, 401)
        self.db.refresh(self.student)
        self.assertIsNone(self.student.google_sub)

    def test_linking_keeps_the_password_name_and_existing_sessions(self):
        session = api.login(visitor(), SimpleNamespace(username=self.student.email, password=PASSWORD), self.db)
        self.link(STUDENT)
        self.db.refresh(self.student)
        self.assertTrue(verify_password(PASSWORD, self.student.hashed_password))
        self.assertEqual(self.student.full_name, "Student")
        self.assertEqual(self.account_of(session).id, self.student.id)

    def test_password_guesses_share_the_login_limit(self):
        for _ in range(10):
            self.refused(lambda: self.link(STUDENT, password="Wrong-Pass-1"))
        self.assertEqual(self.refused(lambda: self.link(STUDENT)).status_code, 429)
        login = lambda: api.login(visitor(), SimpleNamespace(username=STUDENT.email, password=PASSWORD), self.db)
        self.assertEqual(self.refused(login).status_code, 429)

    def test_an_identity_cannot_be_linked_to_two_accounts(self):
        self.link(STUDENT)
        same_person = GoogleIdentity(sub=STUDENT.sub, email=ADMIN.email, name="Same Person")
        self.assertEqual(self.refused(lambda: self.link(same_person)).status_code, 409)
        self.db.refresh(self.admin)
        self.assertIsNone(self.admin.google_sub)

    def test_an_account_cannot_be_linked_to_two_identities(self):
        self.link(STUDENT)
        other = GoogleIdentity(sub="sub-other", email=STUDENT.email, name="Other")
        self.assertEqual(self.refused(lambda: self.link(other)).status_code, 409)
        self.db.refresh(self.student)
        self.assertEqual(self.student.google_sub, STUDENT.sub)

    def test_the_database_refuses_a_duplicate_identity(self):
        self.student.google_sub = "sub-same"
        self.admin.google_sub = "sub-same"
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_unlinked_accounts_can_share_an_empty_identity(self):
        self.db.refresh(self.student)
        self.db.refresh(self.admin)
        self.assertIsNone(self.student.google_sub)
        self.assertIsNone(self.admin.google_sub)

    def test_linking_with_no_matching_account_is_refused(self):
        self.assertEqual(self.refused(lambda: self.link(NEW_PERSON)).status_code, 401)
        self.assertEqual(self.users(), 2)


class GoogleRoleTests(GoogleCase):
    def test_an_admin_stays_an_admin_after_linking(self):
        user = self.account_of(self.link(ADMIN))
        self.assertEqual(require_admin(user).role, "admin")
        self.assertEqual(require_admin(self.account_of(self.sign_in(ADMIN))).role, "admin")

    def test_an_admin_is_not_signed_in_without_the_password(self):
        self.assertEqual(self.refused(lambda: self.sign_in(ADMIN)).detail["code"], "link_required")

    def test_google_never_grants_admin(self):
        self.assertEqual(self.refused(lambda: require_admin(self.account_of(self.sign_in(NEW_PERSON)))).status_code, 403)

    def test_a_request_cannot_supply_a_role_or_email(self):
        data = GoogleCredential(credential=CREDENTIAL, role="admin", email="admin@example.com")
        self.assertFalse(hasattr(data, "role"))
        self.assertFalse(hasattr(data, "email"))


class GooglePasswordTests(GoogleCase):
    def test_a_google_only_account_has_no_usable_password(self):
        user = self.account_of(self.sign_in(NEW_PERSON))
        self.assertTrue(user.hashed_password.startswith("$2"))
        attempt = lambda: api.login(visitor(), SimpleNamespace(username=user.email, password=""), self.db)
        self.assertEqual(self.refused(attempt).status_code, 401)

    def test_a_password_reset_still_ends_google_sessions(self):
        reply = self.sign_in(NEW_PERSON)
        with mock.patch.object(api.secrets, "token_urlsafe", return_value="r" * 43):
            api.forgot_password(ForgotPasswordRequest(email=NEW_PERSON.email), BackgroundTasks(), visitor(), self.db)
        api.reset_password(ResetPasswordRequest(token="r" * 43, new_password="Changed-22"), visitor(), self.db)
        self.assertEqual(self.refused(lambda: self.account_of(reply)).status_code, 401)
        self.assertEqual(self.account_of(self.sign_in(NEW_PERSON)).email, NEW_PERSON.email)

    def test_a_reset_after_linking_keeps_the_link(self):
        self.link(STUDENT)
        with mock.patch.object(api.secrets, "token_urlsafe", return_value="s" * 43):
            api.forgot_password(ForgotPasswordRequest(email=STUDENT.email), BackgroundTasks(), visitor(), self.db)
        api.reset_password(ResetPasswordRequest(token="s" * 43, new_password="Changed-22"), visitor(), self.db)
        self.assertEqual(self.account_of(self.sign_in(STUDENT)).id, self.student.id)


class PasswordRegressionTests(GoogleCase):
    def test_register_then_login_still_work(self):
        created = api.register(UserCreate(email="fresh@example.com", password="Fresh-Pass-1", full_name="Fresh"), visitor(), self.db)
        self.assertEqual(created.role, "student")
        self.assertIsNone(created.google_sub)
        reply = api.login(visitor(), SimpleNamespace(username="fresh@example.com", password="Fresh-Pass-1"), self.db)
        self.assertEqual(self.account_of(reply).id, created.id)

    def test_registration_rejects_case_insensitive_duplicate_email(self):
        error = self.refused(lambda: api.register(
            UserCreate(email="STUDENT@example.com", password=PASSWORD, full_name="Duplicate"),
            visitor(), self.db))
        self.assertEqual(error.status_code, 400)
        self.assertEqual(self.users(), 2)

    def test_login_accepts_email_with_different_case(self):
        reply = api.login(visitor(), SimpleNamespace(username="STUDENT@EXAMPLE.COM", password=PASSWORD), self.db)
        self.assertEqual(self.account_of(reply).id, self.student.id)

    def test_registration_concurrent_duplicate_returns_client_error(self):
        original_commit = self.db.commit

        def simulate_unique_constraint_race():
            self.db.rollback()
            self.db.add(User(
                email="race@example.com",
                hashed_password=hash_password(PASSWORD),
                full_name="Concurrent registration",
                role="student",
            ))
            original_commit()
            raise IntegrityError("insert", {}, Exception("unique email"))

        with mock.patch.object(self.db, "commit", side_effect=simulate_unique_constraint_race):
            error = self.refused(lambda: api.register(
                UserCreate(email="race@example.com", password=PASSWORD, full_name="New"),
                visitor(), self.db))
        self.assertEqual(error.status_code, 400)
        self.assertEqual(self.db.query(User).filter(User.email == "race@example.com").count(), 1)

    def test_a_wrong_password_is_still_refused(self):
        attempt = lambda: api.login(visitor(), SimpleNamespace(username=self.student.email, password="Wrong-Pass-1"), self.db)
        self.assertEqual(self.refused(attempt).status_code, 401)

    def test_a_linked_account_can_still_use_its_password(self):
        self.link(STUDENT)
        reply = api.login(visitor(), SimpleNamespace(username=self.student.email, password=PASSWORD), self.db)
        self.assertEqual(self.account_of(reply).id, self.student.id)

    def test_the_account_reply_does_not_show_the_identity(self):
        self.assertNotIn("google_sub", UserResponse.model_fields)


class GoogleVerificationTests(unittest.TestCase):
    CLAIMS = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "sub-1", "email": "Person@Gmail.com", "email_verified": True, "name": "Person"}

    def verify(self, claims=None, error=None):
        verifier = mock.Mock(return_value={**self.CLAIMS, **(claims or {})}, side_effect=error)
        with mock.patch.dict(os.environ, {"GOOGLE_CLIENT_ID": CLIENT_ID}), mock.patch.object(google_identity.id_token, "verify_oauth2_token", verifier):
            return verify_google_credential(CREDENTIAL), verifier

    def test_a_good_token_gives_the_identity(self):
        identity, verifier = self.verify()
        self.assertEqual(identity, GoogleIdentity(sub="sub-1", email="person@gmail.com", name="Person"))
        self.assertEqual(verifier.call_args.args[2], CLIENT_ID)

    def test_the_older_issuer_spelling_is_accepted(self):
        self.assertEqual(self.verify({"iss": "accounts.google.com"})[0].sub, "sub-1")

    def test_a_wrong_issuer_is_rejected(self):
        with self.assertRaises(GoogleTokenRejected):
            self.verify({"iss": "https://evil.example"})

    def test_invalid_and_expired_tokens_are_rejected(self):
        for error in (ValueError("Token used too late"), google_errors.InvalidValue("Token has wrong audience"), google_errors.MalformedError("bad"), google_errors.GoogleAuthError("wrong issuer")):
            with self.assertRaises(GoogleTokenRejected):
                self.verify(error=error)

    def test_an_unverified_email_is_rejected(self):
        for value in (False, None, "true"):
            with self.assertRaises(GoogleTokenRejected) as rejected:
                self.verify({"email_verified": value})
            self.assertIn("isn't verified", str(rejected.exception))

    def test_a_token_missing_identity_claims_is_rejected(self):
        for claims in ({"sub": ""}, {"email": ""}):
            with self.assertRaises(GoogleTokenRejected):
                self.verify(claims)

    def test_a_google_outage_is_not_an_invalid_token(self):
        with self.assertRaises(GoogleUnavailable):
            self.verify(error=google_errors.TransportError("keys unreachable"))

    def test_a_missing_client_id_never_skips_verification(self):
        verifier = mock.Mock()
        with mock.patch.dict(os.environ, {"GOOGLE_CLIENT_ID": " "}), mock.patch.object(google_identity.id_token, "verify_oauth2_token", verifier):
            with self.assertRaises(GoogleUnavailable):
                verify_google_credential(CREDENTIAL)
        verifier.assert_not_called()

    def test_the_token_is_never_logged(self):
        with self.assertLogs("app.services.google_identity", "WARNING") as logs:
            with self.assertRaises(GoogleUnavailable):
                self.verify(error=google_errors.TransportError(CREDENTIAL))
        self.assertNotIn(CREDENTIAL, "".join(logs.output))


class GoogleEndpointFailureTests(GoogleCase):
    def attempt(self, error, ip="203.0.113.10"):
        with mock.patch.object(api, "verify_google_credential", side_effect=error):
            return self.refused(lambda: api.google_sign_in(GoogleCredential(credential=CREDENTIAL), visitor(ip), self.db))

    def test_a_rejected_token_is_401_and_creates_nothing(self):
        self.assertEqual(self.attempt(GoogleTokenRejected("Google sign-in could not be verified.")).status_code, 401)
        self.assertEqual(self.users(), 2)

    def test_an_outage_is_503_and_not_counted_against_the_visitor(self):
        for _ in range(40):
            self.assertEqual(self.attempt(GoogleUnavailable()).status_code, 503)

    def test_repeated_bad_tokens_are_limited(self):
        for _ in range(30):
            self.attempt(GoogleTokenRejected("no"))
        self.assertEqual(self.attempt(GoogleTokenRejected("no")).status_code, 429)
        self.assertEqual(self.attempt(GoogleTokenRejected("no"), ip="203.0.113.99").status_code, 401)

    def test_new_accounts_share_the_registration_limit(self):
        for number in range(30):
            self.sign_in(GoogleIdentity(sub=f"sub-{number}", email=f"p{number}@gmail.com", name="P"))
        extra = GoogleIdentity(sub="sub-extra", email="extra@gmail.com", name="Extra")
        self.assertEqual(self.refused(lambda: self.sign_in(extra)).status_code, 429)

    def test_a_short_credential_is_refused_before_google_is_asked(self):
        with self.assertRaises(ValidationError):
            GoogleCredential(credential="short")


class GoogleSettingsTests(unittest.TestCase):
    def test_production_needs_the_client_id(self):
        settings = {"APP_ENV": "production", "SECRET_KEY": "k" * 64, "DATABASE_URL": "postgresql://app:strong@db.internal/fit",
                    "FRONTEND_URL": "https://fitscholar.example", "SMTP_HOST": "smtp.example.com", "SMTP_FROM": "no-reply@example.com"}
        with mock.patch.dict(os.environ, settings), mock.patch.dict(os.environ, {"GOOGLE_CLIENT_ID": ""}):
            with self.assertRaises(RuntimeError) as stopped:
                validate_settings()
        self.assertIn("GOOGLE_CLIENT_ID", str(stopped.exception))


if __name__ == "__main__":
    unittest.main()
