# Design: frozen work list demo

Version 0.1, for review. Nothing in this document has been built yet.

## 1. Purpose

The demo shows a client audience what the 3.1 Frozen Work List MVP would look like in use. It has to be convincing to turnaround planners and to architects. Planners need to recognise their own work: the work list, the scope challenge, the freeze, late adds. Architects need to see that the parts are real: a system of record, a separate twin, a one-way sync, a graph built from a standard P&ID format, and AI that proposes rather than decides.

The demo also has to grow. 4.1 (Work Instructions & Job Packages) and 4.2 (Finalized Execution Plan) should be able to attach to the same graph later without a rewrite.

What the demo does not try to prove is whether the client's real data will match well enough. That is what the match-rate gate (31-n5) tests at the pilot site.

## 2. Scope

### In release one of the demo

| MVP item | Requirement IDs | What the demo does |
|---|---|---|
| Tag registry and match rate | 31-d1, 31-n5 | Resolves free-text equipment references to tags, scores each match, reports match rate per site and per area, and sends weak matches to a review queue |
| IMPACT Web read | 31-d3 | Reads work requests through the IMPACT Web API on a schedule. No writes back |
| Scope on the model, shared-cost clusters | 31-f1, 31-f2 | Places jobs on a 2D plot plan and groups jobs that share scaffold, isolation or access |
| Cut line by location | 31-f5 | Ranks scope against a budget target and shows above and below the line on the plant |
| Frozen baseline and change log | 31-n1 | Snapshots the list at freeze, logs each later add or delete with hours, reason and source group, and tracks scope growth |

### Out of release one

- Set-level what-if (31-f3), which waits for standardized Phase 3 estimates (31-d8).
- Remote estimating (31-f6), which waits for craft-level actual hours (31-n6).
- Any write-back to IMPACT Web.
- 3D. The demo is 2D. The plot-plan layer is built so a 3D view can read it later.

The demo can show one "wave 2" screen that previews 31-f3 with fixed data, clearly labeled as a preview.

## 3. Architecture

### 3.1 Components

| Component | Role | Stack | Stands in for |
|---|---|---|---|
| IMPACT Web API | System of record for scope: turnaround events, work requests, estimates, RIPT scores, review decisions, freeze | FastAPI, SQLModel, PostgreSQL | IMPACT Web |
| IMPACT Web UI | Where planners and source groups raise and edit work requests, and the TA manager runs the challenge, DRB and freeze | React, TypeScript, Vite, Tailwind, shadcn/ui, TanStack Router and Query | IMPACT Web screens |
| CMMS / TLM module | Equipment master: tag, description, class, functional location, area, status | Module inside the IMPACT Web service with its own schema and API prefix | Maximo or JDE, plus TLM |
| Twin API | Plant graph, scope mirror, matching, envelopes, clusters, cut line, baseline, KPIs | FastAPI, Neo4j Python driver, pyDEXPI | The twin platform |
| Twin UI | Plot plan, P&ID viewer, graph panel, match review, cut line, baseline and KPIs | React, same front-end stack, SVG and d3-zoom for the plot plan, Cytoscape.js for graph drawing, Relate WASM for the in-browser graph | The twin front end |
| Ingest jobs | DEXPI to Neo4j load, IMPACT Web and CMMS sync, browser graph export | Python, run by the twin service's scheduler or by CLI | Databricks jobs |
| AI matcher | Proposes tags for hard matches with a reason and cited evidence | OpenAI-compatible client, OpenRouter by default | A client-approved LLM endpoint |

### 3.2 Why two services

The twin can only reach IMPACT Web through its public API, the same way it would reach a real export or integration. That keeps the code-freeze constraint and the read-only rule honest: there is no shared database and no back door. Each mock sits behind a client interface in the twin (`ImpactWebClient`, `CmmsClient`), so a real connector can replace it without touching twin logic.

### 3.3 Deployment

