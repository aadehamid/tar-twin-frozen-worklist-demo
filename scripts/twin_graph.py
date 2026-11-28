#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import repo_facts  # noqa: E402

MAJOR_TAG_RE = re.compile(r"\b(?:FL|D|P|R|E|H|A|C|K|KT)-2\d{2}(?:[A-Z](?:/[A-Z])*)?\b")
SLASH_TAG_RE = re.compile(r"^([A-Z]+-\d+)([A-Z](?:/[A-Z])+)$")
ENV_ID_RE = re.compile(r"\b(ENV-200-\d{2})\b")
DECISION_REF_RE = re.compile(r"\b(D\d+)\b")
EXEMPT_DRIVER_RE = re.compile(
    r"`?((?:FL|D|P|R|E|H|A|C|K|KT)-2\d{2}[A-Z]?)`?[^.\n]*\boutside the hydrocarbon isolation envelopes\b",
    re.IGNORECASE,
)

LOAD_CYPHER = """
UNWIND $payload.sheets AS s
MERGE (sh:Sheet {id: s.id})
SET sh.title = s.title;

UNWIND $payload.equipment AS e
MERGE (eq:Equipment {tag: e.tag})
SET eq.area = e.area,
    eq.description = e.description,
    eq.in_master = e.in_master,
    eq.non_process_driver = e.non_process_driver,
    eq.sources = e.sources,
    eq.aliases = e.aliases;

UNWIND $payload.on_sheet AS r
MATCH (eq:Equipment {tag: r.tag}), (sh:Sheet {id: r.sheet_id})
MERGE (eq)-[:ON_SHEET]->(sh);

UNWIND $payload.envelopes AS env
MERGE (en:Envelope {id: env.id})
SET en.name = env.name,
    en.target_boundary_valves = env.target_boundary_valves;

UNWIND $payload.isolates AS iso
MATCH (en:Envelope {id: iso.envelope_id}), (eq:Equipment {tag: iso.tag})
MERGE (en)-[rel:ISOLATES {boundary_side: iso.boundary_side}]->(eq);

UNWIND $payload.valves AS v
MERGE (va:Valve {tag: v.tag})
SET va.role = v.role,
    va.source = v.source;

UNWIND $payload.bounded_by AS b
MATCH (en:Envelope {id: b.envelope_id}), (va:Valve {tag: b.tag})
MERGE (en)-[:BOUNDED_BY]->(va);

UNWIND $payload.work_requests AS wr
MERGE (w:WorkRequest {id: wr.id})
SET w.category = wr.category,
    w.difficulty_class = wr.difficulty_class,
    w.equipment_ref = wr.equipment_ref,
    w.source = wr.source,
    w.is_example = wr.is_example;

UNWIND $payload.work_request_on AS wo
MATCH (w:WorkRequest {id: wo.request_id}), (eq:Equipment {tag: wo.tag})
MERGE (w)-[:ON]->(eq);

UNWIND $payload.decisions AS d
MERGE (dec:Decision {id: d.id})
SET dec.title = d.title,
    dec.superseded = d.superseded;

UNWIND $payload.rules AS r
MERGE (ru:Rule {id: r.id})
SET ru.layer = r.layer,
    ru.text = r.text,
    ru.source = r.source;

UNWIND $payload.rule_decisions AS rd
MATCH (ru:Rule {id: rd.rule_id}), (dec:Decision {id: rd.decision_id})
MERGE (ru)-[:DEFINED_BY]->(dec);

UNWIND $payload.planted_problems AS pp
MERGE (p:PlantedProblem {id: pp.id})
SET p.name = pp.name,
    p.target_text = pp.target_text;

UNWIND $payload.problem_reaches_equipment AS pe
MATCH (p:PlantedProblem {id: pe.problem_id}), (eq:Equipment {tag: pe.tag})
MERGE (p)-[:REACHES]->(eq);

UNWIND $payload.problem_reaches_envelope AS penv
MATCH (p:PlantedProblem {id: penv.problem_id}), (en:Envelope {id: penv.envelope_id})
MERGE (p)-[:REACHES]->(en);

UNWIND $payload.problem_reaches_wr AS pwr
MATCH (p:PlantedProblem {id: pwr.problem_id}), (w:WorkRequest {id: pwr.request_id})
MERGE (p)-[:REACHES]->(w);

UNWIND $payload.clashes AS c
MERGE (cl:Clash {id: c.id})
SET cl.kind = c.kind,
    cl.entity = c.entity,
    cl.details = c.details;
"""

