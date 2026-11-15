"""Make `import app` work however pytest is invoked.

Without this, running pytest from the repository root fails with
`ModuleNotFoundError: No module named 'app'`, because only the rootdir ends up
on sys.path. pytest imports the conftest.py nearest the collected tests before
collecting them, so putting the backend directory on sys.path here covers:

    pytest                                  (from the repository root)
    pytest backend/tests/...                (from the repository root)
    pytest tests/...                        (from backend/)
"""
import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


import pytest

# Modules that call load_dotenv() at import time are imported here, during
# collection. Otherwise the first import inside a test re-runs load_dotenv()
# and resurrects environment variables the fixtures below removed.
import app.core.config  # noqa: E402,F401
import app.core.security  # noqa: E402,F401


@pytest.fixture(autouse=True)
def _no_real_rate_limit_waits(monkeypatch):
    """Keep the shared Groq rate limiter from sleeping in real time.

    The limiters in `_REQUEST_LIMITERS` are process-wide and keyed by
    organization, so token reservations outlive the test that made them. With
    GROQ_TPM_LIMIT=8000 one extraction request reserves ~3,650 tokens, so a
    second request in the same 60-second window has to wait for the first to
    expire -- a real `time.sleep(60)` per test.

    Every limiter built while a test runs therefore gets a fake clock that only
    moves when something sleeps. The limiter's own admission logic is untouched,
    including the 429 cooldown, so tests still exercise production behaviour;
    only the waiting is free. Tests that pass their own `clock`/`sleep` keep
    them.
    """
    from app.services import groq_provider

    now = [0.0]

    def fake_monotonic():
        return now[0]

    def fake_sleep(seconds):
        if isinstance(seconds, (int, float)) and seconds > 0:
            now[0] += float(seconds)

    original_init = groq_provider._GroqRequestLimiter.__init__

    def patched_init(self, *args, **kwargs):
        kwargs.setdefault("clock", fake_monotonic)
        kwargs.setdefault("sleep", fake_sleep)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(
        groq_provider._GroqRequestLimiter, "__init__", patched_init,
    )
    # Reservations from earlier tests would otherwise consume this test's
    # token budget, and the limiters themselves still hold the real clock.
    groq_provider._REQUEST_LIMITERS.clear()
    try:
        yield
    finally:
        groq_provider._REQUEST_LIMITERS.clear()


@pytest.fixture(autouse=True)
def _no_manual_source_subset(monkeypatch):
    """Tests must not depend on the developer's .env.

    backend/.env is now loaded by absolute path, so a real
    SCHOLARSHIP_DISCOVERY_MANUAL_SOURCE_IDS would otherwise change what the
    controlled manual run selects in every test. Tests that exercise the
    setting set it themselves.
    """
    monkeypatch.delenv("SCHOLARSHIP_DISCOVERY_MANUAL_SOURCE_IDS", raising=False)
