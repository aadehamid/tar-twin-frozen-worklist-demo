#!/usr/bin/env python3
"""Evaluate the Unit 200 matcher against live Perplexity Decider + Inkling 2 Mini on OpenRouter.

Reads DECIDER_API_KEY / DECIDER_URL / DECIDER_MODEL / REASON_MODEL from environment or repo .env
(never logs secrets), evaluates the 54 unresolved work requests (plus optional full-200 run),
saves recorded fixtures for offline/CI replay to data/scenario/matcher-ai-fixtures.json, and
writes a per-difficulty-class evaluation report to data/scenario/matcher-eval-report.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TWIN_BACKEND = REPO_ROOT / "apps" / "twin" / "backend"
if str(TWIN_BACKEND) not in sys.path:
    sys.path.insert(0, str(TWIN_BACKEND))

from twin.graph_store import MemoryPlantStore  # noqa: E402
from twin.matcher import (  # noqa: E402
    AiClientConfig,
    MatchingPipeline,
    build_decider_request,
    call_live_decider,
    call_live_inkling_reason,
    check_compatibility,
    check_decider_response,
    filter_inkling_reason,
)
from twin.plant_loader import build_plant_graph  # noqa: E402
from twin.sync import SyncEngine  # noqa: E402


def _load_dotenv_if_needed(repo_root: Path) -> None:
    env_path = repo_root / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and not os.environ.get(k):
            os.environ[k] = v


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate live Perplexity Decider + Inkling matcher on Unit 200.")
    parser.add_argument("--scenario-dir", type=Path, default=REPO_ROOT / "data" / "scenario")
    parser.add_argument("--shapes", type=Path, default=REPO_ROOT / "specs" / "shapes.ttl")
    parser.add_argument("--write-fixtures", action="store_true", help="Write data/scenario/matcher-ai-fixtures.json")
    parser.add_argument("--write-report", action="store_true", help="Write data/scenario/matcher-eval-report.json")
    parser.add_argument("--with-reasons", action="store_true", help="Also call Inkling 2 Mini for checked picks")
    args = parser.parse_args(argv)

    _load_dotenv_if_needed(REPO_ROOT)
    cfg = AiClientConfig.from_env()
    if not cfg.api_key:
        print("ERROR: DECIDER_API_KEY not set in environment or .env", file=sys.stderr)
        return 1

    store = MemoryPlantStore(shapes_path=args.shapes)
    store.load_plant_graph(build_plant_graph(args.scenario_dir))
    eng = SyncEngine(plant_store=store, scenario_dir=args.scenario_dir, ai_config=cfg, recorded_ai_responses={})
    cmms_rows = eng._fallback_cmms_from_scenario()

    pipeline = MatchingPipeline(
        cmms_rows=cmms_rows,
        plant_equipment=store.list_equipment(),
        envelopes=store.list_envelopes(),
        ai_config=cfg,
        recorded_ai_responses={},
    )

    wl = json.loads((args.scenario_dir / "work-requests.json").read_text(encoding="utf-8"))["work_requests"]
    ak_rows = json.loads((args.scenario_dir / "answer-key.json").read_text(encoding="utf-8"))["rows"]

    recorded: dict[str, dict] = {}
    served_models: set[str] = set()

    for wr in wl:
        wr_norm = {**wr, "id": wr["request_id"]}
        code_res = pipeline.match_work_request(wr_norm, use_ai=False)
        if code_res["match_status"] == "accepted":
            continue

        cands = code_res["mapping_trace"]["candidates"][:12]
        cand_tags = [c["tag"] for c in cands]
        facts_map: dict[str, tuple[str, str]] = {}
        compat_map: dict[str, bool] = {}
        for c in cands:
            t = c["tag"]
            compat_map[t] = check_compatibility(wr["work_type_label"], pipeline.cmms_by_tag[t])
            for f in c["facts"]:
                facts_map[f["id"]] = (t, f["text"])

        decider_req = build_decider_request(
            model=cfg.decider_model,
            request_text=f"{wr['equipment_text']} | {wr['title']} | area {wr['area']}",
            candidates=cand_tags,
            facts=facts_map,
        )
        raw_resp, model_served, latency_ms = call_live_decider(cfg, decider_req)
        if raw_resp is None:
            print(f"WARN: no live response for {wr['request_id']}", file=sys.stderr)
            continue
        served_models.add(model_served)
        verdict = check_decider_response(raw_resp, candidates=cand_tags, facts=facts_map, compatible_by_tag=compat_map)
        inkling_raw = None
        if args.with_reasons and verdict["outcome"] == "proposal":
            picked = verdict["tag"]
            inkling_raw = call_live_inkling_reason(
                cfg,
                request_text=f"{wr['equipment_text']} ({wr['title']})",
                picked_tag=picked,
                tag_facts=pipeline.facts_by_tag.get(picked, []),
            )
            inkling_raw = filter_inkling_reason(inkling_raw, picked, set(pipeline.cmms_by_tag.keys()))

        recorded[wr["request_id"]] = {
            "model_served": model_served,
            "latency_ms": latency_ms,
            "response": raw_resp,
            "inkling_reason": inkling_raw,
        }

    # Score full 3-mode comparison using the freshly recorded live responses
    eval_pipeline = MatchingPipeline(
        cmms_rows=cmms_rows,
        plant_equipment=store.list_equipment(),
        envelopes=store.list_envelopes(),
        ai_config=cfg,
        recorded_ai_responses=recorded,
    )
    wrs_norm = [{**w, "id": w["request_id"]} for w in wl]
    comparison = eval_pipeline.run_lab_comparison(wrs_norm, ak_rows, live_ai=False)

    if args.write_fixtures:
        fixtures_doc = {
            "event_id": "TAR-200-2028",
            "provenance": "SYNTHETIC",
            "decider_model_requested": cfg.decider_model,
            "decider_models_served": sorted(served_models),
            "reason_model": cfg.reason_model,
            "recorded_count": len(recorded),
            "by_request_id": recorded,
        }
        (args.scenario_dir / "matcher-ai-fixtures.json").write_text(
            json.dumps(fixtures_doc, indent=2) + "\n", encoding="utf-8"
        )

    report = {
        "event_id": "TAR-200-2028",
        "provenance": "SYNTHETIC",
        "decider_model_requested": cfg.decider_model,
        "decider_models_served": sorted(served_models),
        "reason_model": cfg.reason_model,
        "live_unresolved_evaluated": len(recorded),
        "comparison": comparison,
    }
    if args.write_report:
        (args.scenario_dir / "matcher-eval-report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

    cta = comparison["modes"]["code_then_ai"]
    print(f"Models served: {sorted(served_models)} | Live unresolved evaluated: {len(recorded)}")
    print("Code then AI totals:", json.dumps(cta["totals"], indent=2))
    for row in cta["by_class"]:
        print(
            f"  {row['difficulty_class']:<36} n={row['count']:2d} "
            f"auto={row['auto_accepted']:2d} ok={row['correct']:2d} wrong={row['wrong']:2d} "
            f"abstain={row['abstained']:2d} rej={row['rejected_by_checker']:2d} recall={row['candidate_recall']:.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
