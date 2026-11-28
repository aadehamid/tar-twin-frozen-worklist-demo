"""Natural-language Twin Explorer translating plain-English planning questions into safe named queries.

Never executes arbitrary Cypher or mutates state. Selects strictly from a fixed catalog of read-only
parameterized graph and planning intents, returning structured evidence, the exact named Relate
Cypher query, UI highlight directives, and one-click planning follow-up pivots.
"""

from __future__ import annotations

import re
from typing import Any

from twin.matcher import AiClientConfig, call_live_decider

ENV_RE = re.compile(r"\b(ENV-200-0[1-6])\b", re.IGNORECASE)
AREA_RE = re.compile(r"\b(200-[A-G])\b", re.IGNORECASE)
WR_RE = re.compile(r"\b(WR-200-\d{4})\b", re.IGNORECASE)
TAG_RE = re.compile(r"\b((?:PSV|FL|KT|HV|XV|FV|LV|PV|PT|TT|FT|LT|AT|D|P|R|E|H|A|C|K)-2\d{2,3}[A-Z]?)\b", re.IGNORECASE)
BUDGET_M_RE = re.compile(r"\$?\s*(\d+(?:\.\d+)?)\s*(?:m|million)\b", re.IGNORECASE)
BUDGET_RAW_RE = re.compile(r"\$\s*(\d{1,3}(?:,\d{3})+|\d{6,9})\b")

AREA_NAME_HINTS: dict[str, str] = {
    "feed": "200-A",
    "reactor structure": "200-B",
    "reactor": "200-B",
    "exchanger bay": "200-C",
    "heater": "200-D",
    "separator": "200-E",
    "air cooler": "200-E",
    "gas compression": "200-F",
    "compressor": "200-F",
    "stripping": "200-G",
    "stripper": "200-G",
}

EXPLORE_INTENTS: list[str] = [
    "envelope_scope",
    "equipment_neighborhood",
    "duplicates",
    "cut_line_what_if",
    "clusters_and_bundling",
    "unmatched_or_findings",
    "area_scope",
    "post_freeze_changes",
    "equipment_search",
]

STARTER_PROMPTS: list[dict[str, str]] = [
    {"label": "Shared isolation on E-201B", "query": "What shares isolation envelope ENV-200-02 with E-201B?"},
    {"label": "Duplicates across source groups", "query": "Show all duplicate work requests and overlap hours"},
    {"label": "Test $20M cut line", "query": "What drops below a $20M budget cut line?"},
    {"label": "Wrong-unit and review findings", "query": "Show unmatched work requests and wrong-unit findings"},
    {"label": "C-201 bundle opportunities", "query": "Where is C-201 and what scaffold or isolation bundles with it?"},
    {"label": "Area 200-C scope breakdown", "query": "Summarize work requests, hours, and cost in area 200-C"},
]


def _extract_budget_usd(text: str) -> int | None:
    m_m = BUDGET_M_RE.search(text)
    if m_m:
        return int(round(float(m_m.group(1)) * 1_000_000))
    m_raw = BUDGET_RAW_RE.search(text)
    if m_raw:
        return int(m_raw.group(1).replace(",", ""))
    return None


def _classify_intent_deterministic(query: str, *, env_id: str | None, tag: str | None, area: str | None, budget: int | None) -> tuple[str, bool]:
    """Return (intent, confident). If not confident and external AI is allowed, Decider refines intent."""
    q = query.lower()
    if any(k in q for k in ("duplicate", "double", "overlap", "same work")):
        return "duplicates", True
    if budget is not None or any(k in q for k in ("cut line", "cutline", "budget", "defer", "below the line", "drop below")):
        return "cut_line_what_if", True
    if any(k in q for k in ("late scope", "post-freeze", "post freeze", "change request", "scope growth", "after freeze")):
        return "post_freeze_changes", True
    if any(k in q for k in ("unmatched", "review queue", "wrong unit", "wrong-unit", "retired", "finding", "instruction", "ambiguous")):
        return "unmatched_or_findings", True
    if env_id or any(k in q for k in ("envelope", "isolation", "blind", "boundary valve", "isolat")):
        return "envelope_scope", True
    if any(k in q for k in ("scaffold", "cluster", "bundle", "bundling", "crane", "access", "laydown", "shared cost")):
        return "clusters_and_bundling", True
    if tag or WR_RE.search(query):
        return "equipment_neighborhood", True
    if area or "area " in q:
        return "area_scope", True
    if any(k in q for k in ("exchanger", "pump", "compressor", "reactor", "heater", "column", "vessel", "psv", "relief")):
        return "equipment_search", True
    return "equipment_search", False


