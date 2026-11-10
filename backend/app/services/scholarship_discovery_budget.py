"""Per-run resource limits for controlled manual scholarship discovery."""

import logging
import threading
import time
from dataclasses import replace
from typing import Callable, Iterable, Optional

from app.core.config import ScholarshipDiscoverySettings
from app.services.scholarship_discovery_sources import DiscoverySource, SOURCES

logger = logging.getLogger(__name__)

MAX_MANUAL_SOURCES = 15
MAX_MANUAL_PAGES = 45
MAX_MANUAL_PAGES_PER_SOURCE = 3
MAX_MANUAL_HTTP_ATTEMPTS = 300
MAX_MANUAL_CANDIDATES = 100
MAX_MANUAL_PROVIDER_ATTEMPTS = 100
MAX_MANUAL_DURATION_SECONDS = 30 * 60
MAX_MANUAL_HTTP_TIMEOUT_SECONDS = 15
MAX_MANUAL_RESPONSE_BYTES = 10_000_000
MAX_MANUAL_HTTP_RETRIES = 2
MAX_MANUAL_PROVIDER_TIMEOUT_SECONDS = 60
MAX_MANUAL_LINKED_URLS = 100
MAX_MANUAL_LINKED_URL_CHARS = 2048
MAX_MANUAL_LINKED_URL_BYTES = 16_384
MAX_MANUAL_PROVIDER_REQUEST_BYTES = 512_000
MAX_MANUAL_EXTRACTED_CHARS = 30_000

CONTROLLED_MANUAL_SOURCE_IDS = (
    "daad-helmut-schmidt",
    "daad-epos",
    "nl-scholarship",
    "leiden-excellence",
    "maastricht-nl-high-potential",
    "radboud-scholarship",
    "kth-scholarship",
    "lund-university-scholarships",
    "chalmers-scholarships",
    "eiffel-scholarship",
    "sciences-po-emile-boutmy",
    "chevening-pakistan",
    "commonwealth-masters",
    "commonwealth-shared",
    "turkiye-burslari",
)


class DiscoveryRunLimitExceeded(RuntimeError):
    def __init__(self, resource: str, limit: int):
        self.resource = resource
        self.limit = limit
        super().__init__(f"Discovery run budget exhausted: {resource}")

    def as_dict(self) -> dict:
        return {
            "code": "DISCOVERY_RUN_BUDGET_EXHAUSTED",
            "resource": self.resource,
            "limit": self.limit,
        }


class ControlledManualSourceConfigurationError(ValueError):
    pass


class _DiscoveryOperationGate:
    """Serialize cancellation with invocation using a per-attempt lock.

    The operation is considered started when it passes the budget check while
    holding this lock; cancellation waits for that synchronous call to return.
    The budget-wide lock is released before the client method runs.
    """

    def __init__(
        self,
        budget: "DiscoveryRunBudget",
        token: int,
        callback: Callable[[], None],
        counter: str,
        maximum: int,
        resource: str,
    ):
        self._budget = budget
        self._token = token
        self._callback = callback
        self._counter = counter
        self._maximum = maximum
        self._resource = resource
        self._lock = threading.RLock()
        self._cancelled = False

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
        self._callback()

    def invoke(self, operation: Callable[[float], object]) -> object:
        with self._lock:
            if self._cancelled:
                raise DiscoveryRunLimitExceeded(
                    "duration_seconds",
                    self._budget.duration_seconds,
                )
            remaining = self._budget._start_registered_operation(
                self._token,
                self._counter,
                self._maximum,
                self._resource,
            )
            return operation(remaining)


def controlled_manual_sources(
    registry_sources: Iterable[DiscoverySource] = SOURCES,
) -> tuple[DiscoverySource, ...]:
    sources = tuple(registry_sources)
    matches = {
        source_id: [
            source for source in sources
            if source.source_id == source_id
        ]
        for source_id in CONTROLLED_MANUAL_SOURCE_IDS
    }
    if any(len(entries) != 1 for entries in matches.values()):
        raise ControlledManualSourceConfigurationError
    selected = tuple(
        matches[source_id][0]
        for source_id in CONTROLLED_MANUAL_SOURCE_IDS
    )
    if any(
        source.crawl_enabled is not True
        or source.trust_reviewed is not True
        or not isinstance(source.trust_basis, str)
        or not source.trust_basis.strip()
        or source.discovery_only is not False
        for source in selected
    ):
        raise ControlledManualSourceConfigurationError
    return selected


