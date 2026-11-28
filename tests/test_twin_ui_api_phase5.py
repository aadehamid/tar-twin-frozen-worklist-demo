"""Phase 5 Twin UI backend contract tests (auth proxy, active tags, built frontend assets)."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
for d in (REPO_ROOT / "apps" / "impactweb" / "backend", REPO_ROOT / "apps" / "twin" / "backend"):
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))

from impactweb.app import create_app as create_iw_app
from twin.app import create_app as create_twin_app
from twin.clients import CmmsClient, ImpactWebClient


def test_twin_ui_auth_proxy_active_tags_and_static_assets(tmp_path: Path):
    iw_app = create_iw_app(
        database_url=f"sqlite:///{tmp_path / 'iw-p5.db'}",
        scenario_dir=REPO_ROOT / "data" / "scenario",
        auth_mode="local",
        twin_sync_token="sync-tok-p5",
        twin_raise_token="raise-tok-p5",
    )
    iw_tc = TestClient(iw_app)
    iw_cli = ImpactWebClient(base_url="http://testserver", sync_token="sync-tok-p5", raise_token="raise-tok-p5", http_client=iw_tc)
    cmms_cli = CmmsClient(base_url="http://testserver", sync_token="sync-tok-p5", http_client=iw_tc)

    twin_app = create_twin_app(
        scenario_dir=REPO_ROOT / "data" / "scenario",
        shapes_path=REPO_ROOT / "specs" / "shapes.ttl",
        impactweb_client=iw_cli,
        cmms_client=cmms_cli,
        auth_mode="local",
    )
    tc = TestClient(twin_app)

    # 1. Auth mode & delegated login through IMPACT Web identity authority
    m = tc.get("/api/v1/auth/mode")
    assert m.status_code == 200
    assert m.json()["auth_mode"] == "local"
    assert m.json()["impactweb_connected"] is True

    bad = tc.post("/api/v1/auth/login", json={"email": "j.planner@demo.local", "password": "wrong"})
    assert bad.status_code == 401

    ok = tc.post("/api/v1/auth/login", json={"email": "j.planner@demo.local", "password": "demo-pass-2028"})
    assert ok.status_code == 200
    token = ok.json()["access_token"]

    me = tc.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["role"] == "planner"
    assert me.json()["full_name"] == "J. Planner"

    # 2. Active Unit 200 tags for Pick-another review selector
    tags = tc.get("/api/v1/plant/active-tags")
    assert tags.status_code == 200
    tag_set = {t["tag"] for t in tags.json()}
    assert "E-201B" in tag_set and "C-201" in tag_set
    assert "E-301A" not in tag_set  # Unit 300 excluded
    assert "E-209" not in tag_set  # Retired tag excluded

    # 3. Built Twin SPA index is served on both / and /twin/ when built assets exist
    if (REPO_ROOT / "apps" / "twin" / "backend" / "twin" / "frontend" / "index.html").is_file():
        r_root = tc.get("/")
        r_prefixed = tc.get("/twin/")
        assert r_root.status_code == 200 and "Unit 200 Turnaround Digital Twin" in r_root.text
        assert r_prefixed.status_code == 200 and "Unit 200 Turnaround Digital Twin" in r_prefixed.text

    # 4. In exe mode, password login endpoint is forbidden
    exe_twin = create_twin_app(
        scenario_dir=REPO_ROOT / "data" / "scenario",
        shapes_path=REPO_ROOT / "specs" / "shapes.ttl",
        impactweb_client=iw_cli,
        cmms_client=cmms_cli,
        auth_mode="exe",
        edge_auth_secret="edge-sec",
    )
    exe_tc = TestClient(exe_twin)
    assert exe_tc.post("/api/v1/auth/login", json={"email": "j.planner@demo.local", "password": "demo-pass-2028"}).status_code == 403
    exe_me = exe_tc.get("/api/v1/auth/me", headers={"X-Edge-Auth": "edge-sec", "X-ExeDev-Email": "j.planner@demo.local"})
    assert exe_me.status_code == 200
    assert exe_me.json()["role"] == "planner"


def test_evaluate_cut_line_matches_exact_bend_shared_cost_rule(tmp_path: Path):
    """Verify evaluate_cut_line implements exact Bend rule: saving == sum((count - 1) * shared_cost)."""
    from collections import defaultdict

    iw_app = create_iw_app(
        database_url=f"sqlite:///{tmp_path / 'iw-p5-bend.db'}",
        scenario_dir=REPO_ROOT / "data" / "scenario",
        auth_mode="local",
        twin_sync_token="sync-tok-p5",
    )
    iw_tc = TestClient(iw_app)
    iw_cli = ImpactWebClient(base_url="http://testserver", sync_token="sync-tok-p5", http_client=iw_tc)
    cmms_cli = CmmsClient(base_url="http://testserver", sync_token="sync-tok-p5", http_client=iw_tc)
    twin_app = create_twin_app(
        scenario_dir=REPO_ROOT / "data" / "scenario",
        shapes_path=REPO_ROOT / "specs" / "shapes.ttl",
        impactweb_client=iw_cli,
        cmms_client=cmms_cli,
        auth_mode="local",
    )
    tc = TestClient(twin_app)
    assert tc.post("/api/v1/sync?exercise_id=EX-DEMO").status_code == 200

    items = {it["request_id"]: it for it in tc.get("/api/v1/scope-items?exercise_id=EX-DEMO").json()}
    cl = tc.get("/api/v1/clusters?exercise_id=EX-DEMO").json()
    all_clusters = cl["isolation_clusters"] + cl["scaffold_clusters"] + cl["access_clusters"]
    cluster_cost = {c["id"]: int(c["shared_cost_usd"]) for c in all_clusters}
    clusters_of: dict[str, list[str]] = defaultdict(list)
    for c in all_clusters:
        for rid in c["request_ids"]:
            clusters_of[rid].append(c["id"])

    res = tc.post("/api/v1/cut-line/evaluate", json={"exercise_id": "EX-DEMO", "budget_usd": 22_000_000}).json()
    above = res["above_ids"]
    active_counts: dict[str, int] = defaultdict(int)
    for rid in above:
        for cid in clusters_of[rid]:
            active_counts[cid] += 1

    direct_sum = sum(int(items[rid]["estimate_cost_usd"]) for rid in above)
    shared_once = sum(cluster_cost[cid] for cid in active_counts)
    expected_unclustered = direct_sum + sum(cluster_cost[cid] * cnt for cid, cnt in active_counts.items())
    expected_saved = sum((cnt - 1) * cluster_cost[cid] for cid, cnt in active_counts.items())

    assert res["above_cost_usd"] == direct_sum + shared_once
    assert res["above_unclustered_cost_usd"] == expected_unclustered
    assert res["shared_cost_saved_usd"] == expected_saved
    assert res["above_cost_usd"] <= res["above_unclustered_cost_usd"]
    assert res["shared_cost_saved_usd"] > 0

