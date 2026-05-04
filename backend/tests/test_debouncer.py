"""Debouncer logic test using a fake in-memory Redis-shaped store.

The real implementation uses Redis SET NX EX for atomic claim. Here we
simulate the same primitive to lock down the contract: whoever wins the
SET-NX races creates the work item; everyone else attaches signals to it.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest


@dataclass
class FakeRedis:
    store: dict[str, str] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def set_nx_ex(self, key: str, value: str, ttl: int) -> bool:
        async with self.lock:
            if key in self.store:
                return False
            self.store[key] = value
            return True

    async def get(self, key: str) -> str | None:
        async with self.lock:
            return self.store.get(key)


@pytest.mark.asyncio
async def test_first_signal_claims_dedup_window() -> None:
    r = FakeRedis()
    won = await r.set_nx_ex("dedup:CACHE_01", "42", 10)
    assert won is True
    assert await r.get("dedup:CACHE_01") == "42"


@pytest.mark.asyncio
async def test_second_signal_does_not_steal_window() -> None:
    r = FakeRedis()
    await r.set_nx_ex("dedup:CACHE_01", "42", 10)
    won = await r.set_nx_ex("dedup:CACHE_01", "99", 10)
    assert won is False
    assert await r.get("dedup:CACHE_01") == "42"


@pytest.mark.asyncio
async def test_concurrent_claims_only_one_wins() -> None:
    """100 racers, one window, one work item id wins."""
    r = FakeRedis()
    results = await asyncio.gather(
        *[r.set_nx_ex("dedup:CACHE_01", str(i), 10) for i in range(100)]
    )
    assert sum(results) == 1


@pytest.mark.asyncio
async def test_different_components_get_separate_windows() -> None:
    r = FakeRedis()
    a = await r.set_nx_ex("dedup:CACHE_01", "1", 10)
    b = await r.set_nx_ex("dedup:RDBMS_01", "2", 10)
    assert a and b
    assert await r.get("dedup:CACHE_01") == "1"
    assert await r.get("dedup:RDBMS_01") == "2"