- `compose.yml` runs Postgres, Neo4j, the IMPACT Web service and the twin service. Each service serves its built front end, following the template.
- Two front ends under two paths on one port, `/impactweb/` for IMPACT Web and `/twin/` for the twin, each with its own look, so the audience sees two separate systems. Locally they run on two ports as usual. One port on the VM is explained in [hosting.md](hosting.md) section 1.
- In local development, Neo4j Browser is available on `:7474` for architects who want to query the twin directly. On the hosted VM it is not exposed (see [hosting.md](hosting.md)).
- Development without Docker is also supported: a local Postgres 18, the Mailpit binary in place of the Compose mail catcher, a local Neo4j and `uv run` for each service. The [template spike](spikes/template-no-docker.md) ran the template's own CI this way, and the [SHACL spike](spikes/shacl-n10s.md) ran Neo4j 5.26 with n10s from the release tarball.
- Hosted team exercises run on one exe.dev VM. See [hosting.md](hosting.md).

## 4. Data model

### 4.1 IMPACT Web (Postgres)

Kept close to how a turnaround work list is managed, and deliberately limited where the real system is limited.

- `exercise`: id, name, mode (demo or planning), starting fixture, clock step. Every table below carries `exercise_id`. Demo mode is one fixed exercise.
- `turnaround_event`: id, site, unit, name, planned start, duration days, freeze date, budget target.
- `work_request`: id (for example `WR-200-0147`), event id, title, description (free text), equipment text (free text, no tag lookup), driver (inspection, reliability, regulatory, capital, operations), source group, RIPT score, estimate hours by craft, estimate cost, status (candidate, screened out, accepted, rejected, deferred, deleted), version (raised on every edit, used for optimistic locking), decision reason, submitted at, updated at.
- `review_decision`: request id, request version, stage (fit to frame, challenge, DRB), kind (recommendation or final), decision, reason, decided by, decided at. A decision goes stale when the request moves past its version.
- `freeze`: event id, frozen at, frozen by, list version.
- `freeze_item`: freeze id, request id, request version, and a copy of the request's fields at freeze. Written once, never changed.
- `change_request`: request id, base version, type (add, delete, change), schedule impact days, mandatory or discretionary, risk if not done, hours and cost delta, evidence, raised by, status (pending, approved, rejected), decided by, reason.
- `change_feed`: a sequence number for every committed change to a request, decision, freeze or change request. Writes to the feed take a per-exercise lock, so sequence order matches commit order and the twin never skips a gap. The twin syncs from this feed.
- `user` and auth from the template. The template only has a superuser flag, so the service adds `exercise_membership` (user, exercise, role) with the roles and permissions in [interactive-planning.md](interactive-planning.md) section 2. The twin's service account has its own read-only role.

The equipment field stays free text on purpose. It mirrors the IMPACT Web code freeze that the workshop described, which is the reason the twin needs a tag registry at all.

### 4.2 CMMS / TLM (Postgres, separate schema)

- `equipment`: tag (for example `E-201A`), description, class (exchanger, vessel, column, heater, reactor, pump, compressor, air cooler, PSV, valve, instrument), functional location, area, parent tag, status.
- `functional_location`: code, description, parent.

### 4.3 Twin graph (Neo4j)

Plant, from DEXPI:

- `(:Equipment {tag, dexpi_id, class, description})`
- `(:Nozzle {id})`, `(:PipingSegment {line_number, spec, size})`, `(:Valve {tag, type, role})` where role is block, control, check or relief
- `(:Instrument {tag, type})`
- `(:PidSheet {number, title, svg_path})`
- `(:Area {code, name})`, `(:PlotPosition {x, y, elevation, footprint})`
- Relationships: `HAS_NOZZLE`, `CONNECTED_TO` (directed, following the DEXPI connectivity), `ON_SHEET`, `LOCATED_IN`, `POSITIONED_AT`, `PART_OF`

Derived plant structure:

- `(:IsolationEnvelope {id, boundary_valve_count, blind_estimate})` with `CONTAINS` to equipment and `BOUNDED_BY` to block valves. Computed by walking `CONNECTED_TO` from each piece of equipment until every path ends at a block valve, a blind point or a boundary.

Scope and decisions:

