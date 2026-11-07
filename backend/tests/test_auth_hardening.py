"""
Rate limits, session invalidation, production settings and error replies.
Run from the backend folder:  python -m unittest discover -s tests -v
"""
import asyncio
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import rate_limit as limits
from app.core import security
from app.core.config import validate_settings
from app.core.cors import allowed_origins
from app.core.http_security import GENERIC_ERROR, install_http_security
from app.core.permissions import require_admin
from app.core.rate_limit import RateLimit
from app.core.security import ALGORITHM, SECRET_KEY, create_access_token, hash_password, issue_session_token
from app.database import Base
from app.models.user import User
from app.routers import auth as api
from app.schemas.user import ForgotPasswordRequest, ResetPasswordRequest, UserCreate

PASSWORD = "Original-1"


def visitor(ip="203.0.113.10"):
    return SimpleNamespace(client=SimpleNamespace(host=ip))


class AuthCase(unittest.TestCase):
    def setUp(self):
        for limit in limits.ALL_LIMITS:
            limit.clear()
        # The lowest bcrypt cost: these tests sign in hundreds of times
        fast_hashing = mock.patch.object(security, "pwd_context", CryptContext(schemes=["bcrypt"], bcrypt__rounds=4))
        fast_hashing.start()
        self.addCleanup(fast_hashing.stop)
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        self.user = User(email="student@example.com", hashed_password=hash_password(PASSWORD), full_name="Student", role="student")
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def login(self, email="student@example.com", password=PASSWORD, ip="203.0.113.10"):
        return api.login(visitor(ip), SimpleNamespace(username=email, password=password), self.db)

    def status_of(self, call):
        with self.assertRaises(HTTPException) as refused:
            call()
        return refused.exception

    def fail_login(self, times, **kwargs):
        for _ in range(times):
            self.assertEqual(self.status_of(lambda: self.login(password="Wrong-Pass-1", **kwargs)).status_code, 401)

    def forgot(self, email="student@example.com", ip="203.0.113.10", token="a" * 43):
        with mock.patch.object(api.secrets, "token_urlsafe", return_value=token):
            tasks = BackgroundTasks()
            return api.forgot_password(ForgotPasswordRequest(email=email), tasks, visitor(ip), self.db), tasks

    def reset(self, token="a" * 43, ip="203.0.113.10"):
        return api.reset_password(ResetPasswordRequest(token=token, new_password="Changed-22"), visitor(ip), self.db)


class LoginLimitTests(AuthCase):
    def test_ten_failures_start_a_cooldown(self):
        self.fail_login(10)
        refused = self.status_of(lambda: self.login(password="Wrong-Pass-1"))
        self.assertEqual(refused.status_code, 429)
        self.assertGreater(int(refused.headers["Retry-After"]), 0)
        self.assertIn("Too many attempts", refused.detail)

    def test_the_cooldown_also_stops_the_right_password(self):
        self.fail_login(10)
        self.assertEqual(self.status_of(self.login).status_code, 429)

    def test_success_clears_the_count_so_mistakes_do_not_add_up(self):
        for _ in range(3):
            self.fail_login(9)
            self.assertIn("access_token", self.login())

    def test_successful_logins_are_never_counted(self):
        for _ in range(25):
            self.assertIn("access_token", self.login())

    def test_unknown_and_known_emails_are_treated_alike(self):
        self.fail_login(10, email="nobody@example.com")
        unknown = self.status_of(lambda: self.login(email="nobody@example.com", password="Wrong-Pass-1"))
        self.fail_login(10)
        known = self.status_of(lambda: self.login(password="Wrong-Pass-1"))
        self.assertEqual(unknown.status_code, known.status_code)
        self.assertEqual(unknown.detail[:18], known.detail[:18])

    def test_unknown_email_still_compares_a_password(self):
        with mock.patch.object(api, "verify_password", return_value=False) as compare:
            self.status_of(lambda: self.login(email="nobody@example.com"))
        compare.assert_called_once()

    def test_another_address_can_still_sign_in(self):
        self.fail_login(10, ip="203.0.113.10")
        self.assertIn("access_token", self.login(ip="203.0.113.99"))

    def test_guessing_from_many_addresses_is_slowed(self):
        for number in range(30):
            self.fail_login(1, ip=f"198.51.100.{number}")
        self.assertEqual(self.status_of(lambda: self.login(ip="198.51.100.200")).status_code, 429)

    def test_email_capitals_do_not_escape_the_limit(self):
        self.fail_login(5)
        self.fail_login(5, email="STUDENT@example.com")
        self.assertEqual(self.status_of(self.login).status_code, 429)


