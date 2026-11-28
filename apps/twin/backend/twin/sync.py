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
        self.baseline_frozen_at: str | None = None
        self.baseline_list_version: int = 0
        self.baseline_items: list[dict[str, Any]] = []
        self.match_by_version: dict[str, dict[str, Any]] = {}  # f"{request_id}@v{version}" -> match snapshot
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
            "baseline_frozen_at": state.baseline_frozen_at,
            "baseline_list_version": state.baseline_list_version,
            "baseline_items": state.baseline_items,
            "match_by_version": state.match_by_version,
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
        st.baseline_frozen_at = snap.get("baseline_frozen_at")
        st.baseline_list_version = int(snap.get("baseline_list_version", 0))
        st.baseline_items = list(snap.get("baseline_items", []))
        st.match_by_version = dict(snap.get("match_by_version", {}))
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
                    state.baseline_frozen_at = datetime.now(timezone.utc).isoformat()
                    state.baseline_list_version = 1
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
                state.match_by_version[f"{rid}@v{item['version']}"] = self._match_snapshot(item)

            for rid, item in new_scope.items():
                vkey = f"{rid}@v{item['version']}"
                if vkey not in state.match_by_version:
                    state.match_by_version[vkey] = self._match_snapshot(item)

            # Ensure every frozen item version has a pinned match snapshot (even if already past frozen version)
            if state.baseline_items:
                for bi in state.baseline_items:
                    brid = bi["request_id"]
                    bver = int(bi.get("request_version", 1))
                    bkey = f"{brid}@v{bver}"
                    if bkey not in state.match_by_version:
                        frozen_match = pipeline.match_work_request(
                            {
                                "id": brid,
                                "title": bi.get("title", ""),
                                "description": bi.get("description", ""),
                                "equipment_text": bi.get("equipment_text", ""),
                                "area": bi.get("area", ""),
                                "work_type_label": bi.get("work_type_label", "GeneralCleanup"),
                                "updated_at": "",
                            },
                            use_ai=use_ai,
                            live_ai=live_ai,
                        )
                        state.match_by_version[bkey] = {
                            "match_status": frozen_match["match_status"],
                            "resolved_tag": frozen_match["resolved_tag"],
                            "work_type_label": bi.get("work_type_label", "GeneralCleanup"),
                            "findings": (frozen_match.get("mapping_trace") or {}).get("findings") or [],
                        }

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
            state.match_by_version[f"{request_id}@v{item['version']}"] = self._match_snapshot(item)
            self._push_scope_to_graph_store(state)
            return copy.deepcopy(item)

    def _match_snapshot(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "match_status": item.get("match_status"),
            "resolved_tag": item.get("resolved_tag"),
            "work_type_label": item.get("work_type_label", "GeneralCleanup"),
            "findings": copy.deepcopy((item.get("mapping_trace") or {}).get("findings") or []),
        }

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

    def _classify_frozen_outcome(self, match_snap: dict[str, Any] | None) -> str:
        """One of four frozen outcomes (docs/verification.md section 2): matched, unresolved, unit_general, incompatible."""
        if match_snap is None:
            return "unresolved"
        if match_snap.get("match_status") == "accepted" and match_snap.get("resolved_tag"):
            return "matched"
        findings = match_snap.get("findings") or ((match_snap.get("mapping_trace") or {}).get("findings") or [])
        if any(f.get("kind") in {"incompatible_class", "wrong_unit", "retired_tag"} for f in findings):
            return "incompatible"
        if match_snap.get("work_type_label") == "GeneralCleanup":
            return "unit_general"
        return "unresolved"

    def baseline_summary(self, exercise_id: str) -> dict[str, Any]:
        state = self._get_state(exercise_id)
        frozen = state.baseline_freeze_id is not None
        baseline_items = state.baseline_items
        total = len(baseline_items)
        matched = 0
        outcome_counts: dict[str, int] = {"matched": 0, "unresolved": 0, "unit_general": 0, "incompatible": 0}
        enriched_items: list[dict[str, Any]] = []
        for bi in baseline_items:
            rid = bi["request_id"]
            bver = int(bi.get("request_version", 1))
            # Always evaluate readiness strictly against the frozen request_version snapshot,
            # never against a later post-freeze version of the request.
            snap = state.match_by_version.get(f"{rid}@v{bver}")
            outcome = self._classify_frozen_outcome(snap)
            outcome_counts[outcome] += 1
            if outcome == "matched":
                matched += 1
            enriched_items.append(
                {
                    "request_id": rid,
                    "request_version": bver,
                    "title": bi.get("title", ""),
                    "area": bi.get("area", ""),
                    "source_group": bi.get("source_group", ""),
                    "estimate_hours": int(bi.get("estimate_hours", 0)),
                    "estimate_cost_usd": int(bi.get("estimate_cost_usd", 0)),
                    "resolved_tag": snap.get("resolved_tag") if snap else None,
                    "outcome": outcome,
                }
            )

        frozen_rate = round(matched / total, 4) if total > 0 else None
        ready_for_use = bool(frozen and frozen_rate is not None and frozen_rate >= self.match_rate_gate)
        baseline_hours = sum(int(bi.get("estimate_hours", 0)) for bi in baseline_items)
        baseline_cost = sum(int(bi.get("estimate_cost_usd", 0)) for bi in baseline_items)

        return {
            "exercise_id": exercise_id,
            "event_id": "TAR-200-2028",
            "frozen": frozen,
            "freeze_id": state.baseline_freeze_id,
            "frozen_at": state.baseline_frozen_at,
            "list_version": state.baseline_list_version,
            "baseline_item_count": total,
            "baseline_hours": baseline_hours,
            "baseline_cost_usd": baseline_cost,
            "frozen_matched_count": matched,
            "frozen_match_rate": frozen_rate,
            "gate_threshold": self.match_rate_gate,
            "ready_for_use": ready_for_use,
            "outcome_counts": outcome_counts,
            "items": enriched_items,
            # Release-one scope rule: 4.1 and 4.2 stay schema slots only, null with no features.
            "reserved_slots": {
                "work_packages_4_1": {
                    "status": "schema_slot_only",
                    "work_packages": None,
                    "standards": None,
                    "materials": None,
                    "redlines": None,
                },
                "execution_plan_4_2": {
                    "status": "schema_slot_only",
                    "activities": None,
                    "logistics_objects": None,
                    "permits": None,
                },
            },
        }

    def kpis_summary(self, exercise_id: str) -> dict[str, Any]:
        state = self._get_state(exercise_id)
        baseline = self.baseline_summary(exercise_id)
        matching = self.matching_summary(exercise_id)
        clusters = self.clusters_and_duplicates(exercise_id)

        # Refresh live exercise_meta if IMPACT Web is connected so twin_write_through reflects current switch
        ex_meta = dict(state.exercise_meta)
        if self.impactweb_client is not None:
            try:
                ex_meta = self.impactweb_client.get_exercise(exercise_id)
                state.exercise_meta = ex_meta
            except Exception:
                pass

        events = list(state.change_events.values())
        growth_hours = sum(int(ev["hours_delta"]) for ev in events)
        growth_cost = sum(int(ev["cost_delta_usd"]) for ev in events)
        mandatory_hours = sum(int(ev["hours_delta"]) for ev in events if ev.get("mandatory"))
        discretionary_hours = sum(int(ev["hours_delta"]) for ev in events if not ev.get("mandatory"))
        adds_approved = sum(1 for ev in events if ev.get("type") == "add")
        deletes_approved = sum(1 for ev in events if ev.get("type") == "delete")
        changes_approved = sum(1 for ev in events if ev.get("type") == "change")

        all_crs = state.all_change_requests
        pending_count = sum(1 for c in all_crs if c.get("status") == "pending")
        rejected_count = sum(1 for c in all_crs if c.get("status") == "rejected")

        baseline_hours = baseline["baseline_hours"]
        growth_pct = round((growth_hours / baseline_hours) * 100.0, 2) if baseline_hours > 0 else 0.0

        all_cl = clusters["isolation_clusters"] + clusters["scaffold_clusters"] + clusters["access_clusters"]
        hours_bundled = sum(int(c["shared_hours"]) for c in all_cl)
        duplicate_hours = sum(int(p["overlap_hours"]) for p in clusters["duplicate_pairs"])

        return {
            "exercise_id": exercise_id,
            "frozen": baseline["frozen"],
            "freeze_id": baseline["freeze_id"],
            "ready_for_use": baseline["ready_for_use"],
            "twin_write_through": bool(ex_meta.get("twin_write_through", True)),
            "baseline_hours": baseline_hours,
            "baseline_item_count": baseline["baseline_item_count"],
            "growth_hours": growth_hours,
            "growth_cost_usd": growth_cost,
            "growth_pct_of_baseline": growth_pct,
            "mandatory_growth_hours": mandatory_hours,
            "discretionary_growth_hours": discretionary_hours,
            "adds_approved": adds_approved,
            "deletes_approved": deletes_approved,
            "changes_approved": changes_approved,
            "pending_count": pending_count,
            "rejected_count": rejected_count,
            "change_events": events,
            "all_change_requests": all_crs,
            "tag_match_rate": matching["match_rate"],
            "hours_bundled": hours_bundled,
            "duplicate_hours_flagged": duplicate_hours,
            "duplicate_pair_count": len(clusters["duplicate_pairs"]),
            "last_synced_at": state.last_synced_at,
        }

    def value_panel(self, exercise_id: str) -> dict[str, Any]:
        """Focus-area brief defaults for 3.1, explicitly labeled as unvalidated assumptions (docs/scenario-spec.md section 6)."""
        kpis = self.kpis_summary(exercise_id)
        levers = [
            {
                "lever": "Shared costs bundled",
                "default_usd": 1_130_000,
                "display_amount": "$1.13M",
                "unvalidated_assumption": True,
                "basis": "Focus-area brief 3.1 default assumption",
            },
            {
                "lever": "Scope removed or avoided",
                "default_usd": 750_000,
                "display_amount": "$0.75M",
                "unvalidated_assumption": True,
                "basis": "Focus-area brief 3.1 default assumption",
            },
            {
                "lever": "Duration (0.3 days)",
                "default_usd": 600_000,
                "display_amount": "$0.60M",
                "unvalidated_assumption": True,
                "basis": "Focus-area brief 3.1 default assumption",
            },
            {
                "lever": "Planning hours saved (250 hours)",
                "default_usd": 40_000,
                "display_amount": "$0.04M",
                "unvalidated_assumption": True,
                "basis": "Focus-area brief 3.1 default assumption",
            },
        ]
        return {
            "exercise_id": exercise_id,
            "unvalidated_assumption": True,
            "assumption_notice": (
                "All dollar figures below are unvalidated assumptions from the 3.1 focus-area brief, not measured results. "
                "Measured counts from the synthetic Unit 200 demo dataset are shown separately."
            ),
            "levers": levers,
            "total_default_usd": sum(lv["default_usd"] for lv in levers),
            "total_display": "about $2.5M",
            "measured_in_demo": {
                "hours_bundled": kpis["hours_bundled"],
                "duplicate_pair_count": kpis["duplicate_pair_count"],
                "duplicate_hours_flagged": kpis["duplicate_hours_flagged"],
                "baseline_hours": kpis["baseline_hours"],
                "post_freeze_growth_hours": kpis["growth_hours"],
                "tag_match_rate": kpis["tag_match_rate"],
            },
        }

    def change_request_prefill(self, exercise_id: str, tag: str) -> dict[str, Any]:
        """Build plain-text prefill evidence for raising a post-freeze change request from the Twin."""
        state = self._get_state(exercise_id)
        ex_meta = dict(state.exercise_meta)
        if self.impactweb_client is not None:
            try:
                ex_meta = self.impactweb_client.get_exercise(exercise_id)
                state.exercise_meta = ex_meta
            except Exception:
                pass

        eq = self.plant_store.get_equipment(tag)
        if eq is None:
            raise KeyError(f"Equipment {tag} not found in Unit 200 plant graph")

        matching_jobs = [it for it in state.scope_items.values() if it.get("resolved_tag") == tag]
        clusters = self.clusters_and_duplicates(exercise_id)
        shared_scaffolds = [c["id"] for c in clusters["scaffold_clusters"] if tag in c["equipment_tags"]]
        shared_access = [c["id"] for c in clusters["access_clusters"] if tag in c["equipment_tags"]]
        shared_envelopes = list(eq.get("envelopes", []))

        # Special walkthrough step 7 case: C-201 nozzle N3 while column is already open
        late_path = self.scenario_dir / "late-scope.json"
        live_demo = json.loads(late_path.read_text(encoding="utf-8")).get("live_walkthrough_add", {}) if late_path.is_file() else {}
        if tag == "C-201" and live_demo:
            prefilled_title = live_demo["title"]
            prefilled_reason = live_demo["reason"]
            default_hours = int(live_demo["hours_delta"])
            default_cost = int(live_demo["cost_delta_usd"])
            shared_saved_hours = int(live_demo.get("shared_setup_hours_saved", 420))
        else:
            env_str = ", ".join(shared_envelopes) or "its active isolation boundary"
            scaf_str = f" and scaffold cluster {', '.join(shared_scaffolds)}" if shared_scaffolds else ""
            prefilled_title = f"Post-freeze scope addition on {tag} ({eq['description']})"
            prefilled_reason = (
                f"Add work on {tag}; {len(matching_jobs)} job(s) are already scheduled on this asset sharing "
                f"isolation {env_str}{scaf_str}. Only direct craft execution hours are incremental."
            )
            default_hours = 140
            default_cost = 32900
            shared_saved_hours = 240 if (shared_envelopes or shared_scaffolds) else 0

        return {
            "exercise_id": exercise_id,
            "equipment_tag": tag,
            "equipment_description": eq["description"],
            "area": eq["area"],
            "sheet": eq["sheet"],
            "frozen": bool(ex_meta.get("frozen", state.baseline_freeze_id is not None)),
            "twin_write_through": bool(ex_meta.get("twin_write_through", True)),
            "already_open_job_count": len(matching_jobs),
            "already_open_jobs": [{"request_id": j["request_id"], "title": j["title"]} for j in matching_jobs[:8]],
            "shared_envelopes": shared_envelopes,
            "shared_scaffolds": shared_scaffolds,
            "shared_access": shared_access,
            "shared_setup_hours_saved": shared_saved_hours,
            "prefilled_title": prefilled_title,
            "prefilled_equipment_text": f"{tag} {eq['description']}",
            "prefilled_reason": prefilled_reason,
            "default_hours_delta": default_hours,
            "default_cost_delta_usd": default_cost,
            "default_source_group": "operations",
            "default_driver": "operations",
        }

    def export_twin_only_backup(self) -> dict[str, Any]:
        """Export twin-only state + per-exercise cursor watermarks (docs/hosting.md section 5)."""
        exercise_ids = sorted(set(self._states.keys()) | {"EX-DEMO"})
        cutoffs: dict[str, int] = {}
        exercises: dict[str, dict[str, Any]] = {}
        for ex_id in exercise_ids:
            st = self._get_state(ex_id)
            cutoffs[ex_id] = int(st.cursor_seq)
            exercises[ex_id] = {
                "cursor_seq": int(st.cursor_seq),
                "epoch": int(st.epoch),
                "manual_reviews": copy.deepcopy(st.manual_reviews),
                "saved_cut_line_runs": copy.deepcopy(st.saved_cut_line_runs),
                "match_by_version": copy.deepcopy(st.match_by_version),
            }
        return {
            "format_version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "cutoffs": cutoffs,
            "exercises": exercises,
        }

    def import_twin_only_backup(self, bundle: dict[str, Any]) -> dict[str, Any]:
        """Restore twin-only state after verifying cutoffs match live IMPACT Web / twin cursors."""
        bundle_cutoffs = bundle.get("cutoffs") or {}
        exercises_data = bundle.get("exercises") or {}

        live_cutoffs: dict[str, int] | None = None
        if self.impactweb_client is not None:
            try:
                live_cutoffs = {
                    k: int(v) for k, v in (self.impactweb_client.get_watermarks().get("cutoffs") or {}).items()
                }
            except Exception:
                live_cutoffs = None

        # Refuse mismatched cutoffs (docs/hosting.md section 5 & 6)
        for ex_id, expected_seq in bundle_cutoffs.items():
            st = self._get_state(ex_id)
            exp_int = int(expected_seq)
            if live_cutoffs is not None and ex_id in live_cutoffs and live_cutoffs[ex_id] != exp_int:
                raise RuntimeError(
                    f"Backup cutoff mismatch for {ex_id}: bundle={exp_int}, IMPACT Web={live_cutoffs[ex_id]}"
                )
            if st.cursor_seq != exp_int:
                raise RuntimeError(
                    f"Backup cutoff mismatch for {ex_id}: bundle={exp_int}, twin cursor={st.cursor_seq}"
                )

        restored_exercises: list[str] = []
        for ex_id, payload in exercises_data.items():
            with self._locks[ex_id]:
                st = self._get_state(ex_id)
                st.manual_reviews = copy.deepcopy(payload.get("manual_reviews") or {})
                st.saved_cut_line_runs = copy.deepcopy(payload.get("saved_cut_line_runs") or [])
                if payload.get("match_by_version"):
                    st.match_by_version.update(copy.deepcopy(payload["match_by_version"]))
                # Re-apply manual reviews to current scope items
                for rid, manual in st.manual_reviews.items():
                    item = st.scope_items.get(rid)
                    if item is not None and item.get("equipment_text") == manual.get("equipment_text"):
                        self._apply_manual_decision_to_item(item, manual)
                        st.match_by_version[f"{rid}@v{item['version']}"] = self._match_snapshot(item)
                self._push_scope_to_graph_store(st)
                restored_exercises.append(ex_id)

        return {"restored_exercises": sorted(restored_exercises), "cutoffs": bundle_cutoffs}
