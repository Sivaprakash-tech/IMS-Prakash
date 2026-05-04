from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query, status

from app import rca_validator
from app.logging_setup import get_logger
from app.models import (
    IncidentDetailOut,
    RCAIn,
    RCAOut,
    Severity,
    TransitionIn,
    WorkItemOut,
    WorkItemState,
)
from app.patterns import states
from app.storage import mongo, postgres_repo, redis_cache

log = get_logger(__name__)
router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("", response_model=list[WorkItemOut])
async def list_incidents(
    state: WorkItemState | None = Query(default=None),
    severity: Severity | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[WorkItemOut]:
    rows = await postgres_repo.list_work_items(state=state, severity=severity, limit=limit)
    return [WorkItemOut.model_validate(r) for r in rows]


@router.get("/live")
async def live_feed(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    """Pulled from Redis for fast UI refresh; ordered by severity score desc."""
    entries = await redis_cache.get_live_feed(limit=limit)
    out: list[dict[str, Any]] = []
    for member, score in entries:
        if "|" not in member:
            continue
        wid, _, comp = member.partition("|")
        out.append({"work_item_id": int(wid), "component_id": comp, "severity_score": int(score)})
    return out


@router.get("/{work_item_id}", response_model=IncidentDetailOut)
async def get_incident(work_item_id: int = Path(..., ge=1)) -> IncidentDetailOut:
    wi = await postgres_repo.get_work_item(work_item_id)
    if wi is None:
        raise HTTPException(status_code=404, detail=f"work item {work_item_id} not found")
    rca = await postgres_repo.get_rca(work_item_id)
    return IncidentDetailOut(
        work_item=WorkItemOut.model_validate(wi),
        rca=RCAOut.model_validate(rca) if rca else None,
    )


@router.get("/{work_item_id}/signals")
async def get_incident_signals(
    work_item_id: int = Path(..., ge=1),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    wi = await postgres_repo.get_work_item(work_item_id)
    if wi is None:
        raise HTTPException(status_code=404, detail=f"work item {work_item_id} not found")
    raw = await mongo.find_signals_by_work_item(work_item_id, limit=limit)
    # Coerce datetimes/ObjectIds to JSON-friendly strings.
    coerced: list[dict[str, Any]] = []
    for d in raw:
        d["timestamp"] = d["timestamp"].isoformat() if hasattr(d.get("timestamp"), "isoformat") else d.get("timestamp")
        if "ingested_at" in d and hasattr(d["ingested_at"], "isoformat"):
            d["ingested_at"] = d["ingested_at"].isoformat()
        coerced.append(d)
    return {"work_item_id": work_item_id, "count": len(coerced), "signals": coerced}


@router.post("/{work_item_id}/transition", response_model=WorkItemOut)
async def transition_incident(
    body: TransitionIn,
    work_item_id: int = Path(..., ge=1),
) -> WorkItemOut:
    wi = await postgres_repo.get_work_item(work_item_id)
    if wi is None:
        raise HTTPException(status_code=404, detail=f"work item {work_item_id} not found")
    rca = await postgres_repo.get_rca(work_item_id)
    try:
        result = states.transition(wi, body.target_state, rca)
    except rca_validator.RCARequiredError as e:
        raise HTTPException(status_code=400, detail={"error": "rca_required", "message": str(e)})
    except rca_validator.RCAIncompleteError as e:
        raise HTTPException(
            status_code=400,
            detail={"error": "rca_incomplete", "missing": e.missing, "message": str(e)},
        )
    except states.IllegalTransitionError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "illegal_transition",
                "from": e.source.value,
                "to": e.target.value,
            },
        )

    await postgres_repo.update_state(
        work_item_id=work_item_id,
        new_state=result.new_state,
        end_time=result.end_time,
        mttr_seconds=result.mttr_seconds,
    )
    if result.new_state == WorkItemState.CLOSED:
        # Pull from live feed once closed.
        try:
            await redis_cache.remove_from_live_feed(work_item_id)
            await redis_cache.clear_dedup(wi.component_id)
        except Exception as e:
            log.warning("redis.cleanup.failed", work_item_id=work_item_id, error=str(e))

    fresh = await postgres_repo.get_work_item(work_item_id)
    assert fresh is not None
    return WorkItemOut.model_validate(fresh)


@router.post("/{work_item_id}/rca", response_model=RCAOut)
async def submit_rca(
    body: RCAIn,
    work_item_id: int = Path(..., ge=1),
) -> RCAOut:
    wi = await postgres_repo.get_work_item(work_item_id)
    if wi is None:
        raise HTTPException(status_code=404, detail=f"work item {work_item_id} not found")
    if body.rca_end_time < body.rca_start_time:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_time_range", "message": "end must be >= start"},
        )
    rca = await postgres_repo.upsert_rca(
        work_item_id=work_item_id,
        root_cause_category=body.root_cause_category.value,
        fix_applied=body.fix_applied,
        prevention=body.prevention,
        rca_start_time=body.rca_start_time,
        rca_end_time=body.rca_end_time,
    )
    return RCAOut.model_validate(rca)


@router.post(
    "/{work_item_id}/close",
    response_model=WorkItemOut,
    status_code=status.HTTP_200_OK,
)
async def close_incident(work_item_id: int = Path(..., ge=1)) -> WorkItemOut:
    """Convenience endpoint: submit RCA via /rca first, then call this.
    Equivalent to POST /transition {target_state: CLOSED} but explicit for the UI."""
    return await transition_incident(
        body=TransitionIn(target_state=WorkItemState.CLOSED),
        work_item_id=work_item_id,
    )