CHECK_CYPHER = """
MATCH (e:Equipment) WHERE e.in_master = true RETURN 'metric' AS kind, 'equipment' AS k, count(e) AS n;
MATCH (s:Sheet) RETURN 'metric' AS kind, 'sheets' AS k, count(s) AS n;
MATCH (e:Envelope) RETURN 'metric' AS kind, 'envelopes' AS k, count(e) AS n;
MATCH (e:Envelope) RETURN 'metric' AS kind, 'boundary_valves_target' AS k, sum(e.target_boundary_valves) AS n;
MATCH (:Envelope)-[:BOUNDED_BY]->(v:Valve) RETURN 'metric' AS kind, 'boundary_valves' AS k, count(DISTINCT v) AS n;
MATCH (w:WorkRequest) RETURN 'metric' AS kind, 'work_requests' AS k, count(w) AS n;
MATCH (d:Decision) RETURN 'metric' AS kind, 'decisions' AS k, count(d) AS n;
MATCH (r:Rule) RETURN 'metric' AS kind, 'rules' AS k, count(r) AS n;
MATCH (e:Equipment) WHERE NOT (e)-[:ON_SHEET]->(:Sheet) RETURN 'no_sheet' AS kind, e.tag AS val ORDER BY e.tag;
MATCH (e:Equipment) WHERE e.in_master = true AND e.non_process_driver = false AND NOT (:Envelope)-[:ISOLATES]->(e) RETURN 'no_env' AS kind, e.tag AS val ORDER BY e.tag;
MATCH (v:Valve) WHERE v.role = 'block' AND NOT (:Envelope)-[:BOUNDED_BY]->(v) RETURN 'orphan_valve' AS kind, v.tag AS val ORDER BY v.tag;
MATCH (en:Envelope) WHERE NOT (en)-[:ISOLATES]->(:Equipment) RETURN 'empty_env' AS kind, en.id AS val ORDER BY en.id;
MATCH (p:PlantedProblem) WHERE NOT (p)-[:REACHES]->() RETURN 'unreachable_pp' AS kind, p.id AS id, p.name AS name ORDER BY p.id;
MATCH (r:Rule) WHERE NOT (r)-[:DEFINED_BY]->(:Decision) RETURN 'orphan_rule' AS kind, r.id AS id, r.text AS text ORDER BY r.id;
MATCH (c:Clash) RETURN 'clash' AS kind, c.id AS id, c.kind AS ckind, c.entity AS entity, c.details AS details ORDER BY c.id;
MATCH (w:WorkRequest) RETURN 'wr' AS kind, w.id AS id, w.category AS cat, w.difficulty_class AS dcls ORDER BY w.id;
"""

IMPACT_CYPHER = """
MATCH (e:Equipment {tag: $target})-[:ON_SHEET]->(s:Sheet) RETURN 'sheets' AS kind, s.id AS val;
MATCH (en:Envelope)-[:ISOLATES]->(e:Equipment {tag: $target}) RETURN 'envelopes' AS kind, en.id AS val;
MATCH (en:Envelope)-[:BOUNDED_BY]->(v:Valve {tag: $target}) RETURN 'envelopes' AS kind, en.id AS val;
MATCH (en:Envelope {id: $target})-[:ISOLATES]->(e:Equipment) RETURN 'equipment' AS kind, e.tag AS val;
MATCH (e:Equipment)-[:ON_SHEET]->(s:Sheet {id: $target}) RETURN 'equipment' AS kind, e.tag AS val;
MATCH (w:WorkRequest {id: $target})-[:ON]->(e:Equipment) RETURN 'equipment' AS kind, e.tag AS val;
MATCH (en:Envelope {id: $target})-[:BOUNDED_BY]->(v:Valve) RETURN 'valves' AS kind, v.tag AS val;
MATCH (w:WorkRequest)-[:ON]->(e:Equipment {tag: $target}) RETURN 'work_requests' AS kind, w.id AS val;
MATCH (en:Envelope {id: $target})-[:ISOLATES]->(e:Equipment)<-[:ON]-(w:WorkRequest) RETURN 'work_requests' AS kind, w.id AS val;
MATCH (p:PlantedProblem)-[:REACHES]->(e:Equipment {tag: $target}) RETURN 'planted_problems' AS kind, p.name AS val;
MATCH (p:PlantedProblem)-[:REACHES]->(en:Envelope {id: $target}) RETURN 'planted_problems' AS kind, p.name AS val;
MATCH (p:PlantedProblem)-[:REACHES]->(w:WorkRequest {id: $target}) RETURN 'planted_problems' AS kind, p.name AS val;
MATCH (r:Rule)-[:DEFINED_BY]->(d:Decision {id: $target}) RETURN 'rules' AS kind, r.id AS val;
MATCH (r:Rule {id: $target})-[:DEFINED_BY]->(d:Decision) RETURN 'decisions' AS kind, d.id AS val;
"""


def _expand_tag_token(token: str) -> list[str]:
    m = SLASH_TAG_RE.match(token)
    if not m:
        return [token]
    return [m.group(1) + suffix for suffix in m.group(2).split("/")]


def _require_relate() -> None:
    if shutil.which("relate") is None:
        print(
            "twin_graph: relate is not installed. Install it with: curl -sSfL https://relatedb.ai/install.sh | bash",
            file=sys.stderr,
        )
        raise SystemExit(3)


def _run_relate_jsonl(
    db_path: Path,
    cypher: str,
    fetch_params: dict[str, Path] | None = None,
    read_only: bool = False,
) -> list[dict[str, object]]:
    cmd = ["relate", "query", "--database", str(db_path), "--mode", "jsonl", "--max-rows", "0"]
    if read_only:
        cmd.append("--read-only")
    if fetch_params:
        for name, path in fetch_params.items():
            cmd.extend(["--fetch-params", f"{name}={path}"])
    res = subprocess.run(cmd, input=cypher, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"relate query failed (exit {res.returncode}): {res.stderr.strip()}")
    rows: list[dict[str, object]] = []
    for line in res.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, dict) and not ("rows" in obj and "elapsedMs" in obj and len(obj) <= 3):
            rows.append(obj)
    return rows


