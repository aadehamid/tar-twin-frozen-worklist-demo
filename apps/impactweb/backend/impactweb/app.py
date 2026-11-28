"""IMPACT Web FastAPI application (system of record + CMMS/TLM + write-through contract)."""

from __future__ import annotations

import json
import os
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlmodel import Session, SQLModel, create_engine, select

from impactweb.auth import Caller, get_membership, hash_password, issue_jwt, resolve_caller, verify_password
from impactweb.filter import assert_synthetic_text
from impactweb.models import (
    ArchivedEventLog,
    ChangeFeedEntry,
    ChangeRequest,
    CmmsEquipment,
    CmmsFunctionalLocation,
    Exercise,
    ExerciseInject,
    ExerciseMembership,
    FreezeItem,
    FreezeRecord,
    ReviewDecision,
    TurnaroundEvent,
    UserAccount,
    WorkRequest,
    WorkRequestComment,
)
from impactweb.planning import (
    CLOCK_INDEX,
    CLOCK_STEPS,
    COMMENT_STEPS,
    FREEZE_STEP_INDEX,
    LIBRARY_INJECTS,
    LIBRARY_INJECTS_BY_ID,
    POST_FREEZE_CHANGE_STEPS,
    PRE_FREEZE_EDIT_STEPS,
    enforce_expected_epoch,
    enforce_planning_phase,
    is_active_bootstrap_membership,
    is_facilitator,
    is_global_facilitator,
    load_starting_fixture,
    seed_exercise_from_fixture,
)
from impactweb.seed import DEMO_PASSWORD, seed_demo_exercise, seed_facilitator_emails

DEFAULT_CRAFT_RATES: dict[str, int] = {
    "boilermaker": 235,
    "pipefitter": 225,
    "millwright": 245,
    "instrument_tech": 240,
    "inspector_nde": 260,
    "scaffolder": 195,
    "crane_rigging": 275,
    "catalyst_specialist": 295,
}


class LoginBody(BaseModel):
    email: str
    password: str


class CreateWorkRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: str = "EX-DEMO"
    event_id: str = "TAR-200-2028"
    title: str = Field(min_length=3, max_length=240)
    description: str = Field(min_length=3, max_length=4000)
    equipment_text: str = Field(min_length=1, max_length=240)
    category: str
    work_type_label: str = "GeneralCleanup"
    driver: Literal["inspection", "reliability", "regulatory", "capital", "operations"]
    source_group: Literal["fixed_equipment", "rotating", "inspection", "operations", "projects", "instrumentation"]
    area: str
    ript_score: int = Field(ge=1, le=25)
    mandatory: bool = False
    estimate_hours_by_craft: dict[str, int]


class PatchWorkRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=3, max_length=240)
    description: str | None = Field(default=None, min_length=3, max_length=4000)
    equipment_text: str | None = Field(default=None, min_length=1, max_length=240)
    driver: Literal["inspection", "reliability", "regulatory", "capital", "operations"] | None = None
    area: str | None = None
    ript_score: int | None = Field(default=None, ge=1, le=25)
    mandatory: bool | None = None
    estimate_hours_by_craft: dict[str, int] | None = None


class ReviewDecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["fit_to_frame", "challenge", "drb"]
    kind: Literal["recommendation", "final"] = "final"
    decision: Literal["accept", "reject", "defer", "screen_out", "keep", "merge_duplicate", "remove", "bundle"]
    reason: str = ""


class FreezeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: str = "EX-DEMO"
    event_id: str = "TAR-200-2028"


class DirectChangeRequestBody(BaseModel):
    """Planner/TA/source-group form on POST /api/v1/change-requests. Rejects raised_via with 422."""

    model_config = ConfigDict(extra="forbid")

    exercise_id: str = "EX-DEMO"
    request_id: str | None = None
    change_type: Literal["add", "delete", "change"]
    mandatory: bool = False
    schedule_impact_days: float = 0.0
    risk_if_not_done: str = ""
    hours_delta: int
    cost_delta_usd: int
    title: str = Field(min_length=3, max_length=240)
    equipment_text: str | None = None
    category: str | None = None
    driver: Literal["inspection", "reliability", "regulatory", "capital", "operations"] | None = None
    source_group: Literal["fixed_equipment", "rotating", "inspection", "operations", "projects", "instrumentation"] | None = None
    area: str | None = None
    evidence: str = ""
    reason: str = Field(min_length=3, max_length=4000)


class TwinChangeRequestBody(BaseModel):
    """Delegated raise on POST /api/v1/twin/change-requests (design.md section 5.8). Rejects raised_via with 422."""

    model_config = ConfigDict(extra="forbid")

    exercise_id: str
    request_id: str | None = None
    change_type: Literal["add", "delete", "change"]
    mandatory: bool = False
    schedule_impact_days: float = 0.0
    risk_if_not_done: str = ""
    hours_delta: int
    cost_delta_usd: int
    title: str = Field(min_length=3, max_length=240)
    equipment_text: str | None = None
    category: str | None = None
    driver: Literal["inspection", "reliability", "regulatory", "capital", "operations"] | None = None
    source_group: Literal["fixed_equipment", "rotating", "inspection", "operations", "projects", "instrumentation"] | None = None
    area: str | None = None
    evidence: str = ""
    reason: str = Field(min_length=3, max_length=4000)
    on_behalf_of: str = Field(min_length=1)


class BulkDecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercise_id: str = "EX-DEMO"
    request_ids: list[str] = Field(min_length=1)
    stage: Literal["fit_to_frame", "challenge", "drb"] = "drb"
    decision: Literal["accept", "reject", "defer", "screen_out"] = "accept"
    reason: str = Field(min_length=2, max_length=2000)


class DecideChangeRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=2, max_length=2000)


class WriteThroughToggleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    twin_write_through: bool


class ExerciseSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    twin_write_through: bool | None = None
    allow_external_ai: bool | None = None


class CreateExerciseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, min_length=3, max_length=64)
    name: str = Field(min_length=3, max_length=200)
    mode: Literal["demo", "planning"] = "planning"
    starting_fixture: Literal["seeded", "partial", "blank"] = "seeded"
    twin_write_through: bool = True
    allow_external_ai: bool | None = None


class UpsertMembershipBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=200)
    full_name: str | None = Field(default=None, max_length=200)
    role: Literal["facilitator", "ta_manager", "planner", "source_group", "drb_member", "viewer"]
    source_group: Literal["fixed_equipment", "rotating", "inspection", "operations", "projects", "instrumentation"] | None = None


class AdvanceClockBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_step: Literal[
        "candidate_list",
        "fit_to_frame",
        "challenge",
        "drb",
        "freeze",
        "t_minus_9",
        "t_minus_6",
        "t_minus_3",
        "t_minus_1",
        "closed",
    ]
    reason: str = Field(default="", max_length=1000)


class CreateCommentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=2, max_length=4000)


class ApplyInjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inject_id: str = Field(min_length=2, max_length=80)
    custom: bool = False
    title: str | None = Field(default=None, max_length=240)
    description: str | None = Field(default=None, max_length=4000)
    allowed_phases: list[str] | None = None
    action_kind: Literal["note", "work_request", "change_request", "budget_cut"] = "note"
    source_group: Literal["fixed_equipment", "rotating", "inspection", "operations", "projects", "instrumentation"] | None = None
    driver: Literal["inspection", "reliability", "regulatory", "capital", "operations"] | None = None
    area: str | None = None
    equipment_text: str | None = None
    mandatory: bool = False
    hours_delta: int = 80
    cost_delta_usd: int = 18800
    budget_cut_pct: int = 10


class MaintenanceToggleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


def _compute_hours_and_cost(by_craft: dict[str, int]) -> tuple[int, int]:
    if not by_craft:
        raise HTTPException(status_code=422, detail="estimate_hours_by_craft cannot be empty")
    total_hrs = 0
    total_cost = 0
    for craft, hrs in by_craft.items():
        if hrs < 0:
            raise HTTPException(status_code=422, detail=f"Negative hours for craft {craft}")
        rate = DEFAULT_CRAFT_RATES.get(craft, 235)
        total_hrs += int(hrs)
        total_cost += int(hrs) * rate
    if total_hrs <= 0:
        raise HTTPException(status_code=422, detail="Total estimated hours must be positive")
    return total_hrs, round(total_cost)


def _apply_hours_delta_to_crafts(by_craft: dict[str, int], hours_delta: int) -> dict[str, int]:
    """Adjust craft breakdown atomically so sum(crafts) always equals estimate_hours."""
    updated = {k: max(0, int(v)) for k, v in by_craft.items()}
    if hours_delta == 0:
        return updated
    if hours_delta > 0:
        primary = max(updated, key=lambda k: updated[k]) if updated else "boilermaker"
        updated[primary] = updated.get(primary, 0) + hours_delta
        return updated
    remaining = -hours_delta
    for craft in sorted(updated, key=lambda k: updated[k], reverse=True):
        if remaining <= 0:
            break
        take = min(updated[craft], remaining)
        updated[craft] -= take
        remaining -= take
    return updated