def validate_controlled_manual_run_sources(
    run_sources: Iterable[DiscoverySource],
) -> tuple[DiscoverySource, ...]:
    selected = tuple(run_sources)
    if selected != controlled_manual_sources():
        raise ControlledManualSourceConfigurationError
    return selected


def validate_controlled_manual_budget(budget: "DiscoveryRunBudget") -> None:
    limits = {
        "max_sources": MAX_MANUAL_SOURCES,
        "max_pages": MAX_MANUAL_PAGES,
        "max_pages_per_source": MAX_MANUAL_PAGES_PER_SOURCE,
        "max_http_attempts": MAX_MANUAL_HTTP_ATTEMPTS,
        "max_candidates": MAX_MANUAL_CANDIDATES,
        "max_provider_attempts": MAX_MANUAL_PROVIDER_ATTEMPTS,
        "duration_seconds": MAX_MANUAL_DURATION_SECONDS,
    }
    if any(getattr(budget, name) > maximum for name, maximum in limits.items()):
        raise ControlledManualSourceConfigurationError


def controlled_manual_settings(settings: ScholarshipDiscoverySettings):
    """Clamp environment-configurable settings to the controlled manual profile."""
    return replace(
        settings,
        request_timeout_seconds=min(
            settings.request_timeout_seconds,
            MAX_MANUAL_HTTP_TIMEOUT_SECONDS,
        ),
        max_response_bytes=min(settings.max_response_bytes, MAX_MANUAL_RESPONSE_BYTES),
        max_pages_per_source=min(
            settings.max_pages_per_source,
            MAX_MANUAL_PAGES_PER_SOURCE,
        ),
        max_retries=min(settings.max_retries, MAX_MANUAL_HTTP_RETRIES),
        max_extracted_chars=min(
            settings.max_extracted_chars,
            MAX_MANUAL_EXTRACTED_CHARS,
        ),
        max_linked_urls=min(settings.max_linked_urls, MAX_MANUAL_LINKED_URLS),
        max_linked_url_chars=min(
            settings.max_linked_url_chars,
            MAX_MANUAL_LINKED_URL_CHARS,
        ),
        max_linked_urls_bytes=min(
            settings.max_linked_urls_bytes,
            MAX_MANUAL_LINKED_URL_BYTES,
        ),
        max_provider_request_bytes=min(
            settings.max_provider_request_bytes,
            MAX_MANUAL_PROVIDER_REQUEST_BYTES,
        ),
    )