def _parse_rules(repo: Path) -> list[dict[str, object]]:
    text = (repo / "docs" / "verification.md").read_text(encoding="utf-8")
    rules: list[dict[str, object]] = []
    layer_headings = {
        "## 1. ": "schemas",
        "## 2. ": "engineering",
        "## 3. ": "properties",
        "## 4. ": "quint",
    }
    current_layer = ""
    current_sub = ""
    rule_idx = 0

    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            current_layer = next((v for k, v in layer_headings.items() if line.startswith(k)), "")
            current_sub = ""
            continue
        if not current_layer:
            continue

        if current_layer == "engineering":
            if line in ("- Plant", "- Scope"):
                current_sub = line[2:].strip().lower()
                continue
            if line.startswith("  - ") and current_sub:
                body = line[4:].strip()
                rule_idx += 1
                rules.append({
                    "id": f"RULE-ENG-{rule_idx:02d}",
                    "layer": f"engineering:{current_sub}",
                    "text": body,
                    "decisions": sorted(set(DECISION_REF_RE.findall(body))),
                    "source": "docs/verification.md",
                })
        elif line.startswith("- "):
            body = line[2:].strip()
            rule_idx += 1
            m_name = re.match(r"^\*\*([^*]+?)\.?\*\*", body)
            slug = re.sub(r"[^A-Za-z0-9]+", "_", m_name.group(1)).strip("_") if m_name else f"{rule_idx:02d}"
            rules.append({
                "id": f"RULE-{current_layer.upper()}-{slug}",
                "layer": current_layer,
                "text": body,
                "decisions": sorted(set(DECISION_REF_RE.findall(body))),
                "source": "docs/verification.md",
            })

    return rules


def _parse_spike_sheet_meta(repo: Path) -> tuple[str, str, set[str]] | None:
    expected_py = repo / "spikes" / "dexpi-sheet" / "expected.py"
    if not expected_py.is_file():
        return None
    text = expected_py.read_text(encoding="utf-8")
    m_sheet = re.search(r'^SHEET\s*=\s*"([^"]+)"', text, re.M)
    m_title = re.search(r'^TITLE\s*=\s*"([^"]+)"', text, re.M)
    m_eq = re.search(r"EQUIPMENT\s*=\s*\{(.*?)\}", text, re.S)
    if not (m_sheet and m_title and m_eq):
        return None
    tags = set(re.findall(r'"([A-Z]+-\d+[A-Z]?)":', m_eq.group(1)))
    return m_sheet.group(1), m_title.group(1), tags


def _parse_spike_block_valves(repo: Path) -> list[tuple[str, str]]:
    expected_py = repo / "spikes" / "dexpi-sheet" / "expected.py"
    if not expected_py.is_file():
        return []
    text = expected_py.read_text(encoding="utf-8")
    m = re.search(r"VALVES\s*=\s*\{(.*?)\}", text, re.S)
    if not m:
        return []
    return [
        (tag, "ENV-200-02")
        for tag, cls in re.findall(r'"([A-Z]+-\d+)":\s*"([^"]+)"', m.group(1))
        if cls == "GateValve"
    ]


