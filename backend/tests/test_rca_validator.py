from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app import rca_validator


@dataclass
class FakeRCA:
    root_cause_category: str = "INFRASTRUCTURE"
    fix_applied: str = "restarted node"
    prevention: str = "added healthcheck"
    rca_start_time: datetime = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    rca_end_time: datetime = datetime(2026, 5, 1, 11, 0, tzinfo=timezone.utc)


def test_validate_passes_for_complete_rca() -> None:
    rca_validator.validate(FakeRCA())


def test_validate_raises_when_rca_is_none() -> None:
    with pytest.raises(rca_validator.RCARequiredError):
        rca_validator.validate(None)


@pytest.mark.parametrize("field", ["root_cause_category", "fix_applied", "prevention"])
def test_validate_raises_when_required_field_blank(field: str) -> None:
    rca = FakeRCA()
    setattr(rca, field, "   ")
    with pytest.raises(rca_validator.RCAIncompleteError) as ei:
        rca_validator.validate(rca)
    assert field in ei.value.missing


@pytest.mark.parametrize("field", ["root_cause_category", "fix_applied", "prevention"])
def test_validate_raises_when_required_field_empty(field: str) -> None:
    rca = FakeRCA()
    setattr(rca, field, "")
    with pytest.raises(rca_validator.RCAIncompleteError):
        rca_validator.validate(rca)


def test_validate_raises_when_end_before_start() -> None:
    rca = FakeRCA()
    rca.rca_end_time = rca.rca_start_time - timedelta(minutes=5)
    with pytest.raises(rca_validator.RCAIncompleteError):
        rca_validator.validate(rca)


def test_validate_collects_all_missing_fields() -> None:
    rca = FakeRCA(fix_applied="", prevention="   ")
    with pytest.raises(rca_validator.RCAIncompleteError) as ei:
        rca_validator.validate(rca)
    assert set(ei.value.missing) >= {"fix_applied", "prevention"}
