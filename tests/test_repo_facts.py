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
REPO_FACTS = SCRIPTS_DIR / "repo_facts.py"


def _clean_git_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _run_facts(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_FACTS), "--repo", str(repo), *args],
        env=_clean_git_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def _copy_minimal_repo(tmp_path: Path) -> Path:
    dest = tmp_path / "repo"
    dest.mkdir()
    for rel in (
        "AGENTS.md",
        "README.md",
        "docs/decisions.md",
        "docs/scenario-spec.md",
        "docs/matching-showcase.md",
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
        results = REPO_ROOT / "spikes" / spike_doc.stem / "results.json"
        if results.exists():
            shutil.copy2(results, spike_dir / "results.json")

    subprocess.run(["git", "-C", str(dest), "init", "-b", "main"], env=_clean_git_env(), check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "config", "user.name", "Test User"], env=_clean_git_env(), check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "config", "user.email", "test@example.com"], env=_clean_git_env(), check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "add", "."], env=_clean_git_env(), check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "commit", "-m", "Init"], env=_clean_git_env(), check=True, capture_output=True)
    return dest


def test_summary_pins_current_repo_figures():
    res = _run_facts(REPO_ROOT, "summary", "--json")
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)

    assert data["commit"]
    assert set(data["sources"]) >= {
        "AGENTS.md",
        "docs/decisions.md",
        "docs/scenario-spec.md",
        "docs/matching-showcase.md",
    }
    assert data["decisions"]["count"] == 16
    assert data["decisions"]["ids"][0] == "D1"
    assert data["decisions"]["ids"][-1] == "D16"
    assert "D7" in data["decisions"]["superseded"]

    assert data["spikes"]["count"] == 8
    assert data["spikes"]["slugs"] == [
        "bend-cost",
        "decider-matcher",
        "dexpi-sheet",
        "exe-hosting",
        "quint-worklist",
        "relate-wasm",
        "shacl-n10s",
        "template-no-docker",
    ]

    assert data["scenario"]["major_equipment_count"] == 32
    assert data["scenario"]["major_equipment_target"] == 32
    assert data["scenario"]["pid_sheet_count"] == 5
    assert data["scenario"]["pid_sheet_target"] == 5
    assert data["scenario"]["isolation_envelope_count"] == 6
    assert data["scenario"]["isolation_envelope_target"] == 6
    assert data["scenario"]["boundary_valve_total"] == 112
    assert data["scenario"]["work_request_category_count"] == 12
    assert data["scenario"]["work_request_total"] == 200
    assert data["scenario"]["work_request_target"] == 200

    assert data["matching"]["difficulty_class_count"] == 9
    assert data["matching"]["difficulty_class_total"] == 200


def test_summary_human_output_prints_commit_and_sources():
    res = _run_facts(REPO_ROOT, "summary")
    assert res.returncode == 0, res.stderr
    assert "commit:" in res.stdout.lower()
    assert "docs/decisions.md" in res.stdout
    assert "docs/scenario-spec.md" in res.stdout
    assert "32" in res.stdout
    assert "200" in res.stdout


def test_check_passes_on_current_repo():
    res = _run_facts(REPO_ROOT, "check")
    assert res.returncode == 0, res.stderr


def test_check_survives_reformatting_whitespace_and_citations(tmp_path: Path):
    repo = _copy_minimal_repo(tmp_path)
    spec_path = repo / "docs" / "scenario-spec.md"
    text = spec_path.read_text(encoding="utf-8")
    # Reformat table padding and wrap prose lines without altering figures
    reformatted = text.replace("| FL-201A, FL-201B |", "|  FL-201A ,   FL-201B  |")
    reformatted = reformatted.replace("| 14 |", "|   14   |")
    spec_path.write_text(reformatted, encoding="utf-8")

    res_before = _run_facts(REPO_ROOT, "summary", "--json")
    res_after = _run_facts(repo, "summary", "--json")
    assert res_after.returncode == 0, res_after.stderr
    assert json.loads(res_after.stdout)["scenario"] == json.loads(res_before.stdout)["scenario"]
    assert _run_facts(repo, "check").returncode == 0


def test_check_fails_when_work_request_counts_drift(tmp_path: Path):
    repo = _copy_minimal_repo(tmp_path)
    spec_path = repo / "docs" / "scenario-spec.md"
    text = spec_path.read_text(encoding="utf-8")
    broken = text.replace("| General prep | 2 |", "| General prep | 3 |", 1)
    assert broken != text
    spec_path.write_text(broken, encoding="utf-8")

    res = _run_facts(repo, "check")
    assert res.returncode != 0
    assert "201" in (res.stdout + res.stderr)


def test_check_fails_when_agents_decision_range_drifts(tmp_path: Path):
    repo = _copy_minimal_repo(tmp_path)
    agents_path = repo / "AGENTS.md"
    text = agents_path.read_text(encoding="utf-8")
    broken = text.replace("D1 to D16", "D1 to D15", 1)
    assert broken != text
    agents_path.write_text(broken, encoding="utf-8")

    res = _run_facts(repo, "check")
    assert res.returncode != 0
    assert "D16" in (res.stdout + res.stderr)


def test_check_fails_when_spike_dir_missing_writeup(tmp_path: Path):
    repo = _copy_minimal_repo(tmp_path)
    (repo / "spikes" / "orphan-spike").mkdir(parents=True)
    res = _run_facts(repo, "check")
    assert res.returncode != 0
    assert "orphan-spike" in (res.stdout + res.stderr)


def test_find_matches_phrase_split_across_lines(tmp_path: Path):
    repo = _copy_minimal_repo(tmp_path)
    note = repo / "docs" / "wrapped.md"
    note.write_text("Line one.\nThe twin reads\nIMPACT   Web scope\nwithout writing.\n", encoding="utf-8")

    res = _run_facts(repo, "find", "twin reads IMPACT Web", "--json")
    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    hits = [m for m in payload["matches"] if m["path"] == "docs/wrapped.md"]
    assert len(hits) == 1
    assert hits[0]["line"] == 2


def test_repo_facts_never_mutates_repo(tmp_path: Path):
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import tree_guard

    repo = _copy_minimal_repo(tmp_path)
    before = tree_guard.snapshot(repo)
    assert _run_facts(repo, "summary", "--json").returncode == 0
    assert _run_facts(repo, "check").returncode == 0
    assert _run_facts(repo, "find", "Unit 200", "--json").returncode == 0
    after = tree_guard.snapshot(repo)
    assert tree_guard.diff_snapshots(before, after) == []
