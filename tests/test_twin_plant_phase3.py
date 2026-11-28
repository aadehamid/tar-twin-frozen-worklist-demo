"""Phase 3 Twin plant graph, DEXPI load, isolation envelope walk, and snapshot tests.

Written before implementation (red-before-green). Covers docs/design.md sections 4.3, 4.4, 5.1, 5.7
and docs/spikes/shacl-n10s.md section 6.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TWIN_BACKEND = REPO_ROOT / "apps" / "twin" / "backend"
SCENARIO_DIR = REPO_ROOT / "data" / "scenario"
SHAPES_PATH = REPO_ROOT / "specs" / "shapes.ttl"


def _ensure_twin_path():
    if str(TWIN_BACKEND) not in sys.path:
        sys.path.insert(0, str(TWIN_BACKEND))


def test_dexpi_plant_load_and_envelope_walk():
    _ensure_twin_path()
    from twin.plant_loader import build_plant_graph, verify_plant_graph

    plant = build_plant_graph(SCENARIO_DIR)
    errors = verify_plant_graph(plant, SHAPES_PATH)
    assert errors == [], f"Plant verification errors: {errors}"

    eq_nodes = [n for n in plant["nodes"] if "Equipment" in n["labels"]]
    sheet_nodes = [n for n in plant["nodes"] if "PidSheet" in n["labels"]]
    env_nodes = [n for n in plant["nodes"] if "IsolationEnvelope" in n["labels"]]
    bv_rels = [r for r in plant["rels"] if r["type"] == "BOUNDED_BY"]

    assert len(eq_nodes) == 32
    assert len(sheet_nodes) == 5
    assert len(env_nodes) == 6
    assert len(bv_rels) == 112

    # Computed envelope membership matches docs/scenario-spec.md section 2.4
    spec_envs = json.loads((SCENARIO_DIR / "isolation-envelopes.json").read_text(encoding="utf-8"))["envelopes"]
    spec_by_id = {e["id"]: e for e in spec_envs}
    for env in plant["computed_envelopes"]:
        want = spec_by_id[env["id"]]
        assert set(env["equipment_tags"]) == set(want["equipment_tags"]), env["id"]
        assert set(env["boundary_valves"]) == set(want["boundary_valves"]), env["id"]
        assert env["closed"] is True
        assert env["boundary_valve_count"] == len(want["boundary_valves"])

    # Removing a cross-envelope boundary valve (HV-2081 on ENV-200-05) breaks closure detection
    broken = copy.deepcopy(plant)
    broken["rels"] = [
        r for r in broken["rels"] if not (r["type"] == "BOUNDED_BY" and r["from"] == "env:ENV-200-05" and r["to"] == "valve:HV-2081")
    ]
    broken_errs = verify_plant_graph(broken, SHAPES_PATH)
    assert any("not closed" in e for e in broken_errs), f"Expected closure error, got {broken_errs}"

    # Adversarial shared-equipment leak: an unblocked pipe from split-boundary P-201A suction nozzle
    # (nz:P-201A:N1) directly to outside equipment C-201 must fail ENV-200-01 closure.
    shared_leak = copy.deepcopy(plant)
    shared_leak["rels"].append({"type": "CONNECTED_TO", "from": "nz:P-201A:N1", "to": "eq:C-201"})
    leak_errs = verify_plant_graph(shared_leak, SHAPES_PATH)
    assert any("ENV-200-01 is not closed" in e and "C-201" in e for e in leak_errs), f"Expected shared leak error, got {leak_errs}"


def test_twin_api_plant_endpoints_and_snapshot_matches_twin_graph(tmp_path: Path):
    _ensure_twin_path()
    from fastapi.testclient import TestClient

    from twin.app import create_app

    app = create_app(scenario_dir=SCENARIO_DIR, shapes_path=SHAPES_PATH)
    client = TestClient(app)

    assert client.get("/api/v1/utils/health-check/").status_code == 200
    assert client.get("/twin/api/v1/utils/health-check/").status_code == 200

    summary = client.get("/api/v1/plant/summary").json()
    assert summary["equipment_count"] == 32
    assert summary["sheet_count"] == 5
    assert summary["envelope_count"] == 6
    assert summary["boundary_valve_count"] == 112

    eq_detail = client.get("/api/v1/plant/equipment/E-201B").json()
    assert eq_detail["tag"] == "E-201B"
    assert eq_detail["sheet"] == "200-PID-002"
    assert eq_detail["area"] == "200-C"
    assert "ENV-200-02" in eq_detail["envelopes"]
    assert len(eq_detail["nozzles"]) >= 4

    svg = client.get("/api/v1/plant/sheets/200-PID-002.svg")
    assert svg.status_code == 200
    assert "<svg" in svg.text

    plot = client.get("/api/v1/plant/plot-plan").json()
    assert len(plot["areas"]) == 7
    assert len(plot["equipment"]) == 32

    envs = client.get("/api/v1/plant/envelopes").json()
    assert len(envs) == 6
    assert sum(e["boundary_valve_count"] for e in envs) == 112

    # Snapshot matches scripts/twin_graph.py check --neo4j-snapshot
    snap = client.get("/api/v1/plant/snapshot").json()
    snap_path = tmp_path / "neo4j-snapshot.json"
    snap_path.write_text(json.dumps(snap, indent=2), encoding="utf-8")
    res = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "twin_graph.py"), "--repo", str(REPO_ROOT), "check", "--neo4j-snapshot", str(snap_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"twin_graph snapshot check failed:\n{res.stdout}\n{res.stderr}"

    # Browser Relate Cypher export rejects unknown exercise_id and includes exercise scope when present
    assert client.get("/api/v1/graph/export.cypher?exercise_id=EX-UNKNOWN").status_code == 404
    app.state.store.set_scope_graph(
        "EX-DEMO",
        scope_nodes=[
            {
                "key": "wr:EX-DEMO:WR-200-0147",
                "labels": ["ScopeItem", "BundlePull"],
                "props": {"exercise_id": "EX-DEMO", "request_id": "WR-200-0147", "ript": 21},
            }
        ],
        scope_rels=[
            {"from": "wr:EX-DEMO:WR-200-0147", "to": "eq:E-201B", "type": "RESOLVES_TO", "props": {"status": "accepted"}}
        ],
    )
    cypher_resp = client.get("/api/v1/graph/export.cypher?exercise_id=EX-DEMO&event_id=TAR-200-2028")
    assert cypher_resp.status_code == 200
    assert "CREATE (:Equipment" in cypher_resp.text
    assert "WR-200-0147" in cypher_resp.text
    assert "RESOLVES_TO" in cypher_resp.text
    assert "ENV-200-02" in cypher_resp.text

    import shutil
    if shutil.which("relate"):
        db_file = tmp_path / "browser.relate"
        r_load = subprocess.run(
            ["relate", "query", "--database", str(db_file)],
            input=cypher_resp.text,
            capture_output=True,
            text=True,
            check=False,
        )
        assert r_load.returncode == 0, f"relate load failed: {r_load.stderr}"
        r_chk = subprocess.run(
            [
                "relate",
                "query",
                "--database",
                str(db_file),
                "--format",
                "jsonl",
                "MATCH (e:Equipment) RETURN count(e) AS eq_cnt",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert r_chk.returncode == 0, r_chk.stderr
        rows = [json.loads(line) for line in r_chk.stdout.splitlines() if line.strip()]
        assert rows and rows[0]["eq_cnt"] == 32


def test_memory_store_shacl_guard_rejects_invalid_graph():
    _ensure_twin_path()
    from twin.graph_store import MemoryPlantStore
    from twin.plant_loader import build_plant_graph

    store = MemoryPlantStore(shapes_path=SHAPES_PATH)
    clean = build_plant_graph(SCENARIO_DIR)
    store.load_plant_graph(clean)
    assert store.summary()["equipment_count"] == 32

    # Mutate E-201A tag to break S1 pattern -> guard rejects and preserves clean state
    bad = copy.deepcopy(clean)
    for nd in bad["nodes"]:
        if nd["key"] == "eq:E-201A":
            nd["props"]["tag"] = "E201A"
    with pytest.raises(ValueError, match="SHACL"):
        store.load_plant_graph(bad)

    # Prior valid graph remains intact
    assert store.get_equipment("E-201A")["tag"] == "E-201A"


def test_load_dexpi_cli_job_exports_valid_snapshot(tmp_path: Path):
    snap_out = tmp_path / "cli-snapshot.json"
    res = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "jobs" / "load_dexpi.py"),
            "--scenario-dir",
            str(SCENARIO_DIR),
            "--shapes",
            str(SHAPES_PATH),
            "--export-snapshot",
            str(snap_out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"load_dexpi.py failed:\n{res.stdout}\n{res.stderr}"
    snap = json.loads(snap_out.read_text(encoding="utf-8"))
    assert len(snap["equipment_tags"]) == 32
    assert len(snap["envelope_ids"]) == 6


@pytest.mark.skipif(not os.environ.get("NEO4J_TEST_URI"), reason="Live Neo4j 5.26 + n10s + APOC not configured")
def test_live_neo4j_guarded_load_and_mutant_rejection():
    _ensure_twin_path()
    from twin.neo4j_store import Neo4jPlantStore
    from twin.plant_loader import build_plant_graph

    uri = os.environ["NEO4J_TEST_URI"]
    user = os.environ.get("NEO4J_TEST_USER", "neo4j")
    password = os.environ.get("NEO4J_TEST_PASSWORD", "testpassword")
    store = Neo4jPlantStore(uri=uri, user=user, password=password, shapes_path=SHAPES_PATH)
    try:
        store.ensure_constraints()
        store.install_shacl_guard()
        assert store.guard_ready() is True

        plant = build_plant_graph(SCENARIO_DIR)
        store.load_plant_graph(plant)
        snap = store.export_snapshot()
        assert len(snap["equipment_tags"]) == 32
        assert len(snap["envelope_ids"]) == 6

        # Trigger refuses a bad write (Equipment tag missing dash) and leaves graph intact
        with pytest.raises(Exception):
            store.run_write("CREATE (:Equipment:Asset:Exchanger {tag: 'E201X'})")
        assert len(store.export_snapshot()["equipment_tags"]) == 32
        # Fresh store instance derives pinned shapes from specs/shapes.ttl and passes readiness
        fresh = Neo4jPlantStore(uri=uri, user=user, password=password, shapes_path=SHAPES_PATH)
        try:
            assert fresh.guard_ready() is True
            # Weakening loaded shapes causes fresh instance readiness check to fail closed
            with fresh._driver.session(database="neo4j") as s:
                s.run(
                    "CALL n10s.validation.shacl.import.inline($ttl, 'Turtle')",
                    ttl="@prefix neo4j: <neo4j://graph.schema#> . @prefix sh: <http://www.w3.org/ns/shacl#> . "
                    "neo4j:WeakShape a sh:NodeShape ; sh:targetClass neo4j:Equipment ; "
                    "sh:property [ sh:path neo4j:tag ; sh:minCount 1 ] .",
                ).consume()
            assert fresh.guard_ready() is False
        finally:
            fresh.close()
    finally:
        store.close()
