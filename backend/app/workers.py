from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.ingestion import get_state, snapshot
from app.logging_setup import get_logger
from app.models import SignalIn, WorkItemState
from app.patterns.alerting import AlertContext, alerter_for
from app.storage import mongo, postgres_repo, redis_cache

log = get_logger(__name__)

_workers: list[asyncio.Task[None]] = []
_throughput_task: asyncio.Task[None] | None = None
_shutdown = asyncio.Event()


def _bucket_for(ts: datetime) -> datetime:
    """Floor the timestamp to the start of its 1-minute bucket."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.replace(second=0, microsecond=0)


async def _process_one(sig: SignalIn) -> None:
    settings = get_settings()
    state = get_state()

    # 1. Mongo write (raw payload audit log)
    raw_doc: dict[str, Any] = {
        "component_id": sig.component_id,
        "component_type": sig.component_type.value,
        "severity": sig.severity.value,
        "timestamp": sig.timestamp,
        "payload": sig.payload,
        "ingested_at": datetime.now(timezone.utc),
    }
    mongo_id = await mongo.insert_signal(raw_doc)

    # 2. Debounce via Redis SET NX EX
    # We pre-claim with a placeholder, then write back the real work_item_id.
    # Race-free because SET NX EX is atomic.
    placeholder = f"pending:{mongo_id}"
    won = await redis_cache.client().set(
        f"{redis_cache.DEDUP_KEY_PREFIX}{sig.component_id}",
        placeholder,
        nx=True,
        ex=settings.dedup_window_seconds,
    )

    work_item_id: int | None = None
    if won:
        # 3a. Winner: create the work item.
        work_item_id = await postgres_repo.create_work_item(
            component_id=sig.component_id,
            component_type=sig.component_type,
            severity=sig.severity,
            start_time=sig.timestamp,
            summary=f"{sig.component_type.value} signal: {sig.severity.value}",
        )
        # Replace the placeholder with the real work item id (preserve TTL).
        await redis_cache.client().set(
            f"{redis_cache.DEDUP_KEY_PREFIX}{sig.component_id}",
            str(work_item_id),
            ex=settings.dedup_window_seconds,
            xx=True,
        )
        # Push to live feed (severity-scored sorted set for the dashboard).
        await redis_cache.push_live_feed(
            work_item_id, sig.severity.value, sig.component_id
        )
        # Fire the strategy-pattern alerter.
        try:
            alerter_for(sig.component_type).dispatch(
                AlertContext(
                    work_item_id=work_item_id,
                    component_id=sig.component_id,
                    component_type=sig.component_type,
                    severity=sig.severity,
                    timestamp=sig.timestamp,
                    summary=f"new {sig.component_type.value} incident",
                )
            )
        except Exception as e:
            log.warning("alerter.dispatch.failed", error=str(e))
    else:
        # 3b. Loser: existing work item — fetch its id.
        existing = await redis_cache.get_open_work_item(sig.component_id)
        if existing is None:
            # Window expired between SET and GET; create fresh.
            work_item_id = await postgres_repo.create_work_item(
                component_id=sig.component_id,
                component_type=sig.component_type,
                severity=sig.severity,
                start_time=sig.timestamp,
                summary=f"{sig.component_type.value} signal: {sig.severity.value}",
            )
            await redis_cache.client().set(
                f"{redis_cache.DEDUP_KEY_PREFIX}{sig.component_id}",
                str(work_item_id),
                ex=settings.dedup_window_seconds,
            )
        elif isinstance(existing, int):
            work_item_id = existing
            await postgres_repo.increment_signal_count(work_item_id)
        else:  # placeholder still present (rare); skip increment
            work_item_id = None

    # 4. Always: append signal_link + metrics bucket
    if work_item_id is not None:
        await postgres_repo.add_signal_link(
            work_item_id=work_item_id,
            mongo_signal_id=mongo_id,
            component_id=sig.component_id,
            severity=sig.severity,
            signal_timestamp=sig.timestamp,
        )
        # Backfill the work_item_id onto the Mongo doc so detail queries are easy.
        try:
            from bson import ObjectId  # type: ignore[import-not-found]

            await mongo.signals().update_one(
                {"_id": ObjectId(mongo_id)}, {"$set": {"work_item_id": work_item_id}}
            )
        except Exception as e:
            log.warning("mongo.backfill.failed", error=str(e), mongo_id=mongo_id)

    await postgres_repo.upsert_metric_bucket(
        bucket=_bucket_for(sig.timestamp),
        component_id=sig.component_id,
        severity=sig.severity,
    )

    state.processed += 1


async def _worker_loop(worker_id: int) -> None:
    state = get_state()
    log.info("worker.start", worker_id=worker_id)
    while not _shutdown.is_set():
        try:
            sig = await asyncio.wait_for(state.queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        try:
            await _process_one(sig)
        except Exception as e:
            log.exception("worker.process.error", worker_id=worker_id, error=str(e))
        finally:
            state.queue.task_done()
    log.info("worker.stop", worker_id=worker_id)


async def _throughput_loop() -> None:
    settings = get_settings()
    interval = settings.throughput_log_interval
    state = get_state()
    while not _shutdown.is_set():
        try:
            await asyncio.wait_for(_shutdown.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
        snap = snapshot()
        accepted_window = state.accepted - state.last_accepted_window
        processed_window = state.processed - state.last_processed_window
        state.last_accepted_window = state.accepted
        state.last_processed_window = state.processed
        in_per_sec = accepted_window / interval
        out_per_sec = processed_window / interval
        log.info(
            "throughput.window",
            interval_seconds=interval,
            signals_in_per_sec=round(in_per_sec, 2),
            signals_processed_per_sec=round(out_per_sec, 2),
            queue_depth=snap["queue_depth"],
            queue_pct_full=snap["queue_pct_full"],
            dropped_total=snap["dropped_total"],
        )
        try:
            await redis_cache.set_metrics(
                {
                    "signals_in_per_sec": round(in_per_sec, 2),
                    "signals_processed_per_sec": round(out_per_sec, 2),
                    "queue_depth": snap["queue_depth"],
                    "queue_pct_full": snap["queue_pct_full"],
                    "dropped_total": snap["dropped_total"],
                    "accepted_total": snap["accepted_total"],
                    "processed_total": snap["processed_total"],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as e:
            log.warning("metrics.publish.failed", error=str(e))


async def start_workers() -> None:
    settings = get_settings()
    _shutdown.clear()
    for i in range(settings.worker_count):
        _workers.append(asyncio.create_task(_worker_loop(i)))
    global _throughput_task
    _throughput_task = asyncio.create_task(_throughput_loop())
    log.info("workers.started", count=settings.worker_count)


async def stop_workers() -> None:
    _shutdown.set()
    for t in _workers:
        t.cancel()
    if _throughput_task is not None:
        _throughput_task.cancel()
    for t in _workers:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    if _throughput_task is not None:
        try:
            await _throughput_task
        except (asyncio.CancelledError, Exception):
            pass
    _workers.clear()
    log.info("workers.stopped")
