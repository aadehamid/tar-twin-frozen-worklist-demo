from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
TWIN_GRAPH = SCRIPTS_DIR / "twin_graph.py"


def _clean_git_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _run_tg(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TWIN_GRAPH), "--repo", str(repo), *args],
        env=_clean_git_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def _copy_doc_repo(tmp_path: Path) -> Path:
    dest = tmp_path / "repo"
    dest.mkdir()
    for rel in (
        "AGENTS.md",
        "README.md",
        "docs/decisions.md",
        "docs/design.md",
        "docs/scenario-spec.md",
        "docs/matching-showcase.md",
        "docs/verification.md",
    ):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, target)

    for spike_doc in sorted((REPO_ROOT / "docs" / "spikes").glob("*.md")):
        out = dest / "docs" / "spikes" / spike_doc.name
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(spike_doc, out)
        spike_dir = dest / "spikes" / spike_doc.stem
        spike_dir.mkdir(parents=True, exist_ok=True)
        for fname in ("results.json", "expected.py"):
            src = REPO_ROOT / "spikes" / spike_doc.stem / fname
            if src.exists():
                shutil.copy2(src, spike_dir / fname)

    subprocess.run(["git", "-C", str(dest), "init", "-b", "main"], env=_clean_git_env(), check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "config", "user.name", "Test User"], env=_clean_git_env(), check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "config", "user.email", "test@example.com"], env=_clean_git_env(), check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "add", "."], env=_clean_git_env(), check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "commit", "-m", "Init"], env=_clean_git_env(), check=True, capture_output=True)
    return dest


