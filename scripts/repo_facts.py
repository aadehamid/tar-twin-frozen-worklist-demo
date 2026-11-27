#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

EXCLUDED_DIRS = frozenset({".git", ".venv", "node_modules", "vendor", "__pycache__"})
DECISION_HEADING_RE = re.compile(r"^##\s+(D(\d+))\.\s+(.+?)\s*$")
SUPERSEDED_RE = re.compile(r"\bSuperseded by D\d+\b")
TARGET_RE = re.compile(r"\(target:\s*(\d+)\b", re.IGNORECASE)
AGENTS_DECISION_RANGE_RE = re.compile(r"\bD(\d+)\s+to\s+D(\d+)\b")
SPIKE_LINK_RE = re.compile(r"\bspikes/([a-z0-9-]+)\.md\b")

EXPECTED_BOUNDARY_VALVES = 112
EXPECTED_WORK_REQUEST_CATEGORIES = 12
EXPECTED_DIFFICULTY_CLASSES = 9


def _clean_git_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git_head_short(repo: Path) -> str:
    res = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
        env=_clean_git_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode == 0:
        return res.stdout.strip()
    return "unknown"


def _section_lines(text: str, heading_prefix: str) -> tuple[str, list[str]]:
    lines = text.splitlines()
    start_idx: int | None = None
    heading_line = ""
    level = 0
    for idx, line in enumerate(lines):
        if line.startswith(heading_prefix):
            start_idx = idx
            heading_line = line
            level = len(line) - len(line.lstrip("#"))
            break
    if start_idx is None:
        raise ValueError(f"missing section {heading_prefix!r}")

    body: list[str] = []
    for line in lines[start_idx + 1 :]:
        if line.startswith("#"):
            cur_level = len(line) - len(line.lstrip("#"))
            if cur_level <= level:
                break
        body.append(line)
    return heading_line, body