class ResetLimitTests(AuthCase):
    def test_the_fourth_request_sends_nothing_but_replies_the_same(self):
        replies = []
        for number in range(3):
            reply, tasks = self.forgot(token=str(number) * 43)
            replies.append(reply)
            self.assertEqual(len(tasks.tasks), 1)
        reply, tasks = self.forgot(token="9" * 43)
        self.assertEqual(reply, replies[0])
        self.assertEqual(len(tasks.tasks), 0)

    def test_unknown_addresses_are_limited_the_same_way(self):
        for _ in range(4):
            reply, tasks = self.forgot(email="nobody@example.com")
            self.assertEqual(reply["message"], api.FORGOT_PASSWORD_REPLY)
            self.assertEqual(len(tasks.tasks), 0)

    def test_one_address_cannot_request_for_everyone(self):
        for number in range(10):
            self.forgot(email=f"person{number}@example.com")
        self.assertEqual(self.status_of(lambda: self.forgot(email="next@example.com")).status_code, 429)

    def test_guessed_reset_tokens_are_limited(self):
        for _ in range(10):
            self.assertEqual(self.status_of(lambda: self.reset("b" * 43)).status_code, 400)
        self.assertEqual(self.status_of(lambda: self.reset("b" * 43)).status_code, 429)

    def test_registration_from_one_address_is_limited(self):
        for number in range(30):
            api.register(UserCreate(email=f"new{number}@example.com", password="Password-1", full_name="New"), visitor(), self.db)
        extra = UserCreate(email="extra@example.com", password="Password-1", full_name="New")
        self.assertEqual(self.status_of(lambda: api.register(extra, visitor(), self.db)).status_code, 429)


class CooldownTests(unittest.TestCase):
    def test_the_cooldown_ends_and_old_attempts_fall_away(self):
        limit = RateLimit(limit=2, window=60, cooldown=30)
        with mock.patch.object(limits.time, "monotonic", return_value=1000):
            limit.hit("key")
            self.assertEqual(limit.retry_after("key"), 0)
        with mock.patch.object(limits.time, "monotonic", return_value=1061):
            limit.hit("key")
            self.assertEqual(limit.retry_after("key"), 0)
            limit.hit("key")
            self.assertEqual(limit.retry_after("key"), 30)
        with mock.patch.object(limits.time, "monotonic", return_value=1092):
            self.assertEqual(limit.retry_after("key"), 0)


class SessionTests(AuthCase):
    def current(self, token):
        return api.get_current_user(token, self.db)

    def assert_refused(self, token):
        self.assertEqual(self.status_of(lambda: self.current(token)).status_code, 401)

    def test_a_normal_session_works(self):
        self.assertEqual(self.current(self.login()["access_token"]).id, self.user.id)

    def test_tokens_issued_before_stamps_existed_are_refused(self):
        self.assert_refused(create_access_token({"sub": str(self.user.id), "email": self.user.email}))

    def test_a_reset_ends_every_earlier_session(self):
        first, second = self.login()["access_token"], self.login()["access_token"]
        self.forgot()
        self.reset()
        self.assert_refused(first)
        self.assert_refused(second)

    def test_signing_in_after_a_reset_works(self):
        self.forgot()
        self.reset()
        self.assertEqual(self.status_of(self.login).status_code, 401)
        new_session = api.login(visitor(), SimpleNamespace(username=self.user.email, password="Changed-22"), self.db)
        self.assertEqual(self.current(new_session["access_token"]).id, self.user.id)

    def test_expired_token_is_refused(self):
        payload = {"sub": str(self.user.id), "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}
        self.assert_refused(jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM))

    def test_token_signed_with_another_key_is_refused(self):
        self.assert_refused(jwt.encode({"sub": str(self.user.id), "pwd": "x"}, "another-key-" * 4, algorithm=ALGORITHM))

    def test_unsigned_token_is_refused(self):
        self.assert_refused(jwt.encode({"sub": str(self.user.id)}, "", algorithm="HS256")[:-5] + "abcde")

    def test_token_with_a_bad_subject_is_refused_not_a_crash(self):
        self.assert_refused(create_access_token({"pwd": "x"}))
        self.assert_refused(create_access_token({"sub": "not-a-number", "pwd": "x"}))

    def test_deleted_user_is_refused(self):
        token = issue_session_token(self.user)
        self.db.delete(self.user)
        self.db.commit()
        self.assert_refused(token)

    def test_student_session_cannot_pass_the_admin_check(self):
        student = self.current(self.login()["access_token"])
        self.assertEqual(self.status_of(lambda: require_admin(student)).status_code, 403)

    def test_admin_session_passes_the_admin_check(self):
        self.user.role = "admin"
        self.db.commit()
        self.assertEqual(require_admin(self.current(self.login()["access_token"])).role, "admin")


