"""
Rate limits for the sign-in endpoints. Counts live in this process, so they restart with the
server and aren't shared between workers: run one worker, or move the counts to a shared store.
"""
import math
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

MINUTE = 60
HOUR = 60 * MINUTE
MAX_TRACKED_KEYS = 50_000


class RateLimit:
    """At most `limit` hits per key within `window` seconds, then a `cooldown` in seconds."""

    def __init__(self, limit: int, window: int, cooldown: int):
        self.limit = limit
        self.window = window
        self.cooldown = cooldown
        self._hits = defaultdict(deque)
        self._blocked_until = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int:
        """Seconds until this key may try again; 0 when it isn't blocked."""
        with self._lock:
            blocked_until = self._blocked_until.get(key)
            if blocked_until is None:
                return 0
            remaining = blocked_until - time.monotonic()
            if remaining > 0:
                return math.ceil(remaining)
            del self._blocked_until[key]
            return 0

    def hit(self, key: str) -> None:
        """Count one attempt, and start the cooldown when it reaches the limit."""
        now = time.monotonic()
        with self._lock:
            if len(self._hits) >= MAX_TRACKED_KEYS:
                self._forget_old(now)
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            hits.append(now)
            if len(hits) >= self.limit:
                self._blocked_until[key] = now + self.cooldown
                hits.clear()

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
            self._blocked_until.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()
            self._blocked_until.clear()

    def _forget_old(self, now: float) -> None:
        for key in [key for key, hits in self._hits.items() if not hits or hits[-1] <= now - self.window]:
            del self._hits[key]
        for key in [key for key, until in self._blocked_until.items() if until <= now]:
            del self._blocked_until[key]
        # A flood of made-up keys must not grow memory without limit
        if len(self._hits) >= MAX_TRACKED_KEYS:
            self._hits.clear()


# Failed logins only, so a person who signs in normally never gets near these
LOGIN_FAILURES_BY_ACCOUNT_AND_IP = RateLimit(limit=10, window=15 * MINUTE, cooldown=10 * MINUTE)
# Slows guessing from many addresses, without locking the account for long
LOGIN_FAILURES_BY_ACCOUNT = RateLimit(limit=30, window=15 * MINUTE, cooldown=15 * MINUTE)
# High enough for a campus or office sharing one address
LOGIN_FAILURES_BY_IP = RateLimit(limit=100, window=15 * MINUTE, cooldown=15 * MINUTE)
RESET_EMAILS_BY_ADDRESS = RateLimit(limit=3, window=HOUR, cooldown=HOUR)
RESET_REQUESTS_BY_IP = RateLimit(limit=10, window=HOUR, cooldown=HOUR)
RESET_FAILURES_BY_IP = RateLimit(limit=10, window=15 * MINUTE, cooldown=15 * MINUTE)
REGISTRATIONS_BY_IP = RateLimit(limit=30, window=HOUR, cooldown=HOUR)
# Rejected Google tokens only. Passwords tried while linking count towards the login limits instead
GOOGLE_FAILURES_BY_IP = RateLimit(limit=30, window=15 * MINUTE, cooldown=15 * MINUTE)
ASSISTANT_MESSAGES_BY_USER = RateLimit(limit=30, window=MINUTE, cooldown=MINUTE)

ALL_LIMITS = (LOGIN_FAILURES_BY_ACCOUNT_AND_IP, LOGIN_FAILURES_BY_ACCOUNT, LOGIN_FAILURES_BY_IP, RESET_EMAILS_BY_ADDRESS,
              RESET_REQUESTS_BY_IP, RESET_FAILURES_BY_IP, REGISTRATIONS_BY_IP, GOOGLE_FAILURES_BY_IP, ASSISTANT_MESSAGES_BY_USER)


def client_ip(request: Request) -> str:
    """The connecting address. Behind a proxy, uvicorn's --forwarded-allow-ips sets this from a trusted proxy only."""
    return request.client.host if request.client else "unknown"


def refuse_if_blocked(*checks) -> None:
    """Each check is (limit, key). Answers 429 with the longest wait of any that is blocked."""
    wait = max((limit.retry_after(key) for limit, key in checks), default=0)
    if wait:
        minutes = math.ceil(wait / MINUTE)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many attempts. Please try again in {minutes} minute{'' if minutes == 1 else 's'}.",
            headers={"Retry-After": str(wait)},
        )
