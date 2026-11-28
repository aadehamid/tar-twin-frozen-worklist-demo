#!/usr/bin/env python3
"""Load all 5 Unit 200 DEXPI sheets, plot plan, and isolation envelopes into the twin store (or Neo4j).

Usage:
  python jobs/load_dexpi.py --scenario-dir data/scenario --shapes specs/shapes.ttl --export-snapshot /tmp/snap.json
  python jobs/load_dexpi.py --neo4j-uri bolt://127.0.0.1:7687 --neo4j-user neo4j --neo4j-password ...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TWIN_BACKEND = REPO_ROOT / "apps" / "twin" / "backend"
if str(TWIN_BACKEND) not in sys.path:
    sys.path.insert(0, str(TWIN_BACKEND))

from twin.graph_store import MemoryPlantStore  # noqa: E402
from twin.plant_loader import build_plant_graph, verify_plant_graph  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load Unit 200 DEXPI sheets, plot plan, and isolation envelopes.")
    parser.add_argument("--scenario-dir", type=Path, default=REPO_ROOT / "data" / "scenario")
    parser.add_argument("--shapes", type=Path, default=REPO_ROOT / "specs" / "shapes.ttl")
    parser.add_argument("--neo4j-uri", type=str, default="")
    parser.add_argument("--neo4j-user", type=str, default="neo4j")
    parser.add_argument("--neo4j-password", type=str, default="")
    parser.add_argument("--export-snapshot", type=Path, default=None)
    args = parser.parse_args(argv)

    plant = build_plant_graph(args.scenario_dir)
    errors = verify_plant_graph(plant, args.shapes)
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    if args.neo4j_uri:
        from twin.neo4j_store import Neo4jPlantStore

        store = Neo4jPlantStore(
            uri=args.neo4j_uri,
            user=args.neo4j_user,
            password=args.neo4j_password,
            shapes_path=args.shapes,
        )
        try:
            store.ensure_constraints()
            if not store.guard_ready():
                store.install_shacl_guard()
            store.load_plant_graph(plant)
            snap = store.export_snapshot()
        finally:
            store.close()
    else:
        store = MemoryPlantStore(shapes_path=args.shapes)
        store.load_plant_graph(plant)
        snap = store.export_snapshot()

    if args.export_snapshot is not None:
        args.export_snapshot.parent.mkdir(parents=True, exist_ok=True)
        args.export_snapshot.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")

    print(
        f"Loaded plant graph: {len(snap['equipment_tags'])} equipment, "
        f"{len(snap['sheet_ids'])} sheets, {len(snap['envelope_ids'])} envelopes, "
        f"{snap['boundary_valve_count']} boundary valves."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