def _serialize_wr(session: Session, wr: WorkRequest) -> dict:
    decisions = session.exec(
        select(ReviewDecision).where(
            ReviewDecision.exercise_id == wr.exercise_id,
            ReviewDecision.request_id == wr.id,
        )
    ).all()
    comments = session.exec(
        select(WorkRequestComment)
        .where(
            WorkRequestComment.exercise_id == wr.exercise_id,
            WorkRequestComment.request_id == wr.id,
        )
        .order_by(WorkRequestComment.created_at)
    ).all()
    has_prior_decision = len(decisions) > 0
    has_current_drb_final = any(
        d.stage == "drb" and d.kind == "final" and d.request_version == wr.version for d in decisions
    )
    stale_decisions = [d for d in decisions if d.request_version < wr.version]
    needs_re_review = has_prior_decision and len(stale_decisions) > 0 and not has_current_drb_final
    latest_drb_final = next(
        (d for d in reversed(decisions) if d.stage == "drb" and d.kind == "final" and d.request_version == wr.version),
        None,
    )
    return {
        "id": wr.id,
        "exercise_id": wr.exercise_id,
        "event_id": wr.event_id,
        "title": wr.title,
        "description": wr.description,
        "equipment_text": wr.equipment_text,
        "category": wr.category,
        "work_type_label": wr.work_type_label,
        "driver": wr.driver,
        "source_group": wr.source_group,
        "area": wr.area,
        "ript_score": wr.ript_score,
        "mandatory": wr.mandatory,
        "estimate_hours": wr.estimate_hours,
        "estimate_hours_by_craft": json.loads(wr.estimate_hours_by_craft_json),
        "estimate_cost_usd": wr.estimate_cost_usd,
        "status": wr.status,
        "version": wr.version,
        "decision_reason": wr.decision_reason,
        "work_package_id": wr.work_package_id,
        "schedule_activity_id": wr.schedule_activity_id,
        "needs_re_review": needs_re_review,
        "drb_final_decision": latest_drb_final.decision if latest_drb_final else None,
        "decisions": [
            {
                "id": d.id,
                "stage": d.stage,
                "kind": d.kind,
                "decision": d.decision,
                "reason": d.reason,
                "request_version": d.request_version,
                "stale": d.request_version < wr.version,
                "decided_by": d.decided_by,
                "decided_at": d.decided_at.isoformat(),
            }
            for d in decisions
        ],
        "comments": [
            {
                "id": c.id,
                "request_version": c.request_version,
                "clock_step": c.clock_step,
                "body": c.body,
                "author_id": c.author_id,
                "created_at": c.created_at.isoformat(),
            }
            for c in comments
        ],
        "submitted_at": wr.submitted_at.isoformat(),
        "updated_at": wr.updated_at.isoformat(),
    }


def _serialize_cr(cr: ChangeRequest, user_names: dict[str, str]) -> dict:
    return {
        "id": cr.id,
        "exercise_id": cr.exercise_id,
        "request_id": cr.request_id,
        "base_version": cr.base_version,
        "change_type": cr.change_type,
        "mandatory": cr.mandatory,
        "schedule_impact_days": cr.schedule_impact_days,
        "risk_if_not_done": cr.risk_if_not_done,
        "hours_delta": cr.hours_delta,
        "cost_delta_usd": cr.cost_delta_usd,
        "title": cr.title,
        "equipment_text": cr.equipment_text,
        "category": cr.category,
        "driver": cr.driver,
        "source_group": cr.source_group,
        "area": cr.area,
        "evidence": cr.evidence,
        "reason": cr.reason,
        "raised_by": cr.raised_by,
        "raised_by_name": user_names.get(cr.raised_by, cr.raised_by),
        "raised_via": cr.raised_via,
        "delegate_token_id": cr.delegate_token_id,
        "status": cr.status,
        "decided_by": cr.decided_by,
        "decision_reason": cr.decision_reason,
        "created_at": cr.created_at.isoformat(),
        "decided_at": cr.decided_at.isoformat() if cr.decided_at else None,
    }


