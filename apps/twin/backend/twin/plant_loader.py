"""DEXPI 2.0.1 plant loader, plot-plan loader, isolation envelope graph walk, and verification.

Implements docs/design.md sections 4.3, 4.4, 5.1 and docs/verification.md section 2.
"""

from __future__ import annotations

import json
import re
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

VOCAB = "neo4j://graph.schema#"
INTERNAL_SHEETS = tuple(f"200-PID-00{i}" for i in range(1, 6))


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
    raise TypeError(f"Unexpected literal value: {v!r}")


def parse_dexpi_sheets(dexpi_dir: Path) -> dict[str, Any]:
    """Read all 5 DEXPI XML sheets with pyDEXPI and extract equipment, nozzles, OPCs, tees, and piping edges."""
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from pydexpi.loaders import DexpiXmlSerializer
    from pydexpi.toolkits.model_toolkit import get_all_instances_in_model

    serializer = DexpiXmlSerializer()
    sheets_meta: list[dict[str, str]] = []
    dexpi_eq: dict[str, dict[str, Any]] = {}
    nozzles_by_eq: dict[str, list[dict[str, Any]]] = defaultdict(list)
    opc_records: list[dict[str, Any]] = []
    pipe_edges: list[dict[str, str]] = []
    dexpi_valves: dict[str, dict[str, str]] = {}

    for sheet_no in INTERNAL_SHEETS:
        xml_path = dexpi_dir / f"{sheet_no}.xml"
        if not xml_path.is_file():
            raise FileNotFoundError(f"Missing DEXPI sheet XML: {xml_path}")
        model = serializer.load(dexpi_dir, sheet_no)
        diagram = getattr(model, "diagram", None)
        title = getattr(diagram, "name", "") or sheet_no
        svg_path = dexpi_dir / f"{sheet_no}.svg"
        sheets_meta.append(
            {
                "number": sheet_no,
                "title": str(title),
                "svg_path": str(svg_path.relative_to(dexpi_dir.parent)) if svg_path.exists() else f"dexpi/{sheet_no}.svg",
            }
        )

        objs = list(get_all_instances_in_model(model))
        item_key: dict[int, str] = {}

        for obj in objs:
            cname = type(obj).__name__
            if hasattr(obj, "tagName") and obj.tagName:
                tag = str(obj.tagName)
                key = f"eq:{tag}"
                item_key[id(obj)] = key
                dexpi_eq[tag] = {
                    "dexpi_id": str(getattr(obj, "id", key)),
                    "dexpi_class": cname,
                    "sheet": sheet_no,
                }
                for nz in getattr(obj, "nozzles", None) or []:
                    nkey = f"nz:{tag}:{nz.subTagName}"
                    item_key[id(nz)] = nkey
                    nozzles_by_eq[tag].append(
                        {
                            "key": nkey,
                            "id": str(getattr(nz, "id", nkey)),
                            "sub_tag": str(nz.subTagName),
                            "chamber": str(nz.chamber.subTagName) if getattr(nz, "chamber", None) else "",
                            "sheet": sheet_no,
                        }
                    )
            elif hasattr(obj, "pipingComponentName") and obj.pipingComponentName:
                vtag = str(obj.pipingComponentName)
                vkey = f"valve:{vtag}"
                item_key[id(obj)] = vkey
                dexpi_valves[vtag] = {"dexpi_id": str(getattr(obj, "id", vkey)), "dexpi_class": cname, "sheet": sheet_no}
            elif hasattr(obj, "pipeConnectorNumber") and obj.pipeConnectorNumber:
                direction = "in" if "In" in cname else "out"
                ref = getattr(obj.connectorReference, "referencedDrawingNumber", "") or ""
                okey = f"opc:{sheet_no}:{obj.pipeConnectorNumber}"
                inst_key = f"{okey}:{obj.id}"
                item_key[id(obj)] = inst_key
                opc_records.append(
                    {
                        "key": okey,
                        "obj_id": str(obj.id),
                        "inst_key": inst_key,
                        "sheet": sheet_no,
                        "number": str(obj.pipeConnectorNumber),
                        "direction": direction,
                        "ref_sheet": str(ref),
                    }
                )
            elif cname == "PipeTee":
                item_key[id(obj)] = f"tee:{sheet_no}:{obj.id}"

        for obj in objs:
            if type(obj).__name__ == "PipingNetworkSegment":
                line_no = str(getattr(obj, "segmentNumber", "") or "")
                for conn in obj.connections:
                    src = item_key.get(id(conn.sourceItem))
                    dst = item_key.get(id(conn.targetItem))
                    if src and dst:
                        pipe_edges.append({"from": src, "to": dst, "sheet": sheet_no, "line_number": line_no})

    # Stitch matching cross-sheet off-page connectors
    out_by_pair: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    in_by_pair: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for rec in opc_records:
        if rec["ref_sheet"] in INTERNAL_SHEETS:
            if rec["direction"] == "out":
                out_by_pair[(rec["sheet"], rec["ref_sheet"], rec["number"])].append(rec["inst_key"])
            else:
                in_by_pair[(rec["ref_sheet"], rec["sheet"], rec["number"])].append(rec["inst_key"])
    for pair_key, out_ks in out_by_pair.items():
        for ok in out_ks:
            for ik in in_by_pair.get(pair_key, ()):
                pipe_edges.append({"from": ok, "to": ik, "sheet": "cross_sheet", "line_number": pair_key[2]})

    return {
        "sheets": sheets_meta,
        "dexpi_eq": dexpi_eq,
        "nozzles_by_eq": dict(nozzles_by_eq),
        "opc_records": opc_records,
        "pipe_edges": pipe_edges,
        "dexpi_valves": dexpi_valves,
    }


