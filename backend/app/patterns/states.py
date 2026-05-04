from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from app import rca_validator
from app.models import WorkItemState


class IllegalTransitionError(Exception):
    def __init__(self, source: WorkItemState, target: WorkItemState) -> None:
        self.source = source
        self.target = target
        super().__init__(f"illegal transition: {source.value} -> {target.value}")


class WorkItemLike(Protocol):
    id: int
    state: WorkItemState
    start_time: datetime
    end_time: datetime | None
    mttr_seconds: float | None


@dataclass
class TransitionResult:
    new_state: WorkItemState
    end_time: datetime | None = None
    mttr_seconds: float | None = None


class State(ABC):
    """Base class. Each subclass implements only the transitions that are
    legal from itself. Calls to other transitions raise IllegalTransitionError.
    """

    name: WorkItemState

    def to_open(self, _wi: WorkItemLike) -> TransitionResult:
        raise IllegalTransitionError(self.name, WorkItemState.OPEN)

    def to_investigating(self, _wi: WorkItemLike) -> TransitionResult:
        raise IllegalTransitionError(self.name, WorkItemState.INVESTIGATING)

    def to_resolved(self, _wi: WorkItemLike) -> TransitionResult:
        raise IllegalTransitionError(self.name, WorkItemState.RESOLVED)

    def to_closed(self, _wi: WorkItemLike, rca: rca_validator.RCALike | None) -> TransitionResult:
        raise IllegalTransitionError(self.name, WorkItemState.CLOSED)


class OpenState(State):
    name = WorkItemState.OPEN

    def to_investigating(self, _wi: WorkItemLike) -> TransitionResult:
        return TransitionResult(new_state=WorkItemState.INVESTIGATING)


class InvestigatingState(State):
    name = WorkItemState.INVESTIGATING

    def to_resolved(self, _wi: WorkItemLike) -> TransitionResult:
        return TransitionResult(new_state=WorkItemState.RESOLVED)

    # Allow re-open from INVESTIGATING in case it was claimed in error.
    def to_open(self, _wi: WorkItemLike) -> TransitionResult:
        return TransitionResult(new_state=WorkItemState.OPEN)


class ResolvedState(State):
    name = WorkItemState.RESOLVED

    def to_closed(
        self, wi: WorkItemLike, rca: rca_validator.RCALike | None
    ) -> TransitionResult:
        # The gate. Raises RCARequiredError or RCAIncompleteError on failure.
        rca_validator.validate(rca)

        end_time = datetime.now(timezone.utc)
        # Coerce naive starts to UTC to keep MTTR math consistent.
        start = wi.start_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        mttr = (end_time - start).total_seconds()
        return TransitionResult(
            new_state=WorkItemState.CLOSED, end_time=end_time, mttr_seconds=mttr
        )

    # Allow bouncing back to INVESTIGATING if we were premature about resolved.
    def to_investigating(self, _wi: WorkItemLike) -> TransitionResult:
        return TransitionResult(new_state=WorkItemState.INVESTIGATING)


class ClosedState(State):
    name = WorkItemState.CLOSED
    # Terminal. All transitions raise IllegalTransitionError.


_STATES: dict[WorkItemState, State] = {
    WorkItemState.OPEN: OpenState(),
    WorkItemState.INVESTIGATING: InvestigatingState(),
    WorkItemState.RESOLVED: ResolvedState(),
    WorkItemState.CLOSED: ClosedState(),
}


def state_for(s: WorkItemState) -> State:
    return _STATES[s]


def transition(
    wi: WorkItemLike,
    target: WorkItemState,
    rca: rca_validator.RCALike | None = None,
) -> TransitionResult:
    """Dispatch a transition through the State object owned by the work item.

    This is the one and only entry point for state changes; both the REST API
    and the simulate_outage script call this so the RCA gate is unavoidable.
    """
    current = state_for(wi.state)
    if target == WorkItemState.OPEN:
        return current.to_open(wi)
    if target == WorkItemState.INVESTIGATING:
        return current.to_investigating(wi)
    if target == WorkItemState.RESOLVED:
        return current.to_resolved(wi)
    if target == WorkItemState.CLOSED:
        return current.to_closed(wi, rca)
    raise IllegalTransitionError(current.name, target)