def extract_model(repo: Path, mode: str = "auto") -> dict[str, object]:
    repo_root = repo.resolve()
    facts = repo_facts.collect_facts(repo_root)
    spec_text = (repo_root / "docs" / "scenario-spec.md").read_text(encoding="utf-8")
    data_dir = repo_root / "data" / "scenario"
    has_data = (data_dir / "equipment-master.json").is_file() and (data_dir / "work-requests.json").is_file()
    effective_mode = ("full" if has_data else "docs") if mode == "auto" else mode

    _eq_h, eq_body = repo_facts._section_lines(spec_text, "### 2.2 Major equipment")
    eq_rows = repo_facts._parse_first_table(eq_body)
    equipment_map: dict[str, dict[str, object]] = {}
    current_area = ""
    for row in eq_rows:
        if len(row) < 3:
            continue
        if row[0]:
            current_area = row[0]
        desc = row[2]
        for raw_tag in row[1].split(","):
            tag = raw_tag.strip().strip("`")
            if not tag:
                continue
            equipment_map[tag] = {
                "tag": tag,
                "area": current_area,
                "description": desc,
                "in_master": True,
                "non_process_driver": False,
                "sources": ["docs/scenario-spec.md#2.2"],
                "aliases": [tag],
            }

    _pid_h, pid_body = repo_facts._section_lines(spec_text, "### 2.3 P&ID sheets")
    pid_rows = repo_facts._parse_first_table(pid_body)
    sheets: list[dict[str, object]] = []
    on_sheet: list[dict[str, str]] = []
    spec_sheet_of: dict[str, str] = {}
    for row in pid_rows:
        if len(row) < 3:
            continue
        sid, title, covers = row[0], row[1], row[2]
        sheets.append({"id": sid, "title": title})
        for tok in MAJOR_TAG_RE.findall(covers):
            for tag in _expand_tag_token(tok):
                if tag not in equipment_map:
                    equipment_map[tag] = {
                        "tag": tag,
                        "area": "",
                        "description": "",
                        "in_master": False,
                        "non_process_driver": False,
                        "sources": ["docs/scenario-spec.md#2.3"],
                        "aliases": [tok],
                    }
                else:
                    if tok != tag and tok not in equipment_map[tag]["aliases"]:
                        equipment_map[tag]["aliases"].append(tok)
                    equipment_map[tag]["sources"].append("docs/scenario-spec.md#2.3")
                on_sheet.append({"tag": tag, "sheet_id": sid})
                spec_sheet_of[tag] = sid

    _env_h, env_body = repo_facts._section_lines(spec_text, "### 2.4 Isolation envelopes")
    env_rows = repo_facts._parse_first_table(env_body)
    exempt_drivers = set(EXEMPT_DRIVER_RE.findall("\n".join(env_body)))
    for tag in exempt_drivers:
        if tag in equipment_map:
            equipment_map[tag]["non_process_driver"] = True

    envelopes: list[dict[str, object]] = []
    isolates: list[dict[str, str]] = []
    spec_env_eq: dict[str, set[str]] = {}
    for row in env_rows:
        if len(row) < 3:
            continue
        env_cell, contains_cell, valve_target_str = row[0], row[1], row[2]
        m_env = ENV_ID_RE.search(env_cell)
        if not m_env:
            continue
        env_id = m_env.group(1)
        env_name = env_cell[m_env.end() :].strip()
        envelopes.append({
            "id": env_id,
            "name": env_name,
            "target_boundary_valves": int(valve_target_str),
        })
        spec_env_eq[env_id] = set()
        for chunk in contains_cell.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            low = chunk.lower()
            side = "suction" if "suction" in low else ("discharge" if "discharge" in low else "full")
            for tok in MAJOR_TAG_RE.findall(chunk):
                for tag in _expand_tag_token(tok):
                    if tag not in equipment_map:
                        equipment_map[tag] = {
                            "tag": tag,
                            "area": "",
                            "description": "",
                            "in_master": False,
                            "non_process_driver": False,
                            "sources": ["docs/scenario-spec.md#2.4"],
                            "aliases": [tok],
                        }
                    isolates.append({"envelope_id": env_id, "tag": tag, "boundary_side": side})
                    spec_env_eq[env_id].add(tag)

    _wr_h, wr_body = repo_facts._section_lines(spec_text, "### 4.1 Work request mix")
    wr_rows = repo_facts._parse_first_table(wr_body)
    valid_categories = [row[0] for row in wr_rows if len(row) >= 2]
    valid_difficulty_classes = list(facts["matching"]["classes"].keys())

    _pp_h, pp_body = repo_facts._section_lines(spec_text, "## 5. Problems planted in the data")
    pp_rows = repo_facts._parse_first_table(pp_body)
    planted_problems = [
        {"id": f"PP-{idx:02d}", "name": row[0], "target_text": row[1], "how": row[2]}
        for idx, row in enumerate(pp_rows, start=1)
        if len(row) >= 3
    ]

    valves: dict[str, dict[str, str]] = {}
    bounded_by: list[dict[str, str]] = []
    work_requests: list[dict[str, object]] = []
    work_request_on: list[dict[str, str]] = []
    clashes: list[dict[str, str]] = []
    problem_reaches_equipment: list[dict[str, str]] = []
    problem_reaches_envelope: list[dict[str, str]] = []
    problem_reaches_wr: list[dict[str, str]] = []
    pending_phase_1: list[str] = []
    extra_errors: list[str] = []

    def _add_clash(kind: str, entity: str, details: str) -> None:
        clashes.append({
            "id": f"CLASH-{len(clashes) + 1:03d}",
            "kind": kind,
            "entity": entity,
            "details": details,
        })

    spike_meta = _parse_spike_sheet_meta(repo_root)
    if spike_meta is not None:
        sp_sheet, sp_title, sp_tags = spike_meta
        spec_sheet_titles = {s["id"]: s["title"] for s in sheets}
        if sp_sheet in spec_sheet_titles and spec_sheet_titles[sp_sheet] != sp_title:
            _add_clash(
                "sheet_title",
                sp_sheet,
                f"{sp_sheet} titled {spec_sheet_titles[sp_sheet]!r} in docs/scenario-spec.md "
                f"vs {sp_title!r} in spikes/dexpi-sheet/expected.py",
            )
        spec_tags_on_sheet = {r["tag"] for r in on_sheet if r["sheet_id"] == sp_sheet}
        for diff_tag in sorted(sp_tags ^ spec_tags_on_sheet):
            _add_clash(
                "sheet_equipment",
                diff_tag,
                f"{diff_tag} disagrees between docs/scenario-spec.md and spikes/dexpi-sheet/expected.py on {sp_sheet}",
            )

    if effective_mode == "docs":
        for vtag, env_id in _parse_spike_block_valves(repo_root):
            valves[vtag] = {"tag": vtag, "role": "block", "source": "spikes/dexpi-sheet/expected.py"}
            bounded_by.append({"envelope_id": env_id, "tag": vtag})

        for idx, row in enumerate(wr_rows, start=1):
            if len(row) < 3:
                continue
            cat, _cnt, sample = row[0], row[1], row[2]
            tags = [t for tok in MAJOR_TAG_RE.findall(sample) for t in _expand_tag_token(tok)]
            rid = f"SPEC-EX-{idx:02d}"
            ref = tags[0] if tags else "none"
            work_requests.append({
                "id": rid,
                "category": cat,
                "difficulty_class": "",
                "equipment_ref": ref,
                "source": "docs/scenario-spec.md#4.1",
                "is_example": True,
            })
            if ref != "none" and ref in equipment_map:
                work_request_on.append({"request_id": rid, "tag": ref})
            elif ref != "none":
                extra_errors.append(f"work request {rid} references nonexistent equipment {ref}")

        for pp in planted_problems:
            how = pp["how"]
            name_low = pp["name"].lower()
            reached = False
            for env_id in ENV_ID_RE.findall(how):
                problem_reaches_envelope.append({"problem_id": pp["id"], "envelope_id": env_id})
                reached = True
            for tok in MAJOR_TAG_RE.findall(how):
                for tag in _expand_tag_token(tok):
                    if tag in equipment_map:
                        problem_reaches_equipment.append({"problem_id": pp["id"], "tag": tag})
                        reached = True
            if not reached and work_requests:
                if any(k in name_low for k in ("duplicate", "wrong-unit", "over budget", "changes after freeze")):
                    problem_reaches_wr.append({"problem_id": pp["id"], "request_id": work_requests[0]["id"]})
                elif "isolation" in name_low and envelopes:
                    for env in envelopes:
                        problem_reaches_envelope.append({"problem_id": pp["id"], "envelope_id": env["id"]})

        pending_phase_1.append(
            f"112 named boundary valves pending Phase 1 data/scenario/ (currently {len(valves)} from spikes)"
        )
        pending_phase_1.append(
            f"200 materialized work requests pending Phase 1 data/scenario/ (currently {len(work_requests)} spec examples)"
        )
    else:
        master = json.loads((data_dir / "equipment-master.json").read_text(encoding="utf-8"))
        env_doc = json.loads((data_dir / "isolation-envelopes.json").read_text(encoding="utf-8"))
        wl_doc = json.loads((data_dir / "work-requests.json").read_text(encoding="utf-8"))
        ak_doc = json.loads((data_dir / "answer-key.json").read_text(encoding="utf-8"))
        cd_doc = json.loads((data_dir / "clusters-and-duplicates.json").read_text(encoding="utf-8"))
        ls_doc = json.loads((data_dir / "late-scope.json").read_text(encoding="utf-8"))

        seen_master_tags: set[str] = set()
        for eq in master.get("major_equipment", []):
            tag = eq["tag"]
            seen_master_tags.add(tag)
            sheet = eq.get("sheet", "")
            alt_name = eq.get("name_in_source")
            if tag not in equipment_map:
                _add_clash(
                    "extra_equipment",
                    tag,
                    f"{tag} appears in data/scenario/equipment-master.json but not in docs/scenario-spec.md",
                )
            else:
                equipment_map[tag]["sources"].append("data/scenario/equipment-master.json")
                if alt_name and alt_name != tag:
                    equipment_map[tag]["aliases"].append(alt_name)
                    _add_clash(
                        "equipment_name",
                        tag,
                        f"{tag} named {tag!r} in docs/scenario-spec.md vs {alt_name!r} in data/scenario/equipment-master.json",
                    )
                if sheet and tag in spec_sheet_of and sheet != spec_sheet_of[tag]:
                    _add_clash(
                        "sheet_assignment",
                        tag,
                        f"{tag} on sheet {spec_sheet_of[tag]} in docs/scenario-spec.md vs {sheet} in data/scenario/equipment-master.json",
                    )

        for tag in sorted(set(equipment_map) - seen_master_tags):
            if equipment_map[tag]["in_master"]:
                _add_clash(
                    "missing_equipment",
                    tag,
                    f"{tag} in docs/scenario-spec.md is missing from data/scenario/equipment-master.json",
                )

        for v in master.get("valves", []):
            valves[v["tag"]] = {
                "tag": v["tag"],
                "role": v.get("role", "block"),
                "source": "data/scenario/equipment-master.json",
            }
        for env in env_doc.get("envelopes", []):
            eid = env["id"]
            got_eq = set(env.get("equipment_tags", []))
            if eid in spec_env_eq and got_eq != spec_env_eq[eid]:
                _add_clash(
                    "envelope_equipment",
                    eid,
                    f"{eid} isolates {sorted(spec_env_eq[eid])} in docs/scenario-spec.md vs {sorted(got_eq)} in data/scenario/isolation-envelopes.json",
                )
            for vtag in env.get("boundary_valves", []):
                if vtag not in valves:
                    valves[vtag] = {"tag": vtag, "role": "block", "source": "data/scenario/isolation-envelopes.json"}
                bounded_by.append({"envelope_id": eid, "tag": vtag})

        parent_of: dict[str, str] = {}
        for p in master.get("psvs", []):
            if p.get("protects_tag"):
                parent_of[p["tag"]] = p["protects_tag"]
        for i in master.get("instruments", []):
            if i.get("measures_tag"):
                parent_of[i["tag"]] = i["measures_tag"]
        for v in master.get("valves", []):
            if v.get("parent_equipment"):
                parent_of[v["tag"]] = v["parent_equipment"]
        for s in master.get("piping_segments", []):
            if s.get("parent_equipment"):
                parent_of[s["line_number"]] = s["parent_equipment"]

        ak_by_id = {row["request_id"]: row for row in ak_doc.get("rows", [])}
        valid_supporting_tags = (
            set(equipment_map)
            | {v["tag"] for v in master.get("valves", [])}
            | {p["tag"] for p in master.get("psvs", [])}
            | {i["tag"] for i in master.get("instruments", [])}
            | {s["line_number"] for s in master.get("piping_segments", [])}
        )
        for wr in wl_doc.get("work_requests", []):
            rid = wr["request_id"]
            ak_row = ak_by_id.get(rid, {})
            true_tag = ak_row.get("true_tag", "none")
            dcls = ak_row.get("difficulty_class", "")
            work_requests.append({
                "id": rid,
                "category": wr.get("category", ""),
                "difficulty_class": dcls,
                "equipment_ref": true_tag,
                "source": "data/scenario/work-requests.json",
                "is_example": False,
            })
            if true_tag != "none":
                if true_tag in equipment_map:
                    work_request_on.append({"request_id": rid, "tag": true_tag})
                elif true_tag in valid_supporting_tags:
                    parent = parent_of.get(true_tag)
                    if parent and parent in equipment_map:
                        work_request_on.append({"request_id": rid, "tag": parent})
                else:
                    extra_errors.append(f"work request {rid} targets nonexistent equipment {true_tag}")

        for pp in planted_problems:
            name_low = pp["name"].lower()
            if "duplicate" in name_low:
                for pair in cd_doc.get("duplicate_pairs", []):
                    for rid in pair.get("request_ids", []):
                        problem_reaches_wr.append({"problem_id": pp["id"], "request_id": rid})
            elif "scaffold" in name_low:
                for cl in cd_doc.get("scaffold_clusters", []):
                    for tag in cl.get("equipment_tags", []):
                        if tag in equipment_map:
                            problem_reaches_equipment.append({"problem_id": pp["id"], "tag": tag})
            elif "isolation" in name_low:
                for cl in cd_doc.get("isolation_clusters", []):
                    problem_reaches_envelope.append({"problem_id": pp["id"], "envelope_id": cl["id"]})
            elif "access" in name_low:
                for cl in cd_doc.get("access_clusters", []):
                    for tag in cl.get("equipment_tags", []):
                        if tag in equipment_map:
                            problem_reaches_equipment.append({"problem_id": pp["id"], "tag": tag})
            elif "wrong-unit" in name_low:
                for row in ak_doc.get("rows", []):
                    if row.get("difficulty_class") in ("Wrong unit or retired", "wrong_unit_or_retired"):
                        problem_reaches_wr.append({"problem_id": pp["id"], "request_id": row["request_id"]})
            elif "over budget" in name_low:
                if sum(wr.get("estimate_cost_usd", 0) for wr in wl_doc.get("work_requests", [])) > 22_000_000 and work_requests:
                    problem_reaches_wr.append({"problem_id": pp["id"], "request_id": work_requests[0]["id"]})
            elif "changes after freeze" in name_low:
                for ch in ls_doc.get("scripted_changes", []):
                    tag = ch.get("equipment_tag")
                    if tag in equipment_map:
                        problem_reaches_equipment.append({"problem_id": pp["id"], "tag": tag})
            elif "nozzle" in name_low:
                live = ls_doc.get("live_walkthrough_add")
                if isinstance(live, dict):
                    tag = live.get("equipment_tag")
                    env_id = live.get("envelope_id")
                    if tag in equipment_map:
                        problem_reaches_equipment.append({"problem_id": pp["id"], "tag": tag})
                    if env_id:
                        problem_reaches_envelope.append({"problem_id": pp["id"], "envelope_id": env_id})

    dec_info = facts["decisions"]
    superseded_set = set(dec_info["superseded"])
    decisions = [
        {"id": did, "title": dec_info["titles"][did], "superseded": did in superseded_set}
        for did in dec_info["ids"]
    ]
    decision_id_set = set(dec_info["ids"])

    rules = _parse_rules(repo_root)
    rule_decisions: list[dict[str, str]] = []
    for r in rules:
        for did in r["decisions"]:
            if did in decision_id_set:
                rule_decisions.append({"rule_id": r["id"], "decision_id": did})
            else:
                extra_errors.append(f"rule {r['id']} cites unknown decision {did}")

    return {
        "commit": facts["commit"],
        "mode": effective_mode,
        "repo_facts": facts,
        "valid_categories": valid_categories,
        "valid_difficulty_classes": valid_difficulty_classes,
        "pending_phase_1": pending_phase_1,
        "extra_errors": extra_errors,
        "payload": {
            "sheets": sheets,
            "equipment": list(equipment_map.values()),
            "on_sheet": on_sheet,
            "envelopes": envelopes,
            "isolates": isolates,
            "valves": list(valves.values()),
            "bounded_by": bounded_by,
            "work_requests": work_requests,
            "work_request_on": work_request_on,
            "decisions": decisions,
            "rules": [{"id": r["id"], "layer": r["layer"], "text": r["text"], "source": r["source"]} for r in rules],
            "rule_decisions": rule_decisions,
            "planted_problems": [{"id": p["id"], "name": p["name"], "target_text": p["target_text"]} for p in planted_problems],
            "problem_reaches_equipment": problem_reaches_equipment,
            "problem_reaches_envelope": problem_reaches_envelope,
            "problem_reaches_wr": problem_reaches_wr,
            "clashes": clashes,
        },
    }