def _walk_envelope_closure(
    *,
    env_id: str,
    by_key: dict[str, dict[str, Any]],
    adj: dict[str, set[str]],
    contained: set[str],
    stop_valves: set[str],
    sides: dict[str, str],
    shared_eq: set[str],
    suct_of: dict[str, set[str]],
    disch_of: dict[str, set[str]],
) -> tuple[set[str], set[str]]:
    """Walk every piping path leaving contained equipment (including split-boundary shared equipment).

    For split-boundary shared equipment (for example P-201A/B spanning ENV-200-01 suction and
    ENV-200-02 discharge), start from the equipment's side-appropriate nozzle(s) (N1 for suction,
    N2 for discharge) without crossing internally through the shared body to the opposite envelope.
    """
    leaked: set[str] = set()
    reached_stop_valves: set[str] = set()

    for eq_tag, side in sides.items():
        eq_key = f"eq:{eq_tag}"
        if side == "suction" and not (suct_of.get(eq_key, set()) & stop_valves):
            leaked.add(f"{eq_tag}:suction")
        elif side == "discharge" and not (disch_of.get(eq_key, set()) & stop_valves):
            leaked.add(f"{eq_tag}:discharge")

    starts: list[str] = [ek for ek in contained if ek not in shared_eq]
    blocked_shared_bodies: set[str] = set()
    for ek in contained:
        if ek not in shared_eq:
            continue
        eq_tag = by_key[ek]["props"]["tag"] if ek in by_key else ek.split(":", 1)[-1]
        side = sides.get(eq_tag, "full")
        if side == "suction":
            blocked_shared_bodies.add(ek)
            for nb in adj.get(ek, ()):
                if nb in by_key and "Nozzle" in by_key[nb]["labels"] and by_key[nb]["props"].get("sub_tag") == "N1":
                    starts.append(nb)
        elif side == "discharge":
            blocked_shared_bodies.add(ek)
            for nb in adj.get(ek, ()):
                if nb in by_key and "Nozzle" in by_key[nb]["labels"] and by_key[nb]["props"].get("sub_tag") == "N2":
                    starts.append(nb)
        else:
            starts.append(ek)

    seen = set(starts) | blocked_shared_bodies
    stack = list(starts)
    while stack:
        curr = stack.pop()
        for nxt in adj.get(curr, ()):
            if nxt in seen:
                continue
            if nxt in stop_valves:
                seen.add(nxt)
                if nxt in by_key:
                    reached_stop_valves.add(by_key[nxt]["props"]["tag"])
                continue
            seen.add(nxt)
            if nxt in by_key and "Equipment" in by_key[nxt]["labels"] and nxt not in contained:
                leaked.add(by_key[nxt]["props"]["tag"])
            stack.append(nxt)
    return leaked, reached_stop_valves


