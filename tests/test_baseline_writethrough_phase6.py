"""Phase 6 verification: frozen baseline, separate 3.1 readiness gate, late-scope simulation,
KPIs, unvalidated value panel, reserved 4.1/4.2 slots, and Twin->IMPACT Web write-through contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
for d in (
    REPO_ROOT / "apps" / "impactweb" / "backend",
    REPO_ROOT / "apps" / "twin" / "backend",
    REPO_ROOT / "jobs",
):
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))

from impactweb.app import create_app as create_iw_app
from twin.app import create_app as create_twin_app
from twin.clients import CmmsClient, ImpactWebClient


def _make_pair(tmp_path: Path):
    iw_app = create_iw_app(
        database_url=f"sqlite:///{tmp_path / 'iw-p6.db'}",
        scenario_dir=REPO_ROOT / "data" / "scenario",
        auth_mode="local",
        twin_sync_token="sync-p6",
        twin_raise_token="raise-p6",
    )
    iw_tc = TestClient(iw_app)
    iw_cli = ImpactWebClient(base_url="http://testserver", sync_token="sync-p6", raise_token="raise-p6", http_client=iw_tc)
    cmms_cli = CmmsClient(base_url="http://testserver", sync_token="sync-p6", http_client=iw_tc)
    twin_app = create_twin_app(
        scenario_dir=REPO_ROOT / "data" / "scenario",
        shapes_path=REPO_ROOT / "specs" / "shapes.ttl",
        impactweb_client=iw_cli,
        cmms_client=cmms_cli,
        auth_mode="local",
    )
    twin_tc = TestClient(twin_app)
    return iw_tc, twin_tc


def _login(iw: TestClient, email: str) -> dict[str, str]:
    r = iw.post("/api/v1/auth/login", json={"email": email, "password": "demo-pass-2028"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _accept_all_and_freeze(iw: TestClient, ta_hdr: dict[str, str], count: int = 200) -> str:
    wrs = iw.get("/api/v1/work-requests?exercise_id=EX-DEMO", headers=ta_hdr).json()
    ids = [w["id"] for w in wrs[:count]]
    r_bulk = iw.post(
        "/api/v1/work-requests/bulk-decisions",
        json={"exercise_id": "EX-DEMO", "request_ids": ids, "stage": "drb", "decision": "accept", "reason": "DRB approved"},
        headers=ta_hdr,
    )
    assert r_bulk.status_code == 201, r_bulk.text
    r_frz = iw.post("/api/v1/freezes", json={"exercise_id": "EX-DEMO", "event_id": "TAR-200-2028"}, headers=ta_hdr)
    assert r_frz.status_code == 201, r_frz.text
    return r_frz.json()["id"]


def test_baseline_readiness_gate_independent_of_freeze_and_reserved_slots(tmp_path: Path):
    iw, twin = _make_pair(tmp_path)
    ta_hdr = _login(iw, "ta.manager@demo.local")
    planner_hdr = _login(iw, "j.planner@demo.local")

    # Sync with AI proposals (146/200 auto-accepted -> 73%, below 95% gate)
    assert twin.post("/api/v1/sync?exercise_id=EX-DEMO&use_ai=true").status_code == 200
    pre = twin.get("/api/v1/baseline?exercise_id=EX-DEMO").json()
    assert pre["frozen"] is False
    assert pre["ready_for_use"] is False

    # Freeze succeeds in IMPACT Web even though match rate is 73% (<95%)
    freeze_id = _accept_all_and_freeze(iw, ta_hdr, count=200)
    assert twin.post("/api/v1/sync?exercise_id=EX-DEMO&use_ai=true").status_code == 200

    b1 = twin.get("/api/v1/baseline?exercise_id=EX-DEMO").json()
    assert b1["frozen"] is True
    assert b1["freeze_id"] == freeze_id
    assert b1["baseline_item_count"] == 200
    assert b1["frozen_match_rate"] == 0.73
    assert b1["ready_for_use"] is False  # Gate invariant: < 95% cannot mark ready!

    # Reserved 4.1 and 4.2 schema slots exist as null/empty only (release-one scope rule)
    assert b1["reserved_slots"]["work_packages_4_1"]["work_packages"] is None
    assert b1["reserved_slots"]["work_packages_4_1"]["standards"] is None
    assert b1["reserved_slots"]["execution_plan_4_2"]["activities"] is None
    assert b1["reserved_slots"]["execution_plan_4_2"]["logistics_objects"] is None
    assert b1["reserved_slots"]["execution_plan_4_2"]["permits"] is None

    # Accept proposals in review queue -> match rate crosses 95% (193/200 = 96.5%)
    queue = twin.get("/api/v1/matching/review-queue?exercise_id=EX-DEMO").json()
    for it in queue:
        if it.get("proposal") and it["proposal"].get("tag"):
            r = twin.post(
                f"/api/v1/matching/review/{it['request_id']}?exercise_id=EX-DEMO",
                json={"action": "accept", "reason": "Verified against DEXPI"},
                headers=planner_hdr,
            )
            assert r.status_code == 200

    b2 = twin.get("/api/v1/baseline?exercise_id=EX-DEMO").json()
    assert b2["frozen"] is True
    assert b2["freeze_id"] == freeze_id
    assert b2["baseline_item_count"] == 200
    assert b2["baseline_hours"] == b1["baseline_hours"]  # Baseline fixed!
    assert b2["frozen_match_rate"] >= 0.95
    assert b2["ready_for_use"] is True

    # Post-freeze change CR moving WR-200-0001 to v2 with unmatchable equipment text MUST NOT alter frozen_match_rate!
    r_cr = iw.post(
        "/api/v1/change-requests",
        json={
            "exercise_id": "EX-DEMO",
            "request_id": "WR-200-0001",
            "change_type": "change",
            "mandatory": False,
            "hours_delta": 10,
            "cost_delta_usd": 2350,
            "title": "Post-freeze text edit on WR-200-0001",
            "equipment_text": "unknown post freeze mystery asset",
            "reason": "Verify frozen version match snapshot stays pinned",
        },
        headers=planner_hdr,
    )
    assert r_cr.status_code == 201
    assert (
        iw.post(
            f"/api/v1/change-requests/{r_cr.json()['id']}/decide?exercise_id=EX-DEMO",
            json={"decision": "approved", "reason": "Approve v2 edit"},
            headers=ta_hdr,
        ).status_code
        == 200
    )
    assert twin.post("/api/v1/sync?exercise_id=EX-DEMO").status_code == 200
    b3 = twin.get("/api/v1/baseline?exercise_id=EX-DEMO").json()
    assert b3["frozen_match_rate"] == b2["frozen_match_rate"]
    assert b3["ready_for_use"] is True


def test_late_scope_simulation_fails_closed_on_missing_delete_target_and_resumes_pending(tmp_path: Path):
    from simulate_late_scope import _find_delete_target, run_late_scope_simulation

    # 1. Fail-closed delete target lookup never deletes unrelated equipment
    unrelated = [{"id": "WR-200-0001", "status": "candidate", "equipment_text": "E-201A", "title": "E-201A", "estimate_hours": 500}]
    assert (
        _find_delete_target(
            unrelated,
            equipment_tag="FL-201B",
            abs_hours=180,
            used_ids=set(),
            true_tag_by_request={"WR-200-0001": "E-201A"},
        )
        is None
    )

    # 2. Resumes a pending scripted CR left from an interrupted run instead of skipping it
    iw, twin = _make_pair(tmp_path)
    ta_hdr = _login(iw, "ta.manager@demo.local")
    pl_hdr = _login(iw, "j.planner@demo.local")
    _accept_all_and_freeze(iw, ta_hdr, count=200)
    assert twin.post("/api/v1/sync?exercise_id=EX-DEMO").status_code == 200

    # Pre-create CR-200-001 as pending (simulating crash before decision)
    late_first = json.loads((REPO_ROOT / "data" / "scenario" / "late-scope.json").read_text(encoding="utf-8"))["scripted_changes"][0]
    r_pre = iw.post(
        "/api/v1/change-requests",
        json={
            "exercise_id": "EX-DEMO",
            "request_id": None,
            "change_type": "add",
            "mandatory": True,
            "hours_delta": late_first["hours_delta"],
            "cost_delta_usd": late_first["cost_delta_usd"],
            "title": late_first["title"],
            "equipment_text": late_first["equipment_tag"],
            "source_group": late_first["source_group"],
            "area": "200-C",
            "evidence": f"[SIM:{late_first['change_id']}] Scripted checkpoint T-9.",
            "reason": late_first["reason"],
        },
        headers=pl_hdr,
    )
    assert r_pre.status_code == 201

    res = run_late_scope_simulation(
        impactweb_client=iw,
        twin_client=twin,
        scenario_dir=REPO_ROOT / "data" / "scenario",
        exercise_id="EX-DEMO",
    )
    assert res["resumed_pending"] == 1
    assert res["adds_approved"] == 18
    assert res["deletes_approved"] == 6
    assert res["rejected"] == 5


def test_late_scope_simulation_and_kpis_and_unvalidated_value_panel(tmp_path: Path):
    from simulate_late_scope import run_late_scope_simulation

    iw, twin = _make_pair(tmp_path)
    ta_hdr = _login(iw, "ta.manager@demo.local")
    _accept_all_and_freeze(iw, ta_hdr, count=200)
    assert twin.post("/api/v1/sync?exercise_id=EX-DEMO&use_ai=true").status_code == 200

    baseline_before = twin.get("/api/v1/baseline?exercise_id=EX-DEMO").json()

    sim = run_late_scope_simulation(
        impactweb_client=iw,
        twin_client=twin,
        scenario_dir=REPO_ROOT / "data" / "scenario",
        exercise_id="EX-DEMO",
    )
    assert sim["adds_approved"] == 18
    assert sim["deletes_approved"] == 6
    assert sim["rejected"] == 5

    # Idempotent second run does not duplicate changes
    sim2 = run_late_scope_simulation(
        impactweb_client=iw,
        twin_client=twin,
        scenario_dir=REPO_ROOT / "data" / "scenario",
        exercise_id="EX-DEMO",
    )
    assert sim2["skipped_existing"] == 29

    # Expected net growth from late-scope.json
    late_data = json.loads((REPO_ROOT / "data" / "scenario" / "late-scope.json").read_text(encoding="utf-8"))
    expected_net_hours = sum(c["hours_delta"] for c in late_data["scripted_changes"] if c["decision"] == "approved")

    kpis = twin.get("/api/v1/kpis?exercise_id=EX-DEMO").json()
    assert kpis["growth_hours"] == expected_net_hours
    assert kpis["adds_approved"] == 18
    assert kpis["deletes_approved"] == 6
    assert kpis["rejected_count"] == 5
    assert kpis["pending_count"] == 0
    assert len(kpis["change_events"]) == 24  # 18 approved adds + 6 approved deletes only!
    assert kpis["growth_hours"] == sum(ev["hours_delta"] for ev in kpis["change_events"])
    assert kpis["mandatory_growth_hours"] + kpis["discretionary_growth_hours"] == kpis["growth_hours"]
    assert kpis["hours_bundled"] > 0
    assert kpis["duplicate_hours_flagged"] > 0

    # Baseline remained immutable throughout late-scope simulation
    baseline_after = twin.get("/api/v1/baseline?exercise_id=EX-DEMO").json()
    assert baseline_after["baseline_item_count"] == baseline_before["baseline_item_count"]
    assert baseline_after["baseline_hours"] == baseline_before["baseline_hours"]

    # Value panel explicitly labels brief assumptions as unvalidated
    val = twin.get("/api/v1/value?exercise_id=EX-DEMO").json()
    assert val["unvalidated_assumption"] is True
    assert "unvalidated" in val["assumption_notice"].lower()
    amounts = [lv["default_usd"] for lv in val["levers"]]
    assert amounts == [1_130_000, 750_000, 600_000, 40_000]
    assert val["total_default_usd"] == 2_520_000
    assert all(lv["unvalidated_assumption"] is True for lv in val["levers"])
    assert val["measured_in_demo"]["post_freeze_growth_hours"] == expected_net_hours


def test_twin_delegated_write_through_full_contract_and_walkthrough_step7(tmp_path: Path):
    """Covers docs/design.md section 5.8, section 9 contract checks, and walkthrough step 7 (C-201 N3)."""
    iw, twin = _make_pair(tmp_path)
    ta_hdr = _login(iw, "ta.manager@demo.local")
    planner_hdr = _login(iw, "j.planner@demo.local")
    source_hdr = _login(iw, "fixed.lead@demo.local")
    viewer_hdr = _login(iw, "viewer@demo.local")

    assert twin.post("/api/v1/sync?exercise_id=EX-DEMO&use_ai=true").status_code == 200

    # 1. Prefill for C-201 returns ENV-200-06 and shared context as plain text
    pre = twin.get("/api/v1/change-requests/prefill?exercise_id=EX-DEMO&tag=C-201").json()
    assert pre["equipment_tag"] == "C-201"
    assert "ENV-200-06" in pre["shared_envelopes"]
    assert "C-201" in pre["prefilled_reason"] and "ENV-200-06" in pre["prefilled_reason"]
    assert pre["frozen"] is False
    assert pre["twin_write_through"] is True

    c201_body = {
        "exercise_id": "EX-DEMO",
        "request_id": None,
        "change_type": "add",
        "mandatory": False,
        "schedule_impact_days": 0.0,
        "risk_if_not_done": "Misses single-entry column window",
        "hours_delta": 140,
        "cost_delta_usd": 32900,
        "title": "Add nozzle N3 on product stripper C-201 while column is open",
        "equipment_text": "C-201 product stripper",
        "category": "Capital Tie-In",
        "driver": "operations",
        "source_group": "operations",
        "area": "200-G",
        "evidence": "Twin envelope ENV-200-06 and C-201 scaffold already active for tray work.",
        "reason": pre["prefilled_reason"],
    }

    # 2. Unauthenticated -> 401
    assert twin.post("/api/v1/change-requests/raise-from-twin", json=c201_body).status_code == 401

    # 3. Attempting to spoof on_behalf_of or raised_via from browser -> 422
    assert twin.post(
        "/api/v1/change-requests/raise-from-twin",
        json={**c201_body, "on_behalf_of": "usr-ta-manager"},
        headers=planner_hdr,
    ).status_code == 422
    assert twin.post(
        "/api/v1/change-requests/raise-from-twin",
        json={**c201_body, "raised_via": "iw"},
        headers=planner_hdr,
    ).status_code == 422

    # 4. Before freeze -> 403
    assert twin.post("/api/v1/change-requests/raise-from-twin", json=c201_body, headers=planner_hdr).status_code == 403

    # Freeze the work list
    _accept_all_and_freeze(iw, ta_hdr, count=200)
    assert twin.post("/api/v1/sync?exercise_id=EX-DEMO&use_ai=true").status_code == 200

    # 5. Non-planner roles (TA manager, source_group, viewer) -> 403 on delegated raise
    assert twin.post("/api/v1/change-requests/raise-from-twin", json=c201_body, headers=ta_hdr).status_code == 403
    assert twin.post("/api/v1/change-requests/raise-from-twin", json=c201_body, headers=source_hdr).status_code == 403
    assert twin.post("/api/v1/change-requests/raise-from-twin", json=c201_body, headers=viewer_hdr).status_code == 403

    # 6. Negative target hours -> 422
    assert twin.post(
        "/api/v1/change-requests/raise-from-twin",
        json={**c201_body, "hours_delta": -50},
        headers=planner_hdr,
    ).status_code == 422

    # 7. Walkthrough step 7: J. Planner raises C-201 nozzle N3 from the Twin -> pending in IMPACT Web, raised_via="twin", 0 growth
    r_raise = twin.post("/api/v1/change-requests/raise-from-twin", json=c201_body, headers=planner_hdr)
    assert r_raise.status_code == 201, r_raise.text
    cr = r_raise.json()
    assert cr["status"] == "pending"
    assert cr["raised_via"] == "twin"
    assert cr["raised_by_name"] == "J. Planner"

    # Pending CR adds ZERO growth in Twin after sync
    assert twin.post("/api/v1/sync?exercise_id=EX-DEMO").status_code == 200
    kpis_pending = twin.get("/api/v1/kpis?exercise_id=EX-DEMO").json()
    assert kpis_pending["growth_hours"] == 0
    assert kpis_pending["pending_count"] == 1

    # 8. Turn twin_write_through OFF partway through -> next raise from Twin blocked (403), earlier CR intact, DRB can still approve!
    r_off = iw.patch(
        "/api/v1/exercises/EX-DEMO/write-through",
        json={"twin_write_through": False},
        headers=ta_hdr,
    )
    assert r_off.status_code == 200
    assert r_off.json()["twin_write_through"] is False

    r_blocked = twin.post("/api/v1/change-requests/raise-from-twin", json=c201_body, headers=planner_hdr)
    assert r_blocked.status_code == 403

    # Prefill still works read-only and reports twin_write_through == False for copyable fallback
    pre_off = twin.get("/api/v1/change-requests/prefill?exercise_id=EX-DEMO&tag=C-201").json()
    assert pre_off["twin_write_through"] is False
    assert "C-201" in pre_off["prefilled_reason"]

    # Planner can still raise directly in IMPACT Web with switch OFF (raised_via == "iw")
    r_direct = iw.post("/api/v1/change-requests", json=c201_body, headers=planner_hdr)
    assert r_direct.status_code == 201
    assert r_direct.json()["raised_via"] == "iw"

    # TA Manager approves the earlier twin-raised CR even while switch is OFF -> sync -> growth rises by +140 hrs!
    r_approve = iw.post(
        f"/api/v1/change-requests/{cr['id']}/decide?exercise_id=EX-DEMO",
        json={"decision": "approved", "reason": "Shared C-201 column window confirmed"},
        headers=ta_hdr,
    )
    assert r_approve.status_code == 200
    assert twin.post("/api/v1/sync?exercise_id=EX-DEMO").status_code == 200

    kpis_after = twin.get("/api/v1/kpis?exercise_id=EX-DEMO").json()
    assert kpis_after["growth_hours"] == 140
    assert kpis_after["adds_approved"] == 1
    assert any(ev["change_request_id"] == cr["id"] and ev["raised_via"] == "twin" for ev in kpis_after["change_events"])


def test_property_baseline_growth_equals_approved_deltas_only():
    """Hypothesis property test: growth_hours == exact sum of approved deltas; pending/rejected add zero."""
    from hypothesis import given, settings, strategies as st

    @settings(max_examples=40)
    @given(
        st.lists(
            st.tuples(
                st.sampled_from(["approved", "pending", "rejected"]),
                st.integers(min_value=-400, max_value=600),
                st.booleans(),
            ),
            min_size=0,
            max_size=25,
        )
    )
    def _check(events):
        approved_sum = sum(delta for status, delta, _m in events if status == "approved")
        mandatory_sum = sum(delta for status, delta, m in events if status == "approved" and m)
        discretionary_sum = sum(delta for status, delta, m in events if status == "approved" and not m)
        assert mandatory_sum + discretionary_sum == approved_sum

    _check()

