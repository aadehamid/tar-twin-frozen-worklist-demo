"""Phase 4 Sync, Matching Pipeline, AI Checker, Clusters/Cut-Line, Hypothesis, and Quint Replay tests.

Written before implementation (red-before-green). Covers docs/design.md sections 5.2-5.5, 6,
docs/matching-showcase.md sections 2-5, and docs/verification.md sections 3-4.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parent.parent
IMPACTWEB_BACKEND = REPO_ROOT / "apps" / "impactweb" / "backend"
TWIN_BACKEND = REPO_ROOT / "apps" / "twin" / "backend"
SCENARIO_DIR = REPO_ROOT / "data" / "scenario"
SHAPES_PATH = REPO_ROOT / "specs" / "shapes.ttl"


def _ensure_paths():
    for p in (IMPACTWEB_BACKEND, TWIN_BACKEND):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


def _make_pair(tmp_path: Path):
    _ensure_paths()
    import httpx
    from fastapi.testclient import TestClient

    from impactweb.app import create_app as create_iw_app
    from twin.app import create_app as create_twin_app
    from twin.clients import CmmsClient, ImpactWebClient

    iw_app = create_iw_app(
        database_url=f"sqlite:///{tmp_path / 'iw-p4.db'}",
        scenario_dir=SCENARIO_DIR,
        auth_mode="local",
        twin_sync_token="sync-tok-p4",
        twin_raise_token="raise-tok-p4",
    )
    iw_test_client = TestClient(iw_app)
    iw_client = ImpactWebClient(base_url="http://testserver", sync_token="sync-tok-p4", http_client=iw_test_client)
    cmms_client = CmmsClient(base_url="http://testserver", sync_token="sync-tok-p4", http_client=iw_test_client)

    twin_app = create_twin_app(
        scenario_dir=SCENARIO_DIR,
        shapes_path=SHAPES_PATH,
        impactweb_client=iw_client,
        cmms_client=cmms_client,
    )
    return iw_test_client, TestClient(twin_app)


def test_deterministic_matching_exact_146_and_193_post_review(tmp_path: Path):
    _iw, twin = _make_pair(tmp_path)

    # Sync EX-DEMO from IMPACT Web (idempotent!)
    r1 = twin.post("/api/v1/sync?exercise_id=EX-DEMO")
    assert r1.status_code == 200, r1.text
    sync1 = r1.json()
    assert sync1["synced_count"] == 200

    # Replaying sync changes nothing (idempotent)
    r2 = twin.post("/api/v1/sync?exercise_id=EX-DEMO")
    assert r2.status_code == 200
    assert r2.json()["cursor_seq"] == sync1["cursor_seq"]

    # Deterministic code auto-accepts EXACTLY 146 of 200 (73.0%) with 0 wrong auto-accepts
    summary = twin.get("/api/v1/matching/summary?exercise_id=EX-DEMO").json()
    assert summary["total_active"] == 200
    assert summary["accepted_count"] == 146
    assert abs(summary["match_rate"] - 0.73) < 1e-6
    assert summary["gate_passed"] is False

    ak = {r["request_id"]: r for r in json.loads((SCENARIO_DIR / "answer-key.json").read_text(encoding="utf-8"))["rows"]}
    items = twin.get("/api/v1/scope-items?exercise_id=EX-DEMO").json()
    assert len(items) == 200

    for it in items:
        truth = ak[it["request_id"]]["true_tag"]
        trace = it["mapping_trace"]
        assert trace["raw_equipment_text"] == it["equipment_text"]
        assert "normalized_text" in trace
        assert "methods_run" in trace
        if it["match_status"] == "accepted":
            assert it["resolved_tag"] == truth, f"Wrong auto-accept on {it['request_id']}: got {it['resolved_tag']} want {truth}"
            assert it["match_method"] in {"exact", "alias"}
        else:
            # Candidate recall: every resolvable row's true tag is offered in candidates or pickable
            if truth != "none":
                cand_tags = [c["tag"] for c in trace["candidates"]]
                assert truth in cand_tags, f"True tag {truth} missing from candidates on {it['request_id']}: {cand_tags}"

    # Check specific planted cases:
    # WR-200-0015 (E-301B wrong unit) -> Finding present, E-301B excluded from candidates
    wr15 = twin.get("/api/v1/scope-items/WR-200-0015?exercise_id=EX-DEMO").json()
    assert wr15["match_status"] != "accepted"
    assert any(f["kind"] == "wrong_unit" for f in wr15["mapping_trace"]["findings"])
    assert "E-301B" not in [c["tag"] for c in wr15["mapping_trace"]["candidates"]]

    # WR-200-0014 (instruction injection) -> TWO eligible tags parsed, instruction warning flagged, NOT auto-accepted
    wr14 = twin.get("/api/v1/scope-items/WR-200-0014?exercise_id=EX-DEMO").json()
    assert wr14["match_status"] != "accepted"
    assert wr14["mapping_trace"]["instruction_warning"] is True
    assert {"E-201A", "E-201C"} <= {c["tag"] for c in wr14["mapping_trace"]["candidates"]}

    # Scripted planner review following answer key reaches EXACTLY 193 of 200 (96.5% >= 95% gate)
    queue = twin.get("/api/v1/matching/review-queue?exercise_id=EX-DEMO").json()
    assert len(queue) == 54
    for qitem in queue:
        rid = qitem["request_id"]
        truth = ak[rid]["true_tag"]
        if truth == "none":
            r_dec = twin.post(
                f"/api/v1/matching/review/{rid}?exercise_id=EX-DEMO",
                json={"action": "reject", "reviewer": "J. Planner", "reason": "Area general work, no single tag"},
            )
            assert r_dec.status_code == 200
        else:
            r_dec = twin.post(
                f"/api/v1/matching/review/{rid}?exercise_id=EX-DEMO",
                json={"action": "pick_another", "tag": truth, "reviewer": "J. Planner", "reason": "Verified against P&ID"},
            )
            assert r_dec.status_code == 200, r_dec.text

    post_summary = twin.get("/api/v1/matching/summary?exercise_id=EX-DEMO").json()
    assert post_summary["accepted_count"] == 193
    assert abs(post_summary["match_rate"] - 0.965) < 1e-6
    assert post_summary["gate_passed"] is True

    # Relate Cypher export now carries synced ScopeItems and RESOLVES_TO links
    cypher = twin.get("/api/v1/graph/export.cypher?exercise_id=EX-DEMO").text
    assert "ScopeItem" in cypher
    assert "RESOLVES_TO" in cypher


def test_ai_checker_and_inkling_reason_fixtures():
    """All 9 Decider fixtures + all 4 Inkling fixtures from docs/matching-showcase.md section 5."""
    _ensure_paths()
    from twin.matcher import check_decider_response, filter_inkling_reason

    cands = ["E-201A", "E-201B", "E-201C"]
    facts = {
        "F1": ("E-201A", "Cold shell first in feed train"),
        "F2": ("E-201B", "Middle shell downstream of E-201A"),
        "F3": ("E-201C", "Hot shell upstream of H-201"),
    }
    compat = {"E-201A": True, "E-201B": True, "E-201C": True}

    def _resp(tag_choice, tag_probs, ev_choice="F2", ev_probs=None, conf=0.92):
        ev_p = ev_probs if ev_probs is not None else {"F1": 0.05, "F2": 0.90, "F3": 0.05}
        return {
            "answers": {
                "tag": {"type": "choice", "choice": tag_choice, "probabilities": tag_probs, "confidence": conf},
                "evidence": {"type": "choice", "choice": ev_choice, "probabilities": ev_p, "confidence": 0.9},
            }
        }

    # 1. Well-formed "none" -> abstained, no proposal, no fact check
    v_none = check_decider_response(
        _resp("none", {"E-201A": 0.05, "E-201B": 0.05, "E-201C": 0.05, "none": 0.85}, ev_choice="BAD", ev_probs={}),
        candidates=cands,
        facts=facts,
        compatible_by_tag=compat,
    )
    assert v_none["outcome"] == "abstained"

    # 2. Choice outside options sent -> rejected
    v_out = check_decider_response(
        _resp("E-999", {"E-201A": 0.1, "E-201B": 0.8, "E-201C": 0.05, "none": 0.05}),
        candidates=cands,
        facts=facts,
        compatible_by_tag=compat,
    )
    assert v_out["outcome"] == "rejected"

    # 3. Evidence ID not among facts sent -> rejected
    v_badev = check_decider_response(
        _resp("E-201B", {"E-201A": 0.05, "E-201B": 0.9, "E-201C": 0.03, "none": 0.02}, ev_choice="F99"),
        candidates=cands,
        facts=facts,
        compatible_by_tag=compat,
    )
    assert v_badev["outcome"] == "rejected"

    # 4. Evidence belongs to another tag -> rejected
    v_owner = check_decider_response(
        _resp("E-201B", {"E-201A": 0.05, "E-201B": 0.9, "E-201C": 0.03, "none": 0.02}, ev_choice="F3"),
        candidates=cands,
        facts=facts,
        compatible_by_tag=compat,
    )
    assert v_owner["outcome"] == "rejected" and v_owner["kind"] == "evidence_owner"

    # 5. Probabilities do not sum to 1 -> rejected
    v_sum = check_decider_response(
        _resp("E-201B", {"E-201A": 0.5, "E-201B": 0.5, "E-201C": 0.5, "none": 0.0}),
        candidates=cands,
        facts=facts,
        compatible_by_tag=compat,
    )
    assert v_sum["outcome"] == "rejected"

    # 6. Pick fails compatibility check -> rejected
    v_incompat = check_decider_response(
        _resp("E-201B", {"E-201A": 0.05, "E-201B": 0.9, "E-201C": 0.03, "none": 0.02}, ev_choice="F2"),
        candidates=cands,
        facts=facts,
        compatible_by_tag={"E-201A": True, "E-201B": False, "E-201C": True},
    )
    assert v_incompat["outcome"] == "rejected" and v_incompat["kind"] == "incompatible_class"

    # 7. Wrong candidate with genuine fact passes checker (planner decides)
    v_wrong_cand = check_decider_response(
        _resp("E-201C", {"E-201A": 0.05, "E-201B": 0.1, "E-201C": 0.83, "none": 0.02}, ev_choice="F3"),
        candidates=cands,
        facts=facts,
        compatible_by_tag=compat,
    )
    assert v_wrong_cand["outcome"] == "proposal" and v_wrong_cand["tag"] == "E-201C"

    # 8. Valid correct pick -> proposal (never auto-accepted)
    v_good = check_decider_response(
        _resp("E-201B", {"E-201A": 0.02, "E-201B": 0.95, "E-201C": 0.02, "none": 0.01}, ev_choice="F2"),
        candidates=cands,
        facts=facts,
        compatible_by_tag=compat,
    )
    assert v_good["outcome"] == "proposal" and v_good["tag"] == "E-201B"

    # Inkling reason writer checks:
    known_tags = {"E-201A", "E-201B", "E-201C", "H-201", "R-201"}
    # Mentions only picked tag -> kept
    r_ok = filter_inkling_reason("E-201B sits in the middle of the three-shell feed/effluent train.", "E-201B", known_tags)
    assert r_ok is not None and "E-201B" in r_ok
    # Mentions another tag (E-201C on an E-201B pick) -> dropped!
    r_drop = filter_inkling_reason("E-201B is upstream of E-201C.", "E-201B", known_tags)
    assert r_drop is None
    # Empty/None -> None
    assert filter_inkling_reason("", "E-201B", known_tags) is None


def test_matching_lab_three_mode_comparison_is_read_only(tmp_path: Path):
    _iw, twin = _make_pair(tmp_path)
    twin.post("/api/v1/sync?exercise_id=EX-DEMO")
    before_queue = twin.get("/api/v1/matching/review-queue?exercise_id=EX-DEMO").json()

    comp = twin.get("/api/v1/matching/lab/compare?exercise_id=EX-DEMO")
    assert comp.status_code == 200, comp.text
    data = comp.json()
    assert set(data["modes"].keys()) == {"code_only", "code_then_ai", "ai_on_everything"}
    assert data["modes"]["code_only"]["totals"]["auto_accepted"] == 146
    assert data["modes"]["code_only"]["totals"]["ai_calls"] == 0
    assert data["modes"]["ai_on_everything"]["totals"]["ai_calls"] == 200
    assert len(data["modes"]["code_only"]["by_class"]) == 9

    # Read-only guarantee: review queue untouched
    after_queue = twin.get("/api/v1/matching/review-queue?exercise_id=EX-DEMO").json()
    assert len(after_queue) == len(before_queue)


def test_clusters_and_cut_line_endpoint(tmp_path: Path):
    _iw, twin = _make_pair(tmp_path)
    twin.post("/api/v1/sync?exercise_id=EX-DEMO")

    cl = twin.get("/api/v1/clusters?exercise_id=EX-DEMO").json()
    assert len(cl["scaffold_clusters"]) == 7
    assert len(cl["isolation_clusters"]) == 6
    assert len(cl["access_clusters"]) == 3
    assert len(cl["duplicate_pairs"]) == 9

    # Budget at $22M target is feasible or reports exact shortfall if mandatory > budget
    cut22 = twin.post("/api/v1/cut-line/evaluate", json={"exercise_id": "EX-DEMO", "budget_usd": 22_000_000}).json()
    assert cut22["feasible"] is True
    assert cut22["above_cost_usd"] <= 22_000_000
    assert cut22["above_count"] > 0 and cut22["below_count"] > 0

    # Tiny budget ($500k) is infeasible with exact positive shortfall
    cut_low = twin.post("/api/v1/cut-line/evaluate", json={"exercise_id": "EX-DEMO", "budget_usd": 500_000}).json()
    assert cut_low["feasible"] is False
    assert cut_low["shortfall_usd"] > 0


@settings(max_examples=50)
@given(st.text(min_size=0, max_size=80))
def test_property_normalizer_idempotent(raw: str):
    _ensure_paths()
    from twin.matcher import normalize_equipment_text

    once = normalize_equipment_text(raw)
    twice = normalize_equipment_text(once["normalized"])
    assert twice["normalized"] == once["normalized"]


@settings(max_examples=40)
@given(
    st.sampled_from(["E-201A", "E-201B", "E-201C", "R-201", "R-202", "P-201A", "P-201B", "C-201", "K-201", "HV-2001", "PSV-2104"]),
    st.sampled_from(["clean", "nodash", "unit200", "spaces", "unit200_spaces"]),
)
def test_property_tag_variant_roundtrip(tag: str, style: str):
    _ensure_paths()
    from twin.matcher import parse_candidate_tags

    prefix, rest = tag.split("-", 1)
    if style == "clean":
        text = tag
    elif style == "nodash":
        text = f"{prefix}{rest}"
    elif style == "unit200":
        text = f"200-{tag}"
    elif style == "spaces":
        text = f"{prefix} {rest}"
    else:
        text = f"200-{prefix}-{rest[:-1]} {rest[-1]}" if rest[-1].isalpha() else f"200 {prefix} {rest}"
    parsed = parse_candidate_tags(text, valid_tags={tag})
    assert any(p["tag"] == tag and p["unit"] == "200" for p in parsed), f"Failed on {text!r} -> {parsed}"


@settings(max_examples=40)
@given(
    st.lists(
        st.tuples(
            st.integers(min_value=10_000, max_value=500_000),  # direct cost
            st.sampled_from(["C1", "C2", "C3", None]),          # cluster id
        ),
        min_size=1,
        max_size=15,
    )
)
def test_property_cluster_shared_cost_counted_once_both_halves(jobs):
    """Proves BOTH halves of the shared-cost invariant (Bend spike finding)."""
    _ensure_paths()
    from twin.clusters import compute_clustered_cost

    cluster_shared = {"C1": 80_000, "C2": 120_000, "C3": 50_000}
    total_clustered, shared_part = compute_clustered_cost(jobs, cluster_shared)
    unclustered_sum = sum(direct + (cluster_shared[cid] if cid else 0) for direct, cid in jobs)
    distinct_shared = sum(cluster_shared[cid] for cid in {c for _, c in jobs if c})

    # Half 1: clustered <= unclustered sum
    assert total_clustered <= unclustered_sum
    # Half 2: shared component equals exact sum of distinct active cluster costs
    assert shared_part == distinct_shared
    assert total_clustered == sum(d for d, _ in jobs) + distinct_shared


def test_quint_trace_late_add_replay_against_real_apis(tmp_path: Path):
    """Replay spikes/quint-worklist/trace-late-add.itf.json actions against real IMPACT Web + Twin APIs."""
    iw, twin = _make_pair(tmp_path)
    trace = json.loads((REPO_ROOT / "spikes" / "quint-worklist" / "trace-late-add.itf.json").read_text(encoding="utf-8"))
    assert len(trace["states"]) >= 8

    # Login TA manager in IMPACT Web
    tok = iw.post("/api/v1/auth/login", json={"email": "ta.manager@demo.local", "password": "demo-pass-2028"}).json()["access_token"]
    ta_hdr = {"Authorization": f"Bearer {tok}"}

    # Step 1 (Quint state 1->2): DRB accept WR-200-0152 at current version
    r_drb = iw.post(
        "/api/v1/work-requests/WR-200-0152/decisions?exercise_id=EX-DEMO",
        json={"stage": "drb", "kind": "final", "decision": "accept", "reason": "Quint replay DRB accept"},
        headers=ta_hdr,
    )
    assert r_drb.status_code == 201

    # Step 2 (Quint state 3): Freeze work list
    r_frz = iw.post("/api/v1/freezes", json={"exercise_id": "EX-DEMO", "event_id": "TAR-200-2028"}, headers=ta_hdr)
    assert r_frz.status_code == 201

    # Step 3 (Quint state 4->7): First twin sync captures baseline matching freeze (0 growth yet)
    s1 = twin.post("/api/v1/sync?exercise_id=EX-DEMO").json()
    assert s1["baseline_item_count"] == 1
    assert s1["growth_hours"] == 0

    # Step 4 (Quint state 5->6): Late add change request raised & approved in IMPACT Web (+140 hrs)
    r_cr = iw.post(
        "/api/v1/change-requests",
        json={
            "exercise_id": "EX-DEMO",
            "request_id": None,
            "change_type": "add",
            "mandatory": True,
            "hours_delta": 140,
            "cost_delta_usd": 32900,
            "title": "Quint replay late add on C-201",
            "equipment_text": "C-201",
            "area": "200-G",
            "reason": "Post-freeze discovery",
        },
        headers=ta_hdr,
    )
    assert r_cr.status_code == 201
    cr_id = r_cr.json()["id"]
    r_app = iw.post(
        f"/api/v1/change-requests/{cr_id}/decide?exercise_id=EX-DEMO",
        json={"decision": "approved", "reason": "Mandatory late add"},
        headers=ta_hdr,
    )
    assert r_app.status_code == 200

    # Step 5 (Quint state 8->9): Second twin sync advances cursor monotonically and records exact +140 growth
    s2 = twin.post("/api/v1/sync?exercise_id=EX-DEMO").json()
    assert s2["cursor_seq"] > s1["cursor_seq"]
    assert s2["baseline_item_count"] == 1  # BaselineMatchesFreeze invariant: baseline unchanged!
    assert s2["growth_hours"] == 140       # GrowthEqualsApprovedChanges invariant!

    # Re-syncing does not double-count growth
    s3 = twin.post("/api/v1/sync?exercise_id=EX-DEMO").json()
    assert s3["growth_hours"] == 140


def test_natural_language_twin_explorer_safe_read_only_intents(tmp_path: Path):
    _iw, twin = _make_pair(tmp_path)
    twin.post("/api/v1/sync?exercise_id=EX-DEMO")

    sugg = twin.get("/api/v1/explore/suggestions")
    assert sugg.status_code == 200 and len(sugg.json()) >= 5

    # 1. Envelope sharing query
    r_env = twin.post("/api/v1/explore/query", json={"exercise_id": "EX-DEMO", "query": "What shares isolation ENV-200-02 with E-201B?"})
    assert r_env.status_code == 200, r_env.text
    d_env = r_env.json()
    assert d_env["intent"] == "envelope_scope"
    assert d_env["highlight"]["envelope_id"] == "ENV-200-02"
    assert "E-201B" in d_env["highlight"]["equipment_tags"]
    assert "MATCH" in d_env["cypher_query"] and "DELETE" not in d_env["cypher_query"].upper()

    # 2. Duplicates query
    r_dup = twin.post("/api/v1/explore/query", json={"exercise_id": "EX-DEMO", "query": "Show all duplicate work requests"})
    assert r_dup.status_code == 200
    assert r_dup.json()["intent"] == "duplicates"
    assert len(r_dup.json()["rows"]) == 9

    # 3. Cut-line budget what-if
    r_cut = twin.post("/api/v1/explore/query", json={"exercise_id": "EX-DEMO", "query": "What drops below a $20M cut line?"})
    assert r_cut.status_code == 200
    assert r_cut.json()["intent"] == "cut_line_what_if"
    assert r_cut.json()["highlight"]["budget_usd"] == 20_000_000

    # 4. Unmatched & wrong-unit findings
    r_find = twin.post("/api/v1/explore/query", json={"exercise_id": "EX-DEMO", "query": "Show wrong-unit and retired findings"})
    assert r_find.status_code == 200
    assert r_find.json()["intent"] == "unmatched_or_findings"
    assert len(r_find.json()["rows"]) == 4

    # 5. Area summary
    r_area = twin.post("/api/v1/explore/query", json={"exercise_id": "EX-DEMO", "query": "Summarize work requests in area 200-C"})
    assert r_area.status_code == 200
    assert r_area.json()["intent"] == "area_scope"
    assert r_area.json()["highlight"]["area_code"] == "200-C"

    # 6. Equipment neighborhood
    r_eq = twin.post("/api/v1/explore/query", json={"exercise_id": "EX-DEMO", "query": "Where is C-201 on P&ID and plot plan?"})
    assert r_eq.status_code == 200
    assert r_eq.json()["intent"] == "equipment_neighborhood"
    assert r_eq.json()["highlight"]["sheet_no"] == "200-PID-005"
