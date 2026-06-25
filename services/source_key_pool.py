"""Round-robin API key pool with per-key rate limit state."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


class NoAvailableSourceKey(Exception):
    """Raised when no key can be leased from a source key pool."""


@dataclass(frozen=True)
class KeyMaterial:
    """API key material tracked by a source key pool."""

    id: str | None
    secret: str
    preview: str


@dataclass(frozen=True)
class KeyLease:
    """A lease returned by SourceKeyPool.acquire()."""

    id: str | None
    secret: str
    preview: str


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
        keys: list[KeyMaterial],
        *,
        requests_per_second: float,
        burst_capacity: int,
        now: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        default_cooldown_seconds: float = 60.0,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be greater than 0")
        if burst_capacity < 1:
            raise ValueError("burst_capacity must be at least 1")

        self.requests_per_second = requests_per_second
        self.burst_capacity = burst_capacity
        self.default_cooldown_seconds = max(0.0, default_cooldown_seconds)
        self._now = now or time.monotonic
        self._sleep = sleep or asyncio.sleep
        current_time = self._now()
        self._states = [
            _KeyState(
                key=key,
                tokens=float(burst_capacity),
                last_refill=current_time,
            )
            for key in keys
            if key.secret.strip()
        ]
        self._next_index = 0

    async def acquire(self) -> KeyLease:
        """Return a lease for the next available key."""

        if not self._states:
            raise NoAvailableSourceKey("No source keys are configured")

        while True:
            current_time = self._now()
            active_states = [
                state for state in self._states if not state.disabled
            ]
            if not active_states:
                raise NoAvailableSourceKey("No source keys are currently available")

            for offset in range(len(self._states)):
                index = (self._next_index + offset) % len(self._states)
                state = self._states[index]
                self._refill(state, current_time)

                if not self._is_available(state, current_time):
                    continue

                state.tokens -= 1
                self._next_index = (index + 1) % len(self._states)
                return KeyLease(
                    id=state.key.id,
                    secret=state.key.secret,
                    preview=state.key.preview,
                )

            wait_seconds = min(
                self._seconds_until_available(state, current_time)
                for state in active_states
            )
            await self._sleep(max(0.0, wait_seconds))

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
        current_time = self._now()
        state.tokens = 0.0
        state.last_refill = current_time
        state.cooldown_until = max(
            state.cooldown_until,
            current_time + cooldown_seconds,
        )

    def record_credential_error(self, lease: KeyLease) -> None:
        """Disable only the key associated with an authentication failure."""

        state = self._state_for_lease(lease)
        if state is not None:
            state.disabled = True
            state.tokens = 0.0

    def _refill(self, state: _KeyState, current_time: float) -> None:
        elapsed = max(0.0, current_time - state.last_refill)
        state.tokens = min(
            float(self.burst_capacity),
            state.tokens + elapsed * self.requests_per_second,
        )
        state.last_refill = current_time

    def _is_available(self, state: _KeyState, current_time: float) -> bool:
        return (
            not state.disabled
            and current_time >= state.cooldown_until
            and state.tokens >= 1.0
        )

    def _seconds_until_available(
        self,
        state: _KeyState,
        current_time: float,
    ) -> float:
        self._refill(state, current_time)
        cooldown_remaining = max(0.0, state.cooldown_until - current_time)
        token_remaining = (
            0.0
            if state.tokens >= 1.0
            else (1.0 - state.tokens) / self.requests_per_second
        )
        return max(cooldown_remaining, token_remaining)

    def _state_for_lease(self, lease: KeyLease) -> _KeyState | None:
        for state in self._states:
            if state.key.id == lease.id and state.key.secret == lease.secret:
                return state
        return None
