"""
Password reset, session and CORS tests. Handlers run against in-memory SQLite.
Run from the backend folder:  python -m unittest discover -s tests -v
"""
import contextlib
import io
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.cors import LOCAL_ORIGINS, allowed_origins
from app.core import rate_limit as limits
from app.core.security import hash_password, issue_session_token, verify_password
from app.database import Base
from app.models.user import PasswordResetToken, User
from app.routers import auth as api
from app.schemas.user import ForgotPasswordRequest, ResetPasswordRequest
from app.services.email_service import send_email


VISITOR = SimpleNamespace(client=SimpleNamespace(host="203.0.113.10"))


class PasswordResetTests(unittest.TestCase):
    def setUp(self):
        for limit in limits.ALL_LIMITS:
            limit.clear()
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        self.user = User(email="student@example.com", hashed_password=hash_password("Original-1"), full_name="Student")
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def request_link(self, token="a" * 43):
        with mock.patch.object(api.secrets, "token_urlsafe", return_value=token):
            return api.forgot_password(ForgotPasswordRequest(email=self.user.email), BackgroundTasks(), VISITOR, self.db)

    def reset(self, token="a" * 43, password="Changed-22"):
        return api.reset_password(ResetPasswordRequest(token=token, new_password=password), VISITOR, self.db)

    def assert_refused(self, token="a" * 43):
        with self.assertRaises(HTTPException) as refused:
            self.reset(token)
        self.assertEqual(refused.exception.status_code, 400)

    def test_reset_changes_the_password(self):
        self.request_link()
        self.reset()
        self.db.refresh(self.user)
        self.assertTrue(verify_password("Changed-22", self.user.hashed_password))
        self.assertFalse(verify_password("Original-1", self.user.hashed_password))

    def test_only_a_hash_of_the_token_is_stored(self):
        self.request_link()
        self.assertNotEqual(self.db.query(PasswordResetToken).one().token_hash, "a" * 43)

    def test_unknown_token_is_refused(self):
        self.request_link()
        self.assert_refused("b" * 43)

    def test_expired_token_is_refused(self):
        self.request_link()
        self.db.query(PasswordResetToken).one().expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.db.commit()
        self.assert_refused()

    def test_reused_token_is_refused(self):
        self.request_link()
        self.reset()
        self.assert_refused()

    def test_a_new_request_replaces_the_old_link(self):
        self.request_link("a" * 43)
        self.request_link("c" * 43)
        self.assert_refused("a" * 43)
        self.reset("c" * 43)

    def test_unknown_email_gets_the_same_reply(self):
        known = self.request_link()
        unknown = api.forgot_password(ForgotPasswordRequest(email="nobody@example.com"), BackgroundTasks(), VISITOR, self.db)
        self.assertEqual(known, unknown)

    def sign_in(self):
        return issue_session_token(self.user)

    def test_a_reset_ends_earlier_sign_ins(self):
        token = self.sign_in()
        self.assertEqual(api.get_current_user(token, self.db).id, self.user.id)
        self.request_link()
        self.reset()
        with self.assertRaises(HTTPException) as refused:
            api.get_current_user(token, self.db)
        self.assertEqual(refused.exception.status_code, 401)
        self.assertEqual(api.get_current_user(self.sign_in(), self.db).id, self.user.id)

    def test_login_token_carries_the_stamp(self):
        form = mock.Mock(username=self.user.email, password="Original-1")
        token = api.login(VISITOR, form, self.db)["access_token"]
        self.assertEqual(api.get_current_user(token, self.db).id, self.user.id)
        self.reset_after_login()
        with self.assertRaises(HTTPException):
            api.get_current_user(token, self.db)

    def reset_after_login(self):
        self.request_link()
        self.reset()


class ResetEmailTests(unittest.TestCase):
    def send(self, env):
        output = io.StringIO()
        clean = {key: value for key, value in os.environ.items() if not key.startswith("SMTP_") and key != "APP_ENV"}
        with mock.patch.dict(os.environ, {**clean, **env}, clear=True), contextlib.redirect_stdout(output), self.assertLogs("fitscholar.email", "ERROR") as logs:
            sent = send_email("student@example.com", "Reset", "reset-password?token=secret-value")
        return sent, output.getvalue() + "".join(logs.output)

    def test_production_never_logs_the_link(self):
        sent, logged = self.send({"APP_ENV": "production"})
        self.assertFalse(sent)
        self.assertNotIn("secret-value", logged)


class CorsTests(unittest.TestCase):
    def origins(self, value):
        with mock.patch.dict(os.environ, {"FRONTEND_URL": value}):
            return allowed_origins()

    def test_local_frontend_is_always_allowed(self):
        self.assertEqual(self.origins(""), LOCAL_ORIGINS)

    def test_configured_frontend_is_allowed(self):
        self.assertIn("https://fitscholar.example", self.origins("https://fitscholar.example/"))

    def test_no_wildcard(self):
        self.assertNotIn("*", self.origins("https://fitscholar.example"))


if __name__ == "__main__":
    unittest.main()
