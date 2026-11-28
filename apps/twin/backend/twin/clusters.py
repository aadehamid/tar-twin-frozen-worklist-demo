"""Cluster computation (scaffold, isolation, access), duplicate pairs, and RIPT cut-line optimizer.

Implements docs/design.md section 5.5 and docs/verification.md section 3 (including BOTH halves of the
shared-cost invariant from docs/spikes/bend-cost.md).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def compute_clustered_cost(
    jobs: list[tuple[int, str | None]],
    cluster_shared_costs: dict[str, int],
) -> tuple[int, int]:
    """Return (total_clustered_cost, shared_cost_component) counting each active cluster's shared cost once."""
    direct_sum = sum(int(direct) for direct, _ in jobs)
    active_clusters = {cid for _, cid in jobs if cid is not None and cid in cluster_shared_costs}
    shared_sum = sum(int(cluster_shared_costs[cid]) for cid in active_clusters)
    return direct_sum + shared_sum, shared_sum


def compute_clusters_and_duplicates(
    *,
    scope_items: list[dict[str, Any]],
    scenario_dir: Path,
) -> dict[str, Any]:
    """Map active scope items into the 7 scaffold, 6 isolation, and 3 access clusters + 9 duplicate pairs."""
    cd_doc = json.loads((scenario_dir / "clusters-and-duplicates.json").read_text(encoding="utf-8"))
    by_id = {it["request_id"]: it for it in scope_items}
    active_items = [it for it in scope_items if it.get("status") not in {"deleted", "rejected", "screened_out"}]

    def _by_tag(tags: set[str]) -> list[str]:
        hits = []
        for it in active_items:
            resolved = it.get("resolved_tag")
            prop_tag = (it.get("proposal") or {}).get("tag")
            if resolved in tags or (resolved is None and prop_tag in tags):
                hits.append(it["request_id"])
        return sorted(hits)

    scaffold_clusters = []
    for cl in cd_doc["scaffold_clusters"]:
        req_ids = [rid for rid in cl.get("request_ids", []) if rid in by_id] or _by_tag(set(cl["equipment_tags"]))
        scaffold_clusters.append(
            {
                "id": cl["id"],
                "type": "scaffold",
                "name": cl["name"],
                "area": cl["area"],
                "equipment_tags": cl["equipment_tags"],
                "request_ids": req_ids,
                "shared_hours": int(cl["shared_hours"]),
                "shared_cost_usd": int(cl["shared_cost_usd"]),
            }
        )

    isolation_clusters = []
    for cl in cd_doc["isolation_clusters"]:
        req_ids = [rid for rid in cl.get("request_ids", []) if rid in by_id] or _by_tag(set(cl["equipment_tags"]))
        isolation_clusters.append(
            {
                "id": cl["id"],
                "type": "isolation",
                "name": cl["name"],
                "equipment_tags": cl["equipment_tags"],
                "boundary_valve_count": int(cl.get("boundary_valve_count", len(cl.get("boundary_valves", [])))),
                "request_ids": req_ids,
                "shared_hours": int(cl["shared_hours"]),
                "shared_cost_usd": int(cl["shared_cost_usd"]),
            }
        )

    access_clusters = []
    for cl in cd_doc["access_clusters"]:
        req_ids = [rid for rid in cl.get("request_ids", []) if rid in by_id] or _by_tag(set(cl["equipment_tags"]))
        access_clusters.append(
            {
                "id": cl["id"],
                "type": "access",
                "name": cl["name"],
                "area": cl.get("area", ""),
                "equipment_tags": cl["equipment_tags"],
                "request_ids": req_ids,
                "shared_hours": int(cl["shared_hours"]),
                "shared_cost_usd": int(cl["shared_cost_usd"]),
            }
        )

    duplicate_pairs = []
    for pair in cd_doc["duplicate_pairs"]:
        rids = [rid for rid in pair["request_ids"] if rid in by_id]
        overlap_hrs = int(pair.get("overlap_hours", min((by_id[r]["estimate_hours"] for r in rids), default=0)))
        overlap_cost = int(pair.get("overlap_cost_usd", min((by_id[r]["estimate_cost_usd"] for r in rids), default=0)))
        duplicate_pairs.append(
            {
                "id": pair["id"],
                "equipment_tag": pair["equipment_tag"],
                "request_ids": rids,
                "source_groups": [by_id[r]["source_group"] for r in rids],
                "overlap_hours": overlap_hrs,
                "overlap_cost_usd": overlap_cost,
                "reason": pair.get("reason", ""),
                "titles": [by_id[r]["title"] for r in rids],
            }
        )

    return {
        "scaffold_clusters": scaffold_clusters,
        "isolation_clusters": isolation_clusters,
        "access_clusters": access_clusters,
        "duplicate_pairs": duplicate_pairs,
    }


