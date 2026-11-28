"""Serialized, idempotent per-exercise sync engine bridging IMPACT Web + CMMS to the Twin."""

from __future__ import annotations

import copy
import json
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from twin.clients import CmmsClient, ImpactWebClient
from twin.clusters import compute_clusters_and_duplicates, evaluate_cut_line
from twin.matcher import ALLOWED_WORK_TYPE_LABELS, AiClientConfig, MatchingPipeline


class ExerciseSyncState:
    def __init__(self, exercise_id: str):
        self.exercise_id = exercise_id
        self.cursor_seq: int = 0
        self.epoch: int = 1
        self.exercise_meta: dict[str, Any] = {}
        self.scope_items: dict[str, dict[str, Any]] = {}
        self.manual_reviews: dict[str, dict[str, Any]] = {}  # request_id -> {version, equipment_text, decision...}
        self.baseline_freeze_id: str | None = None
        self.baseline_items: list[dict[str, Any]] = []
        self.change_events: dict[str, dict[str, Any]] = {}  # keyed by change_request_id (unique!)
        self.all_change_requests: list[dict[str, Any]] = []
        self.saved_cut_line_runs: list[dict[str, Any]] = []
        self.last_synced_at: str | None = None


class SyncEngine:
    """One serialized sync per exercise at a time (docs/design.md section 5.2)."""

    def __init__(
        self,
        *,
        plant_store: Any,
        scenario_dir: Path,
        impactweb_client: ImpactWebClient | None = None,
        cmms_client: CmmsClient | None = None,
        ai_config: AiClientConfig | None = None,
        recorded_ai_responses: dict[str, dict[str, Any]] | None = None,
        match_rate_gate: float = 0.95,
    ):
        self.plant_store = plant_store
        self.scenario_dir = scenario_dir
        self.impactweb_client = impactweb_client
        self.cmms_client = cmms_client
        self.ai_config = ai_config or AiClientConfig.from_env()
        self.recorded_ai_responses = recorded_ai_responses or self._load_recorded_ai_fixtures()
        self.match_rate_gate = match_rate_gate

        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._states: dict[str, ExerciseSyncState] = {}
        self._cmms_rows: list[dict[str, Any]] = []
        self._pipeline: MatchingPipeline | None = None
        self._answer_key_rows: list[dict[str, Any]] = []
        ak_path = scenario_dir / "answer-key.json"
        if ak_path.is_file():
            self._answer_key_rows = json.loads(ak_path.read_text(encoding="utf-8")).get("rows", [])

    def _load_recorded_ai_fixtures(self) -> dict[str, dict[str, Any]]:
        fix_path = self.scenario_dir / "matcher-ai-fixtures.json"
        if fix_path.is_file():
            return json.loads(fix_path.read_text(encoding="utf-8")).get("by_request_id", {})
        return {}

    def _ensure_pipeline(self) -> MatchingPipeline:
        if self._pipeline is not None:
            return self._pipeline
        if self.cmms_client is not None:
            self._cmms_rows = self.cmms_client.list_equipment()
        else:
            self._cmms_rows = self._fallback_cmms_from_scenario()
        self._pipeline = MatchingPipeline(
            cmms_rows=self._cmms_rows,
            plant_equipment=self.plant_store.list_equipment(),
            envelopes=self.plant_store.list_envelopes(),
            ai_config=self.ai_config,
            recorded_ai_responses=self.recorded_ai_responses,
        )
        return self._pipeline

    def _fallback_cmms_from_scenario(self) -> list[dict[str, Any]]:
        master = json.loads((self.scenario_dir / "equipment-master.json").read_text(encoding="utf-8"))
        rows: list[dict[str, Any]] = []
        for eq in master["major_equipment"]:
            rows.append({**eq, "unit": "200", "status": "active"})
        for psv in master["psvs"]:
            rows.append({**psv, "equipment_class": "psv", "shacl_class": "ReliefValve", "parent_tag": psv["protects_tag"], "unit": "200", "status": "active"})
        for v in master["valves"]:
            rows.append({**v, "equipment_class": "valve", "shacl_class": "BlockValve" if v["role"] == "block" else "Valve", "parent_tag": v["parent_equipment"], "unit": "200", "status": "active"})
        for inst in master["instruments"]:
            rows.append({**inst, "equipment_class": "instrument", "shacl_class": "Instrument", "parent_tag": inst["measures_tag"], "unit": "200", "status": "active"})
        for seg in master["piping_segments"]:
            rows.append({**seg, "tag": seg["line_number"], "equipment_class": "piping", "shacl_class": "PipingSegment", "parent_tag": seg["parent_equipment"], "unit": "200", "status": "active"})
        for inact in master["inactive_or_external_tags"]:
            rows.append({**inact, "equipment_class": "exchanger" if inact["tag"].startswith("E-") else ("pump" if inact["tag"].startswith("P-") else "psv"), "shacl_class": "Asset", "area": f"{inact['unit']}-X", "sheet": ""})
        return rows

    def _serialize_state(self, state: ExerciseSyncState) -> dict[str, Any]:
        return {
            "exercise_id": state.exercise_id,
            "cursor_seq": state.cursor_seq,
            "epoch": state.epoch,
            "exercise_meta": state.exercise_meta,
            "scope_items": state.scope_items,
            "manual_reviews": state.manual_reviews,
            "baseline_freeze_id": state.baseline_freeze_id,
            "baseline_items": state.baseline_items,
            "change_events": state.change_events,
            "all_change_requests": state.all_change_requests,
            "saved_cut_line_runs": state.saved_cut_line_runs,
            "last_synced_at": state.last_synced_at,
        }

    def _hydrate_state(self, snap: dict[str, Any]) -> ExerciseSyncState:
        st = ExerciseSyncState(snap["exercise_id"])
        st.cursor_seq = int(snap.get("cursor_seq", 0))
        st.epoch = int(snap.get("epoch", 1))
        st.exercise_meta = dict(snap.get("exercise_meta", {}))
        st.scope_items = dict(snap.get("scope_items", {}))
        st.manual_reviews = dict(snap.get("manual_reviews", {}))
        st.baseline_freeze_id = snap.get("baseline_freeze_id")
        st.baseline_items = list(snap.get("baseline_items", []))
        st.change_events = dict(snap.get("change_events", {}))
        st.all_change_requests = list(snap.get("all_change_requests", []))
        st.saved_cut_line_runs = list(snap.get("saved_cut_line_runs", []))
        st.last_synced_at = snap.get("last_synced_at")
        return st

    def _get_state(self, exercise_id: str) -> ExerciseSyncState:
        if exercise_id not in self._states:
            persisted = (
                self.plant_store.load_exercise_state(exercise_id)
                if hasattr(self.plant_store, "load_exercise_state")
                else None
            )
            if persisted is not None:
                self._states[exercise_id] = self._hydrate_state(persisted)
            else:
                self._states[exercise_id] = ExerciseSyncState(exercise_id)
        return self._states[exercise_id]

    def _push_scope_to_graph_store(self, state: ExerciseSyncState) -> None:
        if not hasattr(self.plant_store, "set_scope_graph"):
            return
        scope_nodes: list[dict[str, Any]] = []
        scope_rels: list[dict[str, Any]] = []
        ex = state.exercise_id
        for it in state.scope_items.values():
            skey = f"wr:{ex}:{it['request_id']}"
            raw_wt = str(it.get("work_type_label", "GeneralCleanup"))
            safe_wt = raw_wt if raw_wt in ALLOWED_WORK_TYPE_LABELS else "GeneralCleanup"
            scope_nodes.append(
                {
                    "key": skey,
                    "labels": ["ScopeItem", safe_wt],
                    "props": {
                        "exercise_id": ex,
                        "request_id": it["request_id"],
                        "version": it["version"],
                        "title": it["title"],
                        "driver": it["driver"],
                        "source_group": it["source_group"],
                        "area": it["area"],
                        "ript": it["ript_score"],
                        "estimate_hours": max(1, int(it["estimate_hours"])),
                        "estimate_cost_usd": max(1, int(it["estimate_cost_usd"])),
                        "status": it["status"],
                        "match_status": it["match_status"],
                        "resolved_tag": it["resolved_tag"] or "",
                    },
                }
            )
            if it["match_status"] == "accepted" and it["resolved_tag"]:
                tag = it["resolved_tag"]
                target_key = self._asset_key_for_tag(tag)
                if target_key:
                    scope_rels.append(
                        {
                            "from": skey,
                            "to": target_key,
                            "type": "RESOLVES_TO",
                            "props": {
                                "method": it["match_method"],
                                "confidence": it["confidence"],
                                "status": "accepted",
                            },
                        }
                    )
        self.plant_store.set_scope_graph(
            ex,
            scope_nodes,
            scope_rels,
            sync_snapshot=self._serialize_state(state),
        )

    def _asset_key_for_tag(self, tag: str) -> str | None:
        if self.plant_store.get_equipment(tag) is not None:
            return f"eq:{tag}"
        cmms = self._pipeline.cmms_by_tag.get(tag) if self._pipeline else None
        if cmms is None:
            return None
        cls = cmms.get("equipment_class")
        if cls == "psv":
            return f"psv:{tag}"
        if cls == "valve":
            return f"valve:{tag}"
        if cls == "instrument":
            return f"inst:{tag}"
        if cls == "piping":
            return f"pipe:{tag}"
        return f"eq:{tag}"

    def sync_exercise(self, exercise_id: str = "EX-DEMO", *, use_ai: bool = False, live_ai: bool = False) -> dict[str, Any]:
        """Pull latest IMPACT Web state + change feed for exercise_id in one serialized step."""
        with self._locks[exercise_id]:
            pipeline = self._ensure_pipeline()
            state = self._get_state(exercise_id)

            if self.impactweb_client is not None:
                ex_meta = self.impactweb_client.get_exercise(exercise_id)
                if ex_meta.get("epoch", 1) != state.epoch:
                    # Exercise was reset in IMPACT Web -> wipe stale state cleanly
                    state = ExerciseSyncState(exercise_id)
                    state.epoch = int(ex_meta.get("epoch", 1))
                    self._states[exercise_id] = state
                state.exercise_meta = ex_meta
                wrs = self.impactweb_client.list_work_requests(exercise_id)
                feed = self.impactweb_client.get_changes(exercise_id, after_seq=state.cursor_seq)
                crs = self.impactweb_client.list_change_requests(exercise_id)
                freeze_id = ex_meta.get("freeze_id")
                if freeze_id and state.baseline_freeze_id != freeze_id:
                    state.baseline_items = self.impactweb_client.get_freeze_items(freeze_id)
                    state.baseline_freeze_id = freeze_id
            else:
                wl = json.loads((self.scenario_dir / "work-requests.json").read_text(encoding="utf-8"))
                wrs = [
                    {
                        "id": r["request_id"],
                        "exercise_id": exercise_id,
                        "event_id": r["event_id"],
                        "title": r["title"],
                        "description": r["description"],
                        "equipment_text": r["equipment_text"],
                        "category": r["category"],
                        "work_type_label": r["work_type_label"],
                        "driver": r["driver"],
                        "source_group": r["source_group"],
                        "area": r["area"],
                        "ript_score": r["ript_score"],
                        "mandatory": r["mandatory"],
                        "estimate_hours": r["estimate_hours"],
                        "estimate_hours_by_craft": r["estimate_hours_by_craft"],
                        "estimate_cost_usd": r["estimate_cost_usd"],
                        "status": "candidate",
                        "version": 1,
                        "updated_at": "",
                    }
                    for r in wl["work_requests"]
                ]
                feed = []
                crs = []
                state.exercise_meta = {
                    "id": exercise_id,
                    "name": "TAR-200-2028 Scripted Demo",
                    "mode": "demo",
                    "twin_write_through": True,
                    "frozen": False,
                    "freeze_id": None,
                    "epoch": 1,
                }

            # Upsert scope items + preserve human review decisions while equipment_text is unchanged
            new_scope: dict[str, dict[str, Any]] = {}
            for wr in wrs:
                rid = wr["id"]
                existing = state.scope_items.get(rid)
                manual = state.manual_reviews.get(rid)
                if (
                    existing is not None
                    and existing["version"] == wr["version"]
                    and existing["equipment_text"] == wr["equipment_text"]
                    and existing["status"] == wr["status"]
                    and existing["estimate_hours"] == wr["estimate_hours"]
                ):
                    new_scope[rid] = existing
                    continue

                matched = pipeline.match_work_request(wr, use_ai=use_ai, live_ai=live_ai)
                item = {
                    "request_id": rid,
                    "exercise_id": exercise_id,
                    "event_id": wr.get("event_id", "TAR-200-2028"),
                    "version": wr["version"],
                    "title": wr["title"],
                    "description": wr["description"],
                    "equipment_text": wr["equipment_text"],
                    "category": wr["category"],
                    "work_type_label": wr.get("work_type_label", "GeneralCleanup"),
                    "driver": wr["driver"],
                    "source_group": wr["source_group"],
                    "area": wr["area"],
                    "ript_score": wr["ript_score"],
                    "mandatory": wr.get("mandatory", False),
                    "estimate_hours": wr["estimate_hours"],
                    "estimate_hours_by_craft": wr.get("estimate_hours_by_craft", {}),
                    "estimate_cost_usd": wr["estimate_cost_usd"],
                    "status": wr["status"],
                    "match_status": matched["match_status"],
                    "resolved_tag": matched["resolved_tag"],
                    "match_method": matched["match_method"],
                    "confidence": matched["confidence"],
                    "proposal": matched["proposal"],
                    "mapping_trace": matched["mapping_trace"],
                }
                # Re-apply manual review decision if equipment_text did not change
                if manual and manual["equipment_text"] == wr["equipment_text"]:
                    self._apply_manual_decision_to_item(item, manual)
                new_scope[rid] = item

            state.scope_items = new_scope
            state.all_change_requests = crs

            # Record approved change requests as unique ChangeEvents (deduped on change_request_id!)
            for cr in crs:
                if cr.get("status") == "approved":
                    cr_id = cr["id"]
                    if cr_id not in state.change_events:
                        state.change_events[cr_id] = {
                            "change_request_id": cr_id,
                            "request_id": cr.get("request_id"),
                            "type": cr.get("change_type"),
                            "mandatory": bool(cr.get("mandatory")),
                            "hours_delta": int(cr.get("hours_delta", 0)),
                            "cost_delta_usd": int(cr.get("cost_delta_usd", 0)),
                            "reason": cr.get("reason", ""),
                            "raised_by": cr.get("raised_by_name") or cr.get("raised_by", ""),
                            "raised_via": cr.get("raised_via", "iw"),
                            "source_group": cr.get("source_group") or "fixed_equipment",
                            "at": cr.get("decided_at") or cr.get("created_at"),
                        }

            # Advance cursor monotonically
            if feed:
                state.cursor_seq = max(state.cursor_seq, max(int(e["seq"]) for e in feed))
            state.last_synced_at = datetime.now(timezone.utc).isoformat()
            self._push_scope_to_graph_store(state)

            return {
                "exercise_id": exercise_id,
                "cursor_seq": state.cursor_seq,
                "synced_count": len(state.scope_items),
                "feed_events_applied": len(feed),
                "baseline_freeze_id": state.baseline_freeze_id,
                "baseline_item_count": len(state.baseline_items),
                "change_event_count": len(state.change_events),
                "growth_hours": sum(ev["hours_delta"] for ev in state.change_events.values()),
                "last_synced_at": state.last_synced_at,
            }

    def _apply_manual_decision_to_item(self, item: dict[str, Any], manual: dict[str, Any]) -> None:
        pipeline = self._ensure_pipeline()
        action = manual["action"]
        if action in {"accept", "pick_another"}:
            tag = manual["tag"]
            cmms = pipeline.cmms_by_tag.get(tag, {})
            eq_meta = pipeline.plant_by_tag.get(tag, {})
            item["match_status"] = "accepted"
            item["resolved_tag"] = tag
            item["match_method"] = "human_review" if action == "pick_another" else (item["proposal"]["method"] if item.get("proposal") else "human_review")
            item["confidence"] = 1.0
            item["mapping_trace"]["decision"] = {
                "outcome": "accepted",
                "decided_by": manual["reviewer"],
                "decided_at": manual["decided_at"],
                "reason": manual["reason"],
            }
            item["mapping_trace"]["result"] = {
                "tag": tag,
                "sheet": cmms.get("sheet", ""),
                "area": cmms.get("area", ""),
                "envelopes": pipeline.envelopes_by_tag.get(tag, []),
                "plot_position": eq_meta.get("plot_position"),
            }
        elif action == "reject":
            item["match_status"] = "rejected"
            item["resolved_tag"] = None
            item["mapping_trace"]["decision"] = {
                "outcome": "rejected",
                "decided_by": manual["reviewer"],
                "decided_at": manual["decided_at"],
                "reason": manual["reason"],
            }
            item["mapping_trace"]["result"] = None

    def decide_review(
        self,
        *,
        exercise_id: str,
        request_id: str,
        action: str,
        reviewer: str,
        reason: str = "",
        tag: str | None = None,
    ) -> dict[str, Any]:
        with self._locks[exercise_id]:
            pipeline = self._ensure_pipeline()
            state = self._get_state(exercise_id)
            item = state.scope_items.get(request_id)
            if item is None:
                raise KeyError(f"ScopeItem {request_id} not found in {exercise_id}")
            chosen_tag = tag
            if action == "accept":
                if chosen_tag is None and item.get("proposal"):
                    chosen_tag = item["proposal"]["tag"]
                if not chosen_tag:
                    raise ValueError("Cannot accept without a proposed or supplied tag")
            if action in {"accept", "pick_another"}:
                if not chosen_tag or chosen_tag not in pipeline.active_u200_tags:
                    raise ValueError(f"Tag {chosen_tag!r} is not an active Unit 200 tag")

            manual = {
                "action": action,
                "tag": chosen_tag,
                "reviewer": reviewer,
                "reason": reason,
                "equipment_text": item["equipment_text"],
                "decided_at": datetime.now(timezone.utc).isoformat(),
            }
            state.manual_reviews[request_id] = manual
            self._apply_manual_decision_to_item(item, manual)
            self._push_scope_to_graph_store(state)
            return copy.deepcopy(item)

    def list_scope_items(self, exercise_id: str) -> list[dict[str, Any]]:
        state = self._get_state(exercise_id)
        return [copy.deepcopy(v) for _, v in sorted(state.scope_items.items())]

    def get_scope_item(self, exercise_id: str, request_id: str) -> dict[str, Any] | None:
        state = self._get_state(exercise_id)
        it = state.scope_items.get(request_id)
        return copy.deepcopy(it) if it else None

    def matching_summary(self, exercise_id: str) -> dict[str, Any]:
        state = self._get_state(exercise_id)
        active = [it for it in state.scope_items.values() if it["status"] not in {"deleted", "rejected", "screened_out"}]
        total = len(active)
        accepted = sum(1 for it in active if it["match_status"] == "accepted")
        proposed = sum(1 for it in active if it["match_status"] == "needs_review" and it.get("proposal") is not None)
        needs_review = sum(1 for it in active if it["match_status"] == "needs_review")
        rejected = sum(1 for it in active if it["match_status"] == "rejected")
        rate = (accepted / total) if total > 0 else None
        coverage = ((accepted + proposed) / total) if total > 0 else None

        by_area: dict[str, dict[str, Any]] = {}
        by_source: dict[str, dict[str, Any]] = {}
        for it in active:
            for grp_map, key in ((by_area, it["area"]), (by_source, it["source_group"])):
                b = grp_map.setdefault(key, {"key": key, "total": 0, "accepted": 0, "needs_review": 0})
                b["total"] += 1
                if it["match_status"] == "accepted":
                    b["accepted"] += 1
                elif it["match_status"] == "needs_review":
                    b["needs_review"] += 1
        for m in (by_area, by_source):
            for b in m.values():
                b["match_rate"] = round(b["accepted"] / b["total"], 4) if b["total"] else 0.0

        return {
            "exercise_id": exercise_id,
            "total_active": total,
            "accepted_count": accepted,
            "proposal_coverage_count": accepted + proposed,
            "needs_review_count": needs_review,
            "rejected_count": rejected,
            "match_rate": round(rate, 4) if rate is not None else None,
            "proposal_coverage_rate": round(coverage, 4) if coverage is not None else None,
            "gate_threshold": self.match_rate_gate,
            "gate_passed": bool(rate is not None and rate >= self.match_rate_gate),
            "by_area": sorted(by_area.values(), key=lambda x: x["key"]),
            "by_source_group": sorted(by_source.values(), key=lambda x: x["key"]),
        }

    def review_queue(self, exercise_id: str) -> list[dict[str, Any]]:
        state = self._get_state(exercise_id)
        return [
            copy.deepcopy(it)
            for _, it in sorted(state.scope_items.items())
            if it["match_status"] == "needs_review"
        ]

    def matching_lab_step(self, exercise_id: str, request_id: str) -> dict[str, Any]:
        it = self.get_scope_item(exercise_id, request_id)
        if it is None:
            raise KeyError(f"ScopeItem {request_id} not found")
        ak_map = {r["request_id"]: r for r in self._answer_key_rows}
        return {
            "item": it,
            "answer_key": ak_map.get(request_id),
        }

    def matching_lab_compare(self, exercise_id: str, *, live_ai: bool = False) -> dict[str, Any]:
        pipeline = self._ensure_pipeline()
        state = self._get_state(exercise_id)
        wrs = [
            {
                "id": it["request_id"],
                "title": it["title"],
                "description": it["description"],
                "equipment_text": it["equipment_text"],
                "area": it["area"],
                "work_type_label": it["work_type_label"],
                "updated_at": "",
            }
            for _, it in sorted(state.scope_items.items())
        ]
        return pipeline.run_lab_comparison(wrs, self._answer_key_rows, live_ai=live_ai)

    def clusters_and_duplicates(self, exercise_id: str) -> dict[str, Any]:
        state = self._get_state(exercise_id)
        return compute_clusters_and_duplicates(
            scope_items=list(state.scope_items.values()),
            scenario_dir=self.scenario_dir,
        )

    def evaluate_cut_line(self, exercise_id: str, budget_usd: int, save_name: str | None = None, saved_by: str = "") -> dict[str, Any]:
        state = self._get_state(exercise_id)
        clusters = self.clusters_and_duplicates(exercise_id)
        result = evaluate_cut_line(
            scope_items=list(state.scope_items.values()),
            clusters_payload=clusters,
            budget_usd=budget_usd,
        )
        if save_name:
            run_rec = {
                "name": save_name,
                "budget_usd": budget_usd,
                "saved_by": saved_by or "planner",
                "at": datetime.now(timezone.utc).isoformat(),
                "feasible": result["feasible"],
                "shortfall_usd": result["shortfall_usd"],
                "above_count": result["above_count"],
                "below_count": result["below_count"],
            }
            state.saved_cut_line_runs.append(run_rec)
        return result
