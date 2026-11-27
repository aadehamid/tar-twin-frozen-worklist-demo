# TAR digital twin: frozen work list demo

A working demo of the 3.1 Frozen Work List MVP from the turnaround (TAR) digital twin proposal. It runs on synthetic data for a made-up diesel hydrotreater, Unit 200, and is built like production software so the audience sees how the real thing would behave.

> Status: design phase. This repo holds the design and scenario documents only. No application code has been written yet. Build starts at phase 0 once the documents are approved.

## What the demo shows

The 3.1 MVP ships five things in release one. The demo walks through each of them on one screen flow:

1. **Tag registry and match rate.** Scope items in IMPACT Web name their equipment in free text, because a code freeze stops IMPACT Web from adding a tag lookup. The twin resolves each item to an equipment tag and reports the match rate per site. Weak matches go to a review queue. A mapping trace shows every step from the IMPACT Web entry to the equipment in the twin.
2. **IMPACT Web read.** The twin reads each work request's description, driver, RIPT score and estimate. It never writes back.
3. **Scope on the plant.** Jobs appear on a 2D plot plan. Jobs that share scaffold, isolation or access are grouped, and each group is costed once.
4. **Cut line by location.** A budget target splits scope above and below the line, shown on the plant, ready for the DRB review.
5. **Frozen baseline.** The list is snapshotted at freeze. Every later add or delete is logged with hours and a reason, and scope growth after freeze is tracked in man-hours.

## Two modes

- **Demo mode** runs the scripted 10-minute walkthrough on seeded data.
- **Planning mode** lets a team rehearse a Unit 200 turnaround. People log in with roles (TA manager, planner, source groups, DRB), raise and challenge requests in IMPACT Web, and watch the twin respond, while a facilitator moves the clock and adds surprises. See [docs/interactive-planning.md](docs/interactive-planning.md).

## How it works

```
                 read only, no write-back
 IMPACT Web  ───────────────────────────────►  Digital twin
 (mock, Postgres)        sync job               (Neo4j)
       ▲                                           ▲   │
       │ planners raise and                        │   │ Cypher export
       │ edit work requests          DEXPI P&IDs ──┘   ▼
       │                             (pyDEXPI)     Twin front end
 IMPACT Web UI                                     plot plan, P&ID,
                                                   graph panel (Relate in WASM)
 CMMS / TLM (mock) ── equipment master ──► twin
 AI matcher (OpenRouter, Perplexity Decider) ──► match proposals ──► review queue
```

- **IMPACT Web (mock)** is the system of record for scope. FastAPI, SQLModel and PostgreSQL, with its own React front end.
- **CMMS / TLM (mock)** holds the equipment master: tags, functional locations and classes.
- **The digital twin** is a second FastAPI service on Neo4j. It builds the plant graph from DEXPI P&IDs, mirrors IMPACT Web scope, and computes matches, isolation envelopes, clusters, the cut line and the baseline.
- **The twin front end** shows the plot plan, the P&ID sheets and a graph panel. The graph panel runs Relate, Neo4j's embedded Cypher engine, in the browser as WebAssembly. It holds a read-only copy of the twin graph, so a click on a job runs real Cypher in the page and shows the chain from work request to equipment, piping, block valves, isolation envelope and neighbouring jobs.
- **The AI matcher** handles the tag matches that rules and fuzzy matching can't settle. It calls Perplexity Decider, a decision model, through OpenRouter's Decisions API. Decider picks one of code's candidate tags or none and returns a probability for each. It writes no text, so there's nothing to parse. Other decision models on OpenRouter take the same request, and Decider's weights are open, so a client could host it.

Both services start from the [full-stack FastAPI template](https://github.com/fastapi/full-stack-fastapi-template).

## Repository layout (planned)

```
apps/
  impactweb/          IMPACT Web mock: backend (FastAPI, Postgres) and frontend (React)
  twin/               Digital twin: backend (FastAPI, Neo4j) and frontend (React, Relate WASM)
jobs/                 Ingest and sync jobs: DEXPI to Neo4j, IMPACT Web to twin, browser graph export
data/scenario/        Synthetic Unit 200: DEXPI sheets, plot plan layout, equipment master, work list
specs/                Quint workflow spec and SHACL shapes
docs/                 Design, scenario spec, verification plan and decision records
compose.yml           Postgres, Neo4j, both services
```

## Documents

- [docs/design.md](docs/design.md) covers the architecture, components, graph model, data flows, AI matching, the Relate browser graph, extension to 4.1 and 4.2, testing and build phases.
- [docs/scenario-spec.md](docs/scenario-spec.md) covers Unit 200, the turnaround event, the candidate work list, the problems planted in the data and the demo walkthrough.
- [docs/verification.md](docs/verification.md) covers how everything is checked as it is written: schemas, SHACL engineering rules in Neo4j, property tests, and a Quint (TLA) model of the sync, review and freeze workflow.
- [docs/matching-showcase.md](docs/matching-showcase.md) covers which equipment references plain code resolves, where AI tells similar names apart, how code checks the AI, and how the demo compares the two.
- [docs/interactive-planning.md](docs/interactive-planning.md) covers planning mode: roles, the exercise clock, injects, the debrief, and the checks it must pass.
- [docs/hosting.md](docs/hosting.md) covers the exe.dev VM for team exercises: what runs where, the 4 GB memory budget, sign-in, deploys, backups and the hosting checks.
- [docs/decisions.md](docs/decisions.md) records the technology choices and the reasons for them.

## How we work

Two rules from [CONTRIBUTING.md](CONTRIBUTING.md) apply to every change. First, decide and write down how a change will be validated before writing it. Second, a different AI model from the author reviews every PR before it merges.

## Ground rules

- **All data is synthetic.** Unit 200, its tags and its people are invented. No client data, screens or tags appear anywhere in this repo.
- **The twin never writes to IMPACT Web.** Change data at the source and the twin picks it up on the next sync.
- **Value figures are the focus-area brief's default assumptions** and are labeled as unvalidated wherever they appear.
- **Out of scope for release one:** set-level what-if (31-f3) and remote estimating (31-f6). They wait for standardized Phase 3 estimates and craft-level actual hours.

## Running it

There's nothing to run yet. Once phase 0 lands, `docker compose up` will start Postgres, Neo4j and both services, and seed Unit 200. The README will then list the URLs and demo logins. Team exercises will run on an exe.dev VM (see [docs/hosting.md](docs/hosting.md)).

## Configuration (planned)

| Variable | Purpose | Default |
|---|---|---|
| `DECIDER_URL` | Decisions endpoint for the AI matcher | `https://openrouter.ai/api/alpha/decisions` |
| `DECIDER_MODEL` | Decision model ID | `perplexity/pplx-decider-v1.3:free` |
| `DECIDER_API_KEY` | OpenRouter key; leave empty to run rules-only matching | empty |
| `NEO4J_URI` | Twin graph store | `bolt://neo4j:7687` |
| `POSTGRES_*` | IMPACT Web and CMMS mock database | from the template |
