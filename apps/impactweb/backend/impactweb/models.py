"""SQLModel ORM tables for IMPACT Web and the separate CMMS/TLM module."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Exercise(SQLModel, table=True):
    __tablename__ = "exercise"

    id: str = Field(primary_key=True)
    name: str
    mode: str = Field(default="demo")  # demo | planning
    starting_fixture: str = Field(default="seeded")  # seeded | partial | blank
    clock_step: str = Field(default="candidate_list")
    twin_write_through: bool = Field(default=True)
    allow_external_ai: bool = Field(default=False)
    epoch: int = Field(default=1)
    created_at: datetime = Field(default_factory=utcnow)


class UserAccount(SQLModel, table=True):
    __tablename__ = "user_account"

    id: str = Field(primary_key=True)
    email: str = Field(index=True, unique=True)
    full_name: str
    password_hash: str
    is_superuser: bool = Field(default=False)
    is_service_account: bool = Field(default=False)


class ExerciseMembership(SQLModel, table=True):
    __tablename__ = "exercise_membership"

    id: int | None = Field(default=None, primary_key=True)
    exercise_id: str = Field(index=True)
    user_id: str = Field(index=True)
    role: str  # facilitator | ta_manager | planner | source_group | drb_member | viewer
    source_group: str | None = Field(default=None)


class TurnaroundEvent(SQLModel, table=True):
    __tablename__ = "turnaround_event"

    id: str = Field(primary_key=True)
    exercise_id: str = Field(primary_key=True)
    site: str
    unit: str
    name: str
    planned_start: str
    duration_days: int
    freeze_date: str
    budget_target_usd: int


class WorkRequest(SQLModel, table=True):
    __tablename__ = "work_request"

    id: str = Field(primary_key=True)
    exercise_id: str = Field(primary_key=True)
    event_id: str = Field(index=True)
    title: str
    description: str
    equipment_text: str  # Deliberately free text (code freeze)
    category: str
    work_type_label: str = Field(default="GeneralCleanup")
    driver: str
    source_group: str
    area: str
    ript_score: int
    mandatory: bool = Field(default=False)
    estimate_hours: int
    estimate_hours_by_craft_json: str
    estimate_cost_usd: int
    status: str = Field(default="candidate")
    version: int = Field(default=1)
    decision_reason: str = Field(default="")
    work_package_id: str | None = Field(default=None)
    schedule_activity_id: str | None = Field(default=None)
    submitted_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ReviewDecision(SQLModel, table=True):
    __tablename__ = "review_decision"

    id: int | None = Field(default=None, primary_key=True)
    exercise_id: str = Field(index=True)
    request_id: str = Field(index=True)
    request_version: int
    stage: str  # fit_to_frame | challenge | drb
    kind: str  # recommendation | final
    decision: str
    reason: str = Field(default="")
    decided_by: str
    decided_at: datetime = Field(default_factory=utcnow)


class FreezeRecord(SQLModel, table=True):
    __tablename__ = "freeze_record"

    id: str = Field(primary_key=True)
    exercise_id: str = Field(index=True)
    event_id: str
    list_version: int
    frozen_at: datetime = Field(default_factory=utcnow)
    frozen_by: str


class FreezeItem(SQLModel, table=True):
    __tablename__ = "freeze_item"

    id: int | None = Field(default=None, primary_key=True)
    freeze_id: str = Field(index=True)
    exercise_id: str = Field(index=True)
    request_id: str = Field(index=True)
    request_version: int
    title: str
    description: str
    equipment_text: str
    category: str
    work_type_label: str
    driver: str
    source_group: str
    area: str
    ript_score: int
    mandatory: bool
    estimate_hours: int
    estimate_hours_by_craft_json: str
    estimate_cost_usd: int
    status: str


class ChangeRequest(SQLModel, table=True):
    __tablename__ = "change_request"

    id: str = Field(primary_key=True)
    exercise_id: str = Field(primary_key=True)
    request_id: str | None = Field(default=None, index=True)
    base_version: int
    change_type: str  # add | delete | change
    mandatory: bool = Field(default=False)
    schedule_impact_days: float = Field(default=0.0)
    risk_if_not_done: str = Field(default="")
    hours_delta: int
    cost_delta_usd: int
    title: str
    equipment_text: str | None = Field(default=None)
    category: str | None = Field(default=None)
    driver: str | None = Field(default=None)
    source_group: str | None = Field(default=None)
    area: str | None = Field(default=None)
    evidence: str = Field(default="")
    reason: str
    raised_by: str
    raised_via: str  # iw | twin (set solely from credential, never from request body)
    delegate_token_id: str | None = Field(default=None)
    status: str = Field(default="pending")  # pending | approved | rejected
    decided_by: str | None = Field(default=None)
    decision_reason: str = Field(default="")
    created_at: datetime = Field(default_factory=utcnow)
    decided_at: datetime | None = Field(default=None)


class ChangeFeedEntry(SQLModel, table=True):
    __tablename__ = "change_feed"

    seq: int | None = Field(default=None, primary_key=True)
    exercise_id: str = Field(index=True)
    entity_type: str
    entity_id: str
    action: str
    payload_json: str
    epoch: int = Field(default=1)
    created_at: datetime = Field(default_factory=utcnow)


class ExerciseInject(SQLModel, table=True):
    __tablename__ = "exercise_inject"

    id: int | None = Field(default=None, primary_key=True)
    exercise_id: str = Field(index=True)
    inject_id: str = Field(index=True)
    phase: str
    actor: str
    payload_json: str
    applied_at: datetime = Field(default_factory=utcnow)


class ArchivedEventLog(SQLModel, table=True):
    __tablename__ = "archived_event_log"

    id: int | None = Field(default=None, primary_key=True)
    exercise_id: str = Field(index=True)
    epoch: int
    archived_at: datetime = Field(default_factory=utcnow)
    summary_json: str


# --- CMMS / TLM separate module tables ---


class CmmsFunctionalLocation(SQLModel, table=True):
    __tablename__ = "cmms_functional_location"

    code: str = Field(primary_key=True)
    description: str
    parent: str | None = Field(default=None)


class CmmsEquipment(SQLModel, table=True):
    __tablename__ = "cmms_equipment"

    tag: str = Field(primary_key=True)
    description: str
    equipment_class: str
    shacl_class: str = Field(default="Asset")
    functional_location: str
    area: str
    sheet: str = Field(default="")
    parent_tag: str | None = Field(default=None)
    unit: str = Field(default="200")
    status: str = Field(default="active")  # active | retired | other_unit
    operating_pressure_barg: float | None = Field(default=None)
    design_pressure_barg: float | None = Field(default=None)
    operating_temp_c: float | None = Field(default=None)
    design_temp_c: float | None = Field(default=None)
