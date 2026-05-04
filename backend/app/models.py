from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class ComponentType(str, Enum):
    CACHE = "CACHE"
    RDBMS = "RDBMS"
    API = "API"
    MCP = "MCP"
    QUEUE = "QUEUE"
    NOSQL = "NOSQL"


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class WorkItemState(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class RootCauseCategory(str, Enum):
    INFRASTRUCTURE = "INFRASTRUCTURE"
    NETWORK = "NETWORK"
    CODE_DEFECT = "CODE_DEFECT"
    CONFIG = "CONFIG"
    CAPACITY = "CAPACITY"
    DEPENDENCY = "DEPENDENCY"
    HUMAN_ERROR = "HUMAN_ERROR"
    SECURITY = "SECURITY"
    UNKNOWN = "UNKNOWN"


# ---------- ORM ----------

class Base(DeclarativeBase):
    pass


class WorkItem(Base):
    __tablename__ = "work_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    component_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    component_type: Mapped[ComponentType] = mapped_column(
        SAEnum(ComponentType, name="component_type", create_type=False), nullable=False
    )
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity_level", create_type=False), nullable=False
    )
    state: Mapped[WorkItemState] = mapped_column(
        SAEnum(WorkItemState, name="work_item_state", create_type=False),
        nullable=False,
        default=WorkItemState.OPEN,
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mttr_seconds: Mapped[float | None] = mapped_column(Float)
    signal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    rca: Mapped["RCA | None"] = relationship(back_populates="work_item", uselist=False, lazy="selectin")


class RCA(Base):
    __tablename__ = "rca"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    work_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("work_items.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    root_cause_category: Mapped[str] = mapped_column(Text, nullable=False)
    fix_applied: Mapped[str] = mapped_column(Text, nullable=False)
    prevention: Mapped[str] = mapped_column(Text, nullable=False)
    rca_start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rca_end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    work_item: Mapped[WorkItem] = relationship(back_populates="rca")

    __table_args__ = (
        CheckConstraint("length(btrim(fix_applied)) > 0",   name="rca_fix_applied_not_blank"),
        CheckConstraint("length(btrim(prevention)) > 0",    name="rca_prevention_not_blank"),
        CheckConstraint("length(btrim(root_cause_category)) > 0", name="rca_category_not_blank"),
        CheckConstraint("rca_end_time >= rca_start_time",   name="rca_end_after_start"),
    )


class SignalLink(Base):
    __tablename__ = "signal_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    work_item_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    mongo_signal_id: Mapped[str] = mapped_column(Text, nullable=False)
    component_id: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity_level", create_type=False), nullable=False
    )
    signal_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )


class SignalMetric(Base):
    __tablename__ = "signal_metrics"

    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    component_id: Mapped[str] = mapped_column(Text, primary_key=True)
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity_level", create_type=False), primary_key=True
    )
    count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)


# ---------- Pydantic API schemas ----------

class SignalIn(BaseModel):
    component_id: str = Field(min_length=1, max_length=128)
    component_type: ComponentType
    severity: Severity
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("component_id")
    @classmethod
    def strip_component(cls, v: str) -> str:
        return v.strip()


class SignalAccepted(BaseModel):
    accepted: bool = True
    queue_depth: int
    queue_pct_full: float


class WorkItemOut(BaseModel):
    id: int
    component_id: str
    component_type: ComponentType
    severity: Severity
    state: WorkItemState
    start_time: datetime
    end_time: datetime | None
    mttr_seconds: float | None
    signal_count: int
    summary: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RCAIn(BaseModel):
    root_cause_category: RootCauseCategory
    fix_applied: str = Field(min_length=1)
    prevention: str = Field(min_length=1)
    rca_start_time: datetime
    rca_end_time: datetime

    @field_validator("fix_applied", "prevention")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class RCAOut(BaseModel):
    id: int
    work_item_id: int
    root_cause_category: str
    fix_applied: str
    prevention: str
    rca_start_time: datetime
    rca_end_time: datetime
    submitted_at: datetime

    model_config = {"from_attributes": True}


class IncidentDetailOut(BaseModel):
    work_item: WorkItemOut
    rca: RCAOut | None


class TransitionIn(BaseModel):
    target_state: WorkItemState


class HealthOut(BaseModel):
    status: str
    checks: dict[str, bool]
    errors: dict[str, str] | None = None