def _build_temp_relate_db(tmp_dir: Path, payload: dict[str, object]) -> Path:
    _require_relate()
    payload_file = tmp_dir / "payload.json"
    payload_file.write_text(json.dumps(payload), encoding="utf-8")
    db_path = tmp_dir / "twin.relate"
    _run_relate_jsonl(db_path, LOAD_CYPHER, fetch_params={"payload": payload_file})
    return db_path


def _compare_neo4j_snapshot(snapshot: dict[str, object], model: dict[str, object]) -> list[str]:
    errors: list[str] = []
    expected_eq = {e["tag"] for e in model["payload"]["equipment"] if e["in_master"]}
    got_eq = set(snapshot.get("equipment_tags", []))
    for missing in sorted(expected_eq - got_eq):
        errors.append(f"neo4j twin missing equipment {missing}")
    for extra in sorted(got_eq - expected_eq):
        errors.append(f"neo4j twin has unexpected equipment {extra}")

    expected_envs = {e["id"] for e in model["payload"]["envelopes"]}
    got_envs = set(snapshot.get("envelope_ids", []))
    for missing in sorted(expected_envs - got_envs):
        errors.append(f"neo4j twin missing envelope {missing}")
    return errors


def run_check(repo: Path, mode: str = "auto", neo4j_snapshot: Path | None = None) -> dict[str, object]:
    model = extract_model(repo, mode=mode)
    payload = model["payload"]
    rf = model["repo_facts"]
    sc = rf["scenario"]
    mt = rf["matching"]
    errors: list[str] = list(model["extra_errors"])

    for rf_err in repo_facts.check_consistency(repo):
        errors.append(f"repo_facts: {rf_err}")

    metrics: dict[str, int] = {}
    clash_rows: list[dict[str, object]] = []
    wr_rows: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory(prefix="twin-graph-") as td:
        db = _build_temp_relate_db(Path(td), payload)
        for row in _run_relate_jsonl(db, CHECK_CYPHER, read_only=True):
            kind = row.get("kind")
            if kind == "metric":
                metrics[str(row["k"])] = int(row["n"] or 0)
            elif kind == "no_sheet":
                errors.append(f"equipment {row['val']} is on no P&ID sheet")
            elif kind == "no_env":
                errors.append(f"equipment {row['val']} is in no isolation envelope")
            elif kind == "orphan_valve":
                errors.append(f"valve {row['val']} is in no isolation envelope")
            elif kind == "empty_env":
                errors.append(f"envelope {row['val']} isolates nothing")
            elif kind == "unreachable_pp":
                errors.append(f"planted problem {row['id']} ({row['name']}) cannot be reached in the graph")
            elif kind == "orphan_rule":
                errors.append(f"verification rule {row['id']} has no decision behind it: {row['text']}")
            elif kind == "clash":
                entry = {
                    "id": row["id"],
                    "kind": row["ckind"],
                    "entity": row["entity"],
                    "details": row["details"],
                }
                clash_rows.append(entry)
                errors.append(f"source clash {entry['id']} ({entry['kind']}): {entry['details']}")
            elif kind == "wr":
                wr_rows.append(row)

    eq_count = metrics.get("equipment", 0)
    sheet_count = metrics.get("sheets", 0)
    env_count = metrics.get("envelopes", 0)
    bv_target_sum = metrics.get("boundary_valves_target", 0)
    bv_actual = metrics.get("boundary_valves", 0)
    wr_count = metrics.get("work_requests", 0)
    dec_count = metrics.get("decisions", 0)
    rule_count = metrics.get("rules", 0)

    if eq_count != sc["major_equipment_count"]:
        errors.append(f"equipment count {eq_count} disagrees with repo_facts ({sc['major_equipment_count']})")
    if sheet_count != sc["pid_sheet_count"]:
        errors.append(f"sheet count {sheet_count} disagrees with repo_facts ({sc['pid_sheet_count']})")
    if env_count != sc["isolation_envelope_count"]:
        errors.append(f"envelope count {env_count} disagrees with repo_facts ({sc['isolation_envelope_count']})")
    if bv_target_sum != sc["boundary_valve_total"]:
        errors.append(f"boundary valve target sum {bv_target_sum} disagrees with repo_facts ({sc['boundary_valve_total']})")

    if model["mode"] == "full":
        if bv_actual != sc["boundary_valve_total"]:
            errors.append(f"materialized boundary valve count {bv_actual} disagrees with repo_facts ({sc['boundary_valve_total']})")
        if wr_count != sc["work_request_total"]:
            errors.append(f"materialized work request count {wr_count} disagrees with repo_facts ({sc['work_request_total']})")

        valid_cats = set(model["valid_categories"])
        valid_dcls = set(model["valid_difficulty_classes"])
        for row in wr_rows:
            if row["cat"] not in valid_cats:
                errors.append(f"work request {row['id']} has unknown category {row['cat']!r}")
            if row["dcls"] not in valid_dcls:
                errors.append(f"work request {row['id']} has difficulty class {row['dcls']!r} not in docs/matching-showcase.md")

    if neo4j_snapshot is not None:
        snap_data = json.loads(neo4j_snapshot.read_text(encoding="utf-8"))
        errors.extend(_compare_neo4j_snapshot(snap_data, model))

    return {
        "commit": model["commit"],
        "mode": model["mode"],
        "counts": {
            "equipment": eq_count,
            "sheets": sheet_count,
            "envelopes": env_count,
            "boundary_valves_target": bv_target_sum,
            "boundary_valves": bv_actual,
            "work_requests_target": sc["work_request_total"],
            "work_requests": wr_count,
            "work_request_categories": sc["work_request_category_count"],
            "matching_difficulty_classes": mt["difficulty_class_count"],
            "decisions": dec_count,
            "rules": rule_count,
            "planted_problems": len(payload["planted_problems"]),
        },
        "clashes": clash_rows,
        "pending_phase_1": model["pending_phase_1"],
        "errors": errors,
    }


