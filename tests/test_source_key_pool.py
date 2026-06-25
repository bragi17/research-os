from __future__ import annotations

import pytest

from services.source_key_pool import NoAvailableSourceKey, SourceKeyPool


class ManualClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_acquire_rotates_round_robin_without_reusing_first_key() -> None:
    clock = ManualClock()
    pool = SourceKeyPool(
        ["s2-key-1", "s2-key-2", "s2-key-3"],
        requests_per_second=1.0,
        burst_capacity=1,
        clock=clock,
    )

    leases = [pool.acquire(), pool.acquire(), pool.acquire()]

    assert [lease.key.value for lease in leases] == [
        "s2-key-1",
        "s2-key-2",
        "s2-key-3",
    ]


def test_record_rate_limit_cools_down_only_the_affected_key() -> None:
    clock = ManualClock()
    pool = SourceKeyPool(
        ["s2-key-1", "s2-key-2"],
        requests_per_second=1.0,
        burst_capacity=1,
        clock=clock,
    )

    first = pool.acquire()
    pool.record_rate_limit(first, retry_after_seconds=10.0)

    assert pool.acquire().key.value == "s2-key-2"

    clock.advance(10.0)

    assert pool.acquire().key.value == "s2-key-1"


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
            ["s2-key-1"],
            requests_per_second=requests_per_second,
            burst_capacity=burst_capacity,
        )


def test_empty_key_pool_raises_no_available_source_key() -> None:
    pool = SourceKeyPool([], requests_per_second=1.0, burst_capacity=1)

    with pytest.raises(NoAvailableSourceKey):
        pool.acquire()


def test_record_credential_error_prevents_key_reuse_when_another_key_exists() -> None:
    clock = ManualClock()
    pool = SourceKeyPool(
        ["s2-key-1", "s2-key-2"],
        requests_per_second=1.0,
        burst_capacity=1,
        clock=clock,
    )

    first = pool.acquire()
    pool.record_credential_error(first)

    assert pool.acquire().key.value == "s2-key-2"

    clock.advance(1.0)

    assert pool.acquire().key.value == "s2-key-2"
