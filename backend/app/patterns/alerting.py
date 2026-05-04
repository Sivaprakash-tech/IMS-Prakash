"""Strategy pattern for alerting.

Production swap: replace P0Alerter.dispatch with a PagerDuty webhook call,
P1Alerter.dispatch with a Slack #alerts post, P2Alerter.dispatch with a
Slack #noise post. The interface stays the same; ALERT_MAP rewires the
component-type to severity-tier in one place.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from app.logging_setup import get_logger
from app.models import ComponentType, Severity

log = get_logger(__name__)


@dataclass(frozen=True)
class AlertContext:
    work_item_id: int
    component_id: str
    component_type: ComponentType
    severity: Severity
    timestamp: datetime
    summary: str | None = None


class Alerter(ABC):
    tier: str

    @abstractmethod
    def dispatch(self, ctx: AlertContext) -> None: ...


class P0Alerter(Alerter):
    """Page on-call. RDBMS / MCP failures."""

    tier = "P0"

    def dispatch(self, ctx: AlertContext) -> None:
        log.warning(
            "alert.dispatch",
            tier=self.tier,
            channel="pagerduty+slack#sev0",
            work_item_id=ctx.work_item_id,
            component_id=ctx.component_id,
            component_type=ctx.component_type.value,
            severity=ctx.severity.value,
            summary=ctx.summary,
            timestamp=ctx.timestamp.isoformat(),
        )


class P1Alerter(Alerter):
    """High-priority Slack alert. API / Queue failures."""

    tier = "P1"

    def dispatch(self, ctx: AlertContext) -> None:
        log.info(
            "alert.dispatch",
            tier=self.tier,
            channel="slack#alerts",
            work_item_id=ctx.work_item_id,
            component_id=ctx.component_id,
            component_type=ctx.component_type.value,
            severity=ctx.severity.value,
            summary=ctx.summary,
            timestamp=ctx.timestamp.isoformat(),
        )


class P2Alerter(Alerter):
    """Low-priority noise channel. Cache / NoSQL failures."""

    tier = "P2"

    def dispatch(self, ctx: AlertContext) -> None:
        log.info(
            "alert.dispatch",
            tier=self.tier,
            channel="slack#noise",
            work_item_id=ctx.work_item_id,
            component_id=ctx.component_id,
            component_type=ctx.component_type.value,
            severity=ctx.severity.value,
            summary=ctx.summary,
            timestamp=ctx.timestamp.isoformat(),
        )


ALERT_MAP: dict[ComponentType, Alerter] = {
    ComponentType.RDBMS: P0Alerter(),
    ComponentType.MCP:   P0Alerter(),
    ComponentType.API:   P1Alerter(),
    ComponentType.QUEUE: P1Alerter(),
    ComponentType.CACHE: P2Alerter(),
    ComponentType.NOSQL: P2Alerter(),
}


def alerter_for(component_type: ComponentType) -> Alerter:
    return ALERT_MAP[component_type]