def _parse_first_table(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    in_table = False
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            in_table = True
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            rows.append(cells)
        elif in_table:
            break
    if len(rows) < 3:
        return []
    return rows[2:]


def _parse_target(heading: str) -> int | None:
    match = TARGET_RE.search(heading)
    return int(match.group(1)) if match else None


def _parse_decisions(repo: Path) -> dict[str, object]:
    text = (repo / "docs" / "decisions.md").read_text(encoding="utf-8")
    ids: list[str] = []
    nums: list[int] = []
    titles: dict[str, str] = {}
    superseded: list[str] = []

    current_id: str | None = None
    body_lines: list[str] = []

    def _flush() -> None:
        if current_id is not None and SUPERSEDED_RE.search("\n".join(body_lines)):
            superseded.append(current_id)

    for line in text.splitlines():
        m = DECISION_HEADING_RE.match(line)
        if m:
            _flush()
            current_id = m.group(1)
            ids.append(current_id)
            nums.append(int(m.group(2)))
            titles[current_id] = m.group(3)
            body_lines = []
        elif current_id is not None:
            body_lines.append(line)
    _flush()

    return {
        "count": len(ids),
        "ids": ids,
        "numbers": nums,
        "titles": titles,
        "superseded": superseded,
    }


def _parse_spikes(repo: Path) -> dict[str, object]:
    spike_docs_dir = repo / "docs" / "spikes"
    spikes_dir = repo / "spikes"

    doc_slugs = sorted(p.stem for p in spike_docs_dir.glob("*.md")) if spike_docs_dir.is_dir() else []
    dir_slugs = (
        sorted(
            p.name
            for p in spikes_dir.iterdir()
            if p.is_dir() and not p.name.startswith(".") and p.name != "__pycache__"
        )
        if spikes_dir.is_dir()
        else []
    )
    return {
        "count": len(doc_slugs),
        "slugs": doc_slugs,
        "doc_slugs": doc_slugs,
        "dir_slugs": dir_slugs,
    }


def _parse_scenario(repo: Path) -> dict[str, object]:
    text = (repo / "docs" / "scenario-spec.md").read_text(encoding="utf-8")

    eq_heading, eq_body = _section_lines(text, "### 2.2 Major equipment")
    eq_rows = _parse_first_table(eq_body)
    major_tags: list[str] = []
    for row in eq_rows:
        if len(row) >= 2:
            for item in row[1].split(","):
                tag = item.strip().strip("`")
                if tag:
                    major_tags.append(tag)

    pid_heading, pid_body = _section_lines(text, "### 2.3 P&ID sheets")
    pid_rows = _parse_first_table(pid_body)

    env_heading, env_body = _section_lines(text, "### 2.4 Isolation envelopes")
    env_rows = _parse_first_table(env_body)
    boundary_valve_total = sum(int(row[2]) for row in env_rows if len(row) >= 3)

    wr_heading, wr_body = _section_lines(text, "### 4.1 Work request mix")
    wr_rows = _parse_first_table(wr_body)
    wr_total = sum(int(row[1]) for row in wr_rows if len(row) >= 2)

    return {
        "major_equipment_count": len(major_tags),
        "major_equipment_target": _parse_target(eq_heading),
        "major_equipment_tags": major_tags,
        "pid_sheet_count": len(pid_rows),
        "pid_sheet_target": _parse_target(pid_heading),
        "isolation_envelope_count": len(env_rows),
        "isolation_envelope_target": _parse_target(env_heading),
        "boundary_valve_total": boundary_valve_total,
        "work_request_category_count": len(wr_rows),
        "work_request_total": wr_total,
        "work_request_target": _parse_target(wr_heading),
    }


def _parse_matching(repo: Path) -> dict[str, object]:
    text = (repo / "docs" / "matching-showcase.md").read_text(encoding="utf-8")
    _heading, body = _section_lines(text, "## 3. The cases the scenario plants")
    rows = _parse_first_table(body)
    class_counts = [(row[0], int(row[1])) for row in rows if len(row) >= 2]
    return {
        "difficulty_class_count": len(class_counts),
        "difficulty_class_total": sum(count for _, count in class_counts),
        "classes": {name: count for name, count in class_counts},
    }


def collect_facts(repo: Path) -> dict[str, object]:
    repo_root = repo.resolve()
    decisions = _parse_decisions(repo_root)
    spikes = _parse_spikes(repo_root)
    scenario = _parse_scenario(repo_root)
    matching = _parse_matching(repo_root)
    sources = [
        "AGENTS.md",
        "docs/decisions.md",
        "docs/scenario-spec.md",
        "docs/matching-showcase.md",
        *[f"docs/spikes/{slug}.md" for slug in spikes["doc_slugs"]],
    ]
    return {
        "commit": _git_head_short(repo_root),
        "sources": sources,
        "decisions": decisions,
        "spikes": spikes,
        "scenario": scenario,
        "matching": matching,
    }


def check_consistency(repo: Path) -> list[str]:
    repo_root = repo.resolve()
    facts = collect_facts(repo_root)
    errors: list[str] = []

    decisions = facts["decisions"]
    nums = decisions["numbers"]
    expected_nums = list(range(1, len(nums) + 1))
    if nums != expected_nums:
        errors.append(
            f"docs/decisions.md: decision numbers are {nums}, expected contiguous 1..{len(nums)}"
        )

    agents_path = repo_root / "AGENTS.md"
    if agents_path.is_file():
        agents_text = agents_path.read_text(encoding="utf-8")
        m = AGENTS_DECISION_RANGE_RE.search(agents_text)
        if m and nums:
            start_d, end_d = int(m.group(1)), int(m.group(2))
            if start_d != nums[0] or end_d != nums[-1]:
                errors.append(
                    f"AGENTS.md: states D{start_d} to D{end_d}, but docs/decisions.md has D{nums[0]} to D{nums[-1]}"
                )

    spikes = facts["spikes"]
    doc_set = set(spikes["doc_slugs"])
    dir_set = set(spikes["dir_slugs"])
    decisions_text = (repo_root / "docs" / "decisions.md").read_text(encoding="utf-8")
    cited_spikes = set(SPIKE_LINK_RE.findall(decisions_text))
    for missing_doc in sorted(dir_set - doc_set):
        errors.append(f"spikes/{missing_doc}: missing write-up docs/spikes/{missing_doc}.md")
    for missing_dir in sorted(doc_set - dir_set):
        errors.append(f"docs/spikes/{missing_dir}.md: missing folder spikes/{missing_dir}/")
    for missing_cited in sorted(cited_spikes - (doc_set & dir_set)):
        errors.append(
            f"docs/decisions.md cites spikes/{missing_cited}.md, which is missing from docs/spikes/ or spikes/"
        )

    scenario = facts["scenario"]
    for label, actual_key, target_key in (
        ("major equipment", "major_equipment_count", "major_equipment_target"),
        ("P&ID sheets", "pid_sheet_count", "pid_sheet_target"),
        ("isolation envelopes", "isolation_envelope_count", "isolation_envelope_target"),
        ("work requests", "work_request_total", "work_request_target"),
    ):
        actual = scenario[actual_key]
        target = scenario[target_key]
        if target is None:
            errors.append(f"docs/scenario-spec.md: missing target for {label}")
        elif actual != target:
            errors.append(
                f"docs/scenario-spec.md: {label} table counts {actual}, heading target is {target}"
            )

    if scenario["boundary_valve_total"] != EXPECTED_BOUNDARY_VALVES:
        errors.append(
            f"docs/scenario-spec.md: isolation envelope boundary valves sum to "
            f"{scenario['boundary_valve_total']}, expected {EXPECTED_BOUNDARY_VALVES}"
        )
    if scenario["work_request_category_count"] != EXPECTED_WORK_REQUEST_CATEGORIES:
        errors.append(
            f"docs/scenario-spec.md: work request mix has "
            f"{scenario['work_request_category_count']} categories, expected {EXPECTED_WORK_REQUEST_CATEGORIES}"
        )

    matching = facts["matching"]
    if matching["difficulty_class_count"] != EXPECTED_DIFFICULTY_CLASSES:
        errors.append(
            f"docs/matching-showcase.md: difficulty classes table has "
            f"{matching['difficulty_class_count']} classes, expected {EXPECTED_DIFFICULTY_CLASSES}"
        )
    if matching["difficulty_class_total"] != scenario["work_request_total"]:
        errors.append(
            "docs/matching-showcase.md: difficulty classes sum to "
            f"{matching['difficulty_class_total']}, but docs/scenario-spec.md sums to "
            f"{scenario['work_request_total']}"
        )

    return errors


def _iter_repo_files(repo_root: Path) -> list[Path]:
    res = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        env=_clean_git_env(),
        capture_output=True,
        check=False,
    )
    candidates: list[Path] = []
    if res.returncode == 0:
        seen: set[Path] = set()
        for raw in res.stdout.split(b"\x00"):
            if not raw:
                continue
            rel = Path(os.fsdecode(raw))
            if any(part in EXCLUDED_DIRS for part in rel.parts[:-1]):
                continue
            full = repo_root / rel
            if full.is_symlink() or not full.is_file() or full in seen:
                continue
            seen.add(full)
            candidates.append(full)
        return sorted(candidates)

    for p in repo_root.rglob("*"):
        if p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(repo_root)
        if any(part in EXCLUDED_DIRS for part in rel.parts[:-1]):
            continue
        candidates.append(p)
    return sorted(candidates)


