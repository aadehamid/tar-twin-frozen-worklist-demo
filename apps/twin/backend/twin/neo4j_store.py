"""Neo4j 5.26 Community + n10s 5.26 + APOC SHACL-guarded plant store.

Implements all findings from docs/spikes/shacl-n10s.md section 6:
1. Uniqueness constraints on Equipment.tag, Valve.tag, PidSheet.number, Area.code, IsolationEnvelope.id.
2. Readiness check (N7) verifying exactly one _n10sValidatorConfig node, exact pinned listShapes() rows,
   and an installed, unpaused APOC 'shacl' trigger in the 'before' phase.
3. Single-lock serialized writes executing inside ONE transaction so the trigger validates atomically.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from twin.graph_store import export_browser_cypher
from twin.plant_loader import verify_plant_graph

SHACL_TRIGGER_QUERY = (
    "CALL n10s.validation.shacl.validateTransaction("
    "$createdNodes,$createdRelationships,$assignedLabels,$removedLabels,"
    "$assignedNodeProperties,$removedNodeProperties,$deletedRelationships,$deletedNodes)"
)


def _shape_rows_set(listed: list[dict[str, Any]]) -> set[tuple[str, str, str, str]]:
    return {
        (
            str(r["target"]),
            str(r["propertyOrRelationshipPath"]),
            str(r["param"]),
            json.dumps(r["value"], sort_keys=True, default=str),
        )
        for r in listed
    }


class Neo4jPlantStore:
    """Production Neo4j 5.26 plant store with n10s + APOC SHACL transaction guard."""

    def __init__(self, *, uri: str, user: str, password: str, shapes_path: Path, database: str = "neo4j"):
        from neo4j import GraphDatabase

        self.shapes_path = shapes_path
        self.database = database
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._lock = threading.Lock()
        self._pinned_shapes: set[tuple[str, str, str, str]] | None = None
        self._cached_plot_plan: dict[str, Any] = {"areas": [], "equipment": []}
        self._cached_envelopes: list[dict[str, Any]] = []
        self._cached_sheets: list[dict[str, Any]] = []

    def close(self) -> None:
        self._driver.close()

    def ensure_constraints(self) -> None:
        constraints = [
            "CREATE CONSTRAINT eq_tag_unique IF NOT EXISTS FOR (e:Equipment) REQUIRE e.tag IS UNIQUE",
            "CREATE CONSTRAINT valve_tag_unique IF NOT EXISTS FOR (v:Valve) REQUIRE v.tag IS UNIQUE",
            "CREATE CONSTRAINT sheet_num_unique IF NOT EXISTS FOR (s:PidSheet) REQUIRE s.number IS UNIQUE",
            "CREATE CONSTRAINT area_code_unique IF NOT EXISTS FOR (a:Area) REQUIRE a.code IS UNIQUE",
            "CREATE CONSTRAINT env_id_unique IF NOT EXISTS FOR (e:IsolationEnvelope) REQUIRE e.id IS UNIQUE",
            "CREATE CONSTRAINT node_key_unique IF NOT EXISTS FOR (n:TwinNode) REQUIRE n.key IS UNIQUE",
        ]
        with self._driver.session(database=self.database) as s:
            for stmt in constraints:
                s.run(stmt).consume()

    def install_shacl_guard(self, wait_seconds: float = 10.0) -> None:
        shapes_ttl = self.shapes_path.read_text(encoding="utf-8")
        with self._driver.session(database=self.database) as s:
            s.run("CALL n10s.validation.shacl.import.inline($ttl, 'Turtle')", ttl=shapes_ttl).consume()
            listed = [dict(r) for r in s.run("CALL n10s.validation.shacl.listShapes()")]
            self._pinned_shapes = _shape_rows_set(listed)
        with self._driver.session(database="system") as sys_s:
            sys_s.run(
                "CALL apoc.trigger.install($db, 'shacl', $q, {phase: 'before'})",
                db=self.database,
                q=SHACL_TRIGGER_QUERY,
            ).consume()
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if self.guard_ready():
                return
            time.sleep(0.25)
        raise RuntimeError("Timed out waiting for APOC SHACL trigger to become installed")

    def guard_ready(self) -> bool:
        with self._driver.session(database=self.database) as s:
            cfg_count = s.run("MATCH (n:_n10sValidatorConfig) RETURN count(n) AS c").single()["c"]
            listed = _shape_rows_set([dict(r) for r in s.run("CALL n10s.validation.shacl.listShapes()")])
            triggers = [dict(r) for r in s.run("CALL apoc.trigger.list()")]
        shacl = [t for t in triggers if t.get("name") == "shacl"]
        if cfg_count != 1 or not listed or len(shacl) != 1:
            return False
        if self._pinned_shapes is not None and listed != self._pinned_shapes:
            return False
        t = shacl[0]
        return (
            t.get("query") == SHACL_TRIGGER_QUERY
            and (t.get("selector") or {}).get("phase") == "before"
            and t.get("installed") is True
            and t.get("paused") is False
        )

    def run_write(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        with self._lock:
            if not self.guard_ready():
                raise RuntimeError("SHACL guard not ready; refusing write")
            with self._driver.session(database=self.database) as s:
                return [dict(r) for r in s.run(cypher, **params)]

    def load_plant_graph(self, plant_graph: dict[str, Any]) -> None:
        with self._lock:
            if not self.guard_ready():
                raise RuntimeError("SHACL guard not ready; refusing plant load")
            errors = verify_plant_graph(plant_graph, self.shapes_path)
            if errors:
                raise ValueError("Plant graph rejected before Neo4j write: " + "; ".join(errors[:5]))

            nodes = plant_graph["nodes"]
            rels = plant_graph["rels"]

            def _tx_load(tx):
                # Remove prior plant nodes while preserving _n10sValidatorConfig (finding 2)
                tx.run(
                    "MATCH (n:TwinNode) WHERE NOT n:ScopeItem AND NOT n:Baseline AND NOT n:ChangeEvent DETACH DELETE n"
                )
                by_label_set: dict[tuple[str, ...], list[dict[str, Any]]] = {}
                for nd in nodes:
                    lbls = tuple(["TwinNode", *nd["labels"]])
                    clean_props = {
                        k: v for k, v in nd["props"].items() if v is not None and not isinstance(v, (dict, list))
                    }
                    by_label_set.setdefault(lbls, []).append({"key": nd["key"], "props": clean_props})
                for lbls, batch in by_label_set.items():
                    label_expr = ":".join(lbls)
                    tx.run(
                        f"UNWIND $rows AS row MERGE (n:TwinNode {{key: row.key}}) SET n:{label_expr}, n += row.props",
                        rows=batch,
                    )
                by_rtype: dict[str, list[dict[str, str]]] = {}
                for rel in rels:
                    by_rtype.setdefault(rel["type"], []).append({"from": rel["from"], "to": rel["to"]})
                for rtype, batch in by_rtype.items():
                    tx.run(
                        f"UNWIND $rows AS row "
                        f"MATCH (a:TwinNode {{key: row.from}}), (b:TwinNode {{key: row.to}}) "
                        f"MERGE (a)-[:{rtype}]->(b)",
                        rows=batch,
                    )

            with self._driver.session(database=self.database) as s:
                s.execute_write(_tx_load)

            self._cached_plot_plan = plant_graph.get("plot_plan", {"areas": [], "equipment": []})
            self._cached_envelopes = plant_graph.get("computed_envelopes", [])
            self._cached_sheets = plant_graph.get("sheets", [])

    def summary(self) -> dict[str, Any]:
        with self._driver.session(database=self.database) as s:
            row = s.run(
                """
                RETURN
                  COUNT { MATCH (:Equipment) } AS equipment_count,
                  COUNT { MATCH (:PidSheet) } AS sheet_count,
                  COUNT { MATCH (:IsolationEnvelope) } AS envelope_count,
                  COUNT { MATCH (:IsolationEnvelope)-[:BOUNDED_BY]->(:Valve) } AS boundary_valve_count,
                  COUNT { MATCH (:Valve) } AS valve_count,
                  COUNT { MATCH (:ReliefValve) } AS psv_count,
                  COUNT { MATCH (:Instrument) } AS instrument_count,
                  COUNT { MATCH (:PipingSegment) } AS piping_segment_count,
                  COUNT { MATCH (:TwinNode) } AS node_count,
                  COUNT { MATCH (:TwinNode)-[r]->(:TwinNode) } AS relationship_count
                """
            ).single()
        out = dict(row)
        out["guard_ready"] = self.guard_ready()
        return out

    def list_equipment(self) -> list[dict[str, Any]]:
        with self._driver.session(database=self.database) as s:
            rows = s.run(
                """
                MATCH (e:Equipment)
                OPTIONAL MATCH (env:IsolationEnvelope)-[:CONTAINS]->(e)
                OPTIONAL MATCH (e)-[:HAS_NOZZLE]->(nz:Nozzle)
                OPTIONAL MATCH (e)-[:POSITIONED_AT]->(p:PlotPosition)
                RETURN properties(e) AS props, labels(e) AS labels,
                       collect(DISTINCT env.id) AS envelopes,
                       collect(DISTINCT properties(nz)) AS nozzles,
                       properties(p) AS plot_position
                ORDER BY props.tag
                """
            )
            out = []
            for r in rows:
                d = dict(r["props"])
                d["labels"] = [lbl for lbl in r["labels"] if lbl != "TwinNode"]
                d["envelopes"] = sorted(x for x in r["envelopes"] if x)
                d["nozzles"] = [x for x in r["nozzles"] if x]
                d["plot_position"] = dict(r["plot_position"]) if r["plot_position"] else None
                out.append(d)
            return out

    def get_equipment(self, tag: str) -> dict[str, Any] | None:
        for eq in self.list_equipment():
            if eq["tag"] == tag:
                return eq
        return None

    def list_sheets(self) -> list[dict[str, Any]]:
        if self._cached_sheets:
            return list(self._cached_sheets)
        with self._driver.session(database=self.database) as s:
            return [dict(r["props"]) for r in s.run("MATCH (p:PidSheet) RETURN properties(p) AS props ORDER BY p.number")]

    def plot_plan(self) -> dict[str, Any]:
        return self._cached_plot_plan

    def list_envelopes(self) -> list[dict[str, Any]]:
        if self._cached_envelopes:
            return list(self._cached_envelopes)
        with self._driver.session(database=self.database) as s:
            rows = s.run(
                """
                MATCH (env:IsolationEnvelope)
                OPTIONAL MATCH (env)-[:CONTAINS]->(e:Equipment)
                OPTIONAL MATCH (env)-[:BOUNDED_BY]->(v:Valve)
                RETURN properties(env) AS props,
                       collect(DISTINCT e.tag) AS eqs,
                       collect(DISTINCT v.tag) AS valves
                ORDER BY props.id
                """
            )
            return [
                {
                    **dict(r["props"]),
                    "equipment_tags": sorted(x for x in r["eqs"] if x),
                    "boundary_valves": sorted(x for x in r["valves"] if x),
                }
                for r in rows
            ]

    def get_envelope(self, env_id: str) -> dict[str, Any] | None:
        for env in self.list_envelopes():
            if env["id"] == env_id:
                return env
        return None

    def export_snapshot(self) -> dict[str, Any]:
        envs = self.list_envelopes()
        return {
            "equipment_tags": [e["tag"] for e in self.list_equipment()],
            "envelope_ids": sorted(e["id"] for e in envs),
            "sheet_ids": sorted(s["number"] for s in self.list_sheets()),
            "boundary_valve_count": sum(len(e.get("boundary_valves", [])) for e in envs),
            "envelopes": envs,
        }

    def export_cypher(
        self,
        scope_nodes: list[dict[str, Any]] | None = None,
        scope_rels: list[dict[str, Any]] | None = None,
    ) -> str:
        with self._driver.session(database=self.database) as s:
            plant_nodes = [
                {
                    "key": r["key"],
                    "labels": [lbl for lbl in r["labels"] if lbl != "TwinNode"],
                    "props": dict(r["props"]),
                }
                for r in s.run(
                    "MATCH (n:TwinNode) WHERE NOT n:ScopeItem RETURN n.key AS key, labels(n) AS labels, properties(n) AS props"
                )
            ]
            plant_rels = [
                {"from": r["from"], "to": r["to"], "type": r["type"]}
                for r in s.run(
                    "MATCH (a:TwinNode)-[r]->(b:TwinNode) WHERE NOT a:ScopeItem AND NOT b:ScopeItem "
                    "RETURN a.key AS from, b.key AS to, type(r) AS type"
                )
            ]
        return export_browser_cypher(
            plant_nodes=plant_nodes,
            plant_rels=plant_rels,
            scope_nodes=scope_nodes,
            scope_rels=scope_rels,
        )