def create_app(
    *,
    database_url: str | None = None,
    scenario_dir: Path | None = None,
    auth_mode: str | None = None,
    jwt_secret: str | None = None,
    edge_auth_secret: str | None = None,
    twin_sync_token: str | None = None,
    twin_raise_token: str | None = None,
    frontend_dist_dir: Path | None = None,
) -> FastAPI:
    repo_root = Path(__file__).resolve().parents[4]
    db_url = database_url or os.environ.get("DATABASE_URL") or f"sqlite:///{repo_root / 'impactweb-local.db'}"
    scen_dir = scenario_dir or Path(os.environ.get("SCENARIO_DIR", str(repo_root / "data" / "scenario")))
    mode = auth_mode or os.environ.get("AUTH_MODE", "local")
    j_secret = jwt_secret or os.environ.get("JWT_SECRET", "tar-twin-local-dev-jwt-secret")
    e_secret = edge_auth_secret or os.environ.get("EDGE_AUTH_SECRET", "")
    sync_tok = twin_sync_token or os.environ.get("TWIN_SYNC_TOKEN", "demo-twin-sync-token")
    raise_tok = twin_raise_token or os.environ.get("TWIN_RAISE_TOKEN", "demo-twin-raise-token")
    dist_dir = frontend_dist_dir or (Path(__file__).resolve().parent / "frontend")

    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    engine = create_engine(db_url, connect_args=connect_args)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        if (scen_dir / "work-requests.json").exists():
            seed_demo_exercise(s, scen_dir, auth_mode=mode)
        else:
            seed_facilitator_emails(s, auth_mode=mode)

    locks: dict[str, threading.Lock] = defaultdict(threading.Lock)

    app = FastAPI(title="IMPACT Web (System of Record Mock)", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.maintenance_mode = False
    app.state.write_barrier_cond = threading.Condition()
    app.state.in_flight_writes = 0

    @app.middleware("http")
    async def maintenance_mode_guard(request: Request, call_next):
        is_guarded_write = request.method in {"POST", "PUT", "PATCH", "DELETE"} and not (
            request.url.path.endswith("/api/v1/admin/maintenance")
            or request.url.path.endswith("/api/v1/auth/login")
        )
        if not is_guarded_write:
            return await call_next(request)

        with app.state.write_barrier_cond:
            if app.state.maintenance_mode:
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=503,
                    content={"detail": "IMPACT Web is in maintenance mode for paired backup"},
                )
            app.state.in_flight_writes += 1
        try:
            return await call_next(request)
        finally:
            with app.state.write_barrier_cond:
                app.state.in_flight_writes -= 1
                if app.state.in_flight_writes == 0:
                    app.state.write_barrier_cond.notify_all()
    app.state.engine = engine
    app.state.scenario_dir = scen_dir
    app.state.exercise_locks = locks

    def get_session():
        with Session(engine) as session:
            yield session

    def get_caller(request: Request, session: Session = Depends(get_session)) -> Caller:
        return resolve_caller(
            request,
            session,
            auth_mode=mode,
            jwt_secret=j_secret,
            edge_auth_secret=e_secret,
            twin_sync_token=sync_tok,
            twin_raise_token=raise_tok,
        )

    def _forbid_delegate_token(caller: Caller) -> None:
        if caller.kind == "twin_raise":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Delegate token is restricted to POST /api/v1/twin/change-requests",
            )

    def _require_user(caller: Caller) -> UserAccount:
        _forbid_delegate_token(caller)
        if caller.kind != "user" or caller.user is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Read-only service token cannot perform write or user-scoped actions",
            )
        return caller.user

    def _require_exercise_read(session: Session, caller: Caller, exercise_id: str) -> None:
        _forbid_delegate_token(caller)
        if caller.kind == "twin_sync":
            return
        if caller.user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if is_facilitator(session, caller.user, exercise_id, auth_mode=mode):
            return
        mem = get_membership(session, exercise_id, caller.user.id)
        if mem is None or not is_active_bootstrap_membership(caller.user, mem, auth_mode=mode):
            raise HTTPException(status_code=403, detail="Not a member of this exercise")

    def _require_facilitator(session: Session, caller: Caller, exercise_id: str | None = None) -> UserAccount:
        user = _require_user(caller)
        if not is_facilitator(session, user, exercise_id, auth_mode=mode):
            raise HTTPException(status_code=403, detail="Facilitator role required for this action")
        return user

    def _is_frozen(session: Session, exercise_id: str) -> FreezeRecord | None:
        return session.exec(
            select(FreezeRecord).where(FreezeRecord.exercise_id == exercise_id).order_by(FreezeRecord.list_version.desc())
        ).first()

    def _append_feed(session: Session, ex: Exercise, entity_type: str, entity_id: str, action: str, payload: dict) -> ChangeFeedEntry:
        entry = ChangeFeedEntry(
            exercise_id=ex.id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            payload_json=json.dumps(payload, sort_keys=True),
            epoch=ex.epoch,
        )
        session.add(entry)
        return entry

    def _raise_change_request_shared(
        session: Session,
        *,
        request: Request | None = None,
        exercise_id: str,
        request_id: str | None,
        change_type: str,
        mandatory: bool,
        schedule_impact_days: float,
        risk_if_not_done: str,
        hours_delta: int,
        cost_delta_usd: int,
        title: str,
        equipment_text: str | None,
        category: str | None,
        driver: str | None,
        source_group: str | None,
        area: str | None,
        evidence: str,
        reason: str,
        raised_by_user: UserAccount,
        raised_via: Literal["iw", "twin"],
        delegate_token_id: str | None,
    ) -> dict:
        if change_type == "add" and request_id is not None:
            raise HTTPException(status_code=422, detail="change_type='add' must omit request_id")
        if change_type in {"change", "delete"} and request_id is None:
            raise HTTPException(status_code=422, detail=f"change_type='{change_type}' requires a target request_id")
        try:
            assert_synthetic_text(title, equipment_text, category, area, reason, evidence, risk_if_not_done)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        with locks[exercise_id]:
            ex = session.get(Exercise, exercise_id)
            if ex is None:
                raise HTTPException(status_code=404, detail=f"Exercise {exercise_id} not found")
            if request is not None:
                enforce_expected_epoch(request, ex)
            if raised_via == "twin":
                if not ex.twin_write_through:
                    raise HTTPException(status_code=403, detail="Exercise twin_write_through switch is off")
                mem = get_membership(session, exercise_id, raised_by_user.id)
                if mem is None or mem.role != "planner":
                    raise HTTPException(
                        status_code=403,
                        detail="Delegated twin change requests require a member with the planner role in the named exercise",
                    )
            if _is_frozen(session, exercise_id) is None:
                raise HTTPException(status_code=403, detail="Change requests are only allowed after freeze")
            enforce_planning_phase(ex, POST_FREEZE_CHANGE_STEPS, "Raising a post-freeze change request")

            base_version = 0
            current_hours = 0
            if request_id is not None:
                wr = session.get(WorkRequest, (request_id, exercise_id))
                if wr is None:
                    raise HTTPException(status_code=404, detail=f"Work request {request_id} not found")
                base_version = wr.version
                current_hours = wr.estimate_hours

            if current_hours + hours_delta < 0:
                raise HTTPException(status_code=422, detail="Target hours cannot be negative")

            cr_id = f"CR-200-{uuid.uuid4().hex[:8].upper()}"
            cr = ChangeRequest(
                id=cr_id,
                exercise_id=exercise_id,
                request_id=request_id,
                base_version=base_version,
                change_type=change_type,
                mandatory=mandatory,
                schedule_impact_days=schedule_impact_days,
                risk_if_not_done=risk_if_not_done,
                hours_delta=hours_delta,
                cost_delta_usd=cost_delta_usd,
                title=title,
                equipment_text=equipment_text,
                category=category,
                driver=driver,
                source_group=source_group,
                area=area,
                evidence=evidence,
                reason=reason,
                raised_by=raised_by_user.id,
                raised_via=raised_via,
                delegate_token_id=delegate_token_id,
                status="pending",
            )
            session.add(cr)
            _append_feed(
                session,
                ex,
                "change_request",
                cr.id,
                "raised",
                {
                    "change_request_id": cr.id,
                    "request_id": cr.request_id,
                    "base_version": cr.base_version,
                    "hours_delta": cr.hours_delta,
                    "cost_delta_usd": cr.cost_delta_usd,
                    "raised_by": cr.raised_by,
                    "raised_via": cr.raised_via,
                    "status": "pending",
                },
            )
            session.commit()
            session.refresh(cr)
            users = {u.id: u.full_name for u in session.exec(select(UserAccount)).all()}
            return _serialize_cr(cr, users)

    api = APIRouter()

    @api.get("/api/v1/utils/health-check/")
    def health_check() -> bool:
        return True

    @api.get("/api/v1/auth/mode")
    def auth_mode_info() -> dict[str, str]:
        return {"auth_mode": mode}

    @api.post("/api/v1/auth/login")
    def login(body: LoginBody, session: Session = Depends(get_session)) -> dict:
        if mode == "exe":
            raise HTTPException(status_code=404, detail="Password login is disabled in AUTH_MODE=exe")
        user = session.exec(select(UserAccount).where(UserAccount.email == body.email.strip().lower())).first()
        if user is None or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        token = issue_jwt(user.id, user.email, j_secret)
        return {"access_token": token, "token_type": "bearer", "user": {"id": user.id, "email": user.email, "full_name": user.full_name}}

    @api.get("/api/v1/auth/me")
    def auth_me(caller: Caller = Depends(get_caller), session: Session = Depends(get_session)) -> dict:
        user = _require_user(caller)
        mems = [
            m
            for m in session.exec(select(ExerciseMembership).where(ExerciseMembership.user_id == user.id)).all()
            if is_active_bootstrap_membership(user, m, auth_mode=mode)
        ]
        return {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "memberships": [
                {"exercise_id": m.exercise_id, "role": m.role, "source_group": m.source_group} for m in mems
            ],
        }

    @api.get("/api/v1/exercises")
    def list_exercises(caller: Caller = Depends(get_caller), session: Session = Depends(get_session)) -> list[dict]:
        _forbid_delegate_token(caller)
        exs = session.exec(select(Exercise).order_by(Exercise.created_at)).all()
        allowed_ids: set[str] | None = None
        if caller.kind == "user" and caller.user is not None and not is_facilitator(session, caller.user, auth_mode=mode):
            mems = [
                m.exercise_id
                for m in session.exec(
                    select(ExerciseMembership).where(ExerciseMembership.user_id == caller.user.id)
                ).all()
                if is_active_bootstrap_membership(caller.user, m, auth_mode=mode)
            ]
            allowed_ids = set(mems)
        out = []
        for ex in exs:
            if allowed_ids is not None and ex.id not in allowed_ids:
                continue
            freeze = _is_frozen(session, ex.id)
            out.append(
                {
                    "id": ex.id,
                    "name": ex.name,
                    "mode": ex.mode,
                    "starting_fixture": ex.starting_fixture,
                    "clock_step": ex.clock_step,
                    "twin_write_through": ex.twin_write_through,
                    "allow_external_ai": ex.allow_external_ai,
                    "epoch": ex.epoch,
                    "frozen": freeze is not None,
                    "freeze_id": freeze.id if freeze else None,
                }
            )
        return out

    @api.post("/api/v1/exercises", status_code=201)
    def create_exercise(
        body: CreateExerciseBody,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        user = _require_facilitator(session, caller)
        try:
            assert_synthetic_text(body.name, body.id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        ex_id = (body.id or f"EX-PLAN-{uuid.uuid4().hex[:6].upper()}").strip()
        if session.get(Exercise, ex_id) is not None:
            raise HTTPException(status_code=409, detail=f"Exercise {ex_id} already exists")

        allow_ai = body.allow_external_ai if body.allow_external_ai is not None else (body.mode == "demo")
        with locks[ex_id]:
            ex = Exercise(
                id=ex_id,
                name=body.name.strip(),
                mode=body.mode,
                starting_fixture=body.starting_fixture,
                clock_step="candidate_list",
                twin_write_through=body.twin_write_through,
                allow_external_ai=allow_ai,
                epoch=1,
            )
            session.add(ex)
            session.add(ExerciseMembership(exercise_id=ex_id, user_id=user.id, role="facilitator", source_group=None))
            seeded_count = seed_exercise_from_fixture(session, scen_dir, ex_id, body.starting_fixture)
            _append_feed(
                session,
                ex,
                "exercise",
                ex_id,
                "created",
                {
                    "exercise_id": ex_id,
                    "mode": ex.mode,
                    "starting_fixture": ex.starting_fixture,
                    "seeded_count": seeded_count,
                    "created_by": user.id,
                },
            )
            session.commit()
            session.refresh(ex)
            return {
                "id": ex.id,
                "name": ex.name,
                "mode": ex.mode,
                "starting_fixture": ex.starting_fixture,
                "clock_step": ex.clock_step,
                "twin_write_through": ex.twin_write_through,
                "allow_external_ai": ex.allow_external_ai,
                "epoch": ex.epoch,
                "frozen": False,
                "freeze_id": None,
                "seeded_count": seeded_count,
            }

    @api.get("/api/v1/exercises/{exercise_id}")
    def get_exercise(exercise_id: str, caller: Caller = Depends(get_caller), session: Session = Depends(get_session)) -> dict:
        _require_exercise_read(session, caller, exercise_id)
        ex = session.get(Exercise, exercise_id)
        if ex is None:
            raise HTTPException(status_code=404, detail="Exercise not found")
        ev = session.exec(select(TurnaroundEvent).where(TurnaroundEvent.exercise_id == exercise_id)).first()
        freeze = _is_frozen(session, exercise_id)
        return {
            "id": ex.id,
            "name": ex.name,
            "mode": ex.mode,
            "starting_fixture": ex.starting_fixture,
            "clock_step": ex.clock_step,
            "clock_steps": list(CLOCK_STEPS),
            "twin_write_through": ex.twin_write_through,
            "allow_external_ai": ex.allow_external_ai,
            "epoch": ex.epoch,
            "frozen": freeze is not None,
            "freeze_id": freeze.id if freeze else None,
            "event": ev.model_dump() if ev else None,
        }

    @api.get("/api/v1/exercises/{exercise_id}/briefing-packs")
    def get_briefing_packs(
        exercise_id: str,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        _require_exercise_read(session, caller, exercise_id)
        ex = session.get(Exercise, exercise_id)
        if ex is None:
            raise HTTPException(status_code=404, detail="Exercise not found")
        fixture = load_starting_fixture(scen_dir, ex.starting_fixture)
        return {
            "exercise_id": ex.id,
            "starting_fixture": ex.starting_fixture,
            "fixture_version": fixture.get("fixture_version", 1),
            "expected_request_count": fixture.get("expected_request_count", 0),
            "briefing_packs": fixture.get("briefing_packs", {}),
        }

    @api.get("/api/v1/users")
    def list_users(caller: Caller = Depends(get_caller), session: Session = Depends(get_session)) -> list[dict]:
        _require_facilitator(session, caller)
        users = session.exec(select(UserAccount).order_by(UserAccount.email)).all()
        return [{"id": u.id, "email": u.email, "full_name": u.full_name, "is_superuser": u.is_superuser} for u in users]

    @api.get("/api/v1/exercises/{exercise_id}/memberships")
    def list_memberships(exercise_id: str, caller: Caller = Depends(get_caller), session: Session = Depends(get_session)) -> list[dict]:
        _require_exercise_read(session, caller, exercise_id)
        mems = session.exec(select(ExerciseMembership).where(ExerciseMembership.exercise_id == exercise_id)).all()
        users = {u.id: u for u in session.exec(select(UserAccount)).all()}
        return [
            {
                "exercise_id": m.exercise_id,
                "user_id": m.user_id,
                "email": users[m.user_id].email if m.user_id in users else "",
                "full_name": users[m.user_id].full_name if m.user_id in users else "",
                "role": m.role,
                "source_group": m.source_group,
            }
            for m in mems
            if m.user_id not in users or is_active_bootstrap_membership(users[m.user_id], m, auth_mode=mode)
        ]

    @api.post("/api/v1/exercises/{exercise_id}/memberships", status_code=201)
    def upsert_membership(
        exercise_id: str,
        body: UpsertMembershipBody,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        actor = _require_facilitator(session, caller, exercise_id)
        if body.role == "source_group" and not body.source_group:
            raise HTTPException(status_code=422, detail="source_group role requires a source_group code")
        norm_email = body.email.strip().lower()
        try:
            assert_synthetic_text(body.full_name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        with locks[exercise_id]:
            ex = session.get(Exercise, exercise_id)
            if ex is None:
                raise HTTPException(status_code=404, detail="Exercise not found")
            target_user = session.exec(select(UserAccount).where(UserAccount.email == norm_email)).first()
            if target_user is None:
                new_uid = f"usr-{uuid.uuid4().hex[:8]}"
                target_user = UserAccount(
                    id=new_uid,
                    email=norm_email,
                    full_name=(body.full_name or norm_email.split("@")[0]).strip(),
                    password_hash=hash_password(DEMO_PASSWORD),
                    is_superuser=False,
                )
                session.add(target_user)
                session.flush()
            existing = get_membership(session, exercise_id, target_user.id)
            sg = body.source_group if body.role == "source_group" else None
            if existing is not None:
                existing.role = body.role
                existing.source_group = sg
                session.add(existing)
                action = "updated"
            else:
                session.add(ExerciseMembership(exercise_id=exercise_id, user_id=target_user.id, role=body.role, source_group=sg))
                action = "added"
            _append_feed(
                session,
                ex,
                "membership",
                target_user.id,
                action,
                {"user_id": target_user.id, "email": target_user.email, "role": body.role, "source_group": sg, "by": actor.id},
            )
            session.commit()
            return {
                "exercise_id": exercise_id,
                "user_id": target_user.id,
                "email": target_user.email,
                "full_name": target_user.full_name,
                "role": body.role,
                "source_group": sg,
            }

    @api.delete("/api/v1/exercises/{exercise_id}/memberships/{user_id}")
    def delete_membership(
        exercise_id: str,
        user_id: str,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        actor = _require_facilitator(session, caller, exercise_id)
        with locks[exercise_id]:
            ex = session.get(Exercise, exercise_id)
            if ex is None:
                raise HTTPException(status_code=404, detail="Exercise not found")
            mem = get_membership(session, exercise_id, user_id)
            if mem is None:
                raise HTTPException(status_code=404, detail="Membership not found")
            if mem.role == "facilitator":
                fac_count = len(
                    session.exec(
                        select(ExerciseMembership).where(
                            ExerciseMembership.exercise_id == exercise_id,
                            ExerciseMembership.role == "facilitator",
                        )
                    ).all()
                )
                if fac_count <= 1:
                    raise HTTPException(status_code=409, detail="Cannot remove the sole facilitator of an exercise")
            session.delete(mem)
            _append_feed(
                session,
                ex,
                "membership",
                user_id,
                "removed",
                {"user_id": user_id, "by": actor.id},
            )
            session.commit()
            return {"exercise_id": exercise_id, "user_id": user_id, "removed": True}

    @api.patch("/api/v1/exercises/{exercise_id}/settings")
    def update_exercise_settings(
        exercise_id: str,
        body: ExerciseSettingsBody,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        actor = _require_facilitator(session, caller, exercise_id)
        with locks[exercise_id]:
            ex = session.get(Exercise, exercise_id)
            if ex is None:
                raise HTTPException(status_code=404, detail="Exercise not found")
            if body.twin_write_through is not None:
                ex.twin_write_through = body.twin_write_through
            if body.allow_external_ai is not None:
                ex.allow_external_ai = body.allow_external_ai
            session.add(ex)
            _append_feed(
                session,
                ex,
                "exercise",
                ex.id,
                "settings_updated",
                {
                    "twin_write_through": ex.twin_write_through,
                    "allow_external_ai": ex.allow_external_ai,
                    "by": actor.id,
                },
            )
            session.commit()
            return {
                "exercise_id": ex.id,
                "twin_write_through": ex.twin_write_through,
                "allow_external_ai": ex.allow_external_ai,
            }

    @api.post("/api/v1/exercises/{exercise_id}/clock")
    def advance_clock(
        exercise_id: str,
        body: AdvanceClockBody,
        request: Request,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        actor = _require_facilitator(session, caller, exercise_id)
        try:
            assert_synthetic_text(body.reason)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        with locks[exercise_id]:
            ex = session.get(Exercise, exercise_id)
            if ex is None:
                raise HTTPException(status_code=404, detail="Exercise not found")
            enforce_expected_epoch(request, ex)
            cur_idx = CLOCK_INDEX.get(ex.clock_step, 0)
            tgt_idx = CLOCK_INDEX[body.target_step]
            if tgt_idx <= cur_idx:
                raise HTTPException(
                    status_code=409,
                    detail=f"Clock moves forward only (current '{ex.clock_step}', target '{body.target_step}'). Use reset to go back.",
                )
            if tgt_idx > FREEZE_STEP_INDEX and _is_frozen(session, exercise_id) is None:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot advance clock past 'freeze' until the TA manager freezes the work list",
                )
            prev_step = ex.clock_step
            skipped = list(CLOCK_STEPS[cur_idx + 1 : tgt_idx])
            ex.clock_step = body.target_step
            session.add(ex)
            _append_feed(
                session,
                ex,
                "clock",
                ex.id,
                "advanced",
                {
                    "from_step": prev_step,
                    "to_step": ex.clock_step,
                    "skipped_steps": skipped,
                    "reason": body.reason,
                    "by": actor.id,
                },
            )
            session.commit()
            return {
                "exercise_id": ex.id,
                "from_step": prev_step,
                "clock_step": ex.clock_step,
                "skipped_steps": skipped,
                "frozen": _is_frozen(session, exercise_id) is not None,
            }

    @api.get("/api/v1/injects/library")
    def list_inject_library(caller: Caller = Depends(get_caller)) -> list[dict]:
        _forbid_delegate_token(caller)
        return LIBRARY_INJECTS

    @api.get("/api/v1/exercises/{exercise_id}/injects")
    def list_exercise_injects(
        exercise_id: str,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> list[dict]:
        _require_exercise_read(session, caller, exercise_id)
        rows = session.exec(
            select(ExerciseInject)
            .where(ExerciseInject.exercise_id == exercise_id)
            .order_by(ExerciseInject.applied_at)
        ).all()
        return [
            {
                "id": r.id,
                "exercise_id": r.exercise_id,
                "inject_id": r.inject_id,
                "phase": r.phase,
                "actor": r.actor,
                "payload": json.loads(r.payload_json),
                "applied_at": r.applied_at.isoformat(),
            }
            for r in rows
        ]

    @api.post("/api/v1/exercises/{exercise_id}/injects", status_code=201)
    def apply_inject(
        exercise_id: str,
        body: ApplyInjectBody,
        request: Request,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        from fastapi.responses import JSONResponse

        actor = _require_facilitator(session, caller, exercise_id)
        if body.custom:
            try:
                assert_synthetic_text(body.inject_id, body.title, body.description, body.equipment_text, body.area)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if not body.title or not body.description:
                raise HTTPException(status_code=422, detail="Custom inject requires title and description")
            spec = {
                "inject_id": body.inject_id.strip(),
                "title": body.title.strip(),
                "description": body.description.strip(),
                "allowed_phases": body.allowed_phases or list(CLOCK_STEPS[:-1]),
                "requires_frozen": body.action_kind == "change_request",
                "action_kind": body.action_kind,
                "source_group": body.source_group or "operations",
                "driver": body.driver or "operations",
                "area": body.area or "200-A",
                "equipment_text": body.equipment_text or "Unit 200 general area",
                "category": "General piping and valves",
                "work_type_label": "GeneralCleanup",
                "mandatory": body.mandatory,
                "hours_delta": body.hours_delta,
                "cost_delta_usd": body.cost_delta_usd,
                "budget_cut_pct": body.budget_cut_pct,
                "estimate_hours_by_craft": {"boilermaker": max(10, body.hours_delta)},
                "ript_score": 15,
            }
        else:
            spec = LIBRARY_INJECTS_BY_ID.get(body.inject_id)
            if spec is None:
                raise HTTPException(status_code=404, detail=f"Unknown library inject {body.inject_id}")

        with locks[exercise_id]:
            ex = session.get(Exercise, exercise_id)
            if ex is None:
                raise HTTPException(status_code=404, detail="Exercise not found")
            enforce_expected_epoch(request, ex)
            existing = session.exec(
                select(ExerciseInject).where(
                    ExerciseInject.exercise_id == exercise_id,
                    ExerciseInject.inject_id == spec["inject_id"],
                )
            ).first()
            if existing is not None:
                return JSONResponse(
                    status_code=200,
                    content={
                        "exercise_id": exercise_id,
                        "inject_id": spec["inject_id"],
                        "applied": False,
                        "already_applied": True,
                        "phase": existing.phase,
                    },
                )
            if ex.clock_step not in set(spec["allowed_phases"]):
                raise HTTPException(
                    status_code=409,
                    detail=f"Inject {spec['inject_id']} is not allowed in phase '{ex.clock_step}' (allowed: {', '.join(spec['allowed_phases'])})",
                )
            if spec.get("requires_frozen") and _is_frozen(session, exercise_id) is None:
                raise HTTPException(status_code=409, detail=f"Inject {spec['inject_id']} requires a frozen work list")

            effect: dict = {"action_kind": spec["action_kind"], "title": spec["title"], "description": spec["description"]}
            kind = spec["action_kind"]
            if kind == "budget_cut":
                ev = session.exec(select(TurnaroundEvent).where(TurnaroundEvent.exercise_id == exercise_id)).first()
                if ev is not None:
                    old_b = ev.budget_target_usd
                    pct = int(spec.get("budget_cut_pct", 10))
                    ev.budget_target_usd = round(old_b * (100 - pct) / 100)
                    session.add(ev)
                    effect["old_budget_usd"] = old_b
                    effect["new_budget_usd"] = ev.budget_target_usd
            elif kind == "work_request":
                if _is_frozen(session, exercise_id) is not None:
                    raise HTTPException(status_code=409, detail="Cannot inject a candidate work request after freeze")
                existing_ids = session.exec(select(WorkRequest.id).where(WorkRequest.exercise_id == exercise_id)).all()
                max_num = max((int(rid.split("-")[-1]) for rid in existing_ids if rid.startswith("WR-200-")), default=0)
                new_id = f"WR-200-{max_num + 1:04d}"
                by_craft = spec.get("estimate_hours_by_craft", {"boilermaker": 80})
                hrs, cost = _compute_hours_and_cost(by_craft)
                wr = WorkRequest(
                    id=new_id,
                    exercise_id=exercise_id,
                    event_id="TAR-200-2028",
                    title=spec["title"],
                    description=spec["description"],
                    equipment_text=spec["equipment_text"],
                    category=spec.get("category", "General piping and valves"),
                    work_type_label=spec.get("work_type_label", "GeneralCleanup"),
                    driver=spec.get("driver", "operations"),
                    source_group=spec.get("source_group", "operations"),
                    area=spec.get("area", "200-A"),
                    ript_score=int(spec.get("ript_score", 14)),
                    mandatory=bool(spec.get("mandatory", False)),
                    estimate_hours=hrs,
                    estimate_hours_by_craft_json=json.dumps(by_craft),
                    estimate_cost_usd=cost,
                    status="candidate",
                    version=1,
                )
                session.add(wr)
                _append_feed(session, ex, "work_request", new_id, "created", {"request_id": new_id, "version": 1, "inject_id": spec["inject_id"]})
                effect["request_id"] = new_id
            elif kind == "change_request":
                cr_id = f"CR-200-{uuid.uuid4().hex[:8].upper()}"
                cr = ChangeRequest(
                    id=cr_id,
                    exercise_id=exercise_id,
                    request_id=None,
                    base_version=0,
                    change_type="add",
                    mandatory=bool(spec.get("mandatory", True)),
                    schedule_impact_days=float(spec.get("schedule_impact_days", 0.5)),
                    risk_if_not_done=str(spec.get("risk_if_not_done", "")),
                    hours_delta=int(spec.get("hours_delta", 200)),
                    cost_delta_usd=int(spec.get("cost_delta_usd", 47000)),
                    title=spec["title"],
                    equipment_text=spec.get("equipment_text"),
                    category=spec.get("category"),
                    driver=spec.get("driver", "inspection"),
                    source_group=spec.get("source_group", "inspection"),
                    area=spec.get("area", "200-A"),
                    evidence=f"Inject {spec['inject_id']} ({spec.get('source_group', 'inspection')})",
                    reason=spec["description"],
                    raised_by=f"sys-inject-{spec.get('source_group', 'inspection')}",
                    raised_via="iw",
                    delegate_token_id=None,
                    status="pending",
                )
                session.add(cr)
                _append_feed(
                    session,
                    ex,
                    "change_request",
                    cr_id,
                    "raised",
                    {
                        "change_request_id": cr_id,
                        "inject_id": spec["inject_id"],
                        "hours_delta": cr.hours_delta,
                        "cost_delta_usd": cr.cost_delta_usd,
                        "mandatory": cr.mandatory,
                        "status": "pending",
                    },
                )
                effect["change_request_id"] = cr_id
            elif kind == "comment":
                hint = str(spec.get("target_tag_hint", "")).lower()
                wrs = session.exec(select(WorkRequest).where(WorkRequest.exercise_id == exercise_id).order_by(WorkRequest.id)).all()
                target_wr = next((w for w in wrs if hint and hint in f"{w.equipment_text} {w.title}".lower()), wrs[0] if wrs else None)
                if target_wr is not None:
                    session.add(
                        WorkRequestComment(
                            exercise_id=exercise_id,
                            request_id=target_wr.id,
                            request_version=target_wr.version,
                            clock_step=ex.clock_step,
                            body=str(spec.get("comment_body", spec["description"])),
                            author_id=f"sys-inject-{spec.get('source_group', 'operations')}",
                        )
                    )
                    effect["request_id"] = target_wr.id

            inj = ExerciseInject(
                exercise_id=exercise_id,
                inject_id=spec["inject_id"],
                phase=ex.clock_step,
                actor=actor.id,
                payload_json=json.dumps(effect, sort_keys=True),
            )
            session.add(inj)
            _append_feed(
                session,
                ex,
                "inject",
                spec["inject_id"],
                "applied",
                {"inject_id": spec["inject_id"], "phase": ex.clock_step, "by": actor.id, **effect},
            )
            session.commit()
            return {
                "exercise_id": exercise_id,
                "inject_id": spec["inject_id"],
                "applied": True,
                "already_applied": False,
                "phase": ex.clock_step,
                "effect": effect,
            }

    @api.post("/api/v1/exercises/{exercise_id}/reset")
    def reset_exercise(
        exercise_id: str,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        actor = _require_facilitator(session, caller, exercise_id)
        with locks[exercise_id]:
            ex = session.get(Exercise, exercise_id)
            if ex is None:
                raise HTTPException(status_code=404, detail="Exercise not found")

            # Archive full pre-reset log before bumping epoch and clearing exercise-scoped tables
            prior_epoch = ex.epoch
            wrs = session.exec(select(WorkRequest).where(WorkRequest.exercise_id == exercise_id)).all()
            decs = session.exec(select(ReviewDecision).where(ReviewDecision.exercise_id == exercise_id)).all()
            coms = session.exec(select(WorkRequestComment).where(WorkRequestComment.exercise_id == exercise_id)).all()
            frzs = session.exec(select(FreezeRecord).where(FreezeRecord.exercise_id == exercise_id)).all()
            frz_items = session.exec(select(FreezeItem).where(FreezeItem.exercise_id == exercise_id)).all()
            crs = session.exec(select(ChangeRequest).where(ChangeRequest.exercise_id == exercise_id)).all()
            injs = session.exec(select(ExerciseInject).where(ExerciseInject.exercise_id == exercise_id)).all()
            feeds = session.exec(
                select(ChangeFeedEntry).where(ChangeFeedEntry.exercise_id == exercise_id).order_by(ChangeFeedEntry.seq)
            ).all()

            archive_summary = {
                "exercise_id": ex.id,
                "epoch": prior_epoch,
                "clock_step_at_reset": ex.clock_step,
                "reset_by": actor.id,
                "work_request_count": len(wrs),
                "decision_count": len(decs),
                "comment_count": len(coms),
                "freeze_count": len(frzs),
                "change_request_count": len(crs),
                "inject_count": len(injs),
                "feed_events": [
                    {
                        "seq": f.seq,
                        "entity_type": f.entity_type,
                        "entity_id": f.entity_id,
                        "action": f.action,
                        "payload": json.loads(f.payload_json),
                        "created_at": f.created_at.isoformat(),
                    }
                    for f in feeds
                ],
            }
            session.add(
                ArchivedEventLog(
                    exercise_id=exercise_id,
                    epoch=prior_epoch,
                    summary_json=json.dumps(archive_summary),
                )
            )

            # Raise epoch first and restore clock to candidate_list
            ex.epoch = prior_epoch + 1
            ex.clock_step = "candidate_list"
            session.add(ex)

            for row_group in (frz_items, frzs, crs, coms, decs, injs, feeds, wrs):
                for row in row_group:
                    session.delete(row)
            session.flush()

            seeded_count = seed_exercise_from_fixture(session, scen_dir, exercise_id, ex.starting_fixture)
            _append_feed(
                session,
                ex,
                "exercise",
                ex.id,
                "reset",
                {
                    "previous_epoch": prior_epoch,
                    "epoch": ex.epoch,
                    "starting_fixture": ex.starting_fixture,
                    "seeded_count": seeded_count,
                    "by": actor.id,
                },
            )
            session.commit()
            return {
                "exercise_id": ex.id,
                "previous_epoch": prior_epoch,
                "epoch": ex.epoch,
                "clock_step": ex.clock_step,
                "seeded_count": seeded_count,
                "archived": True,
            }

    @api.get("/api/v1/exercises/{exercise_id}/archives")
    def list_exercise_archives(
        exercise_id: str,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> list[dict]:
        _require_exercise_read(session, caller, exercise_id)
        rows = session.exec(
            select(ArchivedEventLog)
            .where(ArchivedEventLog.exercise_id == exercise_id)
            .order_by(ArchivedEventLog.epoch.desc())
        ).all()
        return [
            {
                "id": r.id,
                "exercise_id": r.exercise_id,
                "epoch": r.epoch,
                "archived_at": r.archived_at.isoformat(),
                "summary": json.loads(r.summary_json),
            }
            for r in rows
        ]

    @api.get("/api/v1/exercises/{exercise_id}/history")
    def get_exercise_history(
        exercise_id: str,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        _require_exercise_read(session, caller, exercise_id)
        ex = session.get(Exercise, exercise_id)
        if ex is None:
            raise HTTPException(status_code=404, detail="Exercise not found")
        users = {u.id: u.full_name for u in session.exec(select(UserAccount)).all()}
        decs = session.exec(
            select(ReviewDecision)
            .where(ReviewDecision.exercise_id == exercise_id)
            .order_by(ReviewDecision.decided_at)
        ).all()
        coms = session.exec(
            select(WorkRequestComment)
            .where(WorkRequestComment.exercise_id == exercise_id)
            .order_by(WorkRequestComment.created_at)
        ).all()
        injs = session.exec(
            select(ExerciseInject)
            .where(ExerciseInject.exercise_id == exercise_id)
            .order_by(ExerciseInject.applied_at)
        ).all()
        feeds = session.exec(
            select(ChangeFeedEntry)
            .where(ChangeFeedEntry.exercise_id == exercise_id)
            .order_by(ChangeFeedEntry.seq)
        ).all()
        frz = _is_frozen(session, exercise_id)
        return {
            "exercise_id": ex.id,
            "epoch": ex.epoch,
            "mode": ex.mode,
            "starting_fixture": ex.starting_fixture,
            "clock_step": ex.clock_step,
            "frozen": frz is not None,
            "freeze": (
                {
                    "id": frz.id,
                    "list_version": frz.list_version,
                    "frozen_by": users.get(frz.frozen_by, frz.frozen_by),
                    "frozen_at": frz.frozen_at.isoformat(),
                }
                if frz
                else None
            ),
            "decisions": [
                {
                    "id": d.id,
                    "request_id": d.request_id,
                    "request_version": d.request_version,
                    "stage": d.stage,
                    "kind": d.kind,
                    "decision": d.decision,
                    "reason": d.reason,
                    "decided_by": users.get(d.decided_by, d.decided_by),
                    "decided_at": d.decided_at.isoformat(),
                }
                for d in decs
            ],
            "comments": [
                {
                    "id": c.id,
                    "request_id": c.request_id,
                    "clock_step": c.clock_step,
                    "body": c.body,
                    "author": users.get(c.author_id, c.author_id),
                    "created_at": c.created_at.isoformat(),
                }
                for c in coms
            ],
            "injects": [
                {
                    "inject_id": i.inject_id,
                    "phase": i.phase,
                    "actor": users.get(i.actor, i.actor),
                    "payload": json.loads(i.payload_json),
                    "applied_at": i.applied_at.isoformat(),
                }
                for i in injs
            ],
            "feed": [
                {
                    "seq": f.seq,
                    "entity_type": f.entity_type,
                    "entity_id": f.entity_id,
                    "action": f.action,
                    "payload": json.loads(f.payload_json),
                    "created_at": f.created_at.isoformat(),
                }
                for f in feeds
            ],
            "user_names": users,
        }

    @api.patch("/api/v1/exercises/{exercise_id}/write-through")
    def toggle_write_through(
        exercise_id: str,
        body: WriteThroughToggleBody,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        user = _require_user(caller)
        mem = get_membership(session, exercise_id, user.id)
        is_ta = mem is not None and mem.role == "ta_manager"
        if not is_facilitator(session, user, exercise_id, auth_mode=mode) and not is_ta:
            raise HTTPException(status_code=403, detail="Only facilitator or TA manager can change write-through switch")
        with locks[exercise_id]:
            ex = session.get(Exercise, exercise_id)
            if ex is None:
                raise HTTPException(status_code=404, detail="Exercise not found")
            ex.twin_write_through = body.twin_write_through
            session.add(ex)
            _append_feed(
                session,
                ex,
                "exercise",
                ex.id,
                "write_through_updated",
                {"twin_write_through": ex.twin_write_through},
            )
            session.commit()
            return {"exercise_id": ex.id, "twin_write_through": ex.twin_write_through}

    @api.get("/api/v1/work-requests")
    def list_work_requests(
        exercise_id: str = Query(default="EX-DEMO"),
        area: str | None = None,
        driver: str | None = None,
        source_group: str | None = None,
        status_filter: str | None = Query(default=None, alias="status"),
        q: str | None = None,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> list[dict]:
        _require_exercise_read(session, caller, exercise_id)
        stmt = select(WorkRequest).where(WorkRequest.exercise_id == exercise_id).order_by(WorkRequest.id)
        rows = session.exec(stmt).all()
        out = []
        q_low = q.lower().strip() if q else ""
        for wr in rows:
            if area and wr.area != area:
                continue
            if driver and wr.driver != driver:
                continue
            if source_group and wr.source_group != source_group:
                continue
            if status_filter and wr.status != status_filter:
                continue
            if q_low and q_low not in f"{wr.id} {wr.title} {wr.equipment_text} {wr.description}".lower():
                continue
            out.append(_serialize_wr(session, wr))
        return out

    @api.get("/api/v1/work-requests/{request_id}")
    def get_work_request(
        request_id: str,
        exercise_id: str = Query(default="EX-DEMO"),
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        _require_exercise_read(session, caller, exercise_id)
        wr = session.get(WorkRequest, (request_id, exercise_id))
        if wr is None:
            raise HTTPException(status_code=404, detail="Work request not found")
        return _serialize_wr(session, wr)

    @api.post("/api/v1/work-requests", status_code=201)
    def create_work_request(
        body: CreateWorkRequestBody,
        request: Request,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        user = _require_user(caller)
        mem = get_membership(session, body.exercise_id, user.id)
        if mem is None or mem.role not in {"ta_manager", "planner", "source_group"}:
            raise HTTPException(status_code=403, detail="Role not permitted to raise work requests")
        if mem.role == "source_group" and mem.source_group != body.source_group:
            raise HTTPException(status_code=403, detail="Source group lead can only raise requests for their own group")

        try:
            assert_synthetic_text(
                body.title,
                body.description,
                body.equipment_text,
                body.category,
                body.work_type_label,
                body.area,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        total_hrs, total_cost = _compute_hours_and_cost(body.estimate_hours_by_craft)

        with locks[body.exercise_id]:
            ex = session.get(Exercise, body.exercise_id)
            if ex is None:
                raise HTTPException(status_code=404, detail="Exercise not found")
            enforce_expected_epoch(request, ex)
            enforce_planning_phase(ex, {"candidate_list"}, "Raising a candidate work request")
            if _is_frozen(session, body.exercise_id) is not None:
                raise HTTPException(status_code=409, detail="Work list is frozen; submit a change request instead")

            existing = session.exec(select(WorkRequest.id).where(WorkRequest.exercise_id == body.exercise_id)).all()
            max_num = max((int(rid.split("-")[-1]) for rid in existing if rid.startswith("WR-200-")), default=0)
            new_id = f"WR-200-{max_num + 1:04d}"
            wr = WorkRequest(
                id=new_id,
                exercise_id=body.exercise_id,
                event_id=body.event_id,
                title=body.title,
                description=body.description,
                equipment_text=body.equipment_text,
                category=body.category,
                work_type_label=body.work_type_label,
                driver=body.driver,
                source_group=body.source_group,
                area=body.area,
                ript_score=body.ript_score,
                mandatory=body.mandatory,
                estimate_hours=total_hrs,
                estimate_hours_by_craft_json=json.dumps(body.estimate_hours_by_craft),
                estimate_cost_usd=total_cost,
                status="candidate",
                version=1,
            )
            session.add(wr)
            _append_feed(session, ex, "work_request", wr.id, "created", {"request_id": wr.id, "version": 1})
            session.commit()
            session.refresh(wr)
            return _serialize_wr(session, wr)

    @api.patch("/api/v1/work-requests/{request_id}")
    def patch_work_request(
        request_id: str,
        body: PatchWorkRequestBody,
        request: Request,
        exercise_id: str = Query(default="EX-DEMO"),
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        user = _require_user(caller)
        mem = get_membership(session, exercise_id, user.id)
        if mem is None or mem.role not in {"ta_manager", "planner", "source_group"}:
            raise HTTPException(status_code=403, detail="Role not permitted to edit work requests")

        try:
            assert_synthetic_text(body.title, body.description, body.equipment_text, body.area)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        with locks[exercise_id]:
            ex = session.get(Exercise, exercise_id)
            if ex is None:
                raise HTTPException(status_code=404, detail="Exercise not found")
            enforce_expected_epoch(request, ex)
            enforce_planning_phase(ex, PRE_FREEZE_EDIT_STEPS, "Editing a work request")
            if _is_frozen(session, exercise_id) is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Work list is frozen; direct edits are closed. Use the change request process.",
                )
            wr = session.get(WorkRequest, (request_id, exercise_id))
            if wr is None:
                raise HTTPException(status_code=404, detail="Work request not found")
            if mem.role == "source_group" and mem.source_group != wr.source_group:
                raise HTTPException(status_code=403, detail="Source group lead can only edit own group's requests")
            if body.version != wr.version:
                raise HTTPException(
                    status_code=409,
                    detail=f"Stale version {body.version}; current version is {wr.version}",
                )

            if body.title is not None:
                wr.title = body.title
            if body.description is not None:
                wr.description = body.description
            if body.equipment_text is not None:
                wr.equipment_text = body.equipment_text
            if body.driver is not None:
                wr.driver = body.driver
            if body.area is not None:
                wr.area = body.area
            if body.ript_score is not None:
                wr.ript_score = body.ript_score
            if body.mandatory is not None:
                wr.mandatory = body.mandatory
            if body.estimate_hours_by_craft is not None:
                hrs, cost = _compute_hours_and_cost(body.estimate_hours_by_craft)
                wr.estimate_hours = hrs
                wr.estimate_hours_by_craft_json = json.dumps(body.estimate_hours_by_craft)
                wr.estimate_cost_usd = cost

            wr.version += 1
            wr.updated_at = datetime.now(timezone.utc)
            session.add(wr)
            _append_feed(
                session,
                ex,
                "work_request",
                wr.id,
                "updated",
                {"request_id": wr.id, "version": wr.version, "estimate_hours": wr.estimate_hours},
            )
            session.commit()
            session.refresh(wr)
            return _serialize_wr(session, wr)

    @api.post("/api/v1/work-requests/{request_id}/comments", status_code=201)
    def add_work_request_comment(
        request_id: str,
        body: CreateCommentBody,
        request: Request,
        exercise_id: str = Query(default="EX-DEMO"),
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        user = _require_user(caller)
        mem = get_membership(session, exercise_id, user.id)
        if mem is None or mem.role not in {"ta_manager", "planner", "source_group", "drb_member"}:
            raise HTTPException(status_code=403, detail="Role not permitted to comment or defend requests")
        try:
            assert_synthetic_text(body.body)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        with locks[exercise_id]:
            ex = session.get(Exercise, exercise_id)
            if ex is None:
                raise HTTPException(status_code=404, detail="Exercise not found")
            enforce_expected_epoch(request, ex)
            enforce_planning_phase(ex, COMMENT_STEPS, "Commenting or defending a request")
            wr = session.get(WorkRequest, (request_id, exercise_id))
            if wr is None:
                raise HTTPException(status_code=404, detail="Work request not found")
            if mem.role == "source_group" and mem.source_group != wr.source_group:
                raise HTTPException(status_code=403, detail="Source group lead can only comment on own group's requests")
            com = WorkRequestComment(
                exercise_id=exercise_id,
                request_id=request_id,
                request_version=wr.version,
                clock_step=ex.clock_step,
                body=body.body.strip(),
                author_id=user.id,
            )
            session.add(com)
            _append_feed(
                session,
                ex,
                "comment",
                request_id,
                "added",
                {"request_id": request_id, "author_id": user.id, "clock_step": ex.clock_step},
            )
            session.commit()
            session.refresh(com)
            return {
                "id": com.id,
                "exercise_id": com.exercise_id,
                "request_id": com.request_id,
                "request_version": com.request_version,
                "clock_step": com.clock_step,
                "body": com.body,
                "author_id": com.author_id,
                "created_at": com.created_at.isoformat(),
            }

    @api.post("/api/v1/work-requests/{request_id}/decisions", status_code=201)
    def record_review_decision(
        request_id: str,
        body: ReviewDecisionBody,
        request: Request,
        exercise_id: str = Query(default="EX-DEMO"),
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        user = _require_user(caller)
        mem = get_membership(session, exercise_id, user.id)
        if mem is None:
            raise HTTPException(status_code=403, detail="Not a member of this exercise")

        if body.stage == "fit_to_frame":
            if mem.role not in {"ta_manager", "planner"}:
                raise HTTPException(status_code=403, detail="Only planner or TA manager may make fit-to-frame decisions")
        elif body.stage == "challenge":
            if mem.role != "ta_manager":
                raise HTTPException(status_code=403, detail="Only TA manager may record challenge decisions")
        elif body.stage == "drb":
            if body.kind == "recommendation" and mem.role != "drb_member":
                raise HTTPException(status_code=403, detail="Only DRB members record DRB recommendations")
            if body.kind == "final" and mem.role != "ta_manager":
                raise HTTPException(status_code=403, detail="Only TA manager records final DRB decisions")

        try:
            assert_synthetic_text(body.reason)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        with locks[exercise_id]:
            ex = session.get(Exercise, exercise_id)
            if ex is None:
                raise HTTPException(status_code=404, detail="Exercise not found")
            enforce_expected_epoch(request, ex)
            enforce_planning_phase(ex, {body.stage}, f"Recording a {body.stage} decision")
            if _is_frozen(session, exercise_id) is not None:
                raise HTTPException(status_code=409, detail="Work list is already frozen")
            wr = session.get(WorkRequest, (request_id, exercise_id))
            if wr is None:
                raise HTTPException(status_code=404, detail="Work request not found")

            dec = ReviewDecision(
                exercise_id=exercise_id,
                request_id=request_id,
                request_version=wr.version,
                stage=body.stage,
                kind=body.kind,
                decision=body.decision,
                reason=body.reason,
                decided_by=user.id,
            )
            session.add(dec)
            if body.kind == "final":
                status_map = {
                    "accept": "accepted",
                    "reject": "rejected",
                    "defer": "deferred",
                    "screen_out": "screened_out",
                    "remove": "rejected",
                    "merge_duplicate": "deleted",
                }
                if body.decision in status_map:
                    wr.status = status_map[body.decision]
                    wr.decision_reason = body.reason
                    wr.updated_at = datetime.now(timezone.utc)
                    session.add(wr)
            _append_feed(
                session,
                ex,
                "review_decision",
                request_id,
                f"{body.stage}_{body.kind}_{body.decision}",
                {
                    "request_id": request_id,
                    "request_version": wr.version,
                    "stage": body.stage,
                    "kind": body.kind,
                    "decision": body.decision,
                },
            )
            session.commit()
            session.refresh(dec)
            return {
                "id": dec.id,
                "request_id": dec.request_id,
                "request_version": dec.request_version,
                "stage": dec.stage,
                "kind": dec.kind,
                "decision": dec.decision,
                "reason": dec.reason,
                "decided_by": dec.decided_by,
            }

    @api.post("/api/v1/work-requests/bulk-decisions", status_code=201)
    def bulk_review_decisions(
        body: BulkDecisionBody,
        request: Request,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        user = _require_user(caller)
        mem = get_membership(session, body.exercise_id, user.id)
        if mem is None or mem.role != "ta_manager":
            raise HTTPException(status_code=403, detail="Only TA manager may record bulk final review decisions")
        try:
            assert_synthetic_text(body.reason)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        status_map = {
            "accept": "accepted",
            "reject": "rejected",
            "defer": "deferred",
            "screen_out": "screened_out",
        }
        with locks[body.exercise_id]:
            ex = session.get(Exercise, body.exercise_id)
            if ex is None:
                raise HTTPException(status_code=404, detail="Exercise not found")
            enforce_expected_epoch(request, ex)
            enforce_planning_phase(ex, {body.stage}, f"Recording bulk {body.stage} decisions")
            if _is_frozen(session, body.exercise_id) is not None:
                raise HTTPException(status_code=409, detail="Work list is already frozen")
            applied = 0
            for req_id in body.request_ids:
                wr = session.get(WorkRequest, (req_id, body.exercise_id))
                if wr is None:
                    continue
                session.add(
                    ReviewDecision(
                        exercise_id=body.exercise_id,
                        request_id=req_id,
                        request_version=wr.version,
                        stage=body.stage,
                        kind="final",
                        decision=body.decision,
                        reason=body.reason,
                        decided_by=user.id,
                    )
                )
                wr.status = status_map[body.decision]
                wr.decision_reason = body.reason
                wr.updated_at = datetime.now(timezone.utc)
                session.add(wr)
                _append_feed(
                    session,
                    ex,
                    "review_decision",
                    req_id,
                    f"{body.stage}_final_{body.decision}",
                    {
                        "request_id": req_id,
                        "request_version": wr.version,
                        "stage": body.stage,
                        "kind": "final",
                        "decision": body.decision,
                    },
                )
                applied += 1
            session.commit()
            return {"exercise_id": body.exercise_id, "applied_count": applied}

    @api.post("/api/v1/freezes", status_code=201)
    def freeze_work_list(
        body: FreezeBody,
        request: Request,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        user = _require_user(caller)
        mem = get_membership(session, body.exercise_id, user.id)
        if mem is None or mem.role != "ta_manager":
            raise HTTPException(status_code=403, detail="Only TA manager can freeze the work list")

        with locks[body.exercise_id]:
            ex = session.get(Exercise, body.exercise_id)
            if ex is None:
                raise HTTPException(status_code=404, detail="Exercise not found")
            enforce_expected_epoch(request, ex)
            enforce_planning_phase(ex, {"freeze"}, "Freezing the work list")
            if _is_frozen(session, body.exercise_id) is not None:
                raise HTTPException(status_code=409, detail="Work list is already frozen")

            freeze_id = f"FRZ-{body.exercise_id}-V1"
            frz = FreezeRecord(
                id=freeze_id,
                exercise_id=body.exercise_id,
                event_id=body.event_id,
                list_version=1,
                frozen_by=user.id,
            )
            session.add(frz)

            wrs = session.exec(select(WorkRequest).where(WorkRequest.exercise_id == body.exercise_id)).all()
            decisions = session.exec(
                select(ReviewDecision).where(
                    ReviewDecision.exercise_id == body.exercise_id,
                    ReviewDecision.stage == "drb",
                    ReviewDecision.kind == "final",
                )
            ).all()
            latest_drb_for_ver: dict[tuple[str, int], str] = {}
            for d in decisions:
                latest_drb_for_ver[(d.request_id, d.request_version)] = d.decision

            copied = 0
            for wr in wrs:
                if latest_drb_for_ver.get((wr.id, wr.version)) == "accept":
                    session.add(
                        FreezeItem(
                            freeze_id=freeze_id,
                            exercise_id=body.exercise_id,
                            request_id=wr.id,
                            request_version=wr.version,
                            title=wr.title,
                            description=wr.description,
                            equipment_text=wr.equipment_text,
                            category=wr.category,
                            work_type_label=wr.work_type_label,
                            driver=wr.driver,
                            source_group=wr.source_group,
                            area=wr.area,
                            ript_score=wr.ript_score,
                            mandatory=wr.mandatory,
                            estimate_hours=wr.estimate_hours,
                            estimate_hours_by_craft_json=wr.estimate_hours_by_craft_json,
                            estimate_cost_usd=wr.estimate_cost_usd,
                            status=wr.status,
                        )
                    )
                    copied += 1

            _append_feed(
                session,
                ex,
                "freeze",
                freeze_id,
                "frozen",
                {"freeze_id": freeze_id, "list_version": 1, "item_count": copied},
            )
            session.commit()
            return {"id": freeze_id, "exercise_id": body.exercise_id, "list_version": 1, "item_count": copied}

    @api.get("/api/v1/freezes/{freeze_id}/items")
    def get_freeze_items(
        freeze_id: str,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> list[dict]:
        _forbid_delegate_token(caller)
        frz = session.get(FreezeRecord, freeze_id)
        if frz is None:
            raise HTTPException(status_code=404, detail="Freeze record not found")
        _require_exercise_read(session, caller, frz.exercise_id)
        items = session.exec(
            select(FreezeItem)
            .where(FreezeItem.freeze_id == freeze_id, FreezeItem.exercise_id == frz.exercise_id)
            .order_by(FreezeItem.request_id)
        ).all()
        return [
            {
                "freeze_id": it.freeze_id,
                "exercise_id": it.exercise_id,
                "request_id": it.request_id,
                "request_version": it.request_version,
                "title": it.title,
                "description": it.description,
                "equipment_text": it.equipment_text,
                "category": it.category,
                "work_type_label": it.work_type_label,
                "driver": it.driver,
                "source_group": it.source_group,
                "area": it.area,
                "ript_score": it.ript_score,
                "mandatory": it.mandatory,
                "estimate_hours": it.estimate_hours,
                "estimate_hours_by_craft": json.loads(it.estimate_hours_by_craft_json),
                "estimate_cost_usd": it.estimate_cost_usd,
                "status": it.status,
            }
            for it in items
        ]

    @api.get("/api/v1/change-requests")
    def list_change_requests(
        exercise_id: str = Query(default="EX-DEMO"),
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> list[dict]:
        _require_exercise_read(session, caller, exercise_id)
        crs = session.exec(
            select(ChangeRequest).where(ChangeRequest.exercise_id == exercise_id).order_by(ChangeRequest.created_at)
        ).all()
        users = {u.id: u.full_name for u in session.exec(select(UserAccount)).all()}
        return [_serialize_cr(cr, users) for cr in crs]

    @api.post("/api/v1/change-requests", status_code=201)
    def raise_change_request_direct(
        body: DirectChangeRequestBody,
        request: Request,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        user = _require_user(caller)
        mem = get_membership(session, body.exercise_id, user.id)
        if mem is None or mem.role not in {"ta_manager", "planner", "source_group"}:
            raise HTTPException(status_code=403, detail="Role not permitted to raise change requests")
        effective_source_group = body.source_group
        if mem.role == "source_group":
            if body.request_id:
                wr = session.get(WorkRequest, (body.request_id, body.exercise_id))
                if wr is not None and wr.source_group != mem.source_group:
                    raise HTTPException(status_code=403, detail="Source group lead may only change own group's items")
            if body.change_type == "add":
                if effective_source_group is None:
                    effective_source_group = mem.source_group
                elif effective_source_group != mem.source_group:
                    raise HTTPException(status_code=403, detail="Source group lead may only add scope for own group")
            elif effective_source_group is not None and effective_source_group != mem.source_group:
                raise HTTPException(status_code=403, detail="Source group lead may not reassign request to another group")
        return _raise_change_request_shared(
            session,
            request=request,
            exercise_id=body.exercise_id,
            request_id=body.request_id,
            change_type=body.change_type,
            mandatory=body.mandatory,
            schedule_impact_days=body.schedule_impact_days,
            risk_if_not_done=body.risk_if_not_done,
            hours_delta=body.hours_delta,
            cost_delta_usd=body.cost_delta_usd,
            title=body.title,
            equipment_text=body.equipment_text,
            category=body.category,
            driver=body.driver,
            source_group=effective_source_group,
            area=body.area,
            evidence=body.evidence,
            reason=body.reason,
            raised_by_user=user,
            raised_via="iw",
            delegate_token_id=None,
        )

    @api.post("/api/v1/twin/change-requests", status_code=201)
    def raise_change_request_from_twin(
        body: TwinChangeRequestBody,
        request: Request,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        """Delegated write-through endpoint (docs/design.md section 5.8, D9)."""
        if caller.kind != "twin_raise":
            raise HTTPException(status_code=403, detail="Endpoint requires TWIN_RAISE_TOKEN delegate credential")

        target_user = session.get(UserAccount, body.on_behalf_of)
        if target_user is None:
            raise HTTPException(status_code=403, detail="Named on_behalf_of user not found")

        return _raise_change_request_shared(
            session,
            request=request,
            exercise_id=body.exercise_id,
            request_id=body.request_id,
            change_type=body.change_type,
            mandatory=body.mandatory,
            schedule_impact_days=body.schedule_impact_days,
            risk_if_not_done=body.risk_if_not_done,
            hours_delta=body.hours_delta,
            cost_delta_usd=body.cost_delta_usd,
            title=body.title,
            equipment_text=body.equipment_text,
            category=body.category,
            driver=body.driver,
            source_group=body.source_group,
            area=body.area,
            evidence=body.evidence,
            reason=body.reason,
            raised_by_user=target_user,
            raised_via="twin",
            delegate_token_id=caller.token_id,
        )

    @api.post("/api/v1/change-requests/{change_id}/decide")
    def decide_change_request(
        change_id: str,
        body: DecideChangeRequestBody,
        request: Request,
        exercise_id: str = Query(default="EX-DEMO"),
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        user = _require_user(caller)
        mem = get_membership(session, exercise_id, user.id)
        if mem is None or mem.role != "ta_manager":
            raise HTTPException(status_code=403, detail="Only TA manager can approve or reject change requests")
        try:
            assert_synthetic_text(body.reason)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        with locks[exercise_id]:
            ex = session.get(Exercise, exercise_id)
            if ex is None:
                raise HTTPException(status_code=404, detail="Exercise not found")
            enforce_expected_epoch(request, ex)
            enforce_planning_phase(ex, POST_FREEZE_CHANGE_STEPS, "Deciding a change request")
            cr = session.get(ChangeRequest, (change_id, exercise_id))
            if cr is None:
                raise HTTPException(status_code=404, detail="Change request not found")
            if cr.status != "pending":
                raise HTTPException(status_code=409, detail=f"Change request already {cr.status}")

            if body.decision == "approved":
                if cr.request_id is not None:
                    wr = session.get(WorkRequest, (cr.request_id, exercise_id))
                    if wr is None:
                        raise HTTPException(status_code=404, detail="Target work request not found")
                    if wr.version != cr.base_version:
                        raise HTTPException(
                            status_code=409,
                            detail=f"Stale base_version {cr.base_version}; request is now at version {wr.version}",
                        )
                    if wr.estimate_hours + cr.hours_delta < 0:
                        raise HTTPException(status_code=422, detail="Target hours cannot be negative")
                    updated_crafts = _apply_hours_delta_to_crafts(
                        json.loads(wr.estimate_hours_by_craft_json),
                        cr.hours_delta,
                    )
                    wr.estimate_hours += cr.hours_delta
                    wr.estimate_hours_by_craft_json = json.dumps(updated_crafts)
                    wr.estimate_cost_usd = max(0, wr.estimate_cost_usd + cr.cost_delta_usd)
                    if cr.change_type == "delete":
                        wr.status = "deleted"
                    else:
                        if cr.equipment_text:
                            wr.equipment_text = cr.equipment_text
                        if cr.category:
                            wr.category = cr.category
                        if cr.driver:
                            wr.driver = cr.driver
                        if cr.source_group:
                            wr.source_group = cr.source_group
                        if cr.area:
                            wr.area = cr.area
                        if cr.mandatory:
                            wr.mandatory = True
                    wr.decision_reason = f"{cr.id}: {cr.title} ({body.reason})"
                    wr.version += 1
                    wr.updated_at = datetime.now(timezone.utc)
                    session.add(wr)
                    _append_feed(
                        session,
                        ex,
                        "work_request",
                        wr.id,
                        "updated",
                        {
                            "request_id": wr.id,
                            "version": wr.version,
                            "estimate_hours": wr.estimate_hours,
                            "status": wr.status,
                            "from_change_request": cr.id,
                        },
                    )
                elif cr.change_type == "add":
                    existing = session.exec(select(WorkRequest.id).where(WorkRequest.exercise_id == exercise_id)).all()
                    max_num = max((int(rid.split("-")[-1]) for rid in existing if rid.startswith("WR-200-")), default=200)
                    new_id = f"WR-200-{max_num + 1:04d}"
                    ev = session.exec(select(TurnaroundEvent).where(TurnaroundEvent.exercise_id == exercise_id)).first()
                    hrs = max(1, cr.hours_delta)
                    cost = max(0, cr.cost_delta_usd)
                    new_wr = WorkRequest(
                        id=new_id,
                        exercise_id=exercise_id,
                        event_id=ev.id if ev else "TAR-200-2028",
                        title=cr.title,
                        description=cr.reason,
                        equipment_text=cr.equipment_text or cr.title,
                        category=cr.category or "General piping and valves",
                        work_type_label="LateScopeAdd",
                        driver=cr.driver or "inspection",
                        source_group=cr.source_group or "fixed_equipment",
                        area=cr.area or "200-A",
                        ript_score=20 if cr.mandatory else 12,
                        mandatory=cr.mandatory,
                        estimate_hours=hrs,
                        estimate_hours_by_craft_json=json.dumps({"boilermaker": hrs}),
                        estimate_cost_usd=cost,
                        status="accepted",
                        version=1,
                        decision_reason=f"Added via approved change request {cr.id}",
                    )
                    session.add(new_wr)
                    cr.request_id = new_id
                    _append_feed(
                        session,
                        ex,
                        "work_request",
                        new_id,
                        "created",
                        {"request_id": new_id, "version": 1, "from_change_request": cr.id},
                    )

            cr.status = body.decision
            cr.decided_by = user.id
            cr.decision_reason = body.reason
            cr.decided_at = datetime.now(timezone.utc)
            session.add(cr)
            _append_feed(
                session,
                ex,
                "change_request",
                cr.id,
                body.decision,
                {
                    "change_request_id": cr.id,
                    "request_id": cr.request_id,
                    "change_type": cr.change_type,
                    "mandatory": cr.mandatory,
                    "hours_delta": cr.hours_delta,
                    "cost_delta_usd": cr.cost_delta_usd,
                    "reason": cr.reason,
                    "raised_by": cr.raised_by,
                    "raised_via": cr.raised_via,
                    "status": cr.status,
                },
            )
            session.commit()
            session.refresh(cr)
            users = {u.id: u.full_name for u in session.exec(select(UserAccount)).all()}
            return _serialize_cr(cr, users)

    @api.get("/api/v1/changes")
    def read_change_feed(
        exercise_id: str = Query(default="EX-DEMO"),
        after_seq: int = Query(default=0, ge=0),
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> list[dict]:
        _require_exercise_read(session, caller, exercise_id)
        entries = session.exec(
            select(ChangeFeedEntry)
            .where(ChangeFeedEntry.exercise_id == exercise_id, ChangeFeedEntry.seq > after_seq)
            .order_by(ChangeFeedEntry.seq)
        ).all()
        return [
            {
                "seq": e.seq,
                "exercise_id": e.exercise_id,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "action": e.action,
                "payload": json.loads(e.payload_json),
                "epoch": e.epoch,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ]

    # --- CMMS / TLM module endpoints ---

    @api.get("/api/v1/cmms/equipment")
    def list_cmms_equipment(caller: Caller = Depends(get_caller), session: Session = Depends(get_session)) -> list[dict]:
        _forbid_delegate_token(caller)
        rows = session.exec(select(CmmsEquipment).order_by(CmmsEquipment.tag)).all()
        return [r.model_dump() for r in rows]

    @api.get("/api/v1/cmms/functional-locations")
    def list_cmms_flocs(caller: Caller = Depends(get_caller), session: Session = Depends(get_session)) -> list[dict]:
        _forbid_delegate_token(caller)
        rows = session.exec(select(CmmsFunctionalLocation).order_by(CmmsFunctionalLocation.code)).all()
        return [r.model_dump() for r in rows]

    # --- Maintenance mode & paired backup watermarks (docs/hosting.md section 5) ---

    @api.post("/api/v1/admin/maintenance")
    def set_maintenance_mode(
        body: MaintenanceToggleBody,
        caller: Caller = Depends(get_caller),
    ) -> dict:
        _forbid_delegate_token(caller)
        if caller.kind == "twin_sync":
            raise HTTPException(status_code=403, detail="Read-only sync token cannot toggle maintenance mode")
        user = _require_user(caller)
        if not is_global_facilitator(user, auth_mode=mode):
            raise HTTPException(status_code=403, detail="Facilitator/superuser role required for maintenance mode")
        with app.state.write_barrier_cond:
            app.state.maintenance_mode = body.enabled
            if body.enabled:
                drained = app.state.write_barrier_cond.wait_for(
                    lambda: app.state.in_flight_writes == 0,
                    timeout=15.0,
                )
                if not drained:
                    raise HTTPException(status_code=503, detail="Timed out waiting for in-flight writes to drain")
        return {"maintenance_mode": app.state.maintenance_mode, "in_flight_writes": app.state.in_flight_writes}

    @api.get("/api/v1/admin/watermarks")
    def get_watermarks(
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        _forbid_delegate_token(caller)
        if caller.kind == "user":
            user = _require_user(caller)
            if not is_global_facilitator(user, auth_mode=mode):
                raise HTTPException(status_code=403, detail="Facilitator or sync token required to read watermarks")
        exs = session.exec(select(Exercise).order_by(Exercise.id)).all()
        cutoffs: dict[str, int] = {}
        for ex in exs:
            max_seq = session.exec(
                select(func.max(ChangeFeedEntry.seq)).where(ChangeFeedEntry.exercise_id == ex.id)
            ).one()
            cutoffs[ex.id] = int(max_seq or 0)
        return {"maintenance_mode": app.state.maintenance_mode, "cutoffs": cutoffs}

    app.include_router(api)
    app.include_router(api, prefix="/impactweb")

    # Serve built React frontend if present (both at / and /impactweb/)
    if (dist_dir / "index.html").exists():
        assets_dir = dist_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="impactweb-assets")
            app.mount("/impactweb/assets", StaticFiles(directory=str(assets_dir)), name="impactweb-prefixed-assets")

        @app.get("/")
        @app.get("/impactweb")
        @app.get("/impactweb/")
        def serve_index():
            return FileResponse(dist_dir / "index.html")

    return app