GOOD = {"APP_ENV": "production", "SECRET_KEY": "k" * 64, "DATABASE_URL": "postgresql://app:strong@db.internal/fit",
        "FRONTEND_URL": "https://fitscholar.example", "SMTP_HOST": "smtp.example.com", "SMTP_FROM": "no-reply@example.com",
        "GOOGLE_CLIENT_ID": "fitscholar.apps.googleusercontent.com",
        "MINILM_MODEL_REVISION": "0123456789abcdef0123456789abcdef01234567"}


class SettingsTests(unittest.TestCase):
    def check(self, **changes):
        settings = {**GOOD, **changes}
        clean = {key: value for key, value in os.environ.items() if key not in GOOD and key != "SMTP_USE_TLS"}
        with mock.patch.dict(os.environ, {**clean, **{k: v for k, v in settings.items() if v is not None}}, clear=True):
            validate_settings()

    def assert_stops(self, text, **changes):
        with self.assertRaises(RuntimeError) as stopped:
            self.check(**changes)
        self.assertIn(text, str(stopped.exception))

    def test_complete_settings_start(self):
        self.check()

    def test_each_missing_setting_stops_the_api(self):
        self.assert_stops("SECRET_KEY", SECRET_KEY="short")
        self.assert_stops("DATABASE_URL", DATABASE_URL=None)
        self.assert_stops("sample password", DATABASE_URL="postgresql://u:fitscholar_password@localhost/x")
        self.assert_stops("FRONTEND_URL", FRONTEND_URL=None)
        self.assert_stops("FRONTEND_URL", FRONTEND_URL="http://fitscholar.example")
        self.assert_stops("FRONTEND_URL", FRONTEND_URL="https://localhost:5173")
        self.assert_stops("SMTP_HOST", SMTP_HOST=None)
        self.assert_stops("SMTP_USE_TLS", SMTP_USE_TLS="false")
        self.assert_stops("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID=None)
        self.assert_stops("MINILM_MODEL_REVISION", MINILM_MODEL_REVISION=None)

    def test_invalid_model_revision_fails_without_echoing_the_value(self):
        invalid_revision = "g" * 40
        with self.assertRaises(RuntimeError) as stopped:
            self.check(MINILM_MODEL_REVISION=invalid_revision)
        self.assertIn("MINILM_MODEL_REVISION", str(stopped.exception))
        self.assertNotIn(invalid_revision, str(stopped.exception))

    def test_the_error_never_contains_a_value(self):
        with self.assertRaises(RuntimeError) as stopped:
            self.check(SECRET_KEY="short-secret-value")
        self.assertNotIn("short-secret-value", str(stopped.exception))

    def test_a_misspelt_environment_stops_the_api(self):
        self.assert_stops("APP_ENV", APP_ENV="prodution")
        self.assert_stops("APP_ENV", APP_ENV="prod")

    def test_development_needs_nothing_more(self):
        with mock.patch.dict(
            os.environ,
            {"APP_ENV": "development", "MINILM_MODEL_REVISION": "main"},
            clear=True,
        ):
            validate_settings()

    def test_unset_environment_is_rejected(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "APP_ENV must be explicitly set"):
                validate_settings()

    def test_production_validation_does_not_load_the_model(self):
        with (
            mock.patch("app.services.rag_service._load_model_with_revision") as load_model,
            mock.patch("app.services.rag_service._gemini_client") as gemini_client,
        ):
            self.check()
        load_model.assert_not_called()
        gemini_client.assert_not_called()

    def test_production_allows_only_the_site_itself(self):
        with mock.patch.dict(os.environ, {"APP_ENV": "production", "FRONTEND_URL": "https://fitscholar.example/"}):
            self.assertEqual(allowed_origins(), ["https://fitscholar.example"])


class Secret(BaseModel):
    new_password: str = Field(..., min_length=6)


def build_app():
    app = FastAPI()
    install_http_security(app)

    @app.get("/crash")
    def crash():
        raise ValueError("internal detail postgresql://user:secret@host")

    @app.get("/fine")
    def fine():
        return {"ok": True}

    @app.post("/secret")
    def secret(data: Secret):
        return {"ok": True}

    return app


def call(app, method, path, body=None, origin=None):
    """One request straight through the app."""
    sent = []
    payload = json.dumps(body).encode() if body is not None else b""

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "path": path, "raw_path": path.encode(),
             "query_string": b"", "headers": [(b"content-type", b"application/json")] + ([(b"origin", origin.encode())] if origin else []), "client": ("127.0.0.1", 1), "server": ("test", 80), "scheme": "http"}
    asyncio.run(app(scope, receive, send))
    headers = {key.decode().lower(): value.decode() for key, value in next(m for m in sent if m["type"] == "http.response.start")["headers"]}
    text = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body").decode()
    return next(m for m in sent if m["type"] == "http.response.start")["status"], headers, text