- `(:ScopeItem {exercise_id, request_id, version, title, driver, ript, hours, cost, status})`, mirrored from IMPACT Web on each sync. Every scope and decision node carries `exercise_id`. The plant graph from DEXPI is shared by all exercises, read-only, and keyed on DEXPI ID
- `(:ScopeItem)-[:RESOLVES_TO {confidence, method, status, reviewed_by}]->(:Equipment)` where method is exact, rule, fuzzy or ai, and status is proposed, accepted or rejected
- `(:MatchProposal {model, question_version, probabilities, confidence, evidence})` for AI proposals, linked to the scope item and the candidate tags
- `(:Cluster {id, type, shared_hours, shared_cost})` where type is scaffold, isolation or access, with `INCLUDES` to scope items
- `(:Baseline {event, freeze_id, list_version, frozen_at, ready_for_use})` built from IMPACT Web's frozen copy, with `INCLUDES` to the frozen item versions
- `(:ChangeEvent {change_request_id, type, mandatory, at, hours_delta, reason, source_group})` for approved changes only, unique on change request ID, linked to the scope item and the baseline
- `(:CutLineRun {name, budget, ranking_rule, scope_version, saved_by, at, feasible, shortfall})` with `ABOVE` and `BELOW` to scope items. Twin-local. Saving one never changes a request

Reserved for later, with no features in release one:

- 4.1: `(:WorkPackage)-[:FOR]->(:ScopeItem)`, `(:Standard)`, `(:Material)`, `(:Redline)`
- 4.2: `(:Activity {start, end})-[:EXECUTES]->(:ScopeItem)`, `(:LogisticsObject {type, footprint, active_from, active_to})` for cranes, laydown, scaffold and tanks, `(:Permit)`

### 4.4 Plot plan layer

DEXPI describes process connectivity, not where equipment sits on the plot. A separate file, `data/scenario/plot-plan.json`, gives each major tag an area, x and y position, elevation and footprint. The twin loads it into `PlotPosition` nodes. Shared scaffold and access are computed from it: jobs on equipment within a set distance and at similar elevation in the same area are scaffold candidates.

## 5. Data flows

### 5.1 Plant load

1. `jobs/load_dexpi.py` reads each DEXPI XML sheet in `data/scenario/dexpi/` with pyDEXPI.
2. It exports the pyDEXPI graph (NetworkX) and writes nodes and relationships to Neo4j with `MERGE` on DEXPI IDs.
3. It renders each sheet to SVG with pyDEXPI and stores the file path on the `PidSheet` node.
4. It loads the plot-plan layer and computes isolation envelopes.

### 5.2 Scope sync (read only)

1. The twin scheduler calls `GET /api/v1/changes?exercise_id=…&after_seq=…` on IMPACT Web every 60 seconds, and on demand from "sync now". Only one sync runs per exercise at a time.
2. It upserts `ScopeItem` nodes keyed on exercise, request ID and version, and stores the last sequence number it applied in the same Neo4j transaction, so a crash mid-sync resumes cleanly. Replaying a sync changes nothing.
3. When the feed shows a freeze, the twin reads the frozen copy (`GET /api/v1/freezes/{id}/items`) and builds the baseline from it.
4. Approved change requests become `ChangeEvent` nodes, unique on change request ID. Pending and rejected ones are mirrored but don't count toward growth.
5. The twin never calls a write endpoint on IMPACT Web. The IMPACT Web API gives the twin's service account a read-only role, and a test checks it.

### 5.3 Matching

1. **Exact.** A tag pattern in the equipment text or description that matches a CMMS tag.
2. **Rules.** Known aliases and patterns, for example "feed/eff exch A" to `E-201A`, or "charge pump south" to `P-201B`, from a small alias table.
3. **Fuzzy.** rapidfuzz scoring against tag descriptions within the work request's area, if one is given.
4. **AI.** Anything left below the confidence threshold goes to the AI matcher (section 6). Code gathers the candidates and their DEXPI facts first, and code checks the AI's answer afterwards. The split, and how the demo shows it, is in [matching-showcase.md](matching-showcase.md).
5. **Review.** A tag is eligible as a candidate only if it is active, in Unit 200 (a unit prefix in the text counts) and passes the compatibility check (work type against equipment class). An ineligible tag gets a `Finding` in the trace and is left out of the candidates. Code accepts a match on its own only when the text yields exactly one eligible tag and, for an alias, the rule scores above the auto-accept threshold. The trace says so. Eligible tags that miss this stay candidates. Every other match, and every AI proposal however confident, lands in the review queue. A planner accepts, rejects or picks another tag. The decision is stored on `RESOLVES_TO`.
6. **Match rate.** The share of active scope items with an accepted match, reported per site, per area and per source group. The gate threshold (default 95 percent) is a setting.

