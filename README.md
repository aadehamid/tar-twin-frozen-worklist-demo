# TAR digital twin: frozen work list demo

A working demo of the 3.1 Frozen Work List MVP from the turnaround (TAR) digital twin proposal. It runs on synthetic data for a made-up diesel hydrotreater, Unit 200, and is built like production software so the audience sees how the real thing would behave.

> Status: design phase. This repo holds the design and scenario documents only. No application code has been written yet. Build starts at phase 0 once the documents are approved.

## What the demo shows

The 3.1 MVP ships five things in release one. The demo walks through each of them on one screen flow:

1. **Tag registry and match rate.** Scope items in IMPACT Web name their equipment in free text, because a code freeze stops IMPACT Web from adding a tag lookup. The twin resolves each item to an equipment tag and reports the match rate per site. Weak matches go to a review queue.
2. **IMPACT Web read.** The twin reads each work request's description, driver, RIPT score and estimate. It never writes back.
3. **Scope on the plant.** Jobs appear on a 2D plot plan. Jobs that share scaffold, isolation or access are grouped, and each group is costed once.
4. **Cut line by location.** A budget target splits scope above and below the line, shown on the plant, ready for the DRB review.
5. **Frozen baseline.** The list is snapshotted at freeze. Every later add or delete is logged with hours and a reason, and scope growth after freeze is tracked in man-hours.

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
 AI matcher (OpenRouter, Inkling 2 Mini) ──► match proposals ──► review queue
```

- **IMPACT Web (mock)** is the system of record for scope. FastAPI, SQLModel and PostgreSQL, with its own React front end.
- **CMMS / TLM (mock)** holds the equipment master: tags, functional locations and classes.
- **The digital twin** is a second FastAPI service on Neo4j. It builds the plant graph from DEXPI P&IDs, mirrors IMPACT Web scope, and computes matches, isolation envelopes, clusters, the cut line and the baseline.
- **The twin front end** shows the plot plan, the P&ID sheets and a graph panel. The graph panel runs Relate, Neo4j's embedded Cypher engine, in the browser as WebAssembly. It holds a read-only copy of the twin graph, so a click on a job runs real Cypher in the page and shows the chain from work request to equipment, piping, block valves, isolation envelope and neighbouring jobs.
- **The AI matcher** handles the tag matches that rules and fuzzy matching can't settle. It calls Inkling 2 Mini through OpenRouter by default. Any OpenRouter model, or a local Ollama model, works through the same setting.

Both services start from the [full-stack FastAPI template](https://github.com/fastapi/full-stack-fastapi-template).

## Repository layout (planned)

```
apps/
  impactweb/          IMPACT Web mock: backend (FastAPI, Postgres) and frontend (React)
  twin/               Digital twin: backend (FastAPI, Neo4j) and frontend (React, Relate WASM)
jobs/                 Ingest and sync jobs: DEXPI to Neo4j, IMPACT Web to twin, browser graph export
data/scenario/        Synthetic Unit 200: DEXPI sheets, plot plan layout, equipment master, work list
docs/                 Design, scenario spec and decision records
compose.yml           Postgres, Neo4j, both services
```

## Documents

- [docs/design.md](docs/design.md) covers the architecture, components, graph model, data flows, AI matching, the Relate browser graph, extension to 4.1 and 4.2, testing and build phases.
- [docs/scenario-spec.md](docs/scenario-spec.md) covers Unit 200, the turnaround event, the candidate work list, the problems planted in the data and the demo walkthrough.
- [docs/decisions.md](docs/decisions.md) records the technology choices and the reasons for them.

## Ground rules

- **All data is synthetic.** Unit 200, its tags and its people are invented. No client data, screens or tags appear anywhere in this repo.
- **The twin never writes to IMPACT Web.** Change data at the source and the twin picks it up on the next sync.
- **Value figures are the focus-area brief's default assumptions** and are labeled as unvalidated wherever they appear.
- **Out of scope for release one:** set-level what-if (31-f3) and remote estimating (31-f6). They wait for standardized Phase 3 estimates and craft-level actual hours.

## Running it

There's nothing to run yet. Once phase 0 lands, `docker compose up` will start Postgres, Neo4j and both services, and seed Unit 200. The README will then list the URLs and demo logins.

## Configuration (planned)

| Variable | Purpose | Default |
|---|---|---|
| `LLM_BASE_URL` | OpenAI-compatible endpoint for the AI matcher | `https://openrouter.ai/api/v1` |
| `LLM_MODEL` | Model ID | `thinkingmachines/inkling-2-mini` |
| `LLM_API_KEY` | OpenRouter key; leave empty to run rules-only matching | empty |
| `NEO4J_URI` | Twin graph store | `bolt://neo4j:7687` |
| `POSTGRES_*` | IMPACT Web and CMMS mock database | from the template |