def _classify_intent_with_decider(query: str, ai_cfg: AiClientConfig) -> str | None:
    if not ai_cfg.api_key:
        return None
    payload = {
        "model": ai_cfg.decider_model,
        "state": f"Turnaround planner question about Unit 200 digital twin: {query}",
        "questions": {
            "intent": {
                "type": "choice",
                "instructions": "Select the single best read-only planning query intent for this question.",
                "criteria": {
                    "envelope_scope": "Isolation envelopes, boundary valves, blinding, or equipment sharing an isolation boundary",
                    "equipment_neighborhood": "Details, P&ID, plot location, or work requests on one specific equipment tag or work request",
                    "duplicates": "Duplicate work requests or overlapping scope across source groups",
                    "cut_line_what_if": "Budget cut line, deferring scope, mandatory floor, or cost target scenarios",
                    "clusters_and_bundling": "Shared scaffold, access, crane, laydown, or bundling opportunities",
                    "unmatched_or_findings": "Unmatched requests, review queue, wrong-unit/retired findings, or match rate gaps",
                    "area_scope": "Summary of work, hours, and equipment in a specific plant area (200-A to 200-G)",
                    "post_freeze_changes": "Post-freeze change requests, late scope additions, or scope growth hours",
                    "equipment_search": "Searching or listing equipment by class or type across Unit 200",
                },
            }
        },
    }
    resp, _model, _lat = call_live_decider(ai_cfg, payload, timeout=10.0)
    if not isinstance(resp, dict):
        return None
    choice = ((resp.get("answers") or {}).get("intent") or {}).get("choice")
    return choice if choice in EXPLORE_INTENTS else None


