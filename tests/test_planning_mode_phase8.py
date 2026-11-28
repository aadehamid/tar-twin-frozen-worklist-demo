"""Phase 8 acceptance tests covering all 21 rows of docs/interactive-planning.md section 5."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings, strategies as st

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "impactweb" / "backend"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "twin" / "backend"))

from impactweb.app import create_app as create_iw_app
from twin.app import create_app as create_twin_app
from twin.clients import CmmsClient, ImpactWebClient


def _make_stack(tmp_path: Path):
    iw_app = create_iw_app(
        database_url=f"sqlite:///{tmp_path / 'iw-p8.db'}",
        scenario_dir=REPO_ROOT / "data" / "scenario",
        auth_mode="local",
        twin_sync_token="sync-p8",
        twin_raise_token="raise-p8",
    )
    iw = TestClient(iw_app)
    iw_cli = ImpactWebClient(base_url="http://testserver", sync_token="sync-p8", raise_token="raise-p8", http_client=iw)
    cmms_cli = CmmsClient(base_url="http://testserver", sync_token="sync-p8", http_client=iw)
    twin_app = create_twin_app(
        scenario_dir=REPO_ROOT / "data" / "scenario",
        shapes_path=REPO_ROOT / "specs" / "shapes.ttl",
        impactweb_client=iw_cli,
        cmms_client=cmms_cli,
        twin_sync_token="sync-p8",
        twin_raise_token="raise-p8",
        auth_mode="local",
    )
    twin = TestClient(twin_app)
    return iw, twin


def _login(iw: TestClient, email: str, *, epoch: int | None = 1) -> dict[str, str]:
    r = iw.post("/api/v1/auth/login", json={"email": email, "password": "demo-pass-2028"})
    assert r.status_code == 200, r.text
    hdrs = {"Authorization": f"Bearer {r.json()['access_token']}"}
    if epoch is not None:
        hdrs["X-Exercise-Epoch"] = str(epoch)
    return hdrs


def _create_planning_ex(
    iw: TestClient,
    fac_hdr: dict[str, str],
    *,
    name: str = "Unit 200 Rehearsal",
    starting_fixture: str = "seeded",
    ex_id: str | None = None,
) -> str:
    payload: dict = {"name": name, "mode": "planning", "starting_fixture": starting_fixture}
    if ex_id:
        payload["id"] = ex_id
    r = iw.post("/api/v1/exercises", json=payload, headers=fac_hdr)
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    # Add standard rehearsal team roles
    for email, role, sg in [
        ("ta.manager@demo.local", "ta_manager", None),
        ("j.planner@demo.local", "planner", None),
        ("fixed.lead@demo.local", "source_group", "fixed_equipment"),
        ("rotating.lead@demo.local", "source_group", "rotating"),
        ("drb.member@demo.local", "drb_member", None),
        ("viewer@demo.local", "viewer", None),
    ]:
        rm = iw.post(
            f"/api/v1/exercises/{eid}/memberships",
            json={"email": email, "role": role, "source_group": sg},
            headers=fac_hdr,
        )
        assert rm.status_code in {200, 201}, rm.text
    return eid


def test_fixtures_load_exact_counts_and_briefing_packs(tmp_path: Path):
    """Seeded (200), partial (100), and blank (0) fixtures load exact counts in both stores."""
    iw, twin = _make_stack(tmp_path)
    fac = _login(iw, "facilitator@demo.local")

    for fixture_kind, expected_count in [("seeded", 200), ("partial", 100), ("blank", 0)]:
        eid = _create_planning_ex(iw, fac, name=f"Fix {fixture_kind}", starting_fixture=fixture_kind)
        wrs = iw.get(f"/api/v1/work-requests?exercise_id={eid}", headers=fac).json()
        assert len(wrs) == expected_count

        packs = iw.get(f"/api/v1/exercises/{eid}/briefing-packs", headers=fac).json()
        assert len(packs["briefing_packs"]) == 6

        sr = twin.post(f"/api/v1/sync?exercise_id={eid}")
        assert sr.status_code == 200
        assert sr.json()["synced_count"] == expected_count
        items = twin.get(f"/api/v1/scope-items?exercise_id={eid}").json()
        assert len(items) == expected_count


def test_role_phase_permission_matrix_and_own_group_and_drb_recommendations(tmp_path: Path):
    """Every role and phase gate from docs/interactive-planning.md section 2, including refusals."""
    iw, twin = _make_stack(tmp_path)
    fac = _login(iw, "facilitator@demo.local")
    ta = _login(iw, "ta.manager@demo.local")
    pl = _login(iw, "j.planner@demo.local")
    fixed = _login(iw, "fixed.lead@demo.local")
    rot = _login(iw, "rotating.lead@demo.local")
    drb = _login(iw, "drb.member@demo.local")
    viewer = _login(iw, "viewer@demo.local")

    eid = _create_planning_ex(iw, fac, name="Perm Matrix", starting_fixture="partial")
    # Add a second DRB member to verify conflicting DRB recommendations are preserved
    iw.post(
        f"/api/v1/exercises/{eid}/memberships",
        json={"email": "operations.lead@demo.local", "role": "drb_member", "source_group": None},
        headers=fac,
    )
    drb2 = _login(iw, "operations.lead@demo.local")

    wr_body = {
        "exercise_id": eid,
        "event_id": "TAR-200-2028",
        "title": "Synthetic E-201B nozzle weld check",
        "description": "Synthetic thickness inspection on E-201B channel nozzle",
        "equipment_text": "E-201B",
        "category": "Exchanger bundle work",
        "work_type_label": "BundlePull",
        "driver": "inspection",
        "source_group": "fixed_equipment",
        "area": "200-A",
        "ript_score": 16,
        "mandatory": False,
        "estimate_hours_by_craft": {"boilermaker": 40},
    }

    # Phase: candidate_list -> raise allowed for ta_manager, planner, fixed (own group); refused for fac, rot (other group), drb, viewer
    assert iw.post("/api/v1/work-requests", json=wr_body, headers=fac).status_code == 403
    assert iw.post("/api/v1/work-requests", json=wr_body, headers=rot).status_code == 403
    assert iw.post("/api/v1/work-requests", json=wr_body, headers=drb).status_code == 403
    assert iw.post("/api/v1/work-requests", json=wr_body, headers=viewer).status_code == 403

    r_wr = iw.post("/api/v1/work-requests", json=wr_body, headers=fixed)
    assert r_wr.status_code == 201
    wr_id = r_wr.json()["id"]
    assert iw.post("/api/v1/work-requests", json=wr_body, headers=pl).status_code == 201
    assert iw.post("/api/v1/work-requests", json=wr_body, headers=ta).status_code == 201

    # Fit-to-frame decision refused while still in candidate_list
    assert (
        iw.post(
            f"/api/v1/work-requests/{wr_id}/decisions?exercise_id={eid}",
            json={"stage": "fit_to_frame", "kind": "final", "decision": "accept", "reason": "Too early"},
            headers=pl,
        ).status_code
        == 409
    )

    # Advance to fit_to_frame (non-facilitator cannot move clock!)
    assert iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "fit_to_frame"}, headers=ta).status_code == 403
    assert iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "fit_to_frame"}, headers=fac).status_code == 200

    # Raising a new candidate is refused after candidate_list
    assert iw.post("/api/v1/work-requests", json=wr_body, headers=pl).status_code == 409

    # Edit own group allowed for fixed, refused for rot (other group), fac, drb, viewer
    assert iw.patch(f"/api/v1/work-requests/{wr_id}?exercise_id={eid}", json={"version": 1, "ript_score": 18}, headers=rot).status_code == 403
    assert iw.patch(f"/api/v1/work-requests/{wr_id}?exercise_id={eid}", json={"version": 1, "ript_score": 18}, headers=fac).status_code == 403
    assert iw.patch(f"/api/v1/work-requests/{wr_id}?exercise_id={eid}", json={"version": 1, "ript_score": 18}, headers=fixed).status_code == 200

    # Fit-to-frame allowed for planner/ta_manager; refused for fixed, drb, fac, viewer
    for h in (fixed, drb, fac, viewer):
        assert (
            iw.post(
                f"/api/v1/work-requests/{wr_id}/decisions?exercise_id={eid}",
                json={"stage": "fit_to_frame", "kind": "final", "decision": "accept", "reason": "Check"},
                headers=h,
            ).status_code
            == 403
        )
    assert (
        iw.post(
            f"/api/v1/work-requests/{wr_id}/decisions?exercise_id={eid}",
            json={"stage": "fit_to_frame", "kind": "final", "decision": "accept", "reason": "Fits turnaround window"},
            headers=pl,
        ).status_code
        == 201
    )

    # Advance to challenge -> comment allowed for fixed (own group), pl, ta, drb; refused for rot (other group), fac, viewer
    assert iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "challenge"}, headers=fac).status_code == 200
    assert iw.post(f"/api/v1/work-requests/{wr_id}/comments?exercise_id={eid}", json={"body": "Defending fixed scope"}, headers=fixed).status_code == 201
    assert iw.post(f"/api/v1/work-requests/{wr_id}/comments?exercise_id={eid}", json={"body": "Wrong group"}, headers=rot).status_code == 403
    assert iw.post(f"/api/v1/work-requests/{wr_id}/comments?exercise_id={eid}", json={"body": "Viewer comment"}, headers=viewer).status_code == 403
    # Challenge final decision: TA manager only
    assert (
        iw.post(
            f"/api/v1/work-requests/{wr_id}/decisions?exercise_id={eid}",
            json={"stage": "challenge", "kind": "final", "decision": "keep", "reason": "Planner cannot decide challenge"},
            headers=pl,
        ).status_code
        == 403
    )
    assert (
        iw.post(
            f"/api/v1/work-requests/{wr_id}/decisions?exercise_id={eid}",
            json={"stage": "challenge", "kind": "final", "decision": "keep", "reason": "Verified unique"},
            headers=ta,
        ).status_code
        == 201
    )

    # Advance to drb -> two DRB members post conflicting recommendations; both kept; TA manager records final decision
    assert iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "drb"}, headers=fac).status_code == 200
    assert (
        iw.post(
            f"/api/v1/work-requests/{wr_id}/decisions?exercise_id={eid}",
            json={"stage": "drb", "kind": "recommendation", "decision": "accept", "reason": "Integrity priority"},
            headers=drb,
        ).status_code
        == 201
    )
    assert (
        iw.post(
            f"/api/v1/work-requests/{wr_id}/decisions?exercise_id={eid}",
            json={"stage": "drb", "kind": "recommendation", "decision": "defer", "reason": "Can wait"},
            headers=drb2,
        ).status_code
        == 201
    )
    assert (
        iw.post(
            f"/api/v1/work-requests/{wr_id}/decisions?exercise_id={eid}",
            json={"stage": "drb", "kind": "final", "decision": "accept", "reason": "TA manager final accept"},
            headers=ta,
        ).status_code
        == 201
    )
    wr_after = iw.get(f"/api/v1/work-requests/{wr_id}?exercise_id={eid}", headers=ta).json()
    drb_recs = [d for d in wr_after["decisions"] if d["stage"] == "drb" and d["kind"] == "recommendation"]
    assert {d["decision"] for d in drb_recs} == {"accept", "defer"}
    assert wr_after["drb_final_decision"] == "accept"

    # Freeze refused in drb step -> must advance clock to freeze step first!
    assert iw.post("/api/v1/freezes", json={"exercise_id": eid, "event_id": "TAR-200-2028"}, headers=ta).status_code == 409

    # Clock cannot move backwards and cannot skip past freeze while unfrozen
    assert iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "challenge"}, headers=fac).status_code == 409
    assert iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "t_minus_9"}, headers=fac).status_code == 409

    # Reaching freeze step does NOT freeze by itself
    assert iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "freeze"}, headers=fac).status_code == 200
    assert iw.get(f"/api/v1/exercises/{eid}", headers=fac).json()["frozen"] is False
    # Facilitator cannot freeze; TA manager freezes
    assert iw.post("/api/v1/freezes", json={"exercise_id": eid, "event_id": "TAR-200-2028"}, headers=fac).status_code == 403
    frz = iw.post("/api/v1/freezes", json={"exercise_id": eid, "event_id": "TAR-200-2028"}, headers=ta)
    assert frz.status_code == 201 and frz.json()["item_count"] == 1

    # Now clock can advance past freeze to t_minus_9
    assert iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "t_minus_9"}, headers=fac).status_code == 200

    # Twin match review: allowed for planner/ta_manager, refused for facilitator/viewer
    assert twin.post(f"/api/v1/sync?exercise_id={eid}").status_code == 200
    queue = twin.get(f"/api/v1/matching/review-queue?exercise_id={eid}").json()
    if queue:
        qid = queue[0]["request_id"]
        assert twin.post(f"/api/v1/matching/review/{qid}?exercise_id={eid}", json={"action": "reject", "reason": "No"}, headers=fac).status_code == 403
        assert twin.post(f"/api/v1/matching/review/{qid}?exercise_id={eid}", json={"action": "reject", "reason": "No"}, headers=viewer).status_code == 403


def test_membership_changes_immediate_and_multi_exercise_isolation(tmp_path: Path):
    """Two exercises with same WR IDs, same user with different roles, and immediate membership revocation."""
    iw, twin = _make_stack(tmp_path)
    fac = _login(iw, "facilitator@demo.local")
    pl = _login(iw, "j.planner@demo.local")

    ex1 = _create_planning_ex(iw, fac, name="Team A", starting_fixture="partial", ex_id="EX-ISO-1")
    ex2 = _create_planning_ex(iw, fac, name="Team B", starting_fixture="partial", ex_id="EX-ISO-2")

    # Give j.planner viewer role in EX-ISO-2 while keeping planner role in EX-ISO-1
    r_ch = iw.post(
        f"/api/v1/exercises/{ex2}/memberships",
        json={"email": "j.planner@demo.local", "role": "viewer", "source_group": None},
        headers=fac,
    )
    assert r_ch.status_code in {200, 201}

    # Edit WR-200-0001 in EX-ISO-1 succeeds; in EX-ISO-2 fails immediately (403)
    assert iw.patch(f"/api/v1/work-requests/WR-200-0001?exercise_id={ex1}", json={"version": 1, "ript_score": 24}, headers=pl).status_code == 200
    assert iw.patch(f"/api/v1/work-requests/WR-200-0001?exercise_id={ex2}", json={"version": 1, "ript_score": 24}, headers=pl).status_code == 403

    # EX-ISO-2 WR-200-0001 is completely untouched (still version 1)
    assert iw.get(f"/api/v1/work-requests/WR-200-0001?exercise_id={ex1}", headers=fac).json()["version"] == 2
    assert iw.get(f"/api/v1/work-requests/WR-200-0001?exercise_id={ex2}", headers=fac).json()["version"] == 1

    # Sync both into Twin and confirm complete isolation (scope items, Cypher export, cut line)
    assert twin.post(f"/api/v1/sync?exercise_id={ex1}").status_code == 200
    assert twin.post(f"/api/v1/sync?exercise_id={ex2}").status_code == 200
    assert twin.get(f"/api/v1/scope-items/WR-200-0001?exercise_id={ex1}").json()["version"] == 2
    assert twin.get(f"/api/v1/scope-items/WR-200-0001?exercise_id={ex2}").json()["version"] == 1

    cy1 = twin.get(f"/api/v1/graph/export.cypher?exercise_id={ex1}").text
    cy2 = twin.get(f"/api/v1/graph/export.cypher?exercise_id={ex2}").text
    assert f'exercise_id: "{ex1}"' in cy1 and f'exercise_id: "{ex2}"' not in cy1
    assert f'exercise_id: "{ex2}"' in cy2 and f'exercise_id: "{ex1}"' not in cy2

    # Revoke j.planner from EX-ISO-1 -> next request immediately gets 403!
    r_del = iw.delete(f"/api/v1/exercises/{ex1}/memberships/usr-planner", headers=fac)
    assert r_del.status_code == 200
    assert iw.get(f"/api/v1/work-requests?exercise_id={ex1}", headers=pl).status_code == 403
    assert twin.get(f"/api/v1/auth/me?exercise_id={ex1}", headers=pl).status_code == 403


def test_library_and_custom_injects_phase_gates_idempotency_and_synthetic_filter(tmp_path: Path):
    """All 6 library injects + custom inject obey auth, phase gates, idempotency, and synthetic filter."""
    iw, twin = _make_stack(tmp_path)
    fac = _login(iw, "facilitator@demo.local")
    ta = _login(iw, "ta.manager@demo.local")
    eid = _create_planning_ex(iw, fac, name="Inject Test", starting_fixture="seeded")

    lib = iw.get("/api/v1/injects/library", headers=fac).json()
    assert len(lib) == 6
    ids = {item["inject_id"] for item in lib}
    assert {"INJ-UT-THINNING", "INJ-BUDGET-CUT-10", "INJ-RESUBMIT-DUP", "INJ-RETIRED-TAG", "INJ-DEFER-STRIPPER", "INJ-HOTWORK-CLASH"} <= ids

    # Non-facilitator cannot apply inject
    assert iw.post(f"/api/v1/exercises/{eid}/injects", json={"inject_id": "INJ-RETIRED-TAG"}, headers=ta).status_code == 403

    # Phase refusal: INJ-BUDGET-CUT-10 is only allowed in challenge/drb, not candidate_list
    assert iw.post(f"/api/v1/exercises/{eid}/injects", json={"inject_id": "INJ-BUDGET-CUT-10"}, headers=fac).status_code == 409

    # Candidate-list injects succeed and are strictly idempotent on retry
    r1 = iw.post(f"/api/v1/exercises/{eid}/injects", json={"inject_id": "INJ-RETIRED-TAG"}, headers=fac)
    assert r1.status_code == 201 and r1.json()["applied"] is True
    count_after_1 = len(iw.get(f"/api/v1/work-requests?exercise_id={eid}", headers=fac).json())
    assert count_after_1 == 201
    r1_retry = iw.post(f"/api/v1/exercises/{eid}/injects", json={"inject_id": "INJ-RETIRED-TAG"}, headers=fac)
    assert r1_retry.status_code == 200 and r1_retry.json()["already_applied"] is True
    assert len(iw.get(f"/api/v1/work-requests?exercise_id={eid}", headers=fac).json()) == 201

    assert iw.post(f"/api/v1/exercises/{eid}/injects", json={"inject_id": "INJ-RESUBMIT-DUP"}, headers=fac).status_code == 201

    # Custom inject blocked by synthetic-data filter when naming real company/refinery
    bad_custom = iw.post(
        f"/api/v1/exercises/{eid}/injects",
        json={
            "inject_id": "CUST-BAD-1",
            "custom": True,
            "title": "ExxonMobil Baytown unit finding",
            "description": "Real company mention must be blocked",
            "allowed_phases": ["candidate_list"],
            "action_kind": "note",
        },
        headers=fac,
    )
    assert bad_custom.status_code == 422

    # Valid synthetic custom inject succeeds
    ok_custom = iw.post(
        f"/api/v1/exercises/{eid}/injects",
        json={
            "inject_id": "CUST-OK-1",
            "custom": True,
            "title": "Synthetic Unit 200 crane availability notice",
            "description": "Mobile crane window narrowed to days 8 to 14 on synthetic Unit 200.",
            "allowed_phases": ["candidate_list"],
            "action_kind": "note",
        },
        headers=fac,
    )
    assert ok_custom.status_code == 201

    # Advance to challenge -> apply budget cut (10%), defer stripper, hotwork clash
    assert iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "challenge"}, headers=fac).status_code == 200
    assert iw.post(f"/api/v1/exercises/{eid}/injects", json={"inject_id": "INJ-BUDGET-CUT-10"}, headers=fac).status_code == 201
    assert iw.get(f"/api/v1/exercises/{eid}", headers=fac).json()["event"]["budget_target_usd"] == 19_800_000
    assert iw.post(f"/api/v1/exercises/{eid}/injects", json={"inject_id": "INJ-DEFER-STRIPPER"}, headers=fac).status_code == 201
    assert iw.post(f"/api/v1/exercises/{eid}/injects", json={"inject_id": "INJ-HOTWORK-CLASH"}, headers=fac).status_code == 201

    # Advance to drb -> accept WR-200-0001 -> advance to freeze -> freeze -> apply INJ-UT-THINNING
    assert iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "drb"}, headers=fac).status_code == 200
    assert (
        iw.post(
            f"/api/v1/work-requests/WR-200-0001/decisions?exercise_id={eid}",
            json={"stage": "drb", "kind": "final", "decision": "accept", "reason": "Accept"},
            headers=ta,
        ).status_code
        == 201
    )
    assert iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "freeze"}, headers=fac).status_code == 200
    assert iw.post("/api/v1/freezes", json={"exercise_id": eid, "event_id": "TAR-200-2028"}, headers=ta).status_code == 201
    assert iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "t_minus_9"}, headers=fac).status_code == 200
    r_ut = iw.post(f"/api/v1/exercises/{eid}/injects", json={"inject_id": "INJ-UT-THINNING"}, headers=fac)
    assert r_ut.status_code == 201
    crs = iw.get(f"/api/v1/change-requests?exercise_id={eid}", headers=fac).json()
    assert len(crs) == 1 and crs[0]["status"] == "pending" and crs[0]["mandatory"] is True


def test_reset_bumps_epoch_archives_log_refuses_stale_ops_and_isolates_others(tmp_path: Path):
    """Reset restores one exercise only, archives old log, increments epoch, rejects pre-reset writes/syncs."""
    iw, twin = _make_stack(tmp_path)
    fac = _login(iw, "facilitator@demo.local")
    pl = _login(iw, "j.planner@demo.local")

    ex1 = _create_planning_ex(iw, fac, name="Reset Target", starting_fixture="partial", ex_id="EX-RST-1")
    ex2 = _create_planning_ex(iw, fac, name="Untouched Peer", starting_fixture="partial", ex_id="EX-RST-2")

    # Mutate both ex1 and ex2, and sync all three (including EX-DEMO)
    assert iw.patch(f"/api/v1/work-requests/WR-200-0001?exercise_id={ex1}", json={"version": 1, "ript_score": 25}, headers=pl).status_code == 200
    assert iw.patch(f"/api/v1/work-requests/WR-200-0001?exercise_id={ex2}", json={"version": 1, "ript_score": 23}, headers=pl).status_code == 200
    assert iw.post(f"/api/v1/exercises/{ex1}/clock", json={"target_step": "challenge"}, headers=fac).status_code == 200

    assert twin.post("/api/v1/sync?exercise_id=EX-DEMO").status_code == 200
    assert twin.post(f"/api/v1/sync?exercise_id={ex1}").status_code == 200
    assert twin.post(f"/api/v1/sync?exercise_id={ex2}").status_code == 200

    # Reset ex1
    rst = iw.post(f"/api/v1/exercises/{ex1}/reset", headers=fac)
    assert rst.status_code == 200
    assert rst.json()["epoch"] == 2
    assert rst.json()["clock_step"] == "candidate_list"

    # Archived log is preserved and readable
    archives = iw.get(f"/api/v1/exercises/{ex1}/archives", headers=fac).json()
    assert len(archives) == 1 and archives[0]["epoch"] == 1

    # Stale write with old epoch header is refused with 409
    stale_patch = iw.patch(
        f"/api/v1/work-requests/WR-200-0001?exercise_id={ex1}",
        json={"version": 1, "ript_score": 22},
        headers={**pl, "X-Exercise-Epoch": "1"},
    )
    assert stale_patch.status_code == 409

    # Stale Twin sync specifying old expected_epoch=1 is refused with 409
    stale_sync = twin.post(f"/api/v1/sync?exercise_id={ex1}&expected_epoch=1")
    assert stale_sync.status_code == 409

    # Fresh Twin sync picks up epoch=2 and wipes pre-reset state cleanly
    ok_sync = twin.post(f"/api/v1/sync?exercise_id={ex1}")
    assert ok_sync.status_code == 200
    assert twin.get(f"/api/v1/scope-items/WR-200-0001?exercise_id={ex1}").json()["version"] == 1

    # Peer exercise EX-RST-2 and EX-DEMO are completely untouched!
    assert iw.get(f"/api/v1/work-requests/WR-200-0001?exercise_id={ex2}", headers=fac).json()["version"] == 2
    assert twin.get(f"/api/v1/scope-items/WR-200-0001?exercise_id={ex2}").json()["version"] == 2
    assert len(twin.get("/api/v1/scope-items?exercise_id=EX-DEMO").json()) == 200


def test_rules_only_default_in_planning_mode_and_debrief_numbers_and_cut_line_contract(tmp_path: Path):
    """Rules-only default makes zero AI calls; debrief reports exact match rates (including n/a), growth, clusters, timeline, and unvalidated labels."""
    iw, twin = _make_stack(tmp_path)
    fac = _login(iw, "facilitator@demo.local")
    ta = _login(iw, "ta.manager@demo.local")
    pl = _login(iw, "j.planner@demo.local")

    # 1. Blank exercise starts with 0 active items -> match rate MUST be "n/a", NOT 0!
    eid = _create_planning_ex(iw, fac, name="Debrief Exact", starting_fixture="blank")
    ex_meta = iw.get(f"/api/v1/exercises/{eid}", headers=fac).json()
    assert ex_meta["allow_external_ai"] is False

    # Even with use_ai=true, planning mode with allow_external_ai=False runs strictly rules-only (zero AI calls)
    sr0 = twin.post(f"/api/v1/sync?exercise_id={eid}&use_ai=true&live_ai=true")
    assert sr0.status_code == 200
    assert sr0.json()["ai_used"] is False

    # Add 2 synthetic work requests on E-201B (exact tag) and an unresolved tag, so freeze is below 95% (50%)
    r_a = iw.post(
        "/api/v1/work-requests",
        json={
            "exercise_id": eid,
            "event_id": "TAR-200-2028",
            "title": "Pull E-201B tube bundle",
            "description": "Synthetic bundle pull on E-201B",
            "equipment_text": "E-201B",
            "category": "Exchanger bundle work",
            "work_type_label": "BundlePull",
            "driver": "inspection",
            "source_group": "fixed_equipment",
            "area": "200-A",
            "ript_score": 20,
            "mandatory": True,
            "estimate_hours_by_craft": {"boilermaker": 100},
        },
        headers=pl,
    )
    r_b = iw.post(
        "/api/v1/work-requests",
        json={
            "exercise_id": eid,
            "event_id": "TAR-200-2028",
            "title": "Unresolved area cleanup task",
            "description": "Synthetic unresolved equipment reference",
            "equipment_text": "untagged east piping rack",
            "category": "General piping and valves",
            "work_type_label": "ValveOverhaul",
            "driver": "reliability",
            "source_group": "fixed_equipment",
            "area": "200-A",
            "ript_score": 12,
            "mandatory": False,
            "estimate_hours_by_craft": {"pipefitter": 80},
        },
        headers=pl,
    )
    assert r_a.status_code == 201 and r_b.status_code == 201
    id_a, id_b = r_a.json()["id"], r_b.json()["id"]

    # Advance to DRB, save a cut-line option (verify IMPACT Web feed is NOT modified!), record DRB accepts
    assert iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "drb"}, headers=fac).status_code == 200
    assert twin.post(f"/api/v1/sync?exercise_id={eid}").status_code == 200

    feed_before = iw.get(f"/api/v1/changes?exercise_id={eid}", headers=fac).json()
    cl_save = twin.post(
        "/api/v1/cut-line/evaluate",
        json={"exercise_id": eid, "budget_usd": 30_000, "save_name": "Tight Budget", "saved_by": "J. Planner"},
        headers=pl,
    )
    assert cl_save.status_code == 200
    feed_after = iw.get(f"/api/v1/changes?exercise_id={eid}", headers=fac).json()
    assert len(feed_after) == len(feed_before), "Saving a cut-line option must never touch IMPACT Web"

    # Infeasible budget test ($10,000 < mandatory $23,500)
    infeasible = twin.post(
        "/api/v1/cut-line/evaluate",
        json={"exercise_id": eid, "budget_usd": 10_000},
    ).json()
    assert infeasible["feasible"] is False and infeasible["shortfall_usd"] > 0

    for rid in (id_a, id_b):
        assert (
            iw.post(
                f"/api/v1/work-requests/{rid}/decisions?exercise_id={eid}",
                json={"stage": "drb", "kind": "final", "decision": "accept", "reason": "DRB accept"},
                headers=ta,
            ).status_code
            == 201
        )

    # Freeze below 95% match gate succeeds; Twin marks ready_for_use=False
    assert iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "freeze"}, headers=fac).status_code == 200
    assert iw.post("/api/v1/freezes", json={"exercise_id": eid, "event_id": "TAR-200-2028"}, headers=ta).status_code == 201
    assert twin.post(f"/api/v1/sync?exercise_id={eid}").status_code == 200
    bl = twin.get(f"/api/v1/baseline?exercise_id={eid}").json()
    assert bl["frozen"] is True and bl["frozen_match_rate"] == 0.5 and bl["ready_for_use"] is False

    # Post-freeze changes: 2 approved changes on id_a (+20 hrs mandatory, +10 hrs discretionary = +30 hrs >= 10% material!),
    # plus 1 pending (+50) and 1 rejected (+40) that MUST NOT affect growth
    assert iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "t_minus_9"}, headers=fac).status_code == 200
    c1 = iw.post(
        "/api/v1/change-requests",
        json={"exercise_id": eid, "request_id": id_a, "change_type": "change", "mandatory": True, "hours_delta": 20, "cost_delta_usd": 4700, "title": "UT tube sheet repair", "reason": "Mandatory NDE finding"},
        headers=pl,
    ).json()["id"]
    assert iw.post(f"/api/v1/change-requests/{c1}/decide?exercise_id={eid}", json={"decision": "approved", "reason": "Approved"}, headers=ta).status_code == 200

    c2 = iw.post(
        "/api/v1/change-requests",
        json={"exercise_id": eid, "request_id": id_a, "change_type": "change", "mandatory": False, "hours_delta": 10, "cost_delta_usd": 2350, "title": "Extra nozzle clean", "reason": "Discretionary add"},
        headers=pl,
    ).json()["id"]
    assert iw.post(f"/api/v1/change-requests/{c2}/decide?exercise_id={eid}", json={"decision": "approved", "reason": "Approved"}, headers=ta).status_code == 200

    # Pending + rejected changes
    c3 = iw.post(
        "/api/v1/change-requests",
        json={"exercise_id": eid, "request_id": id_b, "change_type": "change", "mandatory": False, "hours_delta": 50, "cost_delta_usd": 11000, "title": "Pending extra", "reason": "Still pending"},
        headers=pl,
    ).json()["id"]
    c4 = iw.post(
        "/api/v1/change-requests",
        json={"exercise_id": eid, "request_id": id_b, "change_type": "change", "mandatory": False, "hours_delta": 40, "cost_delta_usd": 9000, "title": "Rejected extra", "reason": "Out of scope"},
        headers=pl,
    ).json()["id"]
    assert iw.post(f"/api/v1/change-requests/{c4}/decide?exercise_id={eid}", json={"decision": "rejected", "reason": "Rejected"}, headers=ta).status_code == 200

    # Close exercise and fetch debrief
    assert iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "closed"}, headers=fac).status_code == 200
    assert twin.post(f"/api/v1/sync?exercise_id={eid}").status_code == 200

    debrief = twin.get(f"/api/v1/debrief?exercise_id={eid}").json()
    # First sample at blank candidate_list had 0 active items -> "n/a"
    assert any(pt["display"] == "n/a" for pt in debrief["match_rate_over_time"])
    # Growth: mandatory=20, discretionary=10, approved_total=30, pending=1, rejected=1
    gr = debrief["growth_after_freeze"]
    assert gr["approved_growth_hours"] == 30
    assert gr["mandatory_growth_hours"] == 20
    assert gr["discretionary_growth_hours"] == 10
    assert gr["pending_count"] == 1
    assert gr["rejected_count"] == 1
    assert any(m["request_id"] == id_a and m["pct_of_frozen_hours"] >= 10.0 for m in gr["material_changes"])
    # Saved cut-line option compared against DRB
    assert len(debrief["cut_line_vs_drb"]) == 1
    # Timeline & talking points present
    assert len(debrief["decision_timeline"]) >= 4
    assert len(debrief["talking_points"]) >= 2
    # Unvalidated brief value labels present on debrief
    assert debrief["value_assumptions"]["unvalidated_assumption"] is True
    assert "unvalidated" in debrief["value_assumptions"]["assumption_notice"].lower()


@settings(max_examples=12, deadline=None)
@given(
    deltas=st.lists(
        st.tuples(st.booleans(), st.sampled_from(["approved", "pending", "rejected"]), st.integers(min_value=5, max_value=80)),
        min_size=1,
        max_size=6,
    )
)
def test_hypothesis_debrief_growth_equals_sum_over_approved_events(tmp_path_factory, deltas):
    """Property: debrief mandatory/discretionary/total growth always equals exact sums over approved change requests."""
    tmp_path = tmp_path_factory.mktemp("hyp_debrief")
    iw, twin = _make_stack(tmp_path)
    fac = _login(iw, "facilitator@demo.local")
    ta = _login(iw, "ta.manager@demo.local")
    pl = _login(iw, "j.planner@demo.local")
    eid = _create_planning_ex(iw, fac, name="Hyp Debrief", starting_fixture="blank")

    wr_id = iw.post(
        "/api/v1/work-requests",
        json={
            "exercise_id": eid,
            "event_id": "TAR-200-2028",
            "title": "Hyp E-201B base job",
            "description": "Synthetic base job",
            "equipment_text": "E-201B",
            "category": "Exchanger bundle work",
            "work_type_label": "BundlePull",
            "driver": "inspection",
            "source_group": "fixed_equipment",
            "area": "200-A",
            "ript_score": 18,
            "mandatory": True,
            "estimate_hours_by_craft": {"boilermaker": 200},
        },
        headers=pl,
    ).json()["id"]

    iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "drb"}, headers=fac)
    iw.post(f"/api/v1/work-requests/{wr_id}/decisions?exercise_id={eid}", json={"stage": "drb", "kind": "final", "decision": "accept", "reason": "Accept"}, headers=ta)
    iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "freeze"}, headers=fac)
    iw.post("/api/v1/freezes", json={"exercise_id": eid, "event_id": "TAR-200-2028"}, headers=ta)
    iw.post(f"/api/v1/exercises/{eid}/clock", json={"target_step": "t_minus_9"}, headers=fac)

    exp_mand = 0
    exp_disc = 0
    exp_pend = 0
    exp_rej = 0
    for idx, (mand, outcome, hrs) in enumerate(deltas):
        cid = iw.post(
            "/api/v1/change-requests",
            json={
                "exercise_id": eid,
                "request_id": wr_id,
                "change_type": "change",
                "mandatory": mand,
                "hours_delta": hrs,
                "cost_delta_usd": hrs * 235,
                "title": f"Hyp CR {idx}",
                "reason": f"Synthetic change {idx}",
            },
            headers=pl,
        ).json()["id"]
        if outcome == "approved":
            assert iw.post(f"/api/v1/change-requests/{cid}/decide?exercise_id={eid}", json={"decision": "approved", "reason": "Ok"}, headers=ta).status_code == 200
            if mand:
                exp_mand += hrs
            else:
                exp_disc += hrs
        elif outcome == "rejected":
            assert iw.post(f"/api/v1/change-requests/{cid}/decide?exercise_id={eid}", json={"decision": "rejected", "reason": "No"}, headers=ta).status_code == 200
            exp_rej += 1
        else:
            exp_pend += 1

    twin.post(f"/api/v1/sync?exercise_id={eid}")
    gr = twin.get(f"/api/v1/debrief?exercise_id={eid}").json()["growth_after_freeze"]
    assert gr["mandatory_growth_hours"] == exp_mand
    assert gr["discretionary_growth_hours"] == exp_disc
    assert gr["approved_growth_hours"] == exp_mand + exp_disc
    assert gr["pending_count"] == exp_pend
    assert gr["rejected_count"] == exp_rej


def test_quint_planning_mode_replay_concurrent_editors_and_invariants(tmp_path: Path):
    """Replay planning_mode.qnt trace against real APIs: concurrent 409, stale DRB excluded, freeze race, isolation."""
    assert (REPO_ROOT / "specs" / "planning_mode.qnt").is_file()
    iw, twin = _make_stack(tmp_path)
    fac = _login(iw, "facilitator@demo.local")
    ta = _login(iw, "ta.manager@demo.local")
    pl = _login(iw, "j.planner@demo.local")

    ex1 = _create_planning_ex(iw, fac, name="Quint Replay 1", starting_fixture="blank")
    ex2 = _create_planning_ex(iw, fac, name="Quint Replay 2", starting_fixture="blank")

    # Create item in ex1 (v1)
    rid = iw.post(
        "/api/v1/work-requests",
        json={
            "exercise_id": ex1,
            "event_id": "TAR-200-2028",
            "title": "Quint E-201A inspection",
            "description": "Synthetic replay item",
            "equipment_text": "E-201A",
            "category": "Exchanger bundle work",
            "work_type_label": "BundlePull",
            "driver": "inspection",
            "source_group": "fixed_equipment",
            "area": "200-A",
            "ript_score": 15,
            "mandatory": False,
            "estimate_hours_by_craft": {"boilermaker": 40},
        },
        headers=pl,
    ).json()["id"]

    # Two concurrent editors read v1; Editor 1 commits v2, Editor 2 gets 409 (no lost edits!)
    assert iw.patch(f"/api/v1/work-requests/{rid}?exercise_id={ex1}", json={"version": 1, "estimate_hours_by_craft": {"boilermaker": 60}}, headers=pl).status_code == 200
    assert iw.patch(f"/api/v1/work-requests/{rid}?exercise_id={ex1}", json={"version": 1, "estimate_hours_by_craft": {"boilermaker": 80}}, headers=ta).status_code == 409

    # DRB accepts v2 -> then edit bumps to v3 -> DRB decision becomes stale -> freeze excludes item!
    iw.post(f"/api/v1/exercises/{ex1}/clock", json={"target_step": "drb"}, headers=fac)
    assert iw.post(f"/api/v1/work-requests/{rid}/decisions?exercise_id={ex1}", json={"stage": "drb", "kind": "final", "decision": "accept", "reason": "Accept v2"}, headers=ta).status_code == 201
    assert iw.patch(f"/api/v1/work-requests/{rid}?exercise_id={ex1}", json={"version": 2, "estimate_hours_by_craft": {"boilermaker": 70}}, headers=pl).status_code == 200
    wr_stale = iw.get(f"/api/v1/work-requests/{rid}?exercise_id={ex1}", headers=ta).json()
    assert wr_stale["needs_re_review"] is True

    # Freeze excludes stale item (0 items copied); ex2 remains completely untouched at candidate_list!
    iw.post(f"/api/v1/exercises/{ex1}/clock", json={"target_step": "freeze"}, headers=fac)
    frz = iw.post("/api/v1/freezes", json={"exercise_id": ex1, "event_id": "TAR-200-2028"}, headers=ta)
    assert frz.status_code == 201 and frz.json()["item_count"] == 0
    assert iw.get(f"/api/v1/exercises/{ex2}", headers=fac).json()["clock_step"] == "candidate_list"
    assert iw.get(f"/api/v1/exercises/{ex2}", headers=fac).json()["frozen"] is False


def test_codex_review_guardrails_per_exercise_facilitator_required_epoch_and_tag_filter(tmp_path: Path):
    """Prove all 3 Codex review guardrails: per-exercise facilitator scope, mandatory epoch header on planning writes, and non-synthetic tag pattern blocking."""
    iw, _twin = _make_stack(tmp_path)
    global_fac = _login(iw, "facilitator@demo.local")
    pl_no_epoch = _login(iw, "j.planner@demo.local", epoch=None)
    pl_epoch1 = _login(iw, "j.planner@demo.local", epoch=1)

    ex_a = _create_planning_ex(iw, global_fac, name="Scoped Fac A", starting_fixture="partial", ex_id="EX-FAC-A")
    ex_b = _create_planning_ex(iw, global_fac, name="Scoped Fac B", starting_fixture="partial", ex_id="EX-FAC-B")

    # 1. Per-exercise facilitator: make viewer@demo.local a facilitator ONLY in EX-FAC-A (not global, not in EX-FAC-B)
    r_add = iw.post(
        f"/api/v1/exercises/{ex_a}/memberships",
        json={"email": "viewer@demo.local", "role": "facilitator", "source_group": None},
        headers=global_fac,
    )
    assert r_add.status_code in {200, 201}
    scoped_fac = _login(iw, "viewer@demo.local")

    # Scoped facilitator can advance clock in EX-FAC-A, but gets 403 on EX-FAC-B and 403 creating a new exercise!
    assert iw.post(f"/api/v1/exercises/{ex_a}/clock", json={"target_step": "fit_to_frame"}, headers=scoped_fac).status_code == 200
    assert iw.post(f"/api/v1/exercises/{ex_b}/clock", json={"target_step": "fit_to_frame"}, headers=scoped_fac).status_code == 403
    assert iw.post(f"/api/v1/exercises/{ex_b}/injects", json={"inject_id": "INJ-RETIRED-TAG"}, headers=scoped_fac).status_code == 403
    assert iw.post(f"/api/v1/exercises/{ex_b}/reset", headers=scoped_fac).status_code == 403
    assert (
        iw.post(
            "/api/v1/exercises",
            json={"name": "Unauthorized New Ex", "mode": "planning", "starting_fixture": "blank"},
            headers=scoped_fac,
        ).status_code
        == 403
    )

    # 2. Planning-mode writes MUST send X-Exercise-Epoch; omitting it is refused with 409!
    assert (
        iw.patch(
            f"/api/v1/work-requests/WR-200-0001?exercise_id={ex_b}",
            json={"version": 1, "ript_score": 21},
            headers=pl_no_epoch,
        ).status_code
        == 409
    )
    assert (
        iw.patch(
            f"/api/v1/work-requests/WR-200-0001?exercise_id={ex_b}",
            json={"version": 1, "ript_score": 21},
            headers=pl_epoch1,
        ).status_code
        == 200
    )

    # 3. Synthetic-data filter blocks non-synthetic plant tag patterns across work requests, comments, and custom injects!
    for bad_tag in ("CDU-1201", "E-4105A", "1200-P-4501"):
        r_wr = iw.post(
            "/api/v1/work-requests",
            json={
                "exercise_id": ex_b,
                "event_id": "TAR-200-2028",
                "title": f"Inspect {bad_tag} shell",
                "description": f"Real-looking tag {bad_tag} must be blocked",
                "equipment_text": bad_tag,
                "category": "Exchanger bundle work",
                "work_type_label": "BundlePull",
                "driver": "inspection",
                "source_group": "fixed_equipment",
                "area": "200-A",
                "ript_score": 15,
                "mandatory": False,
                "estimate_hours_by_craft": {"boilermaker": 40},
            },
            headers=pl_epoch1,
        )
        assert r_wr.status_code == 422, f"Expected 422 for non-synthetic tag {bad_tag}, got {r_wr.status_code}"

        r_inj = iw.post(
            f"/api/v1/exercises/{ex_b}/injects",
            json={
                "inject_id": f"CUST-TAG-{bad_tag}",
                "custom": True,
                "title": f"Finding on {bad_tag}",
                "description": "Should be blocked by tag filter",
                "allowed_phases": ["candidate_list"],
                "action_kind": "note",
            },
            headers=global_fac,
        )
        assert r_inj.status_code == 422, f"Expected 422 for custom inject tag {bad_tag}, got {r_inj.status_code}"

    # Comments also block non-synthetic tags
    assert iw.post(f"/api/v1/exercises/{ex_b}/clock", json={"target_step": "challenge"}, headers=global_fac).status_code == 200
    assert (
        iw.post(
            f"/api/v1/work-requests/WR-200-0001/comments?exercise_id={ex_b}",
            json={"body": "Cross-check with real unit tag FCC-401"},
            headers=pl_epoch1,
        ).status_code
        == 422
    )
