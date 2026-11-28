"""Build a property graph from data/scenario/ (including reloaded DEXPI XML topology)
and verify both SHACL shapes and non-SHACL engineering rules (docs/verification.md section 2).
"""

from __future__ import annotations

import json
import re
import warnings
from collections import defaultdict
from pathlib import Path

VOCAB = "neo4j://graph.schema#"
INTERNAL_SHEETS = {f"200-PID-00{i}" for i in range(1, 6)}


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


def _load_dexpi_topology(dexpi_dir: Path) -> tuple[dict[str, list[dict]], list[dict], list[dict]]:
    """Read nozzles, piping connections, and off-page connectors from the 5 DEXPI XML sheets."""
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    from pydexpi.loaders import DexpiXmlSerializer
    from pydexpi.toolkits.model_toolkit import get_all_instances_in_model

    serializer = DexpiXmlSerializer()
    nozzles_by_eq: dict[str, list[dict]] = defaultdict(list)
    opc_records: list[dict] = []
    pipe_edges: list[dict] = []

    for sheet_no in sorted(INTERNAL_SHEETS):
        model = serializer.load(dexpi_dir, sheet_no)
        objs = list(get_all_instances_in_model(model))
        item_key: dict[int, str] = {}

        for obj in objs:
            cname = type(obj).__name__
            if hasattr(obj, "tagName") and obj.tagName:
                tag = obj.tagName
                item_key[id(obj)] = f"eq:{tag}"
                for nz in getattr(obj, "nozzles", None) or []:
                    nkey = f"nz:{tag}:{nz.subTagName}"
                    item_key[id(nz)] = nkey
                    nozzles_by_eq[tag].append(
                        {
                            "key": nkey,
                            "sub_tag": nz.subTagName,
                            "chamber": nz.chamber.subTagName if nz.chamber else "",
                            "sheet": sheet_no,
                        }
                    )
            elif hasattr(obj, "pipingComponentName") and obj.pipingComponentName:
                item_key[id(obj)] = f"valve:{obj.pipingComponentName}"
            elif hasattr(obj, "pipeConnectorNumber") and obj.pipeConnectorNumber:
                direction = "in" if "In" in cname else "out"
                ref = getattr(obj.connectorReference, "referencedDrawingNumber", "") or ""
                okey = f"opc:{sheet_no}:{obj.pipeConnectorNumber}"
                inst_key = f"{okey}:{obj.id}"
                item_key[id(obj)] = inst_key
                opc_records.append(
                    {
                        "key": okey,
                        "obj_id": obj.id,
                        "inst_key": inst_key,
                        "sheet": sheet_no,
                        "number": obj.pipeConnectorNumber,
                        "direction": direction,
                        "ref_sheet": ref,
                    }
                )
            elif cname == "PipeTee":
                item_key[id(obj)] = f"tee:{sheet_no}:{obj.id}"

        for obj in objs:
            if type(obj).__name__ == "PipingNetworkSegment":
                for conn in obj.connections:
                    src = item_key.get(id(conn.sourceItem))
                    dst = item_key.get(id(conn.targetItem))
                    if src and dst:
                        pipe_edges.append({"from": src, "to": dst, "sheet": sheet_no})

    # Stitch matching cross-sheet OPCs (out on sheet A referencing B <-> in on sheet B referencing A)
    out_by_pair: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    in_by_pair: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for rec in opc_records:
        if rec["ref_sheet"] in INTERNAL_SHEETS:
            if rec["direction"] == "out":
                out_by_pair[(rec["sheet"], rec["ref_sheet"], rec["number"])].append(rec["inst_key"])
            else:
                in_by_pair[(rec["ref_sheet"], rec["sheet"], rec["number"])].append(rec["inst_key"])
    for pair_key, out_ks in out_by_pair.items():
        if pair_key in in_by_pair:
            for ok in out_ks:
                for ik in in_by_pair[pair_key]:
                    pipe_edges.append({"from": ok, "to": ik, "sheet": "cross_sheet"})

    return nozzles_by_eq, opc_records, pipe_edges


