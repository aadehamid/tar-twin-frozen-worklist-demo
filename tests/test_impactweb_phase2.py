"""Phase 2 IMPACT Web backend & write-through contract tests (written before implementation).

Covers docs/design.md sections 4.1, 4.2, 5.8, 9 and docs/interactive-planning.md sections 2, 3.4, 3.5, 3.9, 5.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "apps" / "impactweb" / "backend"


def _make_client(tmp_path: Path, auth_mode: str = "local"):
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    from fastapi.testclient import TestClient

    from impactweb.app import create_app

    db_url = f"sqlite:///{tmp_path / 'impactweb.db'}"
    app = create_app(
        database_url=db_url,
        scenario_dir=REPO_ROOT / "data" / "scenario",
        auth_mode=auth_mode,
        edge_auth_secret="test-edge-secret-123",
        twin_sync_token="sync-token-secret",
        twin_raise_token="raise-token-secret",
    )
    return TestClient(app)


def _login(client, email: str, password: str = "demo-pass-2028") -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_seeded_demo_exercise_and_cmms_master(tmp_path: Path):
    client = _make_client(tmp_path)
    sync_hdr = {"Authorization": "Bearer sync-token-secret"}

    ex = client.get("/api/v1/exercises/EX-DEMO", headers=sync_hdr)
    assert ex.status_code == 200, ex.text
    ex_data = ex.json()
    assert ex_data["mode"] == "demo"
    assert ex_data["twin_write_through"] is True

    wrs = client.get("/api/v1/work-requests?exercise_id=EX-DEMO", headers=sync_hdr)
    assert wrs.status_code == 200
    items = wrs.json()
    assert len(items) == 200
    assert all(it["work_package_id"] is None and it["schedule_activity_id"] is None for it in items)

    eq = client.get("/api/v1/cmms/equipment", headers=sync_hdr)
    assert eq.status_code == 200
    eq_rows = eq.json()
    assert len(eq_rows) >= 386
    assert any(r["tag"] == "E-201B" and r["status"] == "active" for r in eq_rows)
    assert any(r["tag"] == "E-301B" and r["status"] == "other_unit" for r in eq_rows)

    floc = client.get("/api/v1/cmms/functional-locations", headers=sync_hdr)
    assert floc.status_code == 200
    assert len(floc.json()) >= 7


def test_permissions_optimistic_locking_and_stale_decisions(tmp_path: Path):
    client = _make_client(tmp_path)
    ta_hdr = _login(client, "ta.manager@demo.local")
    fixed_hdr = _login(client, "fixed.lead@demo.local")
    rot_hdr = _login(client, "rotating.lead@demo.local")
    drb_hdr = _login(client, "drb.member@demo.local")
    viewer_hdr = _login(client, "viewer@demo.local")

    # Viewer cannot edit or create
    r_v = client.patch(
        "/api/v1/work-requests/WR-200-0147",
        params={"exercise_id": "EX-DEMO"},
        json={"version": 1, "title": "Viewer edit"},
        headers=viewer_hdr,
    )
    assert r_v.status_code == 403

    # Rotating lead cannot edit fixed_equipment item WR-200-0147
    r_other = client.patch(
        "/api/v1/work-requests/WR-200-0147",
        params={"exercise_id": "EX-DEMO"},
        json={"version": 1, "title": "Cross-group edit"},
        headers=rot_hdr,
    )
    assert r_other.status_code == 403

    # Fixed lead CAN edit own group's item WR-200-0147 -> version bumps 1 -> 2
    r_ok = client.patch(
        "/api/v1/work-requests/WR-200-0147",
        params={"exercise_id": "EX-DEMO"},
        json={"version": 1, "equipment_text": "feed eff exchanger middle shell (revised)"},
        headers=fixed_hdr,
    )
    assert r_ok.status_code == 200, r_ok.text
    assert r_ok.json()["version"] == 2

    # Stale version 1 write gets 409 Conflict
    r_stale = client.patch(
        "/api/v1/work-requests/WR-200-0147",
        params={"exercise_id": "EX-DEMO"},
        json={"version": 1, "title": "Lost update"},
        headers=fixed_hdr,
    )
    assert r_stale.status_code == 409

    # DRB member can record recommendation, NOT final decision
    r_rec = client.post(
        "/api/v1/work-requests/WR-200-0147/decisions",
        params={"exercise_id": "EX-DEMO"},
        json={"stage": "drb", "kind": "recommendation", "decision": "accept", "reason": "Mandatory inspection"},
        headers=drb_hdr,
    )
    assert r_rec.status_code == 201, r_rec.text

    r_bad_final = client.post(
        "/api/v1/work-requests/WR-200-0147/decisions",
        params={"exercise_id": "EX-DEMO"},
        json={"stage": "drb", "kind": "final", "decision": "accept", "reason": "Not TA manager"},
        headers=drb_hdr,
    )
    assert r_bad_final.status_code == 403

    # TA manager records final DRB accept on version 2
    r_final = client.post(
        "/api/v1/work-requests/WR-200-0147/decisions",
        params={"exercise_id": "EX-DEMO"},
        json={"stage": "drb", "kind": "final", "decision": "accept", "reason": "Approved at DRB"},
        headers=ta_hdr,
    )
    assert r_final.status_code == 201

    # Also DRB-accept WR-200-0152 at version 1, then edit WR-200-0147 to version 3 (making its DRB decision stale!)
    r_f2 = client.post(
        "/api/v1/work-requests/WR-200-0152/decisions",
        params={"exercise_id": "EX-DEMO"},
        json={"stage": "drb", "kind": "final", "decision": "accept", "reason": "Catalyst mandatory"},
        headers=ta_hdr,
    )
    assert r_f2.status_code == 201

    r_edit_after_drb = client.patch(
        "/api/v1/work-requests/WR-200-0147",
        params={"exercise_id": "EX-DEMO"},
        json={"version": 2, "title": "Edited after DRB"},
        headers=fixed_hdr,
    )
    assert r_edit_after_drb.status_code == 200
    assert r_edit_after_drb.json()["version"] == 3
    assert r_edit_after_drb.json()["needs_re_review"] is True

    # Freeze copies ONLY WR-200-0152 (current version DRB-accepted), NOT stale WR-200-0147!
    r_freeze = client.post("/api/v1/freezes", json={"exercise_id": "EX-DEMO", "event_id": "TAR-200-2028"}, headers=ta_hdr)
    assert r_freeze.status_code == 201, r_freeze.text
    freeze_id = r_freeze.json()["id"]

    frozen_items = client.get(f"/api/v1/freezes/{freeze_id}/items", headers={"Authorization": "Bearer sync-token-secret"})
    assert frozen_items.status_code == 200
    frozen_ids = {it["request_id"] for it in frozen_items.json()}
    assert frozen_ids == {"WR-200-0152"}

    # Direct edit after freeze is refused with 409 pointing to change requests
    r_after_freeze = client.patch(
        "/api/v1/work-requests/WR-200-0152",
        params={"exercise_id": "EX-DEMO"},
        json={"version": 1, "title": "Sneak edit"},
        headers=ta_hdr,
    )
    assert r_after_freeze.status_code == 409
    assert "frozen" in r_after_freeze.json()["detail"].lower()


def test_write_through_contract_and_token_isolation(tmp_path: Path):
    """Exact contract suite from docs/design.md section 9."""
    client = _make_client(tmp_path)
    ta_hdr = _login(client, "ta.manager@demo.local")
    planner_hdr = _login(client, "j.planner@demo.local")
    sync_hdr = {"Authorization": "Bearer sync-token-secret"}
    raise_hdr = {"Authorization": "Bearer raise-token-secret"}

    # Lookup planner, TA manager, and source lead IDs via memberships
    mems = client.get("/api/v1/exercises/EX-DEMO/memberships", headers=sync_hdr).json()
    uid_by_role = {m["role"]: m["user_id"] for m in mems}
    planner_uid = uid_by_role["planner"]
    ta_uid = uid_by_role["ta_manager"]
    src_uid = uid_by_role["source_group"]

    # Sync token gets 403 on EVERY write, including delegated raise
    assert client.post("/api/v1/freezes", json={"exercise_id": "EX-DEMO", "event_id": "TAR-200-2028"}, headers=sync_hdr).status_code == 403
    assert (
        client.post(
            "/api/v1/twin/change-requests",
            json={
                "exercise_id": "EX-DEMO",
                "request_id": "WR-200-0152",
                "change_type": "change",
                "hours_delta": 140,
                "cost_delta_usd": 32900,
                "title": "Add nozzle N3",
                "reason": "C-201 already open",
                "on_behalf_of": planner_uid,
            },
            headers=sync_hdr,
        ).status_code
        == 403
    )

    # Delegate token gets 403 on EVERY endpoint except POST /api/v1/twin/change-requests
    assert client.get("/api/v1/work-requests?exercise_id=EX-DEMO", headers=raise_hdr).status_code == 403
    assert client.get("/api/v1/changes?exercise_id=EX-DEMO&after_seq=0", headers=raise_hdr).status_code == 403
    assert client.post("/api/v1/freezes", json={"exercise_id": "EX-DEMO", "event_id": "TAR-200-2028"}, headers=raise_hdr).status_code == 403

    # Delegated raise gets 403 BEFORE freeze
    r_pre = client.post(
        "/api/v1/twin/change-requests",
        json={
            "exercise_id": "EX-DEMO",
            "request_id": "WR-200-0152",
            "change_type": "change",
            "hours_delta": 140,
            "cost_delta_usd": 32900,
            "title": "Pre-freeze attempt",
            "reason": "Should fail",
            "on_behalf_of": planner_uid,
        },
        headers=raise_hdr,
    )
    assert r_pre.status_code == 403

    # Accept WR-200-0152 and freeze the exercise
    assert (
        client.post(
            "/api/v1/work-requests/WR-200-0152/decisions",
            params={"exercise_id": "EX-DEMO"},
            json={"stage": "drb", "kind": "final", "decision": "accept", "reason": "DRB OK"},
            headers=ta_hdr,
        ).status_code
        == 201
    )
    assert client.post("/api/v1/freezes", json={"exercise_id": "EX-DEMO", "event_id": "TAR-200-2028"}, headers=ta_hdr).status_code == 201

    # Body setting raised_via gets 422 on BOTH endpoints
    assert (
        client.post(
            "/api/v1/twin/change-requests",
            json={
                "exercise_id": "EX-DEMO",
                "request_id": "WR-200-0152",
                "change_type": "change",
                "hours_delta": 140,
                "cost_delta_usd": 32900,
                "title": "Bad field",
                "reason": "Forged provenance",
                "on_behalf_of": planner_uid,
                "raised_via": "iw",
            },
            headers=raise_hdr,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/change-requests",
            json={
                "exercise_id": "EX-DEMO",
                "request_id": "WR-200-0152",
                "change_type": "change",
                "hours_delta": 100,
                "cost_delta_usd": 23500,
                "title": "Bad field",
                "reason": "Forged provenance",
                "raised_via": "twin",
            },
            headers=planner_hdr,
        ).status_code
        == 422
    )

    # Delegated raise gets 403 for non-member, TA manager, or source lead (planner only!)
    for bad_uid in ("nonexistent-user", ta_uid, src_uid):
        r_bad_role = client.post(
            "/api/v1/twin/change-requests",
            json={
                "exercise_id": "EX-DEMO",
                "request_id": "WR-200-0152",
                "change_type": "change",
                "hours_delta": 140,
                "cost_delta_usd": 32900,
                "title": "Wrong role",
                "reason": "Should fail",
                "on_behalf_of": bad_uid,
            },
            headers=raise_hdr,
        )
        assert r_bad_role.status_code == 403, bad_uid

    # Negative target hours gets 422
    r_neg = client.post(
        "/api/v1/twin/change-requests",
        json={
            "exercise_id": "EX-DEMO",
            "request_id": "WR-200-0152",
            "change_type": "change",
            "hours_delta": -999999,
            "cost_delta_usd": -100,
            "title": "Negative target",
            "reason": "Impossible",
            "on_behalf_of": planner_uid,
        },
        headers=raise_hdr,
    )
    assert r_neg.status_code == 422

    # Valid delegated raise succeeds -> pending, raised_via=twin, raised_by=planner_uid, base_version=1, on change_feed
    wr_before = client.get("/api/v1/work-requests/WR-200-0152?exercise_id=EX-DEMO", headers=sync_hdr).json()
    feed_before = client.get("/api/v1/changes?exercise_id=EX-DEMO&after_seq=0", headers=sync_hdr).json()
    last_seq = feed_before[-1]["seq"] if feed_before else 0

    r_tw = client.post(
        "/api/v1/twin/change-requests",
        json={
            "exercise_id": "EX-DEMO",
            "request_id": "WR-200-0152",
            "change_type": "change",
            "hours_delta": 140,
            "cost_delta_usd": 32900,
            "title": "Add nozzle N3 on C-201",
            "reason": "Add nozzle N3 on C-201; shares entry, scaffold and ENV-200-06",
            "on_behalf_of": planner_uid,
        },
        headers=raise_hdr,
    )
    assert r_tw.status_code == 201, r_tw.text
    cr_twin = r_tw.json()
    assert cr_twin["status"] == "pending"
    assert cr_twin["raised_via"] == "twin"
    assert cr_twin["raised_by"] == planner_uid
    assert cr_twin["base_version"] == wr_before["version"]

    # Live hours unchanged while pending, and pending row appeared on change_feed
    wr_pending = client.get("/api/v1/work-requests/WR-200-0152?exercise_id=EX-DEMO", headers=sync_hdr).json()
    assert wr_pending["estimate_hours"] == wr_before["estimate_hours"]
    feed_after = client.get(f"/api/v1/changes?exercise_id=EX-DEMO&after_seq={last_seq}", headers=sync_hdr).json()
    assert any(e["entity_type"] == "change_request" and e["action"] == "raised" for e in feed_after)

    # Turn twin_write_through OFF part way through
    fac_hdr = _login(client, "facilitator@demo.local")
    r_sw = client.patch(
        "/api/v1/exercises/EX-DEMO/write-through",
        json={"twin_write_through": False},
        headers=fac_hdr,
    )
    assert r_sw.status_code == 200
    assert r_sw.json()["twin_write_through"] is False

    # Next delegated raise gets 403
    assert (
        client.post(
            "/api/v1/twin/change-requests",
            json={
                "exercise_id": "EX-DEMO",
                "request_id": "WR-200-0152",
                "change_type": "change",
                "hours_delta": 50,
                "cost_delta_usd": 11750,
                "title": "Blocked after switch off",
                "reason": "Switch off",
                "on_behalf_of": planner_uid,
            },
            headers=raise_hdr,
        ).status_code
        == 403
    )

    # Planner's own form STILL succeeds with switch off and records raised_via=iw
    r_iw = client.post(
        "/api/v1/change-requests",
        json={
            "exercise_id": "EX-DEMO",
            "request_id": "WR-200-0152",
            "change_type": "change",
            "hours_delta": 60,
            "cost_delta_usd": 14100,
            "title": "Direct IMPACT Web raise",
            "reason": "Entered directly by planner",
        },
        headers=planner_hdr,
    )
    assert r_iw.status_code == 201, r_iw.text
    assert r_iw.json()["raised_via"] == "iw"
    cr_iw_id = r_iw.json()["id"]

    # Earlier twin-raised CR can STILL be approved by TA manager even after switch turned off
    r_app = client.post(
        f"/api/v1/change-requests/{cr_twin['id']}/decide",
        params={"exercise_id": "EX-DEMO"},
        json={"decision": "approved", "reason": "DRB approved nozzle N3"},
        headers=ta_hdr,
    )
    assert r_app.status_code == 200, r_app.text
    assert r_app.json()["status"] == "approved"

    # Approving the second CR (whose base_version is now stale because cr_twin bumped version!) gets 409
    r_stale_app = client.post(
        f"/api/v1/change-requests/{cr_iw_id}/decide",
        params={"exercise_id": "EX-DEMO"},
        json={"decision": "approved", "reason": "Stale base"},
        headers=ta_hdr,
    )
    assert r_stale_app.status_code == 409


def test_exe_auth_mode_and_synthetic_filter(tmp_path: Path):
    client = _make_client(tmp_path, auth_mode="exe")

    # Password login returns 404 in AUTH_MODE=exe
    assert client.post("/api/v1/auth/login", json={"email": "j.planner@demo.local", "password": "demo-pass-2028"}).status_code == 404

    # Forged X-ExeDev-Email without valid X-Edge-Auth is refused
    assert client.get("/api/v1/auth/me", headers={"X-ExeDev-Email": "j.planner@demo.local"}).status_code == 401
    assert (
        client.get(
            "/api/v1/auth/me",
            headers={"X-ExeDev-Email": "j.planner@demo.local", "X-Edge-Auth": "wrong-secret"},
        ).status_code
        == 401
    )

    # Valid X-Edge-Auth authenticates member
    r_me = client.get(
        "/api/v1/auth/me",
        headers={"X-ExeDev-Email": "j.planner@demo.local", "X-Edge-Auth": "test-edge-secret-123"},
    )
    assert r_me.status_code == 200
    assert r_me.json()["email"] == "j.planner@demo.local"

    # Synthetic data filter blocks real company names before saving
    r_filt = client.post(
        "/api/v1/work-requests",
        json={
            "exercise_id": "EX-DEMO",
            "event_id": "TAR-200-2028",
            "title": "ExxonMobil Baytown unit tie-in",
            "description": "Blocked real company name",
            "equipment_text": "E-201B",
            "category": "Exchanger bundle work",
            "driver": "inspection",
            "source_group": "fixed_equipment",
            "area": "200-C",
            "ript_score": 15,
            "estimate_hours_by_craft": {"boilermaker": 40},
        },
        headers={"X-ExeDev-Email": "j.planner@demo.local", "X-Edge-Auth": "test-edge-secret-123"},
    )
    assert r_filt.status_code == 422
    assert "synthetic" in r_filt.json()["detail"].lower()


def test_cross_exercise_planner_check_and_late_add_approval(tmp_path: Path):
    client = _make_client(tmp_path)
    from sqlmodel import Session

    from impactweb.models import Exercise, ExerciseMembership, FreezeRecord, TurnaroundEvent

    # Create a second frozen exercise EX-OTHER where j.planner is only a viewer (not planner!)
    with Session(client.app.state.engine) as s:
        s.add(Exercise(id="EX-OTHER", name="Second Exercise", mode="planning", twin_write_through=True))
        s.add(
            TurnaroundEvent(
                id="TAR-200-2028",
                exercise_id="EX-OTHER",
                site="Synthetic Refining Complex",
                unit="200",
                name="Unit 200 Second Exercise",
                planned_start="2028-10-01",
                duration_days=28,
                freeze_date="2027-10-01",
                budget_target_usd=22000000,
            )
        )
        s.add(ExerciseMembership(exercise_id="EX-OTHER", user_id="usr-planner", role="viewer"))
        s.add(ExerciseMembership(exercise_id="EX-OTHER", user_id="usr-ta-manager", role="ta_manager"))
        s.add(FreezeRecord(id="FRZ-EX-OTHER-V1", exercise_id="EX-OTHER", event_id="TAR-200-2028", list_version=1, frozen_by="usr-ta-manager"))
        s.commit()

    raise_hdr = {"Authorization": "Bearer raise-token-secret"}
    ta_hdr = _login(client, "ta.manager@demo.local")
    sync_hdr = {"Authorization": "Bearer sync-token-secret"}

    # Delegated raise targeting EX-OTHER must check planner role in EX-OTHER (NOT EX-DEMO) -> 403!
    r_cross = client.post(
        "/api/v1/twin/change-requests",
        json={
            "exercise_id": "EX-OTHER",
            "request_id": None,
            "change_type": "add",
            "hours_delta": 140,
            "cost_delta_usd": 32900,
            "title": "Cross-exercise role escalation attempt",
            "reason": "Planner in EX-DEMO only",
            "on_behalf_of": "usr-planner",
        },
        headers=raise_hdr,
    )
    assert r_cross.status_code == 403

    # Direct add change request on frozen EX-OTHER approved by TA manager creates a live work request
    r_add_cr = client.post(
        "/api/v1/change-requests",
        json={
            "exercise_id": "EX-OTHER",
            "request_id": None,
            "change_type": "add",
            "mandatory": True,
            "hours_delta": 140,
            "cost_delta_usd": 32900,
            "title": "Add nozzle N3 inspection on C-201",
            "equipment_text": "C-201 nozzle N3",
            "area": "200-E",
            "reason": "UT anomaly found after freeze",
        },
        headers=ta_hdr,
    )
    assert r_add_cr.status_code == 201, r_add_cr.text
    cr_id = r_add_cr.json()["id"]

    r_app = client.post(
        f"/api/v1/change-requests/{cr_id}/decide",
        params={"exercise_id": "EX-OTHER"},
        json={"decision": "approved", "reason": "Mandatory UT follow-up"},
        headers=ta_hdr,
    )
    assert r_app.status_code == 200, r_app.text
    new_req_id = r_app.json()["request_id"]
    assert new_req_id is not None and new_req_id.startswith("WR-200-")

    wrs_other = client.get("/api/v1/work-requests?exercise_id=EX-OTHER", headers=sync_hdr).json()
    assert len(wrs_other) == 1
    assert wrs_other[0]["id"] == new_req_id
    assert wrs_other[0]["estimate_hours"] == 140
    assert wrs_other[0]["status"] == "accepted"

    # Non-member of EX-OTHER (e.g. rotating.lead) cannot list EX-OTHER or read FRZ-EX-OTHER-V1 items
    rot_hdr = _login(client, "rotating.lead@demo.local")
    rot_exs = [e["id"] for e in client.get("/api/v1/exercises", headers=rot_hdr).json()]
    assert "EX-OTHER" not in rot_exs
    assert client.get("/api/v1/freezes/FRZ-EX-OTHER-V1/items", headers=rot_hdr).status_code == 403
    assert client.get("/api/v1/freezes/FRZ-NONEXISTENT/items", headers=rot_hdr).status_code == 404

    # Approving a 'change' CR with updated equipment_text applies that field to the live work request
    r_mod = client.post(
        "/api/v1/change-requests",
        json={
            "exercise_id": "EX-OTHER",
            "request_id": new_req_id,
            "change_type": "change",
            "hours_delta": 20,
            "cost_delta_usd": 4700,
            "title": "Clarify nozzle N3 weld seam tag",
            "equipment_text": "C-201 nozzle N3 lower seam",
            "reason": "Updated UT weld map",
        },
        headers=ta_hdr,
    )
    assert r_mod.status_code == 201, r_mod.text
    r_mod_app = client.post(
        f"/api/v1/change-requests/{r_mod.json()['id']}/decide",
        params={"exercise_id": "EX-OTHER"},
        json={"decision": "approved", "reason": "Confirmed by inspection"},
        headers=ta_hdr,
    )
    assert r_mod_app.status_code == 200, r_mod_app.text
    updated_wr = client.get(f"/api/v1/work-requests/{new_req_id}?exercise_id=EX-OTHER", headers=sync_hdr).json()
    assert updated_wr["equipment_text"] == "C-201 nozzle N3 lower seam"
    assert updated_wr["estimate_hours"] == 160
    assert sum(updated_wr["estimate_hours_by_craft"].values()) == 160
    assert updated_wr["version"] == 2

    # Prefixed /impactweb/api/v1/... endpoints work directly (matches docs/design.md /impactweb/ URL)
    assert client.get("/impactweb/api/v1/auth/mode").status_code == 200
    assert len(client.get("/impactweb/api/v1/work-requests?exercise_id=EX-DEMO", headers=sync_hdr).json()) == 200

    # Synthetic-data filter checks category/area/work_type_label, not only title
    r_bad_cat = client.post(
        "/api/v1/work-requests",
        json={
            "exercise_id": "EX-DEMO",
            "event_id": "TAR-200-2028",
            "title": "Clean synthetic valve inspection",
            "description": "Clean synthetic description",
            "equipment_text": "HV-2001",
            "category": "Chevron tie-in scope",
            "driver": "inspection",
            "source_group": "fixed_equipment",
            "area": "200-A",
            "ript_score": 10,
            "estimate_hours_by_craft": {"pipefitter": 24},
        },
        headers=ta_hdr,
    )
    assert r_bad_cat.status_code == 422

    # Post-freeze add by source-group lead enforces own-group boundary
    with Session(client.app.state.engine) as s:
        s.add(ExerciseMembership(exercise_id="EX-OTHER", user_id="usr-rotating", role="source_group", source_group="rotating"))
        s.commit()

    r_bad_sg = client.post(
        "/api/v1/change-requests",
        json={
            "exercise_id": "EX-OTHER",
            "request_id": None,
            "change_type": "add",
            "hours_delta": 40,
            "cost_delta_usd": 9800,
            "title": "Cross-group add attempt",
            "source_group": "fixed_equipment",
            "reason": "Should be blocked",
        },
        headers=rot_hdr,
    )
    assert r_bad_sg.status_code == 403

    r_own_sg = client.post(
        "/api/v1/change-requests",
        json={
            "exercise_id": "EX-OTHER",
            "request_id": None,
            "change_type": "add",
            "hours_delta": 40,
            "cost_delta_usd": 9800,
            "title": "P-201A seal flush check",
            "equipment_text": "P-201A mechanical seal",
            "reason": "Rotating post-freeze addition",
        },
        headers=rot_hdr,
    )
    assert r_own_sg.status_code == 201, r_own_sg.text
    assert r_own_sg.json()["source_group"] == "rotating"
    r_own_app = client.post(
        f"/api/v1/change-requests/{r_own_sg.json()['id']}/decide",
        params={"exercise_id": "EX-OTHER"},
        json={"decision": "approved", "reason": "Approved for rotating group"},
        headers=ta_hdr,
    )
    assert r_own_app.status_code == 200
    added_wr = client.get(f"/api/v1/work-requests/{r_own_app.json()['request_id']}?exercise_id=EX-OTHER", headers=sync_hdr).json()
    assert added_wr["source_group"] == "rotating"