class ResponseTests(unittest.TestCase):
    def test_security_headers_are_set(self):
        status, headers, _ = call(build_app(), "GET", "/fine")
        self.assertEqual(status, 200)
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertEqual(headers["x-frame-options"], "DENY")
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertIn("default-src 'none'", headers["content-security-policy"])
        self.assertNotIn("strict-transport-security", headers)

    def test_https_is_enforced_only_in_production(self):
        with mock.patch.dict(os.environ, {"APP_ENV": "production"}):
            _, headers, _ = call(build_app(), "GET", "/fine")
        self.assertIn("max-age", headers["strict-transport-security"])

    def test_a_crash_reveals_nothing(self):
        with self.assertLogs("fitscholar.api", "ERROR"):
            status, headers, text = call(build_app(), "GET", "/crash")
        self.assertEqual(status, 500)
        self.assertEqual(json.loads(text), {"detail": GENERIC_ERROR})
        self.assertNotIn("secret", text)
        self.assertEqual(headers["x-frame-options"], "DENY")

    def test_a_crash_reply_can_be_read_by_the_frontend(self):
        app = build_app()
        app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"])
        with self.assertLogs("fitscholar.api", "ERROR"):
            status, headers, _ = call(app, "GET", "/crash", origin="http://localhost:5173")
        self.assertEqual(status, 500)
        self.assertEqual(headers["access-control-allow-origin"], "http://localhost:5173")

    def test_production_logs_leave_out_the_error_text(self):
        with mock.patch.dict(os.environ, {"APP_ENV": "production"}), self.assertLogs("fitscholar.api", "ERROR") as logs:
            call(build_app(), "GET", "/crash")
        self.assertNotIn("secret", "".join(logs.output))
        self.assertIn("ValueError", "".join(logs.output))

    def test_a_validation_error_does_not_repeat_the_password(self):
        status, _, text = call(build_app(), "POST", "/secret", {"new_password": "abc"})
        self.assertEqual(status, 422)
        self.assertNotIn("abc", text)
        self.assertEqual(json.loads(text)["detail"][0]["loc"], ["body", "new_password"])


if __name__ == "__main__":
    unittest.main()
