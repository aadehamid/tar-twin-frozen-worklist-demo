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
from sqlmodel import Session, SQLModel, create_engine, select

from impactweb.auth import Caller, get_membership, issue_jwt, resolve_caller, verify_password
from impactweb.filter import assert_synthetic_text
from impactweb.models import (
    ChangeFeedEntry,
    ChangeRequest,
    CmmsEquipment,
    CmmsFunctionalLocation,
    Exercise,
    ExerciseMembership,
    FreezeItem,
    FreezeRecord,
    ReviewDecision,
    TurnaroundEvent,
    UserAccount,
    WorkRequest,
)
from impactweb.seed import seed_demo_exercise

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
            seed_demo_exercise(s, scen_dir)

    locks: dict[str, threading.Lock] = defaultdict(threading.Lock)

    app = FastAPI(title="IMPACT Web (System of Record Mock)", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
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
        if caller.user.is_superuser:
            return
        if get_membership(session, exercise_id, caller.user.id) is None:
            raise HTTPException(status_code=403, detail="Not a member of this exercise")

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
        mems = session.exec(select(ExerciseMembership).where(ExerciseMembership.user_id == user.id)).all()
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
        exs = session.exec(select(Exercise)).all()
        allowed_ids: set[str] | None = None
        if caller.kind == "user" and caller.user is not None and not caller.user.is_superuser:
            mems = session.exec(
                select(ExerciseMembership.exercise_id).where(ExerciseMembership.user_id == caller.user.id)
            ).all()
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
                    "epoch": ex.epoch,
                    "frozen": freeze is not None,
                    "freeze_id": freeze.id if freeze else None,
                }
            )
        return out

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
            "twin_write_through": ex.twin_write_through,
            "epoch": ex.epoch,
            "frozen": freeze is not None,
            "freeze_id": freeze.id if freeze else None,
            "event": ev.model_dump() if ev else None,
        }

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
        ]

    @api.patch("/api/v1/exercises/{exercise_id}/write-through")
    def toggle_write_through(
        exercise_id: str,
        body: WriteThroughToggleBody,
        caller: Caller = Depends(get_caller),
        session: Session = Depends(get_session),
    ) -> dict:
        user = _require_user(caller)
        mem = get_membership(session, exercise_id, user.id)
        if mem is None or mem.role not in {"facilitator", "ta_manager"}:
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

    @api.post("/api/v1/work-requests/{request_id}/decisions", status_code=201)
    def record_review_decision(
        request_id: str,
        body: ReviewDecisionBody,
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