### 5.4 Mapping trace

Every work request keeps a full record of how it got to its equipment, so anyone can see exactly how an IMPACT Web entry maps to the twin:

1. The raw equipment text and description as they stand in IMPACT Web, with the IMPACT Web request ID and last-updated time.
2. The normalized text, for example `200-E-201 B` to `E-201B`.
3. Each method that ran (exact, rules, fuzzy, AI), what it found and its score.
4. The candidate tags it considered, with class, area and DEXPI neighbours.
5. For AI proposals, the model version, question version, the probability for each candidate and the evidence fact it picked.
6. The reviewer's decision, who made it and when.
7. The result: the equipment node in the twin, its P&ID sheet, its plot position and its isolation envelope.

The trace is stored on the `RESOLVES_TO` relationship and its `MatchProposal`, so it can be queried in Cypher as well as viewed. In IMPACT Web, each request shows a "view in twin" link. It is only a link out to the twin, not a field the twin writes.

### 5.5 Clusters and the cut line

- **Isolation clusters.** Scope items whose resolved equipment sits in the same isolation envelope. The shared blinding and isolation cost is counted once.
- **Scaffold clusters.** Scope items whose equipment is close together at similar elevation.
- **Access clusters.** Scope items in the same congested area that need the same crane or laydown.
- **Cut line.** Scope is ranked by RIPT score, mandatory drivers first, then by cost per risk point using clustered (not summed) shared costs. The budget target sets the line. The plot plan colours above and below the line.

### 5.6 Freeze and change simulation

- Freeze happens in IMPACT Web. The TA manager freezes the list, IMPACT Web writes the frozen copy, and the next sync builds the twin baseline from it. The race rules are in [interactive-planning.md](interactive-planning.md) section 3.4.
- The twin marks the baseline ready for 3.1 use only when the match rate on frozen items passes the gate. This is separate from the freeze itself.
- A simulation job (`jobs/simulate_late_scope.py`) raises a scripted set of change requests in IMPACT Web through its API, and approves or rejects them as the TA manager would, spread over the months after freeze. The twin picks them up through the normal sync. Scope growth in man-hours rises on the KPI panel as approved changes land.

### 5.7 Browser graph export

- `GET /api/v1/graph/export.cypher?event_id=…` on the twin returns a Cypher script for the plant graph and the event's scope.
- The twin UI loads Relate WASM in a module worker, creates an in-memory store and runs the script.
- The graph panel then runs Cypher locally. Example: click `WR-200-0147` and the page runs a fixed query that returns the work request, its resolved equipment, the connected piping and block valves, the isolation envelope and the other scope items inside it. The panel shows the query text next to the drawing.
- Relate's read-only mode starts empty and refuses every write, so the browser copy can't be seeded and then switched to read-only. Instead the store stays private to the worker. The worker seeds once, from the twin's own export endpoint, and after that runs only the panel's named queries with string parameters, refusing any other Cypher text. Neo4j stays the master. The worker has no connection to it ([spike](spikes/relate-wasm.md)).
- After seeding, the worker should run each named query once to warm it up. The first run of a query took about 110 ms in the spike, and later runs about 25 ms.

## 6. AI matcher

