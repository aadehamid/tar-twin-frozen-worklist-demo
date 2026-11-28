"""Interactive planning mode helpers: clock steps, fixtures, library injects, and facilitator checks."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from sqlmodel import Session, select

from impactweb.models import Exercise, ExerciseMembership, TurnaroundEvent, UserAccount, WorkRequest

CLOCK_STEPS: tuple[str, ...] = (
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
)

CLOCK_INDEX: dict[str, int] = {step: idx for idx, step in enumerate(CLOCK_STEPS)}
FREEZE_STEP_INDEX: int = CLOCK_INDEX["freeze"]

PRE_FREEZE_EDIT_STEPS: frozenset[str] = frozenset({"candidate_list", "fit_to_frame", "challenge", "drb"})
COMMENT_STEPS: frozenset[str] = frozenset({"challenge", "drb"})
POST_FREEZE_CHANGE_STEPS: frozenset[str] = frozenset({"freeze", "t_minus_9", "t_minus_6", "t_minus_3", "t_minus_1"})

LIBRARY_INJECTS: list[dict[str, Any]] = [
    {
        "inject_id": "INJ-UT-THINNING",
        "title": "UT shows thinning on line 200-P-0412 near E-201C",
        "description": (
            "On-stream UT thickness scan found localized corrosion on line 200-P-0412 near E-201C. "
            "Creates a pending mandatory post-freeze change request from the inspection group."
        ),
        "allowed_phases": ["freeze", "t_minus_9", "t_minus_6", "t_minus_3", "t_minus_1"],
        "requires_frozen": True,
        "action_kind": "change_request",
        "source_group": "inspection",
        "driver": "inspection",
        "area": "200-A",
        "equipment_text": "200-P-0412 near E-201C",
        "category": "Corrosion and thickness inspection",
        "mandatory": True,
        "hours_delta": 260,
        "cost_delta_usd": 61100,
        "schedule_impact_days": 1.0,
        "risk_if_not_done": "Potential loss of containment on hydrotreater feed piping before next turnaround window.",
    },
    {
        "inject_id": "INJ-BUDGET-CUT-10",
        "title": "10% budget cut before DRB",
        "description": "Site leadership lowers the TAR-200-2028 turnaround budget target by 10% ahead of DRB.",
        "allowed_phases": ["challenge", "drb"],
        "requires_frozen": False,
        "action_kind": "budget_cut",
        "budget_cut_pct": 10,
    },
    {
        "inject_id": "INJ-RESUBMIT-DUP",
        "title": "Source group resubmits duplicate E-201B work under new wording",
        "description": (
            "Fixed equipment submits a duplicate tube bundle cleaning request for E-201B phrased as "
            "'middle feed-effluent heat exchanger shell and tube wash'."
        ),
        "allowed_phases": ["candidate_list", "fit_to_frame", "challenge"],
        "requires_frozen": False,
        "action_kind": "work_request",
        "source_group": "fixed_equipment",
        "driver": "reliability",
        "area": "200-A",
        "equipment_text": "middle feed-effluent heat exchanger E201B",
        "category": "Exchanger bundle work",
        "work_type_label": "BundlePull",
        "ript_score": 16,
        "mandatory": False,
        "estimate_hours_by_craft": {"boilermaker": 140, "pipefitter": 60, "scaffolder": 40},
    },
    {
        "inject_id": "INJ-RETIRED-TAG",
        "title": "Request naming retired tag E-200X",
        "description": "Operations submits a cleaning request that names retired tag E-200X, which must not auto-match.",
        "allowed_phases": ["candidate_list", "fit_to_frame", "challenge"],
        "requires_frozen": False,
        "action_kind": "work_request",
        "source_group": "operations",
        "driver": "operations",
        "area": "200-A",
        "equipment_text": "E-200X retired preheat exchanger",
        "category": "Exchanger bundle work",
        "work_type_label": "BundlePull",
        "ript_score": 11,
        "mandatory": False,
        "estimate_hours_by_craft": {"boilermaker": 90, "pipefitter": 30},
    },
    {
        "inject_id": "INJ-DEFER-STRIPPER",
        "title": "Operations asks to defer C-201 stripper tray work",
        "description": (
            "Operations posts a challenge note asking whether C-201 stripper tray maintenance can be deferred "
            "to reduce critical-path column duration."
        ),
        "allowed_phases": ["challenge", "drb"],
        "requires_frozen": False,
        "action_kind": "comment",
        "target_tag_hint": "C-201",
        "source_group": "operations",
        "comment_body": (
            "Inject from Operations: request review of deferring C-201 stripper tray work to shorten column "
            "critical path if integrity inspection confirms acceptable tray margin."
        ),
    },
    {
        "inject_id": "INJ-HOTWORK-CLASH",
        "title": "Hot-work clash prevents shared setup near E-201B",
        "description": (
            "Two co-located jobs near E-201B cannot share a setup because one needs hot work while the "
            "adjacent line is open to hydrocarbon. The team must overrule the twin cluster suggestion."
        ),
        "allowed_phases": ["challenge", "drb"],
        "requires_frozen": False,
        "action_kind": "comment",
        "target_tag_hint": "E-201B",
        "source_group": "operations",
        "comment_body": (
            "Inject safety clash: co-located jobs near E-201B cannot share a single setup because hot work "
            "conflicts with open hydrocarbon line break; overrule shared-setup bundling here."
        ),
    },
]

LIBRARY_INJECTS_BY_ID: dict[str, dict[str, Any]] = {row["inject_id"]: row for row in LIBRARY_INJECTS}


SSO_DISABLED_PASSWORD_HASH = "!sso-only-disabled"
BOOTSTRAP_FACILITATOR_ID_PREFIX = "usr-fac-"


def facilitator_email_allowlist() -> set[str]:
    raw = os.environ.get("FACILITATOR_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_global_facilitator(user: UserAccount, *, auth_mode: str = "local") -> bool:
    email = user.email.strip().lower()
    if auth_mode == "exe":
        return email in facilitator_email_allowlist()
    return bool(user.is_superuser or email in facilitator_email_allowlist())


def is_active_persisted_membership(user: UserAccount, mem: ExerciseMembership, *, auth_mode: str = "local") -> bool:
    """In AUTH_MODE=exe, facilitator privileges are strictly governed by FACILITATOR_EMAILS.

    Per docs/hosting.md, the facilitator console is open only to emails listed in
    FACILITATOR_EMAILS. Persisted facilitator memberships (seeded or manually added) do not
    grant facilitator access in AUTH_MODE=exe once the email is not in FACILITATOR_EMAILS.
    """
    if auth_mode == "exe" and mem.role == "facilitator":
        return user.email.strip().lower() in facilitator_email_allowlist()
    return True


def is_facilitator(
    session: Session,
    user: UserAccount,
    exercise_id: str | None = None,
    *,
    auth_mode: str = "local",
) -> bool:
    if is_global_facilitator(user, auth_mode=auth_mode):
        return True
    if auth_mode == "exe":
        return False
    if exercise_id is not None:
        mem = session.exec(
            select(ExerciseMembership).where(
                ExerciseMembership.exercise_id == exercise_id,
                ExerciseMembership.user_id == user.id,
                ExerciseMembership.role == "facilitator",
            )
        ).first()
        return mem is not None
    # Creating a new exercise or listing users requires global facilitator privilege
    return False


def enforce_planning_phase(ex: Exercise, allowed_steps: set[str] | frozenset[str], action_label: str) -> None:
    if ex.mode != "planning":
        return
    if ex.clock_step not in allowed_steps:
        allowed_list = ", ".join(sorted(allowed_steps, key=lambda s: CLOCK_INDEX.get(s, 99)))
        raise HTTPException(
            status_code=409,
            detail=f"{action_label} is not allowed in phase '{ex.clock_step}' (allowed: {allowed_list})",
        )


def enforce_expected_epoch(request: Request, ex: Exercise) -> None:
    hdr = request.headers.get("X-Exercise-Epoch")
    if hdr is None or not hdr.strip():
        if ex.mode == "planning":
            raise HTTPException(
                status_code=409,
                detail=f"Missing required X-Exercise-Epoch header for planning-mode write (current epoch is {ex.epoch})",
            )
        return
    try:
        expected = int(hdr.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="X-Exercise-Epoch must be an integer") from exc
    if expected != ex.epoch:
        raise HTTPException(
            status_code=409,
            detail=f"Stale exercise epoch {expected}; current epoch is {ex.epoch} after reset",
        )


def load_starting_fixture(scenario_dir: Path, kind: str) -> dict[str, Any]:
    if kind not in {"seeded", "partial", "blank"}:
        raise ValueError(f"Unsupported starting_fixture {kind!r}")
    fix_path = scenario_dir / "fixtures" / f"{kind}.json"
    if fix_path.is_file():
        return json.loads(fix_path.read_text(encoding="utf-8"))
    # Fallback when fixtures directory is not present in minimal test dirs
    wl = json.loads((scenario_dir / "work-requests.json").read_text(encoding="utf-8"))
    wrs = wl["work_requests"]
    count = len(wrs) if kind == "seeded" else (100 if kind == "partial" else 0)
    return {
        "fixture_version": 1,
        "kind": kind,
        "event_id": wl["event_id"],
        "site": wl["site"],
        "unit": wl["unit"],
        "budget_target_usd": wl["budget_target_usd"],
        "expected_request_count": count,
        "request_ids": [r["request_id"] for r in wrs[:count]],
        "uses_planted_answer_key": kind in {"seeded", "partial"},
        "planted_cluster_ids": [],
        "briefing_packs": {},
    }


def seed_exercise_from_fixture(
    session: Session,
    scenario_dir: Path,
    exercise_id: str,
    starting_fixture: str,
) -> int:
    fixture = load_starting_fixture(scenario_dir, starting_fixture)
    wl = json.loads((scenario_dir / "work-requests.json").read_text(encoding="utf-8"))
    existing_ev = session.get(TurnaroundEvent, (wl["event_id"], exercise_id))
    if existing_ev is not None:
        existing_ev.budget_target_usd = int(fixture.get("budget_target_usd", wl["budget_target_usd"]))
        session.add(existing_ev)
    else:
        session.add(
            TurnaroundEvent(
                id=wl["event_id"],
                exercise_id=exercise_id,
                site=wl["site"],
                unit=wl["unit"],
                name="Unit 200 Diesel Hydrotreater Turnaround 2028",
                planned_start="2028-10-01",
                duration_days=wl["planned_duration_days"],
                freeze_date="2027-10-01",
                budget_target_usd=int(fixture.get("budget_target_usd", wl["budget_target_usd"])),
            )
        )

    want_ids = set(fixture.get("request_ids", []))
    by_id = {r["request_id"]: r for r in wl["work_requests"]}
    inserted = 0
    for rid in fixture.get("request_ids", []):
        wr = by_id.get(rid)
        if wr is None or rid not in want_ids:
            continue
        if session.get(WorkRequest, (wr["request_id"], exercise_id)) is not None:
            continue
        session.add(
            WorkRequest(
                id=wr["request_id"],
                exercise_id=exercise_id,
                event_id=wr["event_id"],
                title=wr["title"],
                description=wr["description"],
                equipment_text=wr["equipment_text"],
                category=wr["category"],
                work_type_label=wr["work_type_label"],
                driver=wr["driver"],
                source_group=wr["source_group"],
                area=wr["area"],
                ript_score=wr["ript_score"],
                mandatory=wr["mandatory"],
                estimate_hours=wr["estimate_hours"],
                estimate_hours_by_craft_json=json.dumps(wr["estimate_hours_by_craft"]),
                estimate_cost_usd=wr["estimate_cost_usd"],
                status="candidate",
                version=1,
            )
        )
        inserted += 1
    return inserted
