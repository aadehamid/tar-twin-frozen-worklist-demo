"""Seed IMPACT Web and CMMS/TLM tables from data/scenario/."""

from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import Session, select

from impactweb.auth import hash_password
from impactweb.models import (
    CmmsEquipment,
    CmmsFunctionalLocation,
    Exercise,
    ExerciseMembership,
    TurnaroundEvent,
    UserAccount,
    WorkRequest,
)

DEMO_PASSWORD = "demo-pass-2028"

DEMO_USERS: list[tuple[str, str, str, str, str | None]] = [
    # (user_id, email, full_name, role, source_group)
    ("usr-facilitator", "facilitator@demo.local", "A. Facilitator", "facilitator", None),
    ("usr-ta-manager", "ta.manager@demo.local", "M. Turnaround", "ta_manager", None),
    ("usr-planner", "j.planner@demo.local", "J. Planner", "planner", None),
    ("usr-fixed", "fixed.lead@demo.local", "R. Fixed-Equip", "source_group", "fixed_equipment"),
    ("usr-rotating", "rotating.lead@demo.local", "S. Rotating", "source_group", "rotating"),
    ("usr-inspection", "inspection.lead@demo.local", "K. Inspection", "source_group", "inspection"),
    ("usr-operations", "operations.lead@demo.local", "D. Operations", "source_group", "operations"),
    ("usr-projects", "projects.lead@demo.local", "L. Projects", "source_group", "projects"),
    ("usr-instrumentation", "inst.lead@demo.local", "T. Instrumentation", "source_group", "instrumentation"),
    ("usr-drb", "drb.member@demo.local", "P. Review-Board", "drb_member", None),
    ("usr-viewer", "viewer@demo.local", "V. Observer", "viewer", None),
]


def seed_cmms(session: Session, scenario_dir: Path) -> None:
    if session.exec(select(CmmsEquipment)).first() is not None:
        return
    master = json.loads((scenario_dir / "equipment-master.json").read_text(encoding="utf-8"))
    plot = json.loads((scenario_dir / "plot-plan.json").read_text(encoding="utf-8"))

    session.add(CmmsFunctionalLocation(code="DEMO-U200", description="Unit 200 Diesel Hydrotreater", parent=None))
    for area in plot["areas"]:
        session.add(
            CmmsFunctionalLocation(
                code=f"DEMO-U200-{area['code']}",
                description=f"Area {area['code']} {area['name']}",
                parent="DEMO-U200",
            )
        )

    for eq in master["major_equipment"]:
        session.add(
            CmmsEquipment(
                tag=eq["tag"],
                description=eq["description"],
                equipment_class=eq["equipment_class"],
                shacl_class=eq["shacl_class"],
                functional_location=eq["functional_location"],
                area=eq["area"],
                sheet=eq["sheet"],
                unit="200",
                status="active",
                operating_pressure_barg=eq["operating_pressure_barg"],
                design_pressure_barg=eq["design_pressure_barg"],
                operating_temp_c=eq["operating_temp_c"],
                design_temp_c=eq["design_temp_c"],
            )
        )
    for psv in master["psvs"]:
        session.add(
            CmmsEquipment(
                tag=psv["tag"],
                description=psv["description"],
                equipment_class="psv",
                shacl_class="ReliefValve",
                functional_location=psv["functional_location"],
                area=psv["area"],
                sheet=psv["sheet"],
                parent_tag=psv["protects_tag"],
                unit="200",
                status="active",
            )
        )
    for v in master["valves"]:
        session.add(
            CmmsEquipment(
                tag=v["tag"],
                description=v["description"],
                equipment_class="valve",
                shacl_class="BlockValve" if v["role"] == "block" else "Valve",
                functional_location=v["functional_location"],
                area=v["area"],
                sheet=v["sheet"],
                parent_tag=v["parent_equipment"],
                unit="200",
                status="active",
            )
        )
    for inst in master["instruments"]:
        session.add(
            CmmsEquipment(
                tag=inst["tag"],
                description=inst["description"],
                equipment_class="instrument",
                shacl_class="Instrument",
                functional_location=inst["functional_location"],
                area=inst["area"],
                sheet=inst["sheet"],
                parent_tag=inst["measures_tag"],
                unit="200",
                status="active",
            )
        )
    for seg in master["piping_segments"]:
        session.add(
            CmmsEquipment(
                tag=seg["line_number"],
                description=seg["description"],
                equipment_class="piping",
                shacl_class="PipingSegment",
                functional_location=f"DEMO-U200-{seg['area']}-{seg['line_number']}",
                area=seg["area"],
                sheet=seg["sheet"],
                parent_tag=seg["parent_equipment"],
                unit="200",
                status="active",
            )
        )
    for inact in master["inactive_or_external_tags"]:
        session.add(
            CmmsEquipment(
                tag=inact["tag"],
                description=inact["description"],
                equipment_class="exchanger" if inact["tag"].startswith("E-") else ("pump" if inact["tag"].startswith("P-") else "psv"),
                shacl_class="Asset",
                functional_location=f"DEMO-U{inact['unit']}-{inact['tag']}",
                area=f"{inact['unit']}-X",
                sheet="",
                unit=inact["unit"],
                status=inact["status"],
            )
        )
    session.commit()


def seed_users(session: Session) -> None:
    pw_hash = hash_password(DEMO_PASSWORD)
    for uid, email, name, role, _sg in DEMO_USERS:
        if session.get(UserAccount, uid) is None:
            session.add(
                UserAccount(
                    id=uid,
                    email=email,
                    full_name=name,
                    password_hash=pw_hash,
                    is_superuser=(role == "facilitator"),
                )
            )
    session.commit()


def seed_exercise_work_requests(
    session: Session,
    scenario_dir: Path,
    exercise_id: str,
    starting_fixture: str = "seeded",
) -> None:
    wl = json.loads((scenario_dir / "work-requests.json").read_text(encoding="utf-8"))
    event = TurnaroundEvent(
        id=wl["event_id"],
        exercise_id=exercise_id,
        site=wl["site"],
        unit=wl["unit"],
        name="Unit 200 Diesel Hydrotreater Turnaround 2028",
        planned_start="2028-10-01",
        duration_days=wl["planned_duration_days"],
        freeze_date="2027-10-01",
        budget_target_usd=wl["budget_target_usd"],
    )
    if session.get(TurnaroundEvent, (event.id, exercise_id)) is None:
        session.add(event)

    rows = wl["work_requests"]
    if starting_fixture == "partial":
        rows = rows[:100]
    elif starting_fixture == "blank":
        rows = []

    for wr in rows:
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
    session.commit()


def seed_demo_exercise(session: Session, scenario_dir: Path) -> None:
    seed_cmms(session, scenario_dir)
    seed_users(session)
    if session.get(Exercise, "EX-DEMO") is None:
        session.add(
            Exercise(
                id="EX-DEMO",
                name="TAR-200-2028 Scripted Demo",
                mode="demo",
                starting_fixture="seeded",
                clock_step="candidate_list",
                twin_write_through=True,
                allow_external_ai=True,
                epoch=1,
            )
        )
        session.commit()
    existing_mems = {
        m.user_id
        for m in session.exec(select(ExerciseMembership).where(ExerciseMembership.exercise_id == "EX-DEMO")).all()
    }
    for uid, _email, _name, role, sg in DEMO_USERS:
        if uid not in existing_mems:
            session.add(ExerciseMembership(exercise_id="EX-DEMO", user_id=uid, role=role, source_group=sg))
    session.commit()
    seed_exercise_work_requests(session, scenario_dir, "EX-DEMO", starting_fixture="seeded")