def _seed_synthetic_data_scenario(repo: Path) -> Path:
    """Create a complete synthetic data/scenario/ slice for full-mode graph tests."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import repo_facts

    facts = repo_facts.collect_facts(repo)
    major_tags = facts["scenario"]["major_equipment_tags"]
    assert len(major_tags) == 32

    sheet_map = {
        "FL-201A": "200-PID-001", "FL-201B": "200-PID-001", "D-201": "200-PID-001",
        "P-201A": "200-PID-001", "P-201B": "200-PID-001",
        "E-201A": "200-PID-002", "E-201B": "200-PID-002", "E-201C": "200-PID-002",
        "H-201": "200-PID-002", "R-201": "200-PID-002", "R-202": "200-PID-002",
        "A-201": "200-PID-003", "E-202": "200-PID-003", "D-202": "200-PID-003",
        "D-203": "200-PID-003", "P-204A": "200-PID-003", "P-204B": "200-PID-003",
        "D-204": "200-PID-004", "C-202": "200-PID-004", "K-201": "200-PID-004",
        "KT-201": "200-PID-004", "D-206": "200-PID-004", "K-202A": "200-PID-004",
        "K-202B": "200-PID-004",
        "C-201": "200-PID-005", "E-203": "200-PID-005", "D-205": "200-PID-005",
        "P-202A": "200-PID-005", "P-202B": "200-PID-005", "P-203A": "200-PID-005",
        "P-203B": "200-PID-005", "E-204": "200-PID-005",
    }
    env_defs = [
        ("ENV-200-01", "Feed", ["FL-201A", "FL-201B", "D-201", "P-201A", "P-201B"], 14),
        ("ENV-200-02", "HP reaction loop", ["P-201A", "P-201B", "E-201A", "E-201B", "E-201C", "H-201", "R-201", "R-202", "A-201", "E-202", "D-202"], 38),
        ("ENV-200-03", "Recycle gas", ["D-204", "C-202", "K-201"], 16),
        ("ENV-200-04", "Makeup gas", ["D-206", "K-202A", "K-202B"], 12),
        ("ENV-200-05", "LP separation", ["D-203", "P-204A", "P-204B"], 10),
        ("ENV-200-06", "Stripper", ["C-201", "E-203", "D-205", "P-202A", "P-202B", "P-203A", "P-203B", "E-204"], 22),
    ]

    valves = []
    envelopes = []
    v_idx = 2001
    for env_id, env_name, eq_tags, v_count in env_defs:
        b_tags = []
        for _ in range(v_count):
            vtag = f"HV-{v_idx}"
            v_idx += 1
            b_tags.append(vtag)
            valves.append({"tag": vtag, "role": "block", "envelope_id": env_id})
        envelopes.append({
            "id": env_id,
            "name": env_name,
            "equipment_tags": eq_tags,
            "boundary_valves": b_tags,
            "closed": True,
        })

    categories = [
        ("Catalyst change-out and reactor internals", 14, "R-202"),
        ("Exchanger bundle work", 22, "E-201B"),
        ("Air cooler", 8, "A-201"),
        ("Heater", 12, "H-201"),
        ("Columns and vessels", 24, "C-201"),
        ("Rotating equipment", 20, "K-201"),
        ("Relief valves", 28, "D-202"),
        ("Valve overhauls", 30, "R-201"),
        ("Thickness, CUI and piping inspection", 26, "E-201A"),
        ("Instruments and analyzers", 10, "D-202"),
        ("Capital tie-in", 4, "E-201A"),
        ("General prep", 2, "none"),
    ]
    diff_classes = (
        ["Clean tag"] * 80
        + ["Tag variant"] * 60
        + ["Known alias"] * 6
        + ["Misspelled or shorthand description"] * 12
        + ["Sibling names"] * 14
        + ["Process context"] * 8
        + ["Wrong unit or retired"] * 4
        + ["Area or unit general"] * 14
        + ["Text with instructions in it"] * 2
    )
    work_requests = []
    answer_rows = []
    idx = 0
    for cat_name, count, default_tag in categories:
        for _ in range(count):
            idx += 1
            rid = f"WR-200-{idx:04d}"
            dcls = diff_classes[idx - 1]
            true_tag = "none" if (dcls == "Area or unit general" and idx > 193) else (default_tag if default_tag != "none" else "E-201A")
            work_requests.append({
                "request_id": rid,
                "category": cat_name,
                "equipment_text": true_tag if true_tag != "none" else "Unit 200 general",
                "estimate_hours": 600,
                "estimate_cost_usd": 140000,
            })
            answer_rows.append({
                "request_id": rid,
                "true_tag": true_tag,
                "difficulty_class": dcls,
            })

    data_dir = repo / "data" / "scenario"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "equipment-master.json").write_text(
        json.dumps({
            "major_equipment": [{"tag": t, "sheet": sheet_map[t]} for t in major_tags],
            "valves": valves,
        }, indent=2),
        encoding="utf-8",
    )
    (data_dir / "isolation-envelopes.json").write_text(
        json.dumps({"envelopes": envelopes}, indent=2),
        encoding="utf-8",
    )
    (data_dir / "work-requests.json").write_text(
        json.dumps({"work_requests": work_requests}, indent=2),
        encoding="utf-8",
    )
    (data_dir / "answer-key.json").write_text(
        json.dumps({"rows": answer_rows}, indent=2),
        encoding="utf-8",
    )
    (data_dir / "clusters-and-duplicates.json").write_text(
        json.dumps({
            "duplicate_pairs": [{"request_ids": [f"WR-200-{i:04d}", f"WR-200-{i+1:04d}"]} for i in range(1, 18, 2)],
            "scaffold_clusters": [{"id": f"SCF-{i}", "equipment_tags": ["C-201"]} for i in range(1, 8)],
            "isolation_clusters": [{"id": e["id"], "equipment_tags": e["equipment_tags"]} for e in envelopes],
            "access_clusters": [
                {"id": "ACC-1", "equipment_tags": ["E-201A", "E-201B", "E-201C"]},
                {"id": "ACC-2", "equipment_tags": ["R-201", "R-202"]},
                {"id": "ACC-3", "equipment_tags": ["K-201", "K-202A", "K-202B"]},
            ],
        }, indent=2),
        encoding="utf-8",
    )
    (data_dir / "late-scope.json").write_text(
        json.dumps({
            "scripted_changes": (
                [{"id": f"CR-A{i}", "type": "add", "decision": "approved", "equipment_tag": "E-201B", "hours_delta": 250} for i in range(1, 19)]
                + [{"id": f"CR-D{i}", "type": "delete", "decision": "approved", "equipment_tag": "E-201B", "hours_delta": -100} for i in range(1, 7)]
                + [{"id": f"CR-R{i}", "type": "add", "decision": "rejected", "equipment_tag": "E-201B", "hours_delta": 100} for i in range(1, 6)]
            ),
            "live_walkthrough_add": {
                "id": "CR-LIVE-N3",
                "equipment_tag": "C-201",
                "envelope_id": "ENV-200-06",
                "title": "Add nozzle N3 on C-201",
                "in_late_scope_simulation": False,
            },
        }, indent=2),
        encoding="utf-8",
    )
    return data_dir


def test_check_passes_on_current_repo_in_docs_mode_and_matches_repo_facts():
    res_docs = _run_tg(REPO_ROOT, "--mode", "docs", "check", "--json")
    assert res_docs.returncode == 0, res_docs.stderr + res_docs.stdout
    docs_payload = json.loads(res_docs.stdout)
    assert docs_payload["mode"] == "docs"
    assert docs_payload["errors"] == []

    res = _run_tg(REPO_ROOT, "check", "--json")
    assert res.returncode == 0, res.stderr + res.stdout
    payload = json.loads(res.stdout)
    assert payload["mode"] == "full"
    assert payload["errors"] == []
    assert payload["counts"]["equipment"] == 32
    assert payload["counts"]["sheets"] == 5
    assert payload["counts"]["envelopes"] == 6
    assert payload["counts"]["boundary_valves_target"] == 112
    assert payload["counts"]["boundary_valves"] == 112
    assert payload["counts"]["work_requests_target"] == 200
    assert payload["counts"]["work_requests"] == 200
    assert payload["counts"]["work_request_categories"] == 12
    assert payload["counts"]["decisions"] == 17
    assert payload["counts"]["rules"] >= 20


def test_rebuilt_relate_graph_has_all_five_edge_types():
    queries = [
        ("MATCH (:Equipment)-[r:ON_SHEET]->(:Sheet) RETURN count(r) AS n", 32),
        ("MATCH (:Envelope)-[r:ISOLATES]->(:Equipment) RETURN count(r) AS n", 33),
        ("MATCH (:Envelope)-[r:BOUNDED_BY]->(:Valve) RETURN count(r) AS n", 1),
        ("MATCH (:WorkRequest)-[r:ON]->(:Equipment) RETURN count(r) AS n", 1),
        ("MATCH (:Rule)-[r:DEFINED_BY]->(:Decision) RETURN count(r) AS n", 20),
    ]
    for cypher, min_expected in queries:
        res = _run_tg(REPO_ROOT, "query", cypher, "--json")
        assert res.returncode == 0, (cypher, res.stderr)
        rows = json.loads(res.stdout)["rows"]
        assert rows and rows[0]["n"] >= min_expected, (cypher, rows)

    # Split-boundary pumps P-201A and P-201B carry suction/discharge edges across ENV-200-01 and ENV-200-02
    res = _run_tg(
        REPO_ROOT,
        "query",
        "MATCH (env:Envelope)-[r:ISOLATES]->(e:Equipment {tag: 'P-201A'}) RETURN env.id AS env, r.boundary_side AS side ORDER BY env.id",
        "--json",
    )
    assert res.returncode == 0, res.stderr
    rows = json.loads(res.stdout)["rows"]
    assert rows == [
        {"env": "ENV-200-01", "side": "suction"},
        {"env": "ENV-200-02", "side": "discharge"},
    ]


def test_impact_traverses_connected_elements():
    res = _run_tg(REPO_ROOT, "impact", "C-201", "--json")
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    assert payload["target"] == "C-201"
    assert "200-PID-005" in payload["sheets"]
    assert "ENV-200-06" in payload["envelopes"]
    assert payload["planted_problems"]


def test_twin_graph_never_mutates_repo(tmp_path: Path):
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import tree_guard

    repo = _copy_doc_repo(tmp_path)
    before = tree_guard.snapshot(repo)
    assert _run_tg(repo, "check", "--json").returncode == 0
    assert _run_tg(repo, "impact", "E-201B", "--json").returncode == 0
    after = tree_guard.snapshot(repo)
    assert tree_guard.diff_snapshots(before, after) == []


def test_detects_equipment_on_no_sheet(tmp_path: Path):
    repo = _copy_doc_repo(tmp_path)
    spec = repo / "docs" / "scenario-spec.md"
    text = spec.read_text(encoding="utf-8")
    broken = text.replace(", E-204 |", " |", 1)
    assert broken != text
    spec.write_text(broken, encoding="utf-8")

    res = _run_tg(repo, "check", "--json")
    assert res.returncode != 0
    payload = json.loads(res.stdout)
    assert any("E-204" in e and "sheet" in e.lower() for e in payload["errors"])


def test_detects_process_equipment_in_no_envelope_while_kt201_exempt(tmp_path: Path):
    repo = _copy_doc_repo(tmp_path)
    spec = repo / "docs" / "scenario-spec.md"
    text = spec.read_text(encoding="utf-8")
    broken = text.replace("| ENV-200-03 Recycle gas | D-204, C-202, K-201 |", "| ENV-200-03 Recycle gas | D-204, K-201 |", 1)
    assert broken != text
    spec.write_text(broken, encoding="utf-8")

    res = _run_tg(repo, "check", "--json")
    assert res.returncode != 0
    payload = json.loads(res.stdout)
    assert any("C-202" in e and "envelope" in e.lower() for e in payload["errors"])
    assert not any("KT-201" in e for e in payload["errors"])

    # Adversarial probe: adding the exemption prose phrase for a process vessel must NOT exempt it
    bypass = broken.replace(
        "hydrocarbon isolation envelopes.",
        "hydrocarbon isolation envelopes. C-202 is the amine scrubber and stays outside the hydrocarbon isolation envelopes.",
        1,
    )
    spec.write_text(bypass, encoding="utf-8")
    res_bypass = _run_tg(repo, "check", "--json")
    assert res_bypass.returncode != 0
    errs_bypass = json.loads(res_bypass.stdout)["errors"]
    assert any("C-202" in e and "exemption" in e.lower() for e in errs_bypass)


def test_detects_empty_envelope(tmp_path: Path):
    repo = _copy_doc_repo(tmp_path)
    spec = repo / "docs" / "scenario-spec.md"
    text = spec.read_text(encoding="utf-8")
    broken = text.replace("| ENV-200-04 Makeup gas | D-206, K-202A/B | 12 |", "| ENV-200-04 Makeup gas |  | 12 |", 1)
    assert broken != text
    spec.write_text(broken, encoding="utf-8")

    res = _run_tg(repo, "check", "--json")
    assert res.returncode != 0
    payload = json.loads(res.stdout)
    assert any("ENV-200-04" in e and "isolates nothing" in e.lower() for e in payload["errors"])


def test_detects_rule_without_decision(tmp_path: Path):
    repo = _copy_doc_repo(tmp_path)
    ver = repo / "docs" / "verification.md"
    text = ver.read_text(encoding="utf-8")
    target = "- **Gate.**"
    assert target in text
    ver.write_text(
        text.replace(target, "- **Orphan rule.** A synthetic check with no backing decision.\n" + target, 1),
        encoding="utf-8",
    )

    res = _run_tg(repo, "check", "--json")
    assert res.returncode != 0
    payload = json.loads(res.stdout)
    assert any("Orphan_rule" in e and "decision" in e.lower() for e in payload["errors"])

    # Adversarial probe: top-level and deeply indented bullets in section 2 must also be parsed and checked
    sec2_target = "- Plant\n"
    assert sec2_target in text
    ver.write_text(
        text.replace(
            sec2_target,
            "- Every twin sync is one transaction with no decision link.\n"
            "    - Four-space orphan rule with no decision link.\n"
            + sec2_target,
            1,
        ),
        encoding="utf-8",
    )
    res_sec2 = _run_tg(repo, "check", "--json")
    assert res_sec2.returncode != 0
    sec2_errors = json.loads(res_sec2.stdout)["errors"]
    assert any("one transaction" in e for e in sec2_errors)
    assert any("Four-space orphan rule" in e for e in sec2_errors)


def test_detects_spike_sheet_title_clash_and_neo4j_snapshot_mismatch(tmp_path: Path):
    repo = _copy_doc_repo(tmp_path)
    exp = repo / "spikes" / "dexpi-sheet" / "expected.py"
    text = exp.read_text(encoding="utf-8")
    exp.write_text(text.replace('TITLE = "Reaction"', 'TITLE = "Hydrotreating"', 1), encoding="utf-8")
    res = _run_tg(repo, "check", "--json")
    assert res.returncode != 0
    payload = json.loads(res.stdout)
    assert any("Reaction" in c["details"] and "Hydrotreating" in c["details"] for c in payload["clashes"])

    # Restore expected.py and verify --neo4j-snapshot catches missing equipment / envelope
    exp.write_text(text, encoding="utf-8")
    snap = tmp_path / "neo4j_snap.json"
    snap.write_text(
        json.dumps({"equipment_tags": ["E-201A"], "envelope_ids": ["ENV-200-01"]}),
        encoding="utf-8",
    )
    res_neo = _run_tg(repo, "check", "--neo4j-snapshot", str(snap), "--json")
    assert res_neo.returncode != 0
    errs = json.loads(res_neo.stdout)["errors"]
    assert any("neo4j twin missing equipment" in e for e in errs)
    assert any("neo4j twin missing envelope" in e for e in errs)


def test_detects_naming_clash_and_records_both_names(tmp_path: Path):
    repo = _copy_doc_repo(tmp_path)
    _seed_synthetic_data_scenario(repo)
    # Introduce a naming/sheet clash: put E-201B on 200-PID-003 in generated master vs 200-PID-002 in spec
    master_path = repo / "data" / "scenario" / "equipment-master.json"
    master = json.loads(master_path.read_text(encoding="utf-8"))
    for eq in master["major_equipment"]:
        if eq["tag"] == "E-201B":
            eq["sheet"] = "200-PID-003"
            eq["name_in_source"] = "E-201B-ALT"
    master_path.write_text(json.dumps(master, indent=2), encoding="utf-8")

    res = _run_tg(repo, "check", "--json")
    assert res.returncode != 0
    payload = json.loads(res.stdout)
    assert any("E-201B" in c["details"] or c["entity"] == "E-201B" for c in payload["clashes"])
    assert any("200-PID-002" in c["details"] and "200-PID-003" in c["details"] for c in payload["clashes"])


def test_full_mode_passes_clean_data_and_catches_valve_wr_category_and_problem_defects(tmp_path: Path):
    repo = _copy_doc_repo(tmp_path)
    data_dir = _seed_synthetic_data_scenario(repo)

    # Clean full mode passes
    clean_res = _run_tg(repo, "check", "--json")
    assert clean_res.returncode == 0, clean_res.stderr + clean_res.stdout
    clean_payload = json.loads(clean_res.stdout)
    assert clean_payload["mode"] == "full"
    assert clean_payload["errors"] == []
    assert clean_payload["counts"]["boundary_valves"] == 112
    assert clean_payload["counts"]["work_requests"] == 200

    # 1. Orphan block valve in no envelope
    master_path = data_dir / "equipment-master.json"
    master = json.loads(master_path.read_text(encoding="utf-8"))
    master["valves"].append({"tag": "HV-2999", "role": "block", "envelope_id": None})
    master_path.write_text(json.dumps(master, indent=2), encoding="utf-8")
    r_valve = _run_tg(repo, "check", "--json")
    assert r_valve.returncode != 0
    assert any("HV-2999" in e and "envelope" in e.lower() for e in json.loads(r_valve.stdout)["errors"])
    master["valves"].pop()
    master_path.write_text(json.dumps(master, indent=2), encoding="utf-8")

    # 2. Work request on nonexistent equipment + unknown difficulty class
    ak_path = data_dir / "answer-key.json"
    ak = json.loads(ak_path.read_text(encoding="utf-8"))
    orig_row = dict(ak["rows"][0])
    ak["rows"][0]["true_tag"] = "E-999Z"
    ak["rows"][0]["difficulty_class"] = "Invented class"
    ak_path.write_text(json.dumps(ak, indent=2), encoding="utf-8")
    r_wr = _run_tg(repo, "check", "--json")
    assert r_wr.returncode != 0
    wr_errors = json.loads(r_wr.stdout)["errors"]
    assert any("E-999Z" in e for e in wr_errors)
    assert any("Invented class" in e for e in wr_errors)
    ak["rows"][0] = orig_row
    ak_path.write_text(json.dumps(ak, indent=2), encoding="utf-8")

    # 3. Unreachable planted problem (remove C-201 N3 live add)
    ls_path = data_dir / "late-scope.json"
    ls = json.loads(ls_path.read_text(encoding="utf-8"))
    ls["live_walkthrough_add"] = None
    ls_path.write_text(json.dumps(ls, indent=2), encoding="utf-8")
    r_pp = _run_tg(repo, "check", "--json")
    assert r_pp.returncode != 0
    assert any("nozzle" in e.lower() or "c-201" in e.lower() for e in json.loads(r_pp.stdout)["errors"])

    # Restore late-scope and test shared boundary valve between two envelopes passes, while compensating swap fails
    ls["live_walkthrough_add"] = {
        "id": "CR-LIVE-N3",
        "equipment_tag": "C-201",
        "envelope_id": "ENV-200-06",
        "title": "Add nozzle N3 on C-201",
        "in_late_scope_simulation": False,
    }
    ls_path.write_text(json.dumps(ls, indent=2), encoding="utf-8")

    env_path = data_dir / "isolation-envelopes.json"
    env_doc = json.loads(env_path.read_text(encoding="utf-8"))
    shared_v = env_doc["envelopes"][4]["boundary_valves"][0]  # ENV-200-05 valve
    replaced_v = env_doc["envelopes"][5]["boundary_valves"][0]  # ENV-200-06 valve
    env_doc["envelopes"][5]["boundary_valves"][0] = shared_v
    # Remove the replaced valve from master so it is not an orphan block valve
    master = json.loads(master_path.read_text(encoding="utf-8"))
    master["valves"] = [v for v in master["valves"] if v["tag"] != replaced_v]
    master_path.write_text(json.dumps(master, indent=2), encoding="utf-8")
    env_path.write_text(json.dumps(env_doc, indent=2), encoding="utf-8")

    r_shared = _run_tg(repo, "check", "--json")
    assert r_shared.returncode == 0, r_shared.stdout + r_shared.stderr

    # Compensating per-envelope swap (move one valve from ENV-200-06 to ENV-200-05: sum stays 112, per-envelope breaks)
    moved_v = env_doc["envelopes"][5]["boundary_valves"].pop()
    env_doc["envelopes"][4]["boundary_valves"].append(moved_v)
    env_path.write_text(json.dumps(env_doc, indent=2), encoding="utf-8")
    r_swap = _run_tg(repo, "check", "--json")
    assert r_swap.returncode != 0
    swap_errs = json.loads(r_swap.stdout)["errors"]
    assert any("ENV-200-05" in e and "11" in e for e in swap_errs)
    assert any("ENV-200-06" in e and "21" in e for e in swap_errs)
