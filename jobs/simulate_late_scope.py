#!/usr/bin/env python3
"""Run the scripted Unit 200 post-freeze late-scope simulation through IMPACT Web's public API.

Raises 18 approved adds, 6 approved deletes, and 5 rejected adds from data/scenario/late-scope.json
using J. Planner (raise) and M. Turnaround (TA manager approve/reject), then triggers a normal Twin
sync so scope growth appears on the KPI panel. Never writes directly to the Twin database.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

MARKER_RE = re.compile(r"\[SIM:(CR-200-\d+)\]")


def _find_delete_target(
    work_requests: list[dict[str, Any]],
    *,
    equipment_tag: str,
    abs_hours: int,
    used_ids: set[str],
    true_tag_by_request: dict[str, str],
) -> dict[str, Any] | None:
    """Fail-closed lookup of an eligible non-deleted work request belonging to equipment_tag."""
    tag_upper = equipment_tag.upper()
    token_re = re.compile(rf"(?<![A-Z0-9-]){re.escape(tag_upper)}(?![A-Z0-9-])")

    # Pass 1: exact answer-key / scenario tag match with enough hours
    for wr in work_requests:
        if wr["id"] in used_ids or wr["status"] == "deleted":
            continue
        if true_tag_by_request.get(wr["id"], "").upper() == tag_upper and int(wr["estimate_hours"]) >= abs_hours:
            return wr

    # Pass 2: exact tag token in equipment_text or title with enough hours
    for wr in work_requests:
        if wr["id"] in used_ids or wr["status"] == "deleted":
            continue
        hay = f"{wr.get('equipment_text', '')} {wr.get('title', '')}".upper()
        if token_re.search(hay) and int(wr["estimate_hours"]) >= abs_hours:
            return wr

    # Fail closed: never delete an unrelated equipment's work request
    return None


def _index_existing_scripted_crs(crs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_change_id: dict[str, dict[str, Any]] = {}
    for cr in crs:
        m = MARKER_RE.search(str(cr.get("evidence", "")))
        if m:
            by_change_id[m.group(1)] = cr
    return by_change_id


def run_late_scope_simulation(
    *,
    impactweb_client: Any,
    twin_client: Any | None = None,
    scenario_dir: Path,
    exercise_id: str = "EX-DEMO",
    planner_email: str = "j.planner@demo.local",
    ta_email: str = "ta.manager@demo.local",
    password: str = "demo-pass-2028",
) -> dict[str, Any]:
    """Execute the 29 scripted changes idempotently via IMPACT Web public API and sync Twin."""
    late_path = scenario_dir / "late-scope.json"
    data = json.loads(late_path.read_text(encoding="utf-8"))
    scripted = data["scripted_changes"]

    ak_path = scenario_dir / "answer-key.json"
    true_tag_by_request: dict[str, str] = {}
    if ak_path.is_file():
        for row in json.loads(ak_path.read_text(encoding="utf-8")).get("rows", []):
            true_tag_by_request[row["request_id"]] = row["true_tag"]

    r_pl = impactweb_client.post("/api/v1/auth/login", json={"email": planner_email, "password": password})
    r_pl.raise_for_status()
    pl_hdr = {"Authorization": f"Bearer {r_pl.json()['access_token']}"}

    r_ta = impactweb_client.post("/api/v1/auth/login", json={"email": ta_email, "password": password})
    r_ta.raise_for_status()
    ta_hdr = {"Authorization": f"Bearer {r_ta.json()['access_token']}"}

    ex = impactweb_client.get(f"/api/v1/exercises/{exercise_id}", headers=ta_hdr)
    ex.raise_for_status()
    if not ex.json().get("frozen"):
        raise RuntimeError(f"Exercise {exercise_id} must be frozen in IMPACT Web before running late-scope simulation")

    existing_crs_resp = impactweb_client.get(f"/api/v1/change-requests?exercise_id={exercise_id}", headers=ta_hdr)
    existing_crs_resp.raise_for_status()
    existing_by_cid = _index_existing_scripted_crs(existing_crs_resp.json())

    wrs_resp = impactweb_client.get(f"/api/v1/work-requests?exercise_id={exercise_id}", headers=ta_hdr)
    wrs_resp.raise_for_status()
    work_requests = wrs_resp.json()
    used_delete_targets: set[str] = {
        cr["request_id"] for cr in existing_by_cid.values() if cr.get("change_type") == "delete" and cr.get("request_id")
    }

    master = json.loads((scenario_dir / "equipment-master.json").read_text(encoding="utf-8"))
    area_by_tag = {e["tag"]: e["area"] for e in master["major_equipment"]}

    adds_approved = 0
    deletes_approved = 0
    rejected = 0
    resumed_pending = 0
    skipped_existing = 0

    for item in scripted:
        cid = item["change_id"]
        ctype = item["type"]
        decision = item["decision"]

        existing = existing_by_cid.get(cid)
        if existing is not None:
            if existing["status"] == decision:
                skipped_existing += 1
                continue
            if existing["status"] == "pending":
                r_dec = impactweb_client.post(
                    f"/api/v1/change-requests/{existing['id']}/decide?exercise_id={exercise_id}",
                    json={"decision": decision, "reason": f"{item['checkpoint']} DRB review: {item['reason']}"},
                    headers=ta_hdr,
                )
                r_dec.raise_for_status()
                resumed_pending += 1
                if decision == "approved" and ctype == "add":
                    adds_approved += 1
                elif decision == "approved" and ctype == "delete":
                    deletes_approved += 1
                else:
                    rejected += 1
                continue
            raise RuntimeError(
                f"Scripted change {cid} ({existing['id']}) is in conflicting state {existing['status']!r}, expected {decision!r}"
            )

        target_id: str | None = None
        if ctype == "delete":
            target = _find_delete_target(
                work_requests,
                equipment_tag=item["equipment_tag"],
                abs_hours=abs(int(item["hours_delta"])),
                used_ids=used_delete_targets,
                true_tag_by_request=true_tag_by_request,
            )
            if target is None:
                raise RuntimeError(
                    f"No exact eligible delete target found for {cid} on equipment {item['equipment_tag']}"
                )
            target_id = target["id"]
            used_delete_targets.add(target_id)

        payload = {
            "exercise_id": exercise_id,
            "request_id": target_id,
            "change_type": ctype,
            "mandatory": bool(item["mandatory"]),
            "schedule_impact_days": float(item.get("schedule_impact_days", 0.0)),
            "risk_if_not_done": item["reason"],
            "hours_delta": int(item["hours_delta"]),
            "cost_delta_usd": int(item["cost_delta_usd"]),
            "title": item["title"],
            "equipment_text": item["equipment_tag"],
            "category": "Late Scope" if ctype == "add" else "Scope Removal",
            "driver": "inspection" if item["source_group"] == "inspection" else "reliability",
            "source_group": item["source_group"],
            "area": area_by_tag.get(item["equipment_tag"], "200-C"),
            "evidence": f"[SIM:{cid}] Scripted checkpoint {item['checkpoint']}.",
            "reason": item["reason"],
        }

        r_cr = impactweb_client.post("/api/v1/change-requests", json=payload, headers=pl_hdr)
        r_cr.raise_for_status()
        cr_id = r_cr.json()["id"]

        r_dec = impactweb_client.post(
            f"/api/v1/change-requests/{cr_id}/decide?exercise_id={exercise_id}",
            json={"decision": decision, "reason": f"{item['checkpoint']} DRB review: {item['reason']}"},
            headers=ta_hdr,
        )
        r_dec.raise_for_status()

        if decision == "approved" and ctype == "add":
            adds_approved += 1
        elif decision == "approved" and ctype == "delete":
            deletes_approved += 1
        else:
            rejected += 1

    sync_result = None
    if twin_client is not None:
        r_sync = twin_client.post(f"/api/v1/sync?exercise_id={exercise_id}")
        r_sync.raise_for_status()
        sync_result = r_sync.json()

    return {
        "exercise_id": exercise_id,
        "adds_approved": adds_approved,
        "deletes_approved": deletes_approved,
        "rejected": rejected,
        "resumed_pending": resumed_pending,
        "skipped_existing": skipped_existing,
        "sync_result": sync_result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run scripted Unit 200 late-scope simulation against IMPACT Web + Twin.")
    parser.add_argument("--impactweb-url", default=os.environ.get("IMPACTWEB_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--twin-url", default=os.environ.get("TWIN_URL", "http://127.0.0.1:8002"))
    parser.add_argument("--exercise-id", default="EX-DEMO")
    parser.add_argument("--scenario-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "scenario")
    args = parser.parse_args(argv)

    with httpx.Client(base_url=args.impactweb_url, timeout=20.0) as iw_cli, httpx.Client(
        base_url=args.twin_url, timeout=20.0
    ) as twin_cli:
        summary = run_late_scope_simulation(
            impactweb_client=iw_cli,
            twin_client=twin_cli,
            scenario_dir=args.scenario_dir,
            exercise_id=args.exercise_id,
        )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