def build_scenario_graph(scenario_dir: Path) -> dict:
    master = json.loads((scenario_dir / "equipment-master.json").read_text(encoding="utf-8"))
    plot = json.loads((scenario_dir / "plot-plan.json").read_text(encoding="utf-8"))
    envs = json.loads((scenario_dir / "isolation-envelopes.json").read_text(encoding="utf-8"))
    wl = json.loads((scenario_dir / "work-requests.json").read_text(encoding="utf-8"))
    ak = json.loads((scenario_dir / "answer-key.json").read_text(encoding="utf-8"))
    nozzles_by_eq, opc_records, pipe_edges = _load_dexpi_topology(scenario_dir / "dexpi")

    nodes: list[dict] = []
    rels: list[dict] = []
    added_keys: set[str] = set()

    def add_node(nd: dict) -> None:
        if nd["key"] not in added_keys:
            added_keys.add(nd["key"])
            nodes.append(nd)

    for sh in sorted({e["sheet"] for e in master["major_equipment"]}):
        add_node({"key": f"sheet:{sh}", "labels": ["PidSheet"], "props": {"number": sh}})

    for area in plot["areas"]:
        add_node({"key": f"area:{area['code']}", "labels": ["Area"], "props": {"code": area["code"], "name": area["name"]}})

    for pos in plot["equipment"]:
        add_node(
            {
                "key": f"pos:{pos['tag']}",
                "labels": ["PlotPosition"],
                "props": {"x": pos["x_m"], "y": pos["y_m"], "elevation": pos["elevation_m"]},
            }
        )

    tag_to_key: dict[str, str] = {}

    for v in master["valves"]:
        key = f"valve:{v['tag']}"
        tag_to_key[v["tag"]] = key
        v_labels = ["Valve", "Asset"]
        if v["role"] == "block":
            v_labels.append("BlockValve")
        add_node({"key": key, "labels": v_labels, "props": {"tag": v["tag"], "role": v["role"], "valve_type": v["valve_type"]}})

    for eq in master["major_equipment"]:
        key = f"eq:{eq['tag']}"
        tag_to_key[eq["tag"]] = key
        labels = ["Equipment", "Asset", eq["shacl_class"]]
        if eq["equipment_class"] in {"pump", "compressor"}:
            labels.append("PumpingOrCompression")
        add_node(
            {
                "key": key,
                "labels": labels,
                "props": {"tag": eq["tag"], "equipment_class": eq["equipment_class"], "description": eq["description"]},
            }
        )
        rels.append({"type": "ON_SHEET", "from": key, "to": f"sheet:{eq['sheet']}"})
        rels.append({"type": "LOCATED_IN", "from": key, "to": f"area:{eq['area']}"})
        rels.append({"type": "POSITIONED_AT", "from": key, "to": f"pos:{eq['tag']}"})
        if eq.get("suction_block_valve"):
            rels.append({"type": "SUCTION_VALVE", "from": key, "to": tag_to_key[eq["suction_block_valve"]]})
        if eq.get("discharge_block_valve"):
            rels.append({"type": "DISCHARGE_VALVE", "from": key, "to": tag_to_key[eq["discharge_block_valve"]]})
        for nz in nozzles_by_eq.get(eq["tag"], []):
            add_node({"key": nz["key"], "labels": ["Nozzle"], "props": {"sub_tag": nz["sub_tag"], "chamber": nz["chamber"]}})
            rels.append({"type": "HAS_NOZZLE", "from": key, "to": nz["key"]})

    for opc in opc_records:
        add_node({"key": f"{opc['key']}:{opc['obj_id']}", "labels": ["OffPageConnector"], "props": {"number": opc["number"], "sheet": opc["sheet"], "ref_sheet": opc["ref_sheet"], "direction": opc["direction"], "canonical_key": opc["key"]}})

    for edge in pipe_edges:
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
                "props": {"tag": psv["tag"], "role": "relief", "set_pressure_barg": psv["set_pressure_barg"]},
            }
        )
        rels.append({"type": "PROTECTS", "from": key, "to": tag_to_key[psv["protects_tag"]]})

    for inst in master["instruments"]:
        key = f"inst:{inst['tag']}"
        tag_to_key[inst["tag"]] = key
        add_node({"key": key, "labels": ["Instrument", "Asset"], "props": {"tag": inst["tag"], "instrument_type": inst["instrument_type"]}})
        rels.append({"type": "MEASURES", "from": key, "to": tag_to_key[inst["measures_tag"]]})

    for seg in master["piping_segments"]:
        key = f"pipe:{seg['line_number']}"
        tag_to_key[seg["line_number"]] = key
        add_node({"key": key, "labels": ["PipingSegment", "Asset"], "props": {"line_number": seg["line_number"], "fluid_code": seg["fluid_code"]}})

    for env in envs["envelopes"]:
        ekey = f"env:{env['id']}"
        add_node({"key": ekey, "labels": ["IsolationEnvelope"], "props": {"id": env["id"], "name": env["name"]}})
        for eq_tag in env["equipment_tags"]:
            rels.append({"type": "CONTAINS", "from": ekey, "to": tag_to_key[eq_tag]})
        for v_tag in env["boundary_valves"]:
            rels.append({"type": "BOUNDED_BY", "from": ekey, "to": tag_to_key[v_tag]})

    truth_by_id = {r["request_id"]: r["true_tag"] for r in ak["rows"]}
    for wr in wl["work_requests"]:
        rid = wr["request_id"]
        skey = f"wr:{rid}"
        add_node(
            {
                "key": skey,
                "labels": ["ScopeItem", wr["work_type_label"]],
                "props": {
                    "request_id": rid,
                    "exercise_id": "EX-DEMO",
                    "driver": wr["driver"],
                    "source_group": wr["source_group"],
                    "ript": wr["ript_score"],
                    "estimate_hours": wr["estimate_hours"],
                    "estimate_cost_usd": wr["estimate_cost_usd"],
                },
            }
        )
        tt = truth_by_id[rid]
        if tt != "none":
            rels.append({"type": "RESOLVES_TO", "from": skey, "to": tag_to_key[tt]})

    return {"nodes": nodes, "rels": rels}


