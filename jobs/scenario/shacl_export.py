"""Build a property graph from data/scenario/ and serialize to SHACL-compatible Turtle.

Matches the neo4j://graph.schema# vocabulary used by Neo4j neosemantics (n10s 5.26)
and specs/shapes.ttl so pySHACL and n10s validate the exact same graph.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

VOCAB = "neo4j://graph.schema#"


def node_iri(key: str) -> str:
    return "urn:twin:node:" + re.sub(r"[^A-Za-z0-9._-]", lambda m: f"%{ord(m.group()):02X}", key)


def _literal(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f'"{v!r}"^^<http://www.w3.org/2001/XMLSchema#double>'
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    raise TypeError(f"unexpected literal value {v!r}")


def build_scenario_graph(scenario_dir: Path) -> dict:
    master = json.loads((scenario_dir / "equipment-master.json").read_text(encoding="utf-8"))
    plot = json.loads((scenario_dir / "plot-plan.json").read_text(encoding="utf-8"))
    envs = json.loads((scenario_dir / "isolation-envelopes.json").read_text(encoding="utf-8"))
    wl = json.loads((scenario_dir / "work-requests.json").read_text(encoding="utf-8"))
    ak = json.loads((scenario_dir / "answer-key.json").read_text(encoding="utf-8"))

    nodes: list[dict] = []
    rels: list[dict] = []

    # Sheets
    sheets = sorted({e["sheet"] for e in master["major_equipment"]})
    for sh in sheets:
        nodes.append({"key": f"sheet:{sh}", "labels": ["PidSheet"], "props": {"number": sh}})

    # Areas
    for area in plot["areas"]:
        nodes.append({"key": f"area:{area['code']}", "labels": ["Area"], "props": {"code": area["code"], "name": area["name"]}})

    # Plot positions
    for pos in plot["equipment"]:
        nodes.append(
            {
                "key": f"pos:{pos['tag']}",
                "labels": ["PlotPosition"],
                "props": {"x": pos["x_m"], "y": pos["y_m"], "elevation": pos["elevation_m"]},
            }
        )

    tag_to_key: dict[str, str] = {}

    # Major equipment
    for eq in master["major_equipment"]:
        key = f"eq:{eq['tag']}"
        tag_to_key[eq["tag"]] = key
        nodes.append(
            {
                "key": key,
                "labels": ["Equipment", "Asset", eq["shacl_class"]],
                "props": {"tag": eq["tag"], "equipment_class": eq["equipment_class"], "description": eq["description"]},
            }
        )
        rels.append({"type": "ON_SHEET", "from": key, "to": f"sheet:{eq['sheet']}"})
        rels.append({"type": "LOCATED_IN", "from": key, "to": f"area:{eq['area']}"})
        rels.append({"type": "POSITIONED_AT", "from": key, "to": f"pos:{eq['tag']}"})

    # PSVs
    for psv in master["psvs"]:
        key = f"psv:{psv['tag']}"
        tag_to_key[psv["tag"]] = key
        nodes.append(
            {
                "key": key,
                "labels": ["Valve", "ReliefValve", "Asset"],
                "props": {"tag": psv["tag"], "role": "relief", "set_pressure_barg": psv["set_pressure_barg"]},
            }
        )
        rels.append({"type": "PROTECTS", "from": key, "to": tag_to_key[psv["protects_tag"]]})

    # Manual & control valves
    for v in master["valves"]:
        key = f"valve:{v['tag']}"
        tag_to_key[v["tag"]] = key
        nodes.append(
            {
                "key": key,
                "labels": ["Valve", "Asset"],
                "props": {"tag": v["tag"], "role": v["role"], "valve_type": v["valve_type"]},
            }
        )

    # Instruments
    for inst in master["instruments"]:
        key = f"inst:{inst['tag']}"
        tag_to_key[inst["tag"]] = key
        nodes.append(
            {
                "key": key,
                "labels": ["Instrument", "Asset"],
                "props": {"tag": inst["tag"], "instrument_type": inst["instrument_type"]},
            }
        )
        rels.append({"type": "MEASURES", "from": key, "to": tag_to_key[inst["measures_tag"]]})

    # Piping segments
    for seg in master["piping_segments"]:
        key = f"pipe:{seg['line_number']}"
        tag_to_key[seg["line_number"]] = key
        nodes.append(
            {
                "key": key,
                "labels": ["PipingSegment", "Asset"],
                "props": {"line_number": seg["line_number"], "fluid_code": seg["fluid_code"]},
            }
        )

    # Isolation envelopes
    for env in envs["envelopes"]:
        ekey = f"env:{env['id']}"
        nodes.append({"key": ekey, "labels": ["IsolationEnvelope"], "props": {"id": env["id"], "name": env["name"]}})
        for eq_tag in env["equipment_tags"]:
            rels.append({"type": "CONTAINS", "from": ekey, "to": tag_to_key[eq_tag]})
        for v_tag in env["boundary_valves"]:
            rels.append({"type": "BOUNDED_BY", "from": ekey, "to": tag_to_key[v_tag]})

    # Scope items (with resolved true_tag links representing post-review state)
    truth_by_id = {r["request_id"]: r["true_tag"] for r in ak["rows"]}
    for wr in wl["work_requests"]:
        rid = wr["request_id"]
        skey = f"wr:{rid}"
        nodes.append(
            {
                "key": skey,
                "labels": ["ScopeItem", wr["work_type_label"]],
                "props": {
                    "request_id": rid,
                    "exercise_id": "EX-DEMO",
                    "driver": wr["driver"],
                    "source_group": wr["source_group"],
                    "ript": wr["ript_score"],
                },
            }
        )
        tt = truth_by_id[rid]
        if tt != "none":
            rels.append({"type": "RESOLVES_TO", "from": skey, "to": tag_to_key[tt]})

    return {"nodes": nodes, "rels": rels}


def graph_to_turtle(graph: dict) -> str:
    out = [f"@prefix n: <{VOCAB}> ."]
    for nd in graph["nodes"]:
        subj = f"<{node_iri(nd['key'])}>"
        for lbl in nd["labels"]:
            out.append(f"{subj} a n:{lbl} .")
        for k, v in sorted(nd["props"].items()):
            if v is None:
                continue
            for item in (v if isinstance(v, list) else [v]):
                out.append(f"{subj} n:{k} {_literal(item)} .")
    for rel in graph["rels"]:
        out.append(f"<{node_iri(rel['from'])}> n:{rel['type']} <{node_iri(rel['to'])}> .")
    return "\n".join(out) + "\n"
