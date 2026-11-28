#!/usr/bin/env python3
"""Generate all Unit 200 synthetic scenario artifacts deterministically from a seed.

Usage:
    python3 jobs/generate_scenario.py --seed 20280200 --out data/scenario
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

JOBS_DIR = Path(__file__).resolve().parent
if str(JOBS_DIR) not in sys.path:
    sys.path.insert(0, str(JOBS_DIR))

from scenario.dexpi_builder import generate_all_dexpi_sheets  # noqa: E402
from scenario.physics import build_process_basis  # noqa: E402
from scenario.plant_spec import build_equipment_master_and_envelopes, build_plot_plan  # noqa: E402
from scenario.schemas import ManifestDoc  # noqa: E402
from scenario.worklist import build_worklist_and_related  # noqa: E402


def _write_json(path: Path, model) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = model.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(seed: int, out_dir: Path) -> Path:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    process_basis = build_process_basis()
    master, envelopes = build_equipment_master_and_envelopes()
    plot_plan = build_plot_plan()
    work_requests, answer_key, clusters_dups, late_scope = build_worklist_and_related(
        master, envelopes, seed=seed
    )

    json_artifacts = {
        "process-basis.json": process_basis,
        "equipment-master.json": master,
        "plot-plan.json": plot_plan,
        "isolation-envelopes.json": envelopes,
        "work-requests.json": work_requests,
        "answer-key.json": answer_key,
        "clusters-and-duplicates.json": clusters_dups,
        "late-scope.json": late_scope,
    }
    for rel, model in json_artifacts.items():
        _write_json(out_dir / rel, model)

    dexpi_paths = generate_all_dexpi_sheets(out_dir / "dexpi")

    file_hashes: dict[str, str] = {}
    for rel in sorted(json_artifacts):
        file_hashes[rel] = _sha256(out_dir / rel)
    for p in sorted(dexpi_paths):
        rel = p.relative_to(out_dir).as_posix()
        file_hashes[rel] = _sha256(p)

    manifest = ManifestDoc(
        seed=seed,
        event_id="TAR-200-2028",
        unit="Unit 200 Diesel Hydrotreater",
        files=file_hashes,
    )
    manifest_path = out_dir / "manifest.json"
    _write_json(manifest_path, manifest)
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic Unit 200 scenario artifacts.")
    parser.add_argument("--seed", type=int, default=20280200)
    parser.add_argument("--out", type=Path, default=Path("data/scenario"))
    args = parser.parse_args(argv)
    manifest_path = generate(args.seed, args.out)
    print(f"Generated Unit 200 scenario artifacts and manifest at {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