def compute_isolation_envelopes(
    *,
    nodes: list[dict[str, Any]],
    rels: list[dict[str, Any]],
    envelope_defs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Verify and compute isolation envelopes by walking CONNECTED_TO and HAS_NOZZLE on the DEXPI topology."""
    by_key = {n["key"]: n for n in nodes}
    adj: dict[str, set[str]] = defaultdict(set)
    suct_of: dict[str, set[str]] = defaultdict(set)
    disch_of: dict[str, set[str]] = defaultdict(set)
    for rel in rels:
        if rel["type"] in ("CONNECTED_TO", "HAS_NOZZLE"):
            adj[rel["from"]].add(rel["to"])
            adj[rel["to"]].add(rel["from"])
        elif rel["type"] == "SUCTION_VALVE":
            suct_of[rel["from"]].add(rel["to"])
        elif rel["type"] == "DISCHARGE_VALVE":
            disch_of[rel["from"]].add(rel["to"])

    all_eq_membership: dict[str, int] = defaultdict(int)
    for env in envelope_defs:
        for tag in env["equipment_tags"]:
            all_eq_membership[f"eq:{tag}"] += 1
    shared_eq = {ek for ek, cnt in all_eq_membership.items() if cnt > 1}

    computed: list[dict[str, Any]] = []
    for env in envelope_defs:
        env_id = env["id"]
        contained = {f"eq:{tag}" for tag in env["equipment_tags"]}
        stop_valves = {
            f"valve:{vtag}"
            for vtag in env["boundary_valves"]
            if f"valve:{vtag}" in by_key and by_key[f"valve:{vtag}"]["props"].get("role") == "block"
        }
        sides = env.get("boundary_sides", {})
        leaked, reached_stop_valves = _walk_envelope_closure(
            env_id=env_id,
            by_key=by_key,
            adj=adj,
            contained=contained,
            stop_valves=stop_valves,
            sides=sides,
            shared_eq=shared_eq,
            suct_of=suct_of,
            disch_of=disch_of,
        )

        computed.append(
            {
                "id": env_id,
                "name": env["name"],
                "equipment_tags": list(env["equipment_tags"]),
                "boundary_sides": dict(sides),
                "boundary_valves": list(env["boundary_valves"]),
                "boundary_valve_count": len(env["boundary_valves"]),
                "reached_piping_valves": sorted(reached_stop_valves),
                "blind_estimate": int(env.get("blind_estimate", len(env["boundary_valves"]) + 2)),
                "closed": len(leaked) == 0,
                "leaked_targets": sorted(leaked),
            }
        )
    return computed


def build_plant_graph(scenario_dir: Path) -> dict[str, Any]:
    """Load all 5 DEXPI XML sheets, equipment master, plot plan, and computed isolation envelopes."""
    dexpi = parse_dexpi_sheets(scenario_dir / "dexpi")
    master = json.loads((scenario_dir / "equipment-master.json").read_text(encoding="utf-8"))
    plot = json.loads((scenario_dir / "plot-plan.json").read_text(encoding="utf-8"))
    env_doc = json.loads((scenario_dir / "isolation-envelopes.json").read_text(encoding="utf-8"))

    nodes: list[dict[str, Any]] = []
    rels: list[dict[str, Any]] = []
    added_keys: set[str] = set()

    def add_node(nd: dict[str, Any]) -> None:
        if nd["key"] not in added_keys:
            added_keys.add(nd["key"])
            nodes.append(nd)

    for sh in dexpi["sheets"]:
        add_node(
            {
                "key": f"sheet:{sh['number']}",
                "labels": ["PidSheet"],
                "props": {"number": sh["number"], "title": sh["title"], "svg_path": sh["svg_path"]},
            }
        )

    add_node(
        {
            "key": "plotmeta:unit-200",
            "labels": ["PlotPlanMeta"],
            "props": {
                "unit": plot.get("unit", "Unit 200 Diesel Hydrotreater"),
                "width_m": float(plot.get("width_m", 120.0)),
                "height_m": float(plot.get("height_m", 80.0)),
                "pipe_rack_y_range_json": json.dumps(plot.get("pipe_rack_y_range_m", [36.0, 44.0])),
                "elevations_json": json.dumps(plot.get("reactor_structure_elevations_m", [0.0, 12.0, 24.0])),
            },
        }
    )

    for area in plot["areas"]:
        add_node(
            {
                "key": f"area:{area['code']}",
                "labels": ["Area"],
                "props": {
                    "code": area["code"],
                    "name": area["name"],
                    "x_min_m": area["x_min_m"],
                    "x_max_m": area["x_max_m"],
                    "y_min_m": area["y_min_m"],
                    "y_max_m": area["y_max_m"],
                },
            }
        )

    for pos in plot["equipment"]:
        add_node(
            {
                "key": f"pos:{pos['tag']}",
                "labels": ["PlotPosition"],
                "props": {
                    "tag": pos["tag"],
                    "x": pos["x_m"],
                    "y": pos["y_m"],
                    "elevation": pos["elevation_m"],
                    "width_m": pos["width_m"],
                    "depth_m": pos["depth_m"],
                    "area": pos["area"],
                },
            }
        )

    tag_to_key: dict[str, str] = {}

    for v in master["valves"]:
        key = f"valve:{v['tag']}"
        tag_to_key[v["tag"]] = key
        v_labels = ["Valve", "Asset"]
        if v["role"] == "block":
            v_labels.append("BlockValve")
        dv = dexpi["dexpi_valves"].get(v["tag"], {})
        add_node(
            {
                "key": key,
                "labels": v_labels,
                "props": {
                    "tag": v["tag"],
                    "dexpi_id": dv.get("dexpi_id", key),
                    "role": v["role"],
                    "valve_type": v["valve_type"],
                    "area": v["area"],
                    "sheet": v["sheet"],
                    "description": v["description"],
                },
            }
        )

    for eq in master["major_equipment"]:
        key = f"eq:{eq['tag']}"
        tag_to_key[eq["tag"]] = key
        deq = dexpi["dexpi_eq"].get(eq["tag"], {})
        labels = ["Equipment", "Asset", eq["shacl_class"]]
        if eq["equipment_class"] in {"pump", "compressor"}:
            labels.append("PumpingOrCompression")
        add_node(
            {
                "key": key,
                "labels": labels,
                "props": {
                    "tag": eq["tag"],
                    "dexpi_id": deq.get("dexpi_id", key),
                    "dexpi_class": deq.get("dexpi_class", eq["shacl_class"]),
                    "equipment_class": eq["equipment_class"],
                    "shacl_class": eq["shacl_class"],
                    "description": eq["description"],
                    "functional_location": eq["functional_location"],
                    "area": eq["area"],
                    "sheet": eq["sheet"],
                    "operating_pressure_barg": eq["operating_pressure_barg"],
                    "design_pressure_barg": eq["design_pressure_barg"],
                    "operating_temp_c": eq["operating_temp_c"],
                    "design_temp_c": eq["design_temp_c"],
                },
            }
        )
        rels.append({"type": "ON_SHEET", "from": key, "to": f"sheet:{eq['sheet']}"})
        rels.append({"type": "LOCATED_IN", "from": key, "to": f"area:{eq['area']}"})
        rels.append({"type": "POSITIONED_AT", "from": key, "to": f"pos:{eq['tag']}"})
        if eq.get("suction_block_valve"):
            rels.append({"type": "SUCTION_VALVE", "from": key, "to": tag_to_key[eq["suction_block_valve"]]})
        if eq.get("discharge_block_valve"):
            rels.append({"type": "DISCHARGE_VALVE", "from": key, "to": tag_to_key[eq["discharge_block_valve"]]})
        for nz in dexpi["nozzles_by_eq"].get(eq["tag"], []):
            add_node(
                {
                    "key": nz["key"],
                    "labels": ["Nozzle"],
                    "props": {
                        "id": nz["id"],
                        "sub_tag": nz["sub_tag"],
                        "chamber": nz["chamber"],
                        "equipment_tag": eq["tag"],
                    },
                }
            )
            rels.append({"type": "HAS_NOZZLE", "from": key, "to": nz["key"]})

    for opc in dexpi["opc_records"]:
        add_node(
            {
                "key": opc["inst_key"],
                "labels": ["OffPageConnector"],
                "props": {
                    "number": opc["number"],
                    "sheet": opc["sheet"],
                    "ref_sheet": opc["ref_sheet"],
                    "direction": opc["direction"],
                    "canonical_key": opc["key"],
                },
            }
        )

    for edge in dexpi["pipe_edges"]:
        for endpoint in (edge["from"], edge["to"]):
            if endpoint.startswith("tee:"):
                add_node({"key": endpoint, "labels": ["PipeTee"], "props": {"id": endpoint}})
        rels.append({"type": "CONNECTED_TO", "from": edge["from"], "to": edge["to"]})

    for psv in master["psvs"]:
        key = f"psv:{psv['tag']}"
        tag_to_key[psv["tag"]] = key
        add_node(
            {
                "key": key,
                "labels": ["Valve", "ReliefValve", "Asset"],
                "props": {
                    "tag": psv["tag"],
                    "role": "relief",
                    "set_pressure_barg": psv["set_pressure_barg"],
                    "area": psv["area"],
                    "sheet": psv["sheet"],
                    "description": psv["description"],
                },
            }
        )
        rels.append({"type": "PROTECTS", "from": key, "to": tag_to_key[psv["protects_tag"]]})

    for inst in master["instruments"]:
        key = f"inst:{inst['tag']}"
        tag_to_key[inst["tag"]] = key
        add_node(
            {
                "key": key,
                "labels": ["Instrument", "Asset"],
                "props": {
                    "tag": inst["tag"],
                    "instrument_type": inst["instrument_type"],
                    "area": inst["area"],
                    "sheet": inst["sheet"],
                    "description": inst["description"],
                },
            }
        )
        rels.append({"type": "MEASURES", "from": key, "to": tag_to_key[inst["measures_tag"]]})

    for seg in master["piping_segments"]:
        key = f"pipe:{seg['line_number']}"
        tag_to_key[seg["line_number"]] = key
        add_node(
            {
                "key": key,
                "labels": ["PipingSegment", "Asset"],
                "props": {
                    "line_number": seg["line_number"],
                    "fluid_code": seg["fluid_code"],
                    "spec": seg.get("piping_class", ""),
                    "size_in": seg.get("nominal_size_in", 0),
                    "area": seg["area"],
                    "sheet": seg["sheet"],
                    "description": seg["description"],
                },
            }
        )

    computed_envelopes = compute_isolation_envelopes(
        nodes=nodes,
        rels=rels,
        envelope_defs=env_doc["envelopes"],
    )
    for env in computed_envelopes:
        ekey = f"env:{env['id']}"
        add_node(
            {
                "key": ekey,
                "labels": ["IsolationEnvelope"],
                "props": {
                    "id": env["id"],
                    "name": env["name"],
                    "boundary_valve_count": env["boundary_valve_count"],
                    "blind_estimate": env["blind_estimate"],
                    "closed": env["closed"],
                    "boundary_sides_json": json.dumps(env["boundary_sides"], sort_keys=True),
                    "reached_piping_valves_json": json.dumps(env["reached_piping_valves"]),
                    "leaked_targets_json": json.dumps(env["leaked_targets"]),
                },
            }
        )
        for eq_tag in env["equipment_tags"]:
            rels.append({"type": "CONTAINS", "from": ekey, "to": tag_to_key[eq_tag]})
        for v_tag in env["boundary_valves"]:
            rels.append({"type": "BOUNDED_BY", "from": ekey, "to": tag_to_key[v_tag]})

    return {
        "nodes": nodes,
        "rels": rels,
        "computed_envelopes": computed_envelopes,
        "plot_plan": plot,
        "sheets": dexpi["sheets"],
    }


def graph_to_turtle(graph: dict[str, Any]) -> str:
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


def verify_plant_graph(graph: dict[str, Any], shapes_path: Path) -> list[str]:
    """Run SHACL shapes (pySHACL) plus non-SHACL engineering rules (docs/verification.md section 2)."""
    import pyshacl
    import rdflib

    errors: list[str] = []

    # 1. SHACL check via pySHACL against specs/shapes.ttl
    data_ttl = graph_to_turtle(graph)
    shapes_ttl = shapes_path.read_text(encoding="utf-8")
    shapes_g = rdflib.Graph().parse(data=shapes_ttl, format="turtle")
    data_g = rdflib.Graph().parse(data=data_ttl, format="turtle")
    conforms, report_g, report_txt = pyshacl.validate(
        data_g,
        shacl_graph=shapes_g,
        inference="none",
        allow_warnings=False,
    )
    if not conforms:
        sh = rdflib.Namespace("http://www.w3.org/ns/shacl#")
        for res in report_g.subjects(rdflib.RDF.type, sh.ValidationResult):
            focus = str(report_g.value(res, sh.focusNode))
            comp = str(report_g.value(res, sh.sourceConstraintComponent))
            path = str(report_g.value(res, sh.resultPath))
            errors.append(f"SHACL violation on {focus}: {comp} ({path})")
        if not errors:
            errors.append(f"SHACL validation failed: {report_txt}")

    by_key = {n["key"]: n for n in graph["nodes"]}

    # 2. Exchangers have >= 2 Tube side and >= 2 Shell side nozzles
    nozzles_of: dict[str, list[dict]] = defaultdict(list)
    for rel in graph["rels"]:
        if rel["type"] == "HAS_NOZZLE" and rel["to"] in by_key:
            nozzles_of[rel["from"]].append(by_key[rel["to"]])
    for nd in graph["nodes"]:
        if "Exchanger" in nd["labels"]:
            ch_counts: dict[str, int] = defaultdict(int)
            for nz in nozzles_of.get(nd["key"], []):
                ch_counts[str(nz["props"].get("chamber", ""))] += 1
            if ch_counts.get("Tube side", 0) < 2 or ch_counts.get("Shell side", 0) < 2:
                errors.append(f"exchanger {nd['props']['tag']} missing tube/shell nozzles: {dict(ch_counts)}")

    # 3. Cross-sheet OPC 1-to-1 consistency (no duplicates, no self-sheet)
    seen_sheet_opc: dict[tuple[str, str], int] = defaultdict(int)
    outs: dict[tuple[str, str, str], int] = defaultdict(int)
    ins: dict[tuple[str, str, str], int] = defaultdict(int)
    for nd in graph["nodes"]:
        if "OffPageConnector" in nd["labels"]:
            sh = nd["props"]["sheet"]
            ref = nd["props"]["ref_sheet"]
            num = nd["props"]["number"]
            seen_sheet_opc[(sh, num)] += 1
            if seen_sheet_opc[(sh, num)] > 1:
                errors.append(f"duplicate off-page connector {num} on {sh}")
            if ref == sh:
                errors.append(f"off-page connector {num} on {sh} references its own drawing")
            elif ref in INTERNAL_SHEETS:
                if nd["props"]["direction"] == "out":
                    outs[(sh, ref, num)] += 1
                else:
                    ins[(ref, sh, num)] += 1
    for pair in sorted(set(outs) | set(ins)):
        if outs.get(pair, 0) != 1 or ins.get(pair, 0) != 1:
            errors.append(f"unmatched cross-sheet OPC {pair[2]} ({pair[0]} -> {pair[1]})")

    # 4. Isolation envelope topology closure (walk graph stopping at envelope BOUNDED_BY block valves)
    adj: dict[str, set[str]] = defaultdict(set)
    env_eq: dict[str, set[str]] = defaultdict(set)
    env_bv: dict[str, set[str]] = defaultdict(set)
    suct_of: dict[str, set[str]] = defaultdict(set)
    disch_of: dict[str, set[str]] = defaultdict(set)
    for rel in graph["rels"]:
        rtype = rel["type"]
        if rtype in ("CONNECTED_TO", "HAS_NOZZLE"):
            adj[rel["from"]].add(rel["to"])
            adj[rel["to"]].add(rel["from"])
        elif rtype == "CONTAINS":
            env_eq[rel["from"]].add(rel["to"])
        elif rtype == "BOUNDED_BY":
            env_bv[rel["from"]].add(rel["to"])
        elif rtype == "SUCTION_VALVE":
            suct_of[rel["from"]].add(rel["to"])
        elif rtype == "DISCHARGE_VALVE":
            disch_of[rel["from"]].add(rel["to"])

    all_env_eq = set().union(*env_eq.values()) if env_eq else set()
    shared_eq = {ek for ek in all_env_eq if sum(1 for eqs in env_eq.values() if ek in eqs) > 1}

    for ekey, contained in sorted(env_eq.items()):
        env_id = by_key[ekey]["props"]["id"]
        stop_valves = {
            vk for vk in env_bv[ekey] if vk in by_key and by_key[vk]["props"].get("role") == "block"
        }
        sides = json.loads(by_key[ekey]["props"].get("boundary_sides_json", "{}"))
        leaked, _ = _walk_envelope_closure(
            env_id=env_id,
            by_key=by_key,
            adj=adj,
            contained=contained,
            stop_valves=stop_valves,
            sides=sides,
            shared_eq=shared_eq,
            suct_of=suct_of,
            disch_of=disch_of,
        )
        if leaked:
            errors.append(f"isolation envelope {env_id} is not closed: piping leaks to {sorted(leaked)}")

    return errors