- **Model.** Perplexity Decider v1.3 through OpenRouter's Decisions API (`POST /api/alpha/decisions`), set by `DECIDER_MODEL`. Decider is a decision model. It returns a probability for each option in a list instead of writing text ([Perplexity Decisions docs](https://docs.perplexity.ai/docs/decisions/decisions)). The weights are on Hugging Face under Apache 2.0, so a client could host it. The phase 0 spike measured about 0.3 seconds median per call ([spike](spikes/decider-matcher.md)).
- **Input.** The work request text, the area if known, and up to 20 candidate tags from the fuzzy step, each with its class, description, area and DEXPI neighbours (for example "downstream of R-201, upstream of A-201").
- **Output.** Two choice answers per request. `tag` is one of the candidates or none, with a probability for each and a confidence. `evidence` is the ID of the fact that best identifies the equipment. "None" is an abstention and creates no proposal. For a picked tag, code checks that the response is well formed (choices from the options sent, probabilities summing to 1), that the evidence fact belongs to the picked tag, and the compatibility rule. A pick that fails any check counts as "no proposal". Decider writes no reason, so the review queue shows the candidate probabilities and the text of the evidence fact.
- **Reason writer.** After the checker passes a pick, Inkling 2 Mini (`REASON_MODEL`, OpenRouter chat completions with a JSON schema) writes one sentence explaining it from the picked tag's facts. It runs in the background, sees only the pick and its facts, and can't change the outcome. Code drops a reason that names any tag other than the pick. The queue labels it as an AI summary of the selected facts. Each reason is stored against the exact proposal ID and version it explains, so a late reason for a superseded proposal is discarded. With no reason, the queue still shows probabilities and evidence.
- **Guardrails.** The model can only choose from the candidate list. It never creates tags. Every proposal goes to the review queue, however confident. Question wording is versioned, and each proposal records the model version served, question version and latency.
- **Offline mode.** With no API key the matcher skips the AI step and more items go to review. The demo still runs.

## 7. Front ends

### 7.1 IMPACT Web UI

Built to look like an enterprise system of record, plain and dense, so it reads as a different product from the twin.

- Turnaround event list and event dashboard: counts by status, hours, cost against target, freeze status.
- Work request list with filters, and a detail and edit form. The equipment field is free text.
- Review screens for fit to frame, challenge and DRB decisions.
- Freeze action for the TA manager role, and the change request process after freeze.
- A banner showing that the twin reads this system and never writes to it.

### 7.2 Twin UI

- **Plot plan.** Unit 200 in 2D, with areas, equipment footprints and job markers. Layers for match status, clusters, cut line and changes after freeze.
- **P&ID viewer.** DEXPI sheets as SVG, with the selected job's equipment and envelope boundary valves highlighted.
- **Graph panel.** Relate in the browser, Cytoscape.js drawing and the Cypher text.
- **Mapping trace.** Pick any IMPACT Web request and see each step from raw text to equipment (section 5.4). The plot plan, P&ID and graph panel highlight the result together. A side-by-side mode shows the IMPACT Web record on the left and the twin equipment on the right.
- **Match review.** The queue with method, confidence, candidate probabilities, the evidence fact and the reason when Inkling has written one, plus accept, reject and pick-another actions. Match rate by area and source group.
- **Matching lab.** Steps through one request showing what code did and what the AI did, in different colours, and compares code only, code then AI, and AI on everything against the answer key. See [matching-showcase.md](matching-showcase.md).
- **Clusters and cut line.** Cluster list with shared hours and cost counted once, the budget slider and the above and below totals.
- **Baseline and KPIs.** Scope growth after freeze in man-hours, tag match rate per site, and hours bundled or removed at the challenge. A value panel uses the brief's default assumptions, labeled unvalidated.

## 8. Extending to 4.1 and 4.2

- **4.1.** Work packages attach to `ScopeItem` and `Equipment`. Alpacka-style drafting would read twin context through a twin API, which keeps the Alpacka boundary decision open. A `jobs/` loader would add standards, materials and redlines.
- **4.2.** Activities from a P6-like schedule attach to `ScopeItem` with time windows. Logistics objects (cranes, laydown, scaffold) are the one place the twin is the system of record, as the brief proposes (42-p5). The plot-plan layer already holds the positions a 4D view needs.
- **The shared base** is the tag registry, the frozen and tagged list, and the isolation envelopes. 3.1 builds them, and 4.1 and 4.2 consume them, which matches the build order on the proposal's dependency slide.