def evaluate_cut_line(
    *,
    scope_items: list[dict[str, Any]],
    clusters_payload: dict[str, Any],
    budget_usd: int,
) -> dict[str, Any]:
    """Rank active scope (mandatory first, then RIPT desc, then incremental cost per RIPT asc) using clustered shared costs."""
    active = [it for it in scope_items if it.get("status") not in {"deleted", "rejected", "screened_out"}]

    all_clusters = (
        clusters_payload["scaffold_clusters"]
        + clusters_payload["isolation_clusters"]
        + clusters_payload["access_clusters"]
    )
    cluster_cost: dict[str, int] = {c["id"]: int(c["shared_cost_usd"]) for c in all_clusters}
    clusters_of_req: dict[str, list[str]] = defaultdict(list)
    for cl in all_clusters:
        for rid in cl["request_ids"]:
            clusters_of_req[rid].append(cl["id"])

    # Compute direct cost per request (backing out per-job unclustered share when shared cluster cost applies,
    # keeping direct >= 65% of estimate so clustered cost <= unclustered sum cleanly).
    unclustered_cost: dict[str, int] = {}
    direct_cost: dict[str, int] = {}
    for it in active:
        rid = it["request_id"]
        est = int(it["estimate_cost_usd"])
        unclustered_cost[rid] = est
        cids = clusters_of_req.get(rid, [])
        if cids:
            # Share of cluster overhead embedded in individual request estimate
            share_deduct = sum(cluster_cost[cid] // max(2, len(next(c["request_ids"] for c in all_clusters if c["id"] == cid))) for cid in cids)
            direct_cost[rid] = max(round(est * 0.65), est - share_deduct)
        else:
            direct_cost[rid] = est

    def _rank_key(it: dict[str, Any]) -> tuple[int, int, float, str]:
        rid = it["request_id"]
        ript = max(1, int(it.get("ript_score", 1)))
        return (
            0 if it.get("mandatory") else 1,
            -ript,
            direct_cost[rid] / float(ript),
            rid,
        )

    ordered = sorted(active, key=_rank_key)

    above_ids: list[str] = []
    below_ids: list[str] = []
    paid_clusters: set[str] = set()
    running_cost = 0
    mandatory_cost = 0
    above_hours = 0
    below_hours = 0
    above_unclustered = 0

    # First pass: include all mandatory items
    mandatory_items = [it for it in ordered if it.get("mandatory")]
    discretionary_items = [it for it in ordered if not it.get("mandatory")]

    for it in mandatory_items:
        rid = it["request_id"]
        new_clusters = [cid for cid in clusters_of_req.get(rid, []) if cid not in paid_clusters]
        inc = direct_cost[rid] + sum(cluster_cost[cid] for cid in new_clusters)
        paid_clusters.update(new_clusters)
        running_cost += inc
        mandatory_cost = running_cost
        above_ids.append(rid)
        above_hours += int(it["estimate_hours"])
        above_unclustered += unclustered_cost[rid]

    feasible = running_cost <= budget_usd
    shortfall = max(0, running_cost - budget_usd)

    if feasible:
        for it in discretionary_items:
            rid = it["request_id"]
            new_clusters = [cid for cid in clusters_of_req.get(rid, []) if cid not in paid_clusters]
            inc = direct_cost[rid] + sum(cluster_cost[cid] for cid in new_clusters)
            if running_cost + inc <= budget_usd:
                paid_clusters.update(new_clusters)
                running_cost += inc
                above_ids.append(rid)
                above_hours += int(it["estimate_hours"])
                above_unclustered += unclustered_cost[rid]
            else:
                below_ids.append(rid)
                below_hours += int(it["estimate_hours"])
    else:
        for it in discretionary_items:
            below_ids.append(it["request_id"])
            below_hours += int(it["estimate_hours"])

    below_cost = sum(unclustered_cost[rid] for rid in below_ids)
    shared_saved = max(0, above_unclustered - running_cost)

    return {
        "budget_usd": int(budget_usd),
        "feasible": feasible,
        "shortfall_usd": int(shortfall),
        "mandatory_cost_usd": int(mandatory_cost),
        "above_count": len(above_ids),
        "below_count": len(below_ids),
        "above_cost_usd": int(running_cost),
        "above_unclustered_cost_usd": int(above_unclustered),
        "shared_cost_saved_usd": int(shared_saved),
        "below_cost_usd": int(below_cost),
        "above_hours": int(above_hours),
        "below_hours": int(below_hours),
        "active_clusters": sorted(paid_clusters),
        "above_ids": above_ids,
        "below_ids": below_ids,
    }
