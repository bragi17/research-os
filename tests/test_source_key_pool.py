from __future__ import annotations

import pytest

from services.source_key_pool import KeyMaterial, NoAvailableSourceKey, SourceKeyPool


class ManualClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class ManualSleep:
    def __init__(self, clock: ManualClock) -> None:
        self.clock = clock
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        self.clock.advance(seconds)


def key(secret: str, *, id: str | None = None, preview: str | None = None) -> KeyMaterial:
    return KeyMaterial(id=id, secret=secret, preview=preview or secret[-4:])


@pytest.mark.asyncio
async def test_acquire_rotates_round_robin_without_reusing_first_key() -> None:
    clock = ManualClock()
    pool = SourceKeyPool(
        [
            key("s2-key-1", id="1", preview="key-1"),
            key("s2-key-2", id="2", preview="key-2"),
            key("s2-key-3", id="3", preview="key-3"),
        ],
        requests_per_second=1.0,
        burst_capacity=1,
        now=clock,
    )

    leases = [await pool.acquire(), await pool.acquire(), await pool.acquire()]

    assert [lease.secret for lease in leases] == [
        "s2-key-1",
        "s2-key-2",
        "s2-key-3",
    ]
    assert [lease.id for lease in leases] == ["1", "2", "3"]
    assert [lease.preview for lease in leases] == ["key-1", "key-2", "key-3"]


@pytest.mark.asyncio
async def test_record_rate_limit_cools_down_only_the_affected_key() -> None:
    clock = ManualClock()
    pool = SourceKeyPool(
        [key("s2-key-1"), key("s2-key-2")],
        requests_per_second=1.0,
        burst_capacity=1,
        now=clock,
    )

    first = await pool.acquire()
    pool.record_rate_limit(first, retry_after_seconds=10.0)

    assert (await pool.acquire()).secret == "s2-key-2"

    clock.advance(10.0)

    assert (await pool.acquire()).secret == "s2-key-1"


@pytest.mark.asyncio
async def test_acquire_waits_for_temporarily_unavailable_keys() -> None:
    clock = ManualClock()
    sleep = ManualSleep(clock)
    pool = SourceKeyPool(
        [key("s2-key-1")],
        requests_per_second=2.0,
        burst_capacity=1,
        now=clock,
        sleep=sleep,
    )

    assert (await pool.acquire()).secret == "s2-key-1"
    assert (await pool.acquire()).secret == "s2-key-1"

    assert sleep.calls == [0.5]


@pytest.mark.asyncio
async def test_constructor_filters_empty_secrets() -> None:
    pool = SourceKeyPool(
        [
            KeyMaterial(id="empty", secret="", preview="empty"),
            key("s2-key-1", id="1"),
            KeyMaterial(id="blank", secret="   ", preview="blank"),
        ],
        requests_per_second=1.0,
        burst_capacity=1,
    )

    assert (await pool.acquire()).secret == "s2-key-1"


@pytest.mark.parametrize(
    ("requests_per_second", "burst_capacity"),
    [
        (0.0, 1),
        (-1.0, 1),
        (1.0, 0),
    ],
)
def test_constructor_rejects_invalid_rate_limit_values(
    requests_per_second: float,
    burst_capacity: int,
) -> None:
    with pytest.raises(ValueError):
        SourceKeyPool(
            [key("s2-key-1")],
            requests_per_second=requests_per_second,
            burst_capacity=burst_capacity,
        )


@pytest.mark.asyncio
async def test_empty_key_pool_raises_no_available_source_key() -> None:
    pool = SourceKeyPool([], requests_per_second=1.0, burst_capacity=1)

    with pytest.raises(NoAvailableSourceKey):
        await pool.acquire()


@pytest.mark.asyncio
async def test_record_credential_error_prevents_key_reuse_when_another_key_exists() -> None:
    clock = ManualClock()
    pool = SourceKeyPool(
        [key("s2-key-1", id="1"), key("s2-key-2", id="2")],
        requests_per_second=1.0,
        burst_capacity=1,
        now=clock,
    )

    first = await pool.acquire()
    pool.record_credential_error(first)

    assert (await pool.acquire()).secret == "s2-key-2"

    clock.advance(1.0)

    assert (await pool.acquire()).secret == "s2-key-2"


@pytest.mark.asyncio
async def test_acquire_raises_when_all_keys_are_credential_disabled() -> None:
    pool = SourceKeyPool(
        [key("s2-key-1", id="1"), key("s2-key-2", id="2")],
        requests_per_second=1.0,
        burst_capacity=1,
    )

    first = await pool.acquire()
    second = await pool.acquire()
    pool.record_credential_error(first)
    pool.record_credential_error(second)

    with pytest.raises(NoAvailableSourceKey):
        await pool.acquire()