## 9. Testing and verification

See [verification.md](verification.md) for the full plan: schemas, SHACL engineering rules, property tests and a Quint model of the workflow. The tests below sit alongside it.

- **Backend.** Pytest for both services, with a Neo4j test container or local instance for the twin.
- **Contract tests.** Twin to IMPACT Web, including a test that the twin's service account gets a 403 on any write.
- **Scenario tests.** The seeded Unit 200 data produces the expected match rate before and after review, the expected clusters, and the expected scope growth after the simulation runs.
- **Front end.** Playwright end-to-end tests that follow the demo script.
- **CI.** GitHub Actions on each push.

## 10. Build phases

Each phase ends with a check-in before the next starts. Within each phase, the checks are written before the code, and each PR gets a review from a different model before merge ([CONTRIBUTING.md](../CONTRIBUTING.md)).

| Phase | Work | Exit check |
|---|---|---|
| 0. Spikes | Build and render one DEXPI sheet with pyDEXPI (done, see [spike](spikes/dexpi-sheet.md)). Seed Relate WASM from a Cypher script and run a traversal in a browser page (done, see [spike](spikes/relate-wasm.md)). Call Perplexity Decider on OpenRouter's Decisions API (done, see [spike](spikes/decider-matcher.md)). Run the template without Docker (done, see [spike](spikes/template-no-docker.md)). Run SHACL through n10s on a small graph (done, see [spike](spikes/shacl-n10s.md)). Model-check a first Quint spec of freeze and sync (done, see [spike](spikes/quint-worklist.md)). Optional: prove one cost rule in Bend 2 | Each spike works or has a named fallback |
| 1. Scenario data | Generate the Unit 200 DEXPI sheets, plot plan, equipment master and work list from the scenario spec, with schema and SHACL checks on every write | All engineering rules pass, the counts match the spec, and Hamid signs off the scenario |
| 2. IMPACT Web | Service and UI, including review and freeze | Source groups and planners raise requests, the TA manager runs the challenge and DRB and freezes the list, and changes after freeze go through change requests. Permission and freeze-race tests pass |
| 3. Twin plant graph | DEXPI load, plot plan, isolation envelopes | Envelopes match the scenario spec |
| 4. Sync and matching | Read-only sync, matching pipeline, AI matcher, review queue, match rate, mapping trace | Match rate before and after review matches the spec. Every request has a complete trace. The Quint workflow spec passes. Its sync and matching traces replay cleanly against the APIs. Baseline and change traces replay in phase 6. Planning-mode parts are checked as a model only until phase 8 |
| 5. Twin UI | Plot plan, P&ID viewer, graph panel, clusters, cut line | The demo script runs to the end of the cut-line step |
| 6. Baseline and KPIs | Freeze baseline, late-scope simulation, KPIs, value panel | Scope growth after freeze matches the spec. The Quint baseline and change traces replay cleanly |
| 7. Hardening | Compose, CI, Playwright, demo script, README | A fresh clone runs the demo with one command |
| 8. Planning mode | Exercises, roles per exercise, exercise clock, facilitator console, injects, reset, debrief ([interactive-planning.md](interactive-planning.md)) | All checks in section 5 of that document pass, the Quint planning traces replay cleanly, and the demo-mode suite still passes |

## 11. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| pyDEXPI cannot render a sheet built in code to SVG, because it lacks drawing data | No P&ID view | Write drawing positions into the generated sheets, or render our own SVG from DEXPI topology |
| Relate WASM limits, such as no multi-statement transactions and no loading a saved file in the browser | Seeding is slower or larger | Seed from a script in batches. The graph is small (a few thousand nodes) |
| An LLM proposes a plausible but wrong tag | Loss of trust | Candidate-only choices, every proposal reviewed, evidence shown |
| The demo looks too clean | Planners don't believe it | Plant the problems the workshop named, at realistic rates (see the scenario spec) |
| Scope creep into 4.1 or 4.2 | Release one slips | Schema slots only, no features |
