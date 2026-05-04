from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.config import get_settings
from app.logging_setup import get_logger
from app.models import SignalIn

log = get_logger(__name__)


@dataclass
class IngestQueueState:
    queue: asyncio.Queue[SignalIn]
    accepted: int = 0
    dropped: int = 0
    processed: int = 0
    last_accepted_window: int = 0
    last_processed_window: int = 0


_state: IngestQueueState | None = None


def get_state() -> IngestQueueState:
    global _state
    if _state is None:
        s = get_settings()
        _state = IngestQueueState(queue=asyncio.Queue(maxsize=s.queue_maxsize))
    return _state


def reset_state_for_tests() -> None:
    global _state
    _state = None


def queue_pct_full() -> float:
    s = get_state()
    cap = s.queue.maxsize
    return (s.queue.qsize() / cap) if cap else 0.0


def is_backpressured() -> bool:
    return queue_pct_full() >= get_settings().queue_backpressure_threshold


async def offer(signal: SignalIn) -> bool:
    """Try to enqueue a signal. Returns False if backpressured (caller
    should send 503). Never blocks waiting for queue capacity."""
    s = get_state()
    if is_backpressured():
        s.dropped += 1
        return False
    try:
        s.queue.put_nowait(signal)
    except asyncio.QueueFull:
        s.dropped += 1
        return False
    s.accepted += 1
    return True


def snapshot() -> dict[str, float | int]:
    s = get_state()
    return {
        "queue_depth": s.queue.qsize(),
        "queue_pct_full": round(queue_pct_full(), 4),
        "accepted_total": s.accepted,
        "dropped_total": s.dropped,
        "processed_total": s.processed,
    }