def find_text(repo: Path, query: str, case_sensitive: bool = False) -> dict[str, object]:
    repo_root = repo.resolve()
    parts = query.strip().split()
    if not parts:
        raise ValueError("query must not be empty")

    pattern = r"\s+".join(re.escape(part) for part in parts)
    flags = 0 if case_sensitive else re.IGNORECASE
    regex = re.compile(pattern, flags)

    matches: list[dict[str, object]] = []
    for path in _iter_repo_files(repo_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(repo_root).as_posix()
        for m in regex.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            snippet = " ".join(m.group(0).split())
            matches.append({"path": rel, "line": line, "match": snippet})

    return {
        "commit": _git_head_short(repo_root),
        "query": query,
        "count": len(matches),
        "matches": matches,
    }


def _print_summary(facts: dict[str, object]) -> None:
    d = facts["decisions"]
    s = facts["spikes"]
    sc = facts["scenario"]
    mt = facts["matching"]
    print(f"Commit: {facts['commit']}")
    print("Sources: " + ", ".join(facts["sources"]))
    d_range = f"{d['ids'][0]} to {d['ids'][-1]}" if d["ids"] else "none"
    print(
        f"Decisions: {d['count']} ({d_range}; "
        f"superseded: {', '.join(d['superseded']) or 'none'})"
    )
    print(f"Spikes: {s['count']} ({', '.join(s['slugs'])})")
    print(
        f"Scenario targets: {sc['major_equipment_count']} major equipment, "
        f"{sc['pid_sheet_count']} P&ID sheets, "
        f"{sc['isolation_envelope_count']} isolation envelopes "
        f"({sc['boundary_valve_total']} boundary valves), "
        f"{sc['work_request_total']} work requests across {sc['work_request_category_count']} categories"
    )
    print(
        f"Matching classes: {mt['difficulty_class_count']} classes summing to "
        f"{mt['difficulty_class_total']} requests"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Shared deterministic facts and search tool for the repository.")
    parser.add_argument("--repo", type=Path, default=Path("."), help="Repository root path")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sum = sub.add_parser("summary", help="Print repository counts and sources")
    p_sum.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output")

    sub.add_parser("check", help="Check consistency across repository documents")

    p_find = sub.add_parser("find", help="Search repository files, matching phrases split across lines")
    p_find.add_argument("query", help="Phrase to search for")
    p_find.add_argument("--case-sensitive", action="store_true", help="Match case exactly")
    p_find.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output")

    args = parser.parse_args(argv)

    if args.cmd == "summary":
        facts = collect_facts(args.repo)
        if args.as_json:
            print(json.dumps(facts, indent=2))
        else:
            _print_summary(facts)
        return 0

    if args.cmd == "check":
        errors = check_consistency(args.repo)
        if errors:
            for err in errors:
                print(err, file=sys.stderr)
            return 1
        return 0

    if args.cmd == "find":
        try:
            result = find_text(args.repo, args.query, case_sensitive=args.case_sensitive)
        except ValueError as exc:
            print(f"repo_facts: {exc}", file=sys.stderr)
            return 2
        if args.as_json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Commit: {result['commit']} ({result['count']} matches)")
            for item in result["matches"]:
                print(f"{item['path']}:{item['line']}: {item['match']}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