def verify_engineering_rules(scenario_dir: Path, graph_override: dict | None = None) -> list[str]:
    """Run non-SHACL engineering rules from docs/verification.md section 2 on the scenario graph."""
    errors: list[str] = []
    graph = graph_override if graph_override is not None else build_scenario_graph(scenario_dir)
    by_key = {n["key"]: n for n in graph["nodes"]}

    # 1. Every shell-and-tube exchanger has >= 2 Tube side nozzles and >= 2 Shell side nozzles
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
                errors.append(
                    f"exchanger {nd['props']['tag']} missing tube/shell nozzles: {dict(ch_counts)}"
                )

    # 2. Cross-sheet OPC consistency: zero duplicate (sheet, number) OPCs, zero self-sheet OPCs,
    #    and 1-to-1 pairing across internal sheets
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
            errors.append(
                f"unmatched cross-sheet OPC {pair[2]} ({pair[0]} -> {pair[1]}): out={outs.get(pair, 0)}, in={ins.get(pair, 0)}"
            )

    # 3. Topology-derived isolation envelope closure on the connected 5-sheet DEXPI piping graph:
    # Walking CONNECTED_TO and HAS_NOZZLE from any equipment inside an envelope, stopping at that
    # envelope's listed boundary block valves (or external battery-limit OPCs), must never reach
    # equipment that belongs exclusively to another envelope.
    adj: dict[str, set[str]] = defaultdict(set)
    for rel in graph["rels"]:
        if rel["type"] in ("CONNECTED_TO", "HAS_NOZZLE"):
            adj[rel["from"]].add(rel["to"])
            adj[rel["to"]].add(rel["from"])

    env_eq: dict[str, set[str]] = defaultdict(set)
    env_bv: dict[str, set[str]] = defaultdict(set)
    for rel in graph["rels"]:
        if rel["type"] == "CONTAINS":
            env_eq[rel["from"]].add(rel["to"])
        elif rel["type"] == "BOUNDED_BY":
            env_bv[rel["from"]].add(rel["to"])

    all_env_eq = set().union(*env_eq.values()) if env_eq else set()
    # Split-boundary equipment (P-201A/B) appear in both ENV-200-01 (suction) and ENV-200-02 (discharge)
    shared_eq = {ek for ek in all_env_eq if sum(1 for eqs in env_eq.values() if ek in eqs) > 1}

    for ekey, contained in sorted(env_eq.items()):
        stop_valves = {
            vk for vk in env_bv[ekey] if vk in by_key and by_key[vk]["props"].get("role") == "block"
        }
        # Also stop at other envelopes' listed boundary valves that sit directly on the external side
        # ONLY if our own envelope's boundary valve already closed our side — so check strictly with
        # stop_valves of THIS envelope!
        starts = [ek for ek in contained if ek not in shared_eq]
        seen = set(starts)
        stack = list(starts)
        leaked: set[str] = set()
        while stack:
            curr = stack.pop()
            for nxt in adj.get(curr, ()):
                if nxt in seen:
                    continue
                # Stop at this envelope's own block boundary valves
                if nxt in stop_valves:
                    seen.add(nxt)
                    continue
                # Stop traversing THROUGH split-boundary pumps into the opposite side
                if nxt in shared_eq:
                    seen.add(nxt)
                    continue
                seen.add(nxt)
                if nxt in by_key and "Equipment" in by_key[nxt]["labels"] and nxt not in contained:
                    leaked.add(by_key[nxt]["props"]["tag"])
                stack.append(nxt)
        if leaked:
            errors.append(
                f"isolation envelope {by_key[ekey]['props']['id']} is not closed: piping leaks to {sorted(leaked)}"
            )

    return errors


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