def run_impact(repo: Path, target: str, mode: str = "auto") -> dict[str, object]:
    model = extract_model(repo, mode=mode)
    buckets: dict[str, set[str]] = {
        k: set()
        for k in ("equipment", "sheets", "envelopes", "valves", "work_requests", "planted_problems", "rules", "decisions")
    }
    with tempfile.TemporaryDirectory(prefix="twin-graph-") as td:
        db = _build_temp_relate_db(Path(td), model["payload"])
        target_param = Path(td) / "target.json"
        target_param.write_text(json.dumps(target), encoding="utf-8")
        for row in _run_relate_jsonl(db, IMPACT_CYPHER, fetch_params={"target": target_param}, read_only=True):
            kind = str(row.get("kind", ""))
            if kind in buckets and row.get("val") is not None:
                buckets[kind].add(str(row["val"]))

    return {
        "commit": model["commit"],
        "mode": model["mode"],
        "target": target,
        **{k: sorted(v) for k, v in buckets.items()},
    }


def run_query(repo: Path, cypher: str, mode: str = "auto") -> dict[str, object]:
    model = extract_model(repo, mode=mode)
    with tempfile.TemporaryDirectory(prefix="twin-graph-") as td:
        db = _build_temp_relate_db(Path(td), model["payload"])
        rows = _run_relate_jsonl(db, cypher, read_only=True)
    return {"commit": model["commit"], "mode": model["mode"], "rows": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild and check the Unit 200 twin specification graph in Relate.")
    parser.add_argument("--repo", type=Path, default=Path("."), help="Repository root path")
    parser.add_argument("--mode", choices=("auto", "docs", "full"), default="auto", help="Graph source mode")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_chk = sub.add_parser("check", help="Rebuild the Relate graph and run all consistency checks")
    p_chk.add_argument("--neo4j-snapshot", type=Path, default=None, help="Optional Neo4j snapshot JSON to compare against spec")
    p_chk.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output")

    p_imp = sub.add_parser("impact", help="Show everything connected to an equipment tag, envelope, sheet, work request, decision, or rule")
    p_imp.add_argument("target", help="Tag or ID (for example C-201, ENV-200-02, D9)")
    p_imp.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output")

    p_qry = sub.add_parser("query", help="Run a read-only Cypher query against the rebuilt Relate graph")
    p_qry.add_argument("cypher", help="Cypher query")
    p_qry.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output")

    args = parser.parse_args(argv)

    if args.cmd == "check":
        res = run_check(args.repo, mode=args.mode, neo4j_snapshot=args.neo4j_snapshot)
        if args.as_json:
            print(json.dumps(res, indent=2))
        else:
            c = res["counts"]
            print(f"Commit: {res['commit']} (mode: {res['mode']})")
            print(
                f"Graph: {c['equipment']} equipment, {c['sheets']} sheets, {c['envelopes']} envelopes "
                f"({c['boundary_valves_target']} target / {c['boundary_valves']} materialized boundary valves), "
                f"{c['work_requests_target']} target / {c['work_requests']} materialized work requests, "
                f"{c['rules']} rules across {c['decisions']} decisions"
            )
            for note in res["pending_phase_1"]:
                print(f"Pending: {note}")
            for err in res["errors"]:
                print(f"ERROR: {err}", file=sys.stderr)
        return 1 if res["errors"] else 0

    if args.cmd == "impact":
        res = run_impact(args.repo, args.target, mode=args.mode)
        if args.as_json:
            print(json.dumps(res, indent=2))
        else:
            print(f"Target: {res['target']} (commit {res['commit']}, mode {res['mode']})")
            for key in ("equipment", "sheets", "envelopes", "valves", "work_requests", "planted_problems", "rules", "decisions"):
                if res[key]:
                    print(f"  {key}: {', '.join(res[key])}")
        return 0

    if args.cmd == "query":
        res = run_query(args.repo, args.cypher, mode=args.mode)
        if args.as_json:
            print(json.dumps(res, indent=2))
        else:
            for row in res["rows"]:
                print(json.dumps(row))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
