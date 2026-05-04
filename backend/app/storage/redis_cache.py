from typing import Any

import redis.asyncio as redis_async

from app.config import get_settings

_client: redis_async.Redis | None = None

DEDUP_KEY_PREFIX = "dedup:"
LIVE_FEED_KEY = "live_feed"
METRICS_KEY = "metrics:throughput"

SEVERITY_SCORE: dict[str, int] = {
    "INFO": 1,
    "WARN": 2,
    "ERROR": 3,
    "CRITICAL": 4,
}


def init_client() -> redis_async.Redis:
    global _client
    if _client is None:
        settings = get_settings()
        _client = redis_async.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def client() -> redis_async.Redis:
    if _client is None:
        init_client()
    assert _client is not None
    return _client


async def claim_dedup_window(component_id: str, work_item_id: int, ttl_seconds: int) -> bool:
    """Atomic SET NX EX. Returns True if this caller is the first to claim the
    dedup window (i.e., should create a new work item). Returns False if a
    work item already exists for this component within the window."""
    key = f"{DEDUP_KEY_PREFIX}{component_id}"
    result = await client().set(key, str(work_item_id), nx=True, ex=ttl_seconds)
    return bool(result)


async def get_open_work_item(component_id: str) -> int | None:
    key = f"{DEDUP_KEY_PREFIX}{component_id}"
    val = await client().get(key)
    return int(val) if val else None


async def clear_dedup(component_id: str) -> None:
    await client().delete(f"{DEDUP_KEY_PREFIX}{component_id}")


async def push_live_feed(work_item_id: int, severity: str, payload: str) -> None:
    score = SEVERITY_SCORE.get(severity, 0)
    member = f"{work_item_id}|{payload}"
    await client().zadd(LIVE_FEED_KEY, {member: score})


async def remove_from_live_feed(work_item_id: int) -> None:
    members = await client().zrange(LIVE_FEED_KEY, 0, -1)
    for m in members:
        if m.startswith(f"{work_item_id}|"):
            await client().zrem(LIVE_FEED_KEY, m)


async def get_live_feed(limit: int = 100) -> list[tuple[str, float]]:
    return await client().zrevrange(LIVE_FEED_KEY, 0, limit - 1, withscores=True)


async def set_metrics(metrics: dict[str, Any]) -> None:
    await client().hset(METRICS_KEY, mapping={k: str(v) for k, v in metrics.items()})


async def get_metrics() -> dict[str, str]:
    return await client().hgetall(METRICS_KEY)


async def ping() -> bool:
    return bool(await client().ping())