def run_explore_query(
    *,
    query: str,
    exercise_id: str,
    plant_store: Any,
    sync_engine: Any,
    allow_external_ai: bool = False,
) -> dict[str, Any]:
    """Execute a safe, read-only natural-language exploration over the plant graph and synced scope."""
    q_clean = (query or "").strip()
    if not q_clean:
        raise ValueError("Explore query cannot be empty")

    # Ensure exercise has synced scope if empty
    items = sync_engine.list_scope_items(exercise_id)
    if not items:
        sync_engine.sync_exercise(exercise_id)
        items = sync_engine.list_scope_items(exercise_id)

    envelopes = plant_store.list_envelopes()
    equipment_list = plant_store.list_equipment()
    eq_by_tag = {e["tag"]: e for e in equipment_list}
    env_by_id = {e["id"]: e for e in envelopes}
    clusters = sync_engine.clusters_and_duplicates(exercise_id)

    m_env = ENV_RE.search(q_clean)
    m_area = AREA_RE.search(q_clean)
    m_wr = WR_RE.search(q_clean)
    m_tag = TAG_RE.search(q_clean)
    budget = _extract_budget_usd(q_clean)

    env_id = m_env.group(1).upper() if m_env else None
    area_code = m_area.group(1).upper() if m_area else None
    wr_id = m_wr.group(1).upper() if m_wr else None
    tag = m_tag.group(1).upper() if m_tag else None

    if area_code is None:
        q_low = q_clean.lower()
        for hint, code in AREA_NAME_HINTS.items():
            if hint in q_low and tag is None and env_id is None:
                area_code = code
                break

    if wr_id and tag is None:
        wr_obj = sync_engine.get_scope_item(exercise_id, wr_id)
        if wr_obj and wr_obj.get("resolved_tag"):
            tag = wr_obj["resolved_tag"]

    intent, confident = _classify_intent_deterministic(q_clean, env_id=env_id, tag=tag, area=area_code, budget=budget)
    routed_by = "code"
    if not confident and allow_external_ai:
        ai_intent = _classify_intent_with_decider(q_clean, sync_engine.ai_config)
        if ai_intent:
            intent = ai_intent
            routed_by = "decider"

    active_items = [it for it in items if it.get("status") not in {"deleted", "rejected", "screened_out"}]

    if intent == "envelope_scope":
        if env_id is None and tag and tag in eq_by_tag and eq_by_tag[tag]["envelopes"]:
            env_id = eq_by_tag[tag]["envelopes"][0]
        if env_id is None:
            env_id = "ENV-200-02"
        env = env_by_id.get(env_id) or envelopes[0]
        env_id = env["id"]
        eq_tags = env["equipment_tags"]
        matching_wrs = [it for it in active_items if it.get("resolved_tag") in set(eq_tags)]
        total_hrs = sum(it["estimate_hours"] for it in matching_wrs)
        first_sheet = eq_by_tag[eq_tags[0]]["sheet"] if eq_tags and eq_tags[0] in eq_by_tag else "200-PID-002"
        return {
            "query": q_clean,
            "intent": intent,
            "routed_by": routed_by,
            "headline": (
                f"{env_id} ({env['name']}) isolates {len(eq_tags)} major equipment items behind "
                f"{env['boundary_valve_count']} boundary valves with {len(matching_wrs)} matched active jobs ({total_hrs:,} hrs)."
            ),
            "cypher_name": "envelope_scope",
            "cypher_params": {"envelope_id": env_id},
            "cypher_query": (
                f"MATCH (env:IsolationEnvelope {{id: '{env_id}'}})-[:CONTAINS]->(e:Equipment) "
                "OPTIONAL MATCH (env)-[:BOUNDED_BY]->(v:Valve) "
                "OPTIONAL MATCH (s:ScopeItem)-[:RESOLVES_TO]->(e) "
                "RETURN env.id, e.tag, collect(DISTINCT v.tag) AS boundary_valves, count(DISTINCT s) AS jobs"
            ),
            "highlight": {
                "view": "plot",
                "envelope_id": env_id,
                "equipment_tags": eq_tags,
                "boundary_valves": env["boundary_valves"],
                "request_ids": [w["request_id"] for w in matching_wrs],
                "sheet_no": first_sheet,
            },
            "rows": [
                {
                    "kind": "equipment",
                    "id": t,
                    "title": eq_by_tag[t]["description"] if t in eq_by_tag else t,
                    "area": eq_by_tag[t]["area"] if t in eq_by_tag else "",
                    "sheet": eq_by_tag[t]["sheet"] if t in eq_by_tag else "",
                    "jobs": sum(1 for w in matching_wrs if w.get("resolved_tag") == t),
                    "hours": sum(w["estimate_hours"] for w in matching_wrs if w.get("resolved_tag") == t),
                }
                for t in eq_tags
            ],
            "follow_ups": [
                {"label": f"Inspect {first_sheet} P&ID", "view": "pid", "sheet_no": first_sheet, "envelope_id": env_id},
                {"label": f"Open {env_id} in Relate graph", "view": "graph", "envelope_id": env_id},
                {"label": "Check shared scaffold clusters", "query": f"Show shared scaffold clusters touching {eq_tags[0]}"},
            ],
        }

    if intent == "duplicates":
        pairs = clusters["duplicate_pairs"]
        if tag:
            pairs = [p for p in pairs if p["equipment_tag"] == tag]
        elif area_code:
            area_tags = {e["tag"] for e in equipment_list if e["area"] == area_code}
            pairs = [p for p in pairs if p["equipment_tag"] in area_tags]
        tot_hrs = sum(p["overlap_hours"] for p in pairs)
        tot_cost = sum(p["overlap_cost_usd"] for p in pairs)
        req_ids = [rid for p in pairs for rid in p["request_ids"]]
        eq_tags = sorted({p["equipment_tag"] for p in pairs})
        return {
            "query": q_clean,
            "intent": intent,
            "routed_by": routed_by,
            "headline": (
                f"Found {len(pairs)} duplicate scope pairs representing {tot_hrs:,} overlapping hours "
                f"(${tot_cost:,}) across separate source groups."
            ),
            "cypher_name": "duplicate_scope_pairs",
            "cypher_params": {"area": area_code or "", "tag": tag or ""},
            "cypher_query": (
                "MATCH (s1:ScopeItem)-[:RESOLVES_TO]->(e:Equipment)<-[:RESOLVES_TO]-(s2:ScopeItem) "
                "WHERE s1.request_id < s2.request_id AND s1.source_group <> s2.source_group "
                "RETURN e.tag, s1.request_id, s2.request_id, s1.source_group, s2.source_group"
            ),
            "highlight": {"view": "clusters", "equipment_tags": eq_tags, "request_ids": req_ids},
            "rows": [
                {
                    "kind": "duplicate",
                    "id": p["id"],
                    "equipment_tag": p["equipment_tag"],
                    "request_ids": p["request_ids"],
                    "source_groups": p["source_groups"],
                    "overlap_hours": p["overlap_hours"],
                    "overlap_cost_usd": p["overlap_cost_usd"],
                    "reason": p["reason"],
                }
                for p in pairs
            ],
            "follow_ups": [
                {"label": "Highlight duplicates on plot plan", "view": "plot", "equipment_tags": eq_tags},
                {"label": "Test $22M cut line", "query": "Evaluate the $22M budget cut line"},
            ],
        }

    if intent == "cut_line_what_if":
        target_budget = budget if budget is not None else 22_000_000
        res = sync_engine.evaluate_cut_line(exercise_id, target_budget)
        below_set = set(res["below_ids"])
        below_items = [it for it in active_items if it["request_id"] in below_set]
        below_items.sort(key=lambda x: (-x["estimate_cost_usd"], x["request_id"]))
        status_phrase = (
            f"Feasible: {res['above_count']} jobs stay above the line (${res['above_cost_usd']:,}) "
            f"and {res['below_count']} discretionary jobs (${res['below_cost_usd']:,}) drop below."
            if res["feasible"]
            else f"Infeasible: mandatory scope alone costs ${res['mandatory_cost_usd']:,}, leaving a ${res['shortfall_usd']:,} shortfall."
        )
        return {
            "query": q_clean,
            "intent": intent,
            "routed_by": routed_by,
            "headline": f"At ${target_budget:,} budget: {status_phrase} Shared clustering saves ${res['shared_cost_saved_usd']:,}.",
            "cypher_name": "cut_line_budget",
            "cypher_params": {"budget_usd": target_budget},
            "cypher_query": (
                "MATCH (s:ScopeItem)-[:RESOLVES_TO]->(e:Equipment) "
                "RETURN s.request_id, e.tag, s.ript, s.estimate_cost_usd ORDER BY s.ript DESC"
            ),
            "highlight": {
                "view": "clusters",
                "budget_usd": target_budget,
                "request_ids": res["below_ids"][:25],
                "equipment_tags": sorted({it["resolved_tag"] for it in below_items if it.get("resolved_tag")}),
            },
            "rows": [
                {
                    "kind": "work_request",
                    "id": it["request_id"],
                    "title": it["title"],
                    "equipment_tag": it.get("resolved_tag") or it["equipment_text"],
                    "area": it["area"],
                    "ript_score": it["ript_score"],
                    "estimate_hours": it["estimate_hours"],
                    "estimate_cost_usd": it["estimate_cost_usd"],
                    "placement": "below",
                }
                for it in below_items[:20]
            ],
            "follow_ups": [
                {"label": "Compare at $22M target", "query": "Test $22M budget cut line"},
                {"label": "Compare at $20M budget", "query": "What drops below a $20M cut line?"},
                {"label": "Show cut line on plot plan", "view": "plot", "layer": "cut_line"},
            ],
        }

    if intent == "clusters_and_bundling":
        all_cl = clusters["scaffold_clusters"] + clusters["isolation_clusters"] + clusters["access_clusters"]
        q_low = q_clean.lower()
        if "scaffold" in q_low:
            all_cl = clusters["scaffold_clusters"]
        elif "access" in q_low or "crane" in q_low or "laydown" in q_low:
            all_cl = clusters["access_clusters"]
        if tag:
            all_cl = [c for c in all_cl if tag in c["equipment_tags"]]
        elif area_code:
            all_cl = [c for c in all_cl if c.get("area") == area_code or any(eq_by_tag.get(t, {}).get("area") == area_code for t in c["equipment_tags"])]
        tot_shared_hrs = sum(c["shared_hours"] for c in all_cl)
        tot_shared_cost = sum(c["shared_cost_usd"] for c in all_cl)
        eq_tags = sorted({t for c in all_cl for t in c["equipment_tags"]})
        req_ids = sorted({r for c in all_cl for r in c["request_ids"]})
        return {
            "query": q_clean,
            "intent": intent,
            "routed_by": routed_by,
            "headline": (
                f"Found {len(all_cl)} shared clusters covering {len(eq_tags)} equipment tags and {len(req_ids)} jobs "
                f"({tot_shared_hrs:,} shared hours, ${tot_shared_cost:,} counted once)."
            ),
            "cypher_name": "shared_clusters",
            "cypher_params": {"tag": tag or "", "area": area_code or ""},
            "cypher_query": (
                "MATCH (env:IsolationEnvelope)-[:CONTAINS]->(e:Equipment)<-[:RESOLVES_TO]-(s:ScopeItem) "
                "RETURN env.id, e.tag, count(DISTINCT s) AS bundled_jobs"
            ),
            "highlight": {"view": "clusters", "equipment_tags": eq_tags, "request_ids": req_ids},
            "rows": [
                {
                    "kind": "cluster",
                    "id": c["id"],
                    "type": c["type"],
                    "name": c["name"],
                    "equipment_tags": c["equipment_tags"],
                    "job_count": len(c["request_ids"]),
                    "shared_hours": c["shared_hours"],
                    "shared_cost_usd": c["shared_cost_usd"],
                }
                for c in all_cl
            ],
            "follow_ups": [
                {"label": "Show clusters on plot plan", "view": "plot", "layer": "clusters", "equipment_tags": eq_tags},
                {"label": "Check duplicate pairs", "query": "Show all duplicate work requests"},
            ],
        }

    if intent == "unmatched_or_findings":
        queue = sync_engine.review_queue(exercise_id)
        q_low = q_clean.lower()
        if "wrong" in q_low or "retired" in q_low or "finding" in q_low:
            rows_src = [it for it in items if it["mapping_trace"]["findings"]]
        elif "instruction" in q_low:
            rows_src = [it for it in items if it["mapping_trace"]["instruction_warning"]]
        else:
            rows_src = queue
        summary = sync_engine.matching_summary(exercise_id)
        return {
            "query": q_clean,
            "intent": intent,
            "routed_by": routed_by,
            "headline": (
                f"{len(rows_src)} items match this filter ({summary['accepted_count']}/{summary['total_active']} "
                f"accepted, {round((summary['match_rate'] or 0) * 100, 1)}% match rate vs 95% gate)."
            ),
            "cypher_name": "unmatched_scope",
            "cypher_params": {"exercise_id": exercise_id},
            "cypher_query": (
                f"MATCH (s:ScopeItem {{exercise_id: '{exercise_id}'}}) "
                "WHERE s.match_status <> 'accepted' "
                "RETURN s.request_id, s.title, s.area, s.match_status"
            ),
            "highlight": {"view": "review", "request_ids": [r["request_id"] for r in rows_src]},
            "rows": [
                {
                    "kind": "review_item",
                    "id": r["request_id"],
                    "title": r["title"],
                    "equipment_text": r["equipment_text"],
                    "proposed_tag": (r.get("proposal") or {}).get("tag") or "none",
                    "findings": [f["reason"] for f in r["mapping_trace"]["findings"]],
                    "instruction_warning": r["mapping_trace"]["instruction_warning"],
                }
                for r in rows_src[:25]
            ],
            "follow_ups": [
                {"label": "Open match review queue", "view": "review"},
                {"label": "Open Matching lab comparison", "view": "lab"},
            ],
        }

    if intent == "post_freeze_changes":
        state = sync_engine._get_state(exercise_id)
        crs = state.all_change_requests
        approved_hrs = sum(ev["hours_delta"] for ev in state.change_events.values())
        return {
            "query": q_clean,
            "intent": intent,
            "routed_by": routed_by,
            "headline": (
                f"{len(crs)} post-freeze change requests recorded ({len(state.change_events)} approved, "
                f"net growth {approved_hrs:+,} hrs; baseline has {len(state.baseline_items)} frozen items)."
            ),
            "cypher_name": "post_freeze_growth",
            "cypher_params": {"exercise_id": exercise_id},
            "cypher_query": (
                f"MATCH (s:ScopeItem {{exercise_id: '{exercise_id}'}}) "
                "RETURN count(s) AS active_scope, sum(s.estimate_hours) AS total_hours"
            ),
            "highlight": {"view": "kpis", "request_ids": [c["request_id"] for c in crs if c.get("request_id")]},
            "rows": [
                {
                    "kind": "change_request",
                    "id": c["id"],
                    "request_id": c.get("request_id") or "New scope",
                    "change_type": c["change_type"],
                    "title": c["title"],
                    "hours_delta": c["hours_delta"],
                    "raised_via": c["raised_via"],
                    "status": c["status"],
                }
                for c in crs[:25]
            ],
            "follow_ups": [
                {"label": "Open Baseline and KPIs", "view": "kpis"},
                {"label": "Test $22M cut line", "query": "Test $22M budget cut line"},
            ],
        }

    if intent == "area_scope" and area_code:
        area_eq = [e for e in equipment_list if e["area"] == area_code]
        area_wrs = [it for it in active_items if it["area"] == area_code]
        hrs = sum(it["estimate_hours"] for it in area_wrs)
        cost = sum(it["estimate_cost_usd"] for it in area_wrs)
        accepted = sum(1 for it in area_wrs if it["match_status"] == "accepted")
        return {
            "query": q_clean,
            "intent": intent,
            "routed_by": routed_by,
            "headline": (
                f"Area {area_code} contains {len(area_eq)} major equipment tags and {len(area_wrs)} active work requests "
                f"({hrs:,} hrs, ${cost:,}; {accepted}/{len(area_wrs)} matched)."
            ),
            "cypher_name": "area_equipment",
            "cypher_params": {"area": area_code},
            "cypher_query": (
                f"MATCH (e:Equipment)-[:LOCATED_IN]->(a:Area {{code: '{area_code}'}}) "
                "OPTIONAL MATCH (s:ScopeItem)-[:RESOLVES_TO]->(e) "
                "RETURN e.tag, e.sheet, count(DISTINCT s) AS jobs"
            ),
            "highlight": {
                "view": "plot",
                "area_code": area_code,
                "equipment_tags": [e["tag"] for e in area_eq],
                "request_ids": [w["request_id"] for w in area_wrs],
            },
            "rows": [
                {
                    "kind": "equipment",
                    "id": e["tag"],
                    "title": e["description"],
                    "area": e["area"],
                    "sheet": e["sheet"],
                    "envelopes": e["envelopes"],
                    "jobs": sum(1 for w in area_wrs if w.get("resolved_tag") == e["tag"]),
                }
                for e in area_eq
            ],
            "follow_ups": [
                {"label": f"Check duplicates in {area_code}", "query": f"Show duplicates in {area_code}"},
                {"label": f"Check clusters in {area_code}", "query": f"Show shared clusters in {area_code}"},
            ],
        }

    if intent == "equipment_neighborhood" and (tag or wr_id):
        target_tag = tag or "E-201B"
        eq = eq_by_tag.get(target_tag)
        wrs = [it for it in active_items if it.get("resolved_tag") == target_tag or it["request_id"] == wr_id]
        if eq is None and wrs and wrs[0].get("resolved_tag") in eq_by_tag:
            target_tag = wrs[0]["resolved_tag"]
            eq = eq_by_tag[target_tag]
        sheet_no = eq["sheet"] if eq else "200-PID-002"
        env_ids = eq["envelopes"] if eq else []
        hrs = sum(w["estimate_hours"] for w in wrs)
        return {
            "query": q_clean,
            "intent": intent,
            "routed_by": routed_by,
            "headline": (
                f"{target_tag} ({eq['description'] if eq else 'Unit 200 asset'}) sits in area {eq['area'] if eq else ''}, "
                f"sheet {sheet_no}, envelope {', '.join(env_ids) or 'none'}, with {len(wrs)} active work requests ({hrs:,} hrs)."
            ),
            "cypher_name": "equipment_context",
            "cypher_params": {"tag": target_tag},
            "cypher_query": (
                f"MATCH (e:Equipment {{tag: '{target_tag}'}}) "
                "OPTIONAL MATCH (env:IsolationEnvelope)-[:CONTAINS]->(e) "
                "OPTIONAL MATCH (s:ScopeItem)-[:RESOLVES_TO]->(e) "
                "RETURN e.tag, e.sheet, collect(DISTINCT env.id) AS envelopes, collect(DISTINCT s.request_id) AS requests"
            ),
            "highlight": {
                "view": "pid",
                "equipment_tags": [target_tag],
                "sheet_no": sheet_no,
                "envelope_id": env_ids[0] if env_ids else None,
                "request_ids": [w["request_id"] for w in wrs],
            },
            "rows": [
                {
                    "kind": "work_request",
                    "id": w["request_id"],
                    "title": w["title"],
                    "source_group": w["source_group"],
                    "ript_score": w["ript_score"],
                    "estimate_hours": w["estimate_hours"],
                    "match_status": w["match_status"],
                }
                for w in wrs
            ],
            "follow_ups": [
                {"label": f"Show {target_tag} in Relate graph", "view": "graph", "equipment_tags": [target_tag]},
                {"label": f"Highlight {target_tag} on plot plan", "view": "plot", "equipment_tags": [target_tag]},
                *(
                    [{"label": f"Everything in {env_ids[0]}", "query": f"What shares {env_ids[0]} with {target_tag}?"}]
                    if env_ids
                    else []
                ),
            ],
        }

    # Default: equipment_search by class/keyword across Unit 200
    q_low = q_clean.lower()
    class_filter = None
    for kw, cls in (
        ("exchanger", "exchanger"),
        ("pump", "pump"),
        ("compressor", "compressor"),
        ("reactor", "reactor"),
        ("heater", "heater"),
        ("column", "column"),
        ("vessel", "vessel"),
        ("drum", "vessel"),
        ("air cooler", "air_cooler"),
        ("filter", "filter"),
    ):
        if kw in q_low:
            class_filter = cls
            break
    matched_eq = [
        e for e in equipment_list if (class_filter is None or e["equipment_class"] == class_filter)
    ]
    return {
        "query": q_clean,
        "intent": "equipment_search",
        "routed_by": routed_by,
        "headline": f"Found {len(matched_eq)} matching Unit 200 major equipment tags" + (f" ({class_filter})." if class_filter else "."),
        "cypher_name": "equipment_list",
        "cypher_params": {"equipment_class": class_filter or ""},
        "cypher_query": (
            "MATCH (e:Equipment) "
            + (f"WHERE e.equipment_class = '{class_filter}' " if class_filter else "")
            + "RETURN e.tag, e.equipment_class, e.area, e.sheet ORDER BY e.tag"
        ),
        "highlight": {
            "view": "plot",
            "equipment_tags": [e["tag"] for e in matched_eq],
        },
        "rows": [
            {
                "kind": "equipment",
                "id": e["tag"],
                "title": e["description"],
                "area": e["area"],
                "sheet": e["sheet"],
                "envelopes": e["envelopes"],
                "jobs": sum(1 for w in active_items if w.get("resolved_tag") == e["tag"]),
            }
            for e in matched_eq[:20]
        ],
        "follow_ups": [
            {"label": "Check duplicate scope pairs", "query": "Show all duplicate work requests"},
            {"label": "Test $22M budget cut line", "query": "Test $22M budget cut line"},
        ],
    }
