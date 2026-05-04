"""Repository layer for Postgres. All DB writes are wrapped with tenacity retries."""
from datetime import datetime
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.models import (
    ComponentType,
    RCA,
    Severity,
    SignalLink,
    SignalMetric,
    WorkItem,
    WorkItemState,
)
from app.storage.postgres import session_scope

RETRY_POLICY = dict(
    retry=retry_if_exception_type(OperationalError),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=0.1, min=0.1, max=2.0),
    reraise=True,
)


async def create_work_item(
    component_id: str,
    component_type: ComponentType,
    severity: Severity,
    start_time: datetime,
    summary: str | None = None,
) -> int:
    async for attempt in AsyncRetrying(**RETRY_POLICY):
        with attempt:
            async with session_scope() as s:
                wi = WorkItem(
                    component_id=component_id,
                    component_type=component_type,
                    severity=severity,
                    state=WorkItemState.OPEN,
                    start_time=start_time,
                    summary=summary,
                )
                s.add(wi)
                await s.flush()
                return wi.id
    raise RuntimeError("unreachable")


async def increment_signal_count(work_item_id: int) -> None:
    async for attempt in AsyncRetrying(**RETRY_POLICY):
        with attempt:
            async with session_scope() as s:
                await s.execute(
                    update(WorkItem)
                    .where(WorkItem.id == work_item_id)
                    .values(signal_count=WorkItem.signal_count + 1)
                )


async def add_signal_link(
    work_item_id: int,
    mongo_signal_id: str,
    component_id: str,
    severity: Severity,
    signal_timestamp: datetime,
) -> None:
    async for attempt in AsyncRetrying(**RETRY_POLICY):
        with attempt:
            async with session_scope() as s:
                s.add(
                    SignalLink(
                        work_item_id=work_item_id,
                        mongo_signal_id=mongo_signal_id,
                        component_id=component_id,
                        severity=severity,
                        signal_timestamp=signal_timestamp,
                    )
                )


async def upsert_metric_bucket(
    bucket: datetime, component_id: str, severity: Severity
) -> None:
    """Increment 1-minute bucket count via INSERT ... ON CONFLICT."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    async for attempt in AsyncRetrying(**RETRY_POLICY):
        with attempt:
            async with session_scope() as s:
                stmt = pg_insert(SignalMetric).values(
                    bucket=bucket, component_id=component_id, severity=severity, count=1
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["bucket", "component_id", "severity"],
                    set_={"count": SignalMetric.count + 1},
                )
                await s.execute(stmt)


async def get_work_item(work_item_id: int) -> WorkItem | None:
    async with session_scope() as s:
        result = await s.execute(select(WorkItem).where(WorkItem.id == work_item_id))
        return result.scalar_one_or_none()


async def list_work_items(
    state: WorkItemState | None = None,
    severity: Severity | None = None,
    limit: int = 200,
) -> Sequence[WorkItem]:
    async with session_scope() as s:
        stmt = select(WorkItem)
        if state is not None:
            stmt = stmt.where(WorkItem.state == state)
        if severity is not None:
            stmt = stmt.where(WorkItem.severity == severity)
        stmt = stmt.order_by(WorkItem.start_time.desc()).limit(limit)
        return list((await s.execute(stmt)).scalars().all())


async def update_state(
    work_item_id: int,
    new_state: WorkItemState,
    end_time: datetime | None = None,
    mttr_seconds: float | None = None,
) -> None:
    async for attempt in AsyncRetrying(**RETRY_POLICY):
        with attempt:
            async with session_scope() as s:
                values: dict = {"state": new_state}
                if end_time is not None:
                    values["end_time"] = end_time
                if mttr_seconds is not None:
                    values["mttr_seconds"] = mttr_seconds
                await s.execute(
                    update(WorkItem).where(WorkItem.id == work_item_id).values(**values)
                )


async def upsert_rca(
    work_item_id: int,
    root_cause_category: str,
    fix_applied: str,
    prevention: str,
    rca_start_time: datetime,
    rca_end_time: datetime,
) -> RCA:
    async for attempt in AsyncRetrying(**RETRY_POLICY):
        with attempt:
            async with session_scope() as s:
                existing = await s.execute(
                    select(RCA).where(RCA.work_item_id == work_item_id)
                )
                row = existing.scalar_one_or_none()
                if row is None:
                    row = RCA(
                        work_item_id=work_item_id,
                        root_cause_category=root_cause_category,
                        fix_applied=fix_applied,
                        prevention=prevention,
                        rca_start_time=rca_start_time,
                        rca_end_time=rca_end_time,
                    )
                    s.add(row)
                else:
                    row.root_cause_category = root_cause_category
                    row.fix_applied = fix_applied
                    row.prevention = prevention
                    row.rca_start_time = rca_start_time
                    row.rca_end_time = rca_end_time
                await s.flush()
                await s.refresh(row)
                return row
    raise RuntimeError("unreachable")


async def get_rca(work_item_id: int) -> RCA | None:
    async with session_scope() as s:
        result = await s.execute(select(RCA).where(RCA.work_item_id == work_item_id))
        return result.scalar_one_or_none()


async def get_signal_links(work_item_id: int, limit: int = 1000) -> Sequence[SignalLink]:
    async with session_scope() as s:
        stmt = (
            select(SignalLink)
            .where(SignalLink.work_item_id == work_item_id)
            .order_by(SignalLink.signal_timestamp.desc())
            .limit(limit)
        )
        return list((await s.execute(stmt)).scalars().all())
