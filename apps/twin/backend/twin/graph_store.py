"""In-memory SHACL-guarded plant store and Relate WASM Cypher exporter."""

from __future__ import annotations

import copy
import json
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

from twin.plant_loader import verify_plant_graph


def _cypher_val(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if v is None:
        return "null"
    return json.dumps(str(v), ensure_ascii=False)


def export_browser_cypher(
    *,
    plant_nodes: list[dict[str, Any]],
    plant_rels: list[dict[str, Any]],
    scope_nodes: list[dict[str, Any]] | None = None,
    scope_rels: list[dict[str, Any]] | None = None,
) -> str:
    """Generate Relate-compatible Cypher statements (one statement per line) for the browser worker."""
    lines: list[str] = []
    all_nodes = list(plant_nodes) + list(scope_nodes or [])
    all_rels = list(plant_rels) + list(scope_rels or [])

    for nd in all_nodes:
        labels = ":".join(nd["labels"])
        props = {"key": nd["key"]}
        for k, v in nd["props"].items():
            if v is not None and not isinstance(v, (dict, list)):
                props[k] = v
        prop_str = ", ".join(f"{k}: {_cypher_val(v)}" for k, v in sorted(props.items()))
        lines.append(f"CREATE (:{labels} {{{prop_str}}});")

    for rel in all_rels:
        rtype = rel["type"]
        rprops = rel.get("props") or {}
        if rprops:
            pstr = " {" + ", ".join(f"{k}: {_cypher_val(v)}" for k, v in sorted(rprops.items()) if v is not None) + "}"
        else:
            pstr = ""
        lines.append(
            f"MATCH (a {{key: {_cypher_val(rel['from'])}}}), (b {{key: {_cypher_val(rel['to'])}}}) "
            f"CREATE (a)-[:{rtype}{pstr}]->(b);"
        )
    return "\n".join(lines) + "\n"


class MemoryPlantStore:
    """SHACL-guarded in-memory plant store with identical contract to Neo4jPlantStore."""

    def __init__(self, *, shapes_path: Path):
        self.shapes_path = shapes_path
        self._lock = threading.Lock()
        self._plant: dict[str, Any] = {
            "nodes": [],
            "rels": [],
            "computed_envelopes": [],
            "plot_plan": {"areas": [], "equipment": []},
            "sheets": [],
        }

    def guard_ready(self) -> bool:
        return self.shapes_path.is_file()

    def load_plant_graph(self, plant_graph: dict[str, Any]) -> None:
        with self._lock:
            if not self.guard_ready():
                raise RuntimeError("SHACL guard not ready: shapes file missing")
            errors = verify_plant_graph(plant_graph, self.shapes_path)
            if errors:
                raise ValueError("Plant graph rejected by SHACL / engineering guard: " + "; ".join(errors[:5]))
            self._plant = copy.deepcopy(plant_graph)

    def _index(self):
        nodes = self._plant["nodes"]
        rels = self._plant["rels"]
        by_key = {n["key"]: n for n in nodes}
        return nodes, rels, by_key

    def summary(self) -> dict[str, Any]:
        nodes, rels, _ = self._index()
        return {
            "equipment_count": sum(1 for n in nodes if "Equipment" in n["labels"]),
            "sheet_count": sum(1 for n in nodes if "PidSheet" in n["labels"]),
            "envelope_count": sum(1 for n in nodes if "IsolationEnvelope" in n["labels"]),
            "boundary_valve_count": sum(1 for r in rels if r["type"] == "BOUNDED_BY"),
            "valve_count": sum(1 for n in nodes if "Valve" in n["labels"]),
            "psv_count": sum(1 for n in nodes if "ReliefValve" in n["labels"]),
            "instrument_count": sum(1 for n in nodes if "Instrument" in n["labels"]),
            "piping_segment_count": sum(1 for n in nodes if "PipingSegment" in n["labels"]),
            "node_count": len(nodes),
            "relationship_count": len(rels),
            "guard_ready": self.guard_ready(),
        }

    def list_equipment(self) -> list[dict[str, Any]]:
        nodes, rels, by_key = self._index()
        env_of: dict[str, list[str]] = defaultdict(list)
        nozzles_of: dict[str, list[dict[str, Any]]] = defaultdict(list)
        pos_of: dict[str, dict[str, Any]] = {}
        for r in rels:
            if r["type"] == "CONTAINS" and r["from"] in by_key:
                env_of[r["to"]].append(by_key[r["from"]]["props"]["id"])
            elif r["type"] == "HAS_NOZZLE" and r["to"] in by_key:
                nozzles_of[r["from"]].append(by_key[r["to"]]["props"])
            elif r["type"] == "POSITIONED_AT" and r["to"] in by_key:
                pos_of[r["from"]] = by_key[r["to"]]["props"]

        out = []
        for nd in nodes:
            if "Equipment" not in nd["labels"]:
                continue
            p = dict(nd["props"])
            p["labels"] = list(nd["labels"])
            p["envelopes"] = sorted(env_of.get(nd["key"], []))
            p["nozzles"] = nozzles_of.get(nd["key"], [])
            p["plot_position"] = pos_of.get(nd["key"])
            out.append(p)
        return sorted(out, key=lambda x: x["tag"])

    def get_equipment(self, tag: str) -> dict[str, Any] | None:
        for eq in self.list_equipment():
            if eq["tag"] == tag:
                return eq
        return None

    def list_sheets(self) -> list[dict[str, Any]]:
        return list(self._plant.get("sheets", []))

    def plot_plan(self) -> dict[str, Any]:
        return copy.deepcopy(self._plant.get("plot_plan", {"areas": [], "equipment": []}))

    def list_envelopes(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._plant.get("computed_envelopes", []))

    def get_envelope(self, env_id: str) -> dict[str, Any] | None:
        for env in self._plant.get("computed_envelopes", []):
            if env["id"] == env_id:
                return copy.deepcopy(env)
        return None

    def export_snapshot(self) -> dict[str, Any]:
        nodes, rels, _ = self._index()
        return {
            "equipment_tags": sorted(n["props"]["tag"] for n in nodes if "Equipment" in n["labels"]),
            "envelope_ids": sorted(n["props"]["id"] for n in nodes if "IsolationEnvelope" in n["labels"]),
            "sheet_ids": sorted(n["props"]["number"] for n in nodes if "PidSheet" in n["labels"]),
            "boundary_valve_count": sum(1 for r in rels if r["type"] == "BOUNDED_BY"),
            "envelopes": self.list_envelopes(),
        }

    def export_cypher(
        self,
        scope_nodes: list[dict[str, Any]] | None = None,
        scope_rels: list[dict[str, Any]] | None = None,
    ) -> str:
        return export_browser_cypher(
            plant_nodes=self._plant["nodes"],
            plant_rels=self._plant["rels"],
            scope_nodes=scope_nodes,
            scope_rels=scope_rels,
        )
