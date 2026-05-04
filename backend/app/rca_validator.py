"""Mandatory RCA validator. Lives outside the State object so it can be
unit-tested in isolation, but is invoked from the State object so the gate
is enforced for ANY caller (API, script, future cron).
"""
from datetime import datetime
from typing import Protocol


class RCARequiredError(Exception):
    """Raised when a CLOSE transition is attempted with no RCA at all."""


class RCAIncompleteError(Exception):
    """Raised when an RCA exists but is missing a required field."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(f"RCA incomplete; missing or blank: {', '.join(missing)}")


class RCALike(Protocol):
    root_cause_category: str
    fix_applied: str
    prevention: str
    rca_start_time: datetime
    rca_end_time: datetime


REQUIRED_FIELDS: tuple[str, ...] = ("root_cause_category", "fix_applied", "prevention")


def validate(rca: RCALike | None) -> None:
    """Raise if the RCA is missing or any required field is blank."""
    if rca is None:
        raise RCARequiredError("RCA is required to close a work item")

    missing: list[str] = []
    for field in REQUIRED_FIELDS:
        value = getattr(rca, field, None)
        if value is None or not isinstance(value, str) or not value.strip():
            missing.append(field)

    start = getattr(rca, "rca_start_time", None)
    end = getattr(rca, "rca_end_time", None)
    if not isinstance(start, datetime):
        missing.append("rca_start_time")
    if not isinstance(end, datetime):
        missing.append("rca_end_time")
    if isinstance(start, datetime) and isinstance(end, datetime) and end < start:
        raise RCAIncompleteError(["rca_end_time must be >= rca_start_time"])

    if missing:
        raise RCAIncompleteError(missing)
