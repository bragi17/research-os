"""Round-robin API key pool with per-key rate limit state."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass


class NoAvailableSourceKey(Exception):
    """Raised when no key can be leased from a source key pool."""


@dataclass(frozen=True)
class KeyMaterial:
    """API key material tracked by a source key pool."""

    value: str
    label: str | None = None


@dataclass(frozen=True)
class KeyLease:
    """A lease returned by SourceKeyPool.acquire()."""

    key: KeyMaterial
    issued_at: float


@dataclass
class _KeyState:
    key: KeyMaterial
    tokens: float
    last_refill: float
    cooldown_until: float = 0.0
    disabled: bool = False


class SourceKeyPool:
    """Lease keys in round-robin order while isolating per-key failures."""

    def __init__(
        self,
        keys: Iterable[str | KeyMaterial],
        *,
        requests_per_second: float,
        burst_capacity: int,
        clock: Callable[[], float] | None = None,
        default_cooldown_seconds: float = 60.0,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be greater than 0")
        if burst_capacity < 1:
            raise ValueError("burst_capacity must be at least 1")

        self.requests_per_second = requests_per_second
        self.burst_capacity = burst_capacity
        self.default_cooldown_seconds = max(0.0, default_cooldown_seconds)
        self._clock = clock or time.monotonic
        now = self._clock()
        self._states = [
            _KeyState(
                key=key if isinstance(key, KeyMaterial) else KeyMaterial(value=key),
                tokens=float(burst_capacity),
                last_refill=now,
            )
            for key in keys
        ]
        self._next_index = 0

    def acquire(self) -> KeyLease:
        """Return a lease for the next available key."""

        if not self._states:
            raise NoAvailableSourceKey("No source keys are configured")

        now = self._clock()
        for offset in range(len(self._states)):
            index = (self._next_index + offset) % len(self._states)
            state = self._states[index]
            self._refill(state, now)

            if not self._is_available(state, now):
                continue

            state.tokens -= 1
            self._next_index = (index + 1) % len(self._states)
            return KeyLease(key=state.key, issued_at=now)

        raise NoAvailableSourceKey("No source keys are currently available")

    def record_rate_limit(
        self,
        lease: KeyLease,
        retry_after_seconds: float | None = None,
    ) -> None:
        """Cool down only the key associated with a rate-limited lease."""

        state = self._state_for_lease(lease)
        if state is None:
            return

        cooldown_seconds = (
            self.default_cooldown_seconds
            if retry_after_seconds is None
            else max(0.0, retry_after_seconds)
        )
        now = self._clock()
        state.tokens = 0.0
        state.last_refill = now
        state.cooldown_until = max(state.cooldown_until, now + cooldown_seconds)

    def record_credential_error(self, lease: KeyLease) -> None:
        """Disable only the key associated with an authentication failure."""

        state = self._state_for_lease(lease)
        if state is not None:
            state.disabled = True
            state.tokens = 0.0

    def _refill(self, state: _KeyState, now: float) -> None:
        elapsed = max(0.0, now - state.last_refill)
        state.tokens = min(
            float(self.burst_capacity),
            state.tokens + elapsed * self.requests_per_second,
        )
        state.last_refill = now

    def _is_available(self, state: _KeyState, now: float) -> bool:
        return (
            not state.disabled
            and now >= state.cooldown_until
            and state.tokens >= 1.0
        )

    def _state_for_lease(self, lease: KeyLease) -> _KeyState | None:
        for state in self._states:
            if state.key == lease.key:
                return state
        return None
