from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from app import rca_validator
from app.models import WorkItemState
from app.patterns import states


@dataclass
class FakeWorkItem:
    id: int = 1
    state: WorkItemState = WorkItemState.OPEN
    start_time: datetime = field(
        default_factory=lambda: datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    )
    end_time: datetime | None = None
    mttr_seconds: float | None = None


@dataclass
class FakeRCA:
    root_cause_category: str = "INFRASTRUCTURE"
    fix_applied: str = "restarted node"
    prevention: str = "added healthcheck"
    rca_start_time: datetime = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    rca_end_time: datetime = datetime(2026, 5, 1, 11, 0, tzinfo=timezone.utc)


def test_open_to_investigating_ok() -> None:
    wi = FakeWorkItem(state=WorkItemState.OPEN)
    r = states.transition(wi, WorkItemState.INVESTIGATING)
    assert r.new_state == WorkItemState.INVESTIGATING


def test_open_to_resolved_illegal() -> None:
    wi = FakeWorkItem(state=WorkItemState.OPEN)
    with pytest.raises(states.IllegalTransitionError):
        states.transition(wi, WorkItemState.RESOLVED)


def test_open_to_closed_illegal() -> None:
    wi = FakeWorkItem(state=WorkItemState.OPEN)
    with pytest.raises(states.IllegalTransitionError):
        states.transition(wi, WorkItemState.CLOSED, FakeRCA())


def test_investigating_to_resolved_ok() -> None:
    wi = FakeWorkItem(state=WorkItemState.INVESTIGATING)
    r = states.transition(wi, WorkItemState.RESOLVED)
    assert r.new_state == WorkItemState.RESOLVED


def test_resolved_to_closed_requires_rca() -> None:
    wi = FakeWorkItem(state=WorkItemState.RESOLVED)
    with pytest.raises(rca_validator.RCARequiredError):
        states.transition(wi, WorkItemState.CLOSED, None)


def test_resolved_to_closed_rejects_incomplete_rca() -> None:
    wi = FakeWorkItem(state=WorkItemState.RESOLVED)
    bad_rca = FakeRCA(fix_applied="")
    with pytest.raises(rca_validator.RCAIncompleteError):
        states.transition(wi, WorkItemState.CLOSED, bad_rca)


def test_resolved_to_closed_computes_mttr() -> None:
    wi = FakeWorkItem(state=WorkItemState.RESOLVED)
    r = states.transition(wi, WorkItemState.CLOSED, FakeRCA())
    assert r.new_state == WorkItemState.CLOSED
    assert r.end_time is not None
    assert r.mttr_seconds is not None and r.mttr_seconds > 0


def test_closed_is_terminal() -> None:
    wi = FakeWorkItem(state=WorkItemState.CLOSED)
    for target in (
        WorkItemState.OPEN,
        WorkItemState.INVESTIGATING,
        WorkItemState.RESOLVED,
        WorkItemState.CLOSED,
    ):
        with pytest.raises(states.IllegalTransitionError):
            states.transition(wi, target, FakeRCA())


def test_resolved_can_bounce_back_to_investigating() -> None:
    wi = FakeWorkItem(state=WorkItemState.RESOLVED)
    r = states.transition(wi, WorkItemState.INVESTIGATING)
    assert r.new_state == WorkItemState.INVESTIGATING


def test_investigating_can_reopen() -> None:
    wi = FakeWorkItem(state=WorkItemState.INVESTIGATING)
    r = states.transition(wi, WorkItemState.OPEN)
    assert r.new_state == WorkItemState.OPEN


def test_state_for_returns_correct_object() -> None:
    assert isinstance(states.state_for(WorkItemState.OPEN), states.OpenState)
    assert isinstance(states.state_for(WorkItemState.INVESTIGATING), states.InvestigatingState)
    assert isinstance(states.state_for(WorkItemState.RESOLVED), states.ResolvedState)
    assert isinstance(states.state_for(WorkItemState.CLOSED), states.ClosedState)