class DiscoveryRunBudget:
    """Thread-safe run limits with a monotonic deadline and active-call cancellation."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        max_sources: int = MAX_MANUAL_SOURCES,
        max_pages: int = MAX_MANUAL_PAGES,
        max_pages_per_source: int = MAX_MANUAL_PAGES_PER_SOURCE,
        max_http_attempts: int = MAX_MANUAL_HTTP_ATTEMPTS,
        max_candidates: int = MAX_MANUAL_CANDIDATES,
        max_provider_attempts: int = MAX_MANUAL_PROVIDER_ATTEMPTS,
        duration_seconds: int = MAX_MANUAL_DURATION_SECONDS,
        start_deadline_timer: bool = True,
    ):
        self.clock = clock
        self.sleep = sleep
        self.max_sources = max_sources
        self.max_pages = max_pages
        self.max_pages_per_source = max_pages_per_source
        self.max_http_attempts = max_http_attempts
        self.max_candidates = max_candidates
        self.max_provider_attempts = max_provider_attempts
        self.duration_seconds = duration_seconds
        self.start_deadline_timer = start_deadline_timer
        self._lock = threading.Lock()
        self._started_at: Optional[float] = None
        self._deadline: Optional[float] = None
        self._timer: Optional[threading.Timer] = None
        self._expired = False
        self._closed = False
        self._cancellations = {}
        self._operation_gates = {}
        self._next_cancellation_id = 0
        self._sources_started = 0
        self._pages_started = 0
        self._pages_fetched = 0
        self._http_attempts = 0
        self._candidates_persisted = 0
        self._candidate_reservations = 0
        self._provider_attempts = 0
        self._pages_per_source = {}

    def start(self) -> None:
        with self._lock:
            if self._started_at is not None:
                return
            if self._closed:
                raise RuntimeError("Discovery run budget is closed")
            self._started_at = self.clock()
            self._deadline = self._started_at + self.duration_seconds
            if self.start_deadline_timer:
                self._timer = threading.Timer(
                    self.duration_seconds,
                    self._expire,
                )
                self._timer.daemon = True
                self._timer.start()

    def _guard_locked(self):
        if self._closed:
            raise RuntimeError("Discovery run budget is closed")
        if self._started_at is None:
            self._started_at = self.clock()
            self._deadline = self._started_at + self.duration_seconds
            if self.start_deadline_timer:
                self._timer = threading.Timer(self.duration_seconds, self._expire)
                self._timer.daemon = True
                self._timer.start()
        remaining = self._deadline - self.clock()
        if self._expired or remaining <= 0:
            self._expired = True
            callbacks = tuple(self._cancellations.values())
            self._cancellations.clear()
            return 0.0, callbacks, DiscoveryRunLimitExceeded(
                "duration_seconds",
                self.duration_seconds,
            )
        return remaining, (), None

    @staticmethod
    def _run_cancellations(callbacks) -> None:
        for callback in callbacks:
            try:
                callback()
            except Exception as exc:
                logger.warning(
                    "Discovery deadline cancellation failed: %s",
                    type(exc).__name__,
                )

    def _expire(self) -> None:
        with self._lock:
            if self._closed or self._expired:
                return
            self._expired = True
            callbacks = tuple(self._cancellations.values())
            self._cancellations.clear()
        self._run_cancellations(callbacks)

    def _check_deadline(self) -> float:
        with self._lock:
            remaining, callbacks, error = self._guard_locked()
        self._run_cancellations(callbacks)
        if error is not None:
            raise error
        return remaining

    def ensure_active(self) -> None:
        self._check_deadline()

    def remaining_seconds(self) -> float:
        return self._check_deadline()

    def wait(self, seconds: float) -> None:
        remaining = self.remaining_seconds()
        self.sleep(min(max(seconds, 0), remaining))
        self.ensure_active()

    def register_cancellation(self, callback: Callable[[], None]) -> int:
        immediate = False
        with self._lock:
            _, callbacks, error = self._guard_locked()
            if error is not None:
                immediate = True
                token = -1
            else:
                token = self._next_cancellation_id
                self._next_cancellation_id += 1
                self._cancellations[token] = callback
        self._run_cancellations(callbacks)
        if immediate:
            callback()
            raise error
        return token

    def begin_http_attempt(self, callback: Callable[[], None]) -> tuple[int, float]:
        return self._register_operation(
            callback,
            "_http_attempts",
            self.max_http_attempts,
            "http_attempts",
        )

    def begin_provider_attempt(self, callback: Callable[[], None]) -> tuple[int, float]:
        return self._register_operation(
            callback,
            "_provider_attempts",
            self.max_provider_attempts,
            "provider_attempts",
        )

    def _register_operation(
        self,
        callback: Callable[[], None],
        counter: str,
        maximum: int,
        resource: str,
    ) -> tuple[int, float]:
        with self._lock:
            remaining, callbacks, error = self._guard_locked()
            if error is None:
                token = self._next_cancellation_id
                self._next_cancellation_id += 1
                gate = _DiscoveryOperationGate(
                    self,
                    token,
                    callback,
                    counter,
                    maximum,
                    resource,
                )
                self._operation_gates[token] = gate
                self._cancellations[token] = gate.cancel
            else:
                token = -1
        self._run_cancellations(callbacks)
        if error is not None:
            raise error
        return token, remaining

    def invoke_http_attempt(
        self,
        token: int,
        operation: Callable[[float], object],
    ) -> object:
        return self._invoke_registered_operation(token, operation)

    def invoke_provider_attempt(
        self,
        token: int,
        operation: Callable[[float], object],
    ) -> object:
        return self._invoke_registered_operation(token, operation)

    def _invoke_registered_operation(
        self,
        token: int,
        operation: Callable[[float], object],
    ) -> object:
        with self._lock:
            gate = self._operation_gates.get(token)
        if gate is None:
            raise RuntimeError("Discovery operation was not registered")
        return gate.invoke(operation)

    def _start_registered_operation(
        self,
        token: int,
        counter: str,
        maximum: int,
        resource: str,
    ) -> float:
        with self._lock:
            remaining, callbacks, error = self._guard_locked()
            if error is None and token not in self._cancellations:
                error = RuntimeError("Discovery operation was not registered")
            if error is None and getattr(self, counter) >= maximum:
                error = DiscoveryRunLimitExceeded(resource, maximum)
            if error is None:
                setattr(self, counter, getattr(self, counter) + 1)
        self._run_cancellations(callbacks)
        if error is not None:
            raise error
        return remaining

    def unregister_cancellation(self, token: int) -> None:
        if token < 0:
            return
        with self._lock:
            self._cancellations.pop(token, None)
            self._operation_gates.pop(token, None)

    def _reserve(self, counter: str, maximum: int, resource: str) -> float:
        with self._lock:
            remaining, callbacks, error = self._guard_locked()
            if error is None and getattr(self, counter) >= maximum:
                error = DiscoveryRunLimitExceeded(resource, maximum)
            if error is None:
                setattr(self, counter, getattr(self, counter) + 1)
        self._run_cancellations(callbacks)
        if error is not None:
            raise error
        return remaining

    def start_source(self, source_id: str) -> float:
        remaining = self._reserve("_sources_started", self.max_sources, "sources")
        with self._lock:
            self._pages_per_source.setdefault(source_id, 0)
        return remaining

    def start_page(self, source_id: str) -> float:
        with self._lock:
            remaining, callbacks, error = self._guard_locked()
            source_pages = self._pages_per_source.get(source_id, 0)
            if error is None and self._pages_started >= self.max_pages:
                error = DiscoveryRunLimitExceeded("pages", self.max_pages)
            elif error is None and source_pages >= self.max_pages_per_source:
                error = DiscoveryRunLimitExceeded(
                    "pages_per_source",
                    self.max_pages_per_source,
                )
            if error is None:
                self._pages_started += 1
                self._pages_per_source[source_id] = source_pages + 1
        self._run_cancellations(callbacks)
        if error is not None:
            raise error
        return remaining

    def record_page_fetched(self) -> None:
        with self._lock:
            self._pages_fetched += 1
            _, callbacks, error = self._guard_locked()
        self._run_cancellations(callbacks)
        if error is not None:
            raise error

    def consume_http_attempt(self) -> float:
        return self._reserve(
            "_http_attempts",
            self.max_http_attempts,
            "http_attempts",
        )

    def begin_candidate_persistence(self) -> None:
        with self._lock:
            _, callbacks, error = self._guard_locked()
            if (
                error is None
                and self._candidates_persisted + self._candidate_reservations
                >= self.max_candidates
            ):
                error = DiscoveryRunLimitExceeded(
                    "candidates",
                    self.max_candidates,
                )
            if error is None:
                self._candidate_reservations += 1
        self._run_cancellations(callbacks)
        if error is not None:
            raise error

    def ensure_candidate_capacity(self) -> None:
        with self._lock:
            _, callbacks, error = self._guard_locked()
            if (
                error is None
                and self._candidates_persisted + self._candidate_reservations
                >= self.max_candidates
            ):
                error = DiscoveryRunLimitExceeded(
                    "candidates",
                    self.max_candidates,
                )
        self._run_cancellations(callbacks)
        if error is not None:
            raise error

    def finish_candidate_persistence(self, persisted: bool) -> None:
        with self._lock:
            self._candidate_reservations = max(0, self._candidate_reservations - 1)
            if persisted:
                self._candidates_persisted += 1

    def consume_provider_attempt(self) -> float:
        return self._reserve(
            "_provider_attempts",
            self.max_provider_attempts,
            "provider_attempts",
        )

    def snapshot(self) -> dict:
        with self._lock:
            now = self.clock()
            elapsed = (
                max(0.0, now - self._started_at)
                if self._started_at is not None
                else 0.0
            )
            return {
                "sources_started": self._sources_started,
                "pages_started": self._pages_started,
                "pages_fetched": self._pages_fetched,
                "http_attempts": self._http_attempts,
                "candidates_persisted": self._candidates_persisted,
                "provider_attempts": self._provider_attempts,
                "duration_seconds": round(elapsed, 3),
                "duration_limit_seconds": self.duration_seconds,
            }

    def close(self) -> None:
        with self._lock:
            self._closed = True
            timer = self._timer
            self._cancellations.clear()
            self._operation_gates.clear()
        if timer is not None:
            timer.cancel()
