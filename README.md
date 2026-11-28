# TAR digital twin: frozen work list demo

A working demo of the 3.1 Frozen Work List MVP from the turnaround (TAR) digital twin proposal. It runs on synthetic data for a made-up diesel hydrotreater, Unit 200, and is built like production software so planners and architects see how the real system behaves.

## What the demo shows

The 3.1 MVP ships five capabilities in release one. The demo walks through each of them in one flow:

1. **Tag registry and match rate.** Scope items in IMPACT Web name their equipment in free text because a code freeze keeps IMPACT Web from adding a tag lookup. The twin resolves each item to a Unit 200 equipment tag, reports the match rate per site, area, and source group, and sends weak or AI-proposed matches to a review queue. A 7-step mapping trace shows every step from raw IMPACT Web text to the equipment in the twin.
2. **IMPACT Web read, and change requests raised from the twin.** The twin reads each work request's description, driver, RIPT score, and estimate through IMPACT Web's public API. After freeze, a planner can raise a change request from the twin. That call goes through IMPACT Web's own change request handler, as that planner, and waits for DRB approval there. That is the only write. IMPACT Web checks the planner role, the freeze, and the exercise's write-through switch. Write-through is a demo choice; the real write-back boundary stays open (see [D9](docs/decisions.md)).
3. **Scope on the plant and natural-language exploration.** Jobs appear on a 2D plot plan, real DEXPI 2.0.1 P&ID SVGs, and an in-browser Relate WASM graph panel. Planners can also type plain-English questions into the native Explore command bar to highlight shared isolation envelopes, duplicates, clusters, or budget cut-line options directly on the workspace.
4. **Shared-cost clusters and cut line by location.** Jobs sharing scaffold, isolation, or crane access are grouped so each shared setup is counted once. A budget slider ranks mandatory drivers first and shows above and below the cut line by location.
5. **Frozen baseline and post-freeze growth.** Freeze happens in IMPACT Web. The twin snapshots the immutable baseline, tracks 3.1 readiness separately against the 95% match-rate gate, logs approved post-freeze adds and deletes in man-hours, and displays focus-area brief value assumptions labeled as unvalidated.

## Running the demo with one command

Prerequisites: Docker Desktop (or OrbStack) with Docker Compose v2.

1. Copy the example environment file (optional, defaults work locally):

```bash
cp .env.example .env
```

2. Start the full stack (PostgreSQL 16, Neo4j 5.26 with n10s and APOC, IMPACT Web, Digital Twin, and Caddy edge proxy):

```bash
docker compose up --build
```

3. Open the landing page in your browser:

- Landing page: `http://127.0.0.1:8000/`
- IMPACT Web (system of record): `http://127.0.0.1:8000/impactweb/`
- Unit 200 Digital Twin: `http://127.0.0.1:8000/twin/`

To expose Neo4j Browser locally on `http://127.0.0.1:7474` without changing the hardened default stack, run:

```bash
docker compose -f compose.yml -f compose.local.yml up --build
```

### Demo accounts (local mode)

All local demo accounts share password `demo-pass-2028`:

| Account | Role | Purpose |
|---|---|---|
| `ta.manager@demo.local` | `ta_manager` | Challenge, DRB decisions, freeze list, approve or reject change requests, toggle write-through |
| `j.planner@demo.local` | `planner` | Accept or reject equipment matches in the twin, raise change requests from IMPACT Web or the twin |
| `fixed.lead@demo.local` | `source_group` | Create and edit fixed-equipment work requests |
| `rotating.lead@demo.local` | `source_group` | Create and edit rotating-equipment work requests |
| `drb.member@demo.local` | `drb_member` | Record DRB recommendations |
| `facilitator@demo.local` | `facilitator` | Administer exercises and maintenance mode |
| `viewer@demo.local` | `viewer` | Read-only observer |

### Running the scripted late-scope simulation

After freezing `TAR-200-2028` in IMPACT Web, run the 29 scripted post-freeze changes (18 approved adds, 6 approved deletes, 5 rejected; +4,020 net man-hours) through IMPACT Web's public API and sync the twin:

```bash
uv run --no-project --with httpx python jobs/simulate_late_scope.py \
  --impactweb-url http://127.0.0.1:18001 \
  --twin-url http://127.0.0.1:18002
```

## Architecture

- **Edge (`deploy/caddy/Caddyfile`).** Runs in host network mode on `127.0.0.1:8000`, serves the landing page, routes `/impactweb/` and `/twin/`, strips forged headers, and injects `X-Edge-Auth` only for loopback proxy traffic.
- **IMPACT Web (`apps/impactweb/`).** FastAPI, SQLModel, PostgreSQL 16, and a plain enterprise React UI. Includes the CMMS/TLM equipment master module.
- **Digital Twin (`apps/twin/`).** FastAPI, Neo4j 5.26 with neosemantics (n10s) SHACL validation and APOC triggers, pyDEXPI, and a React UI with 2D SVG plot plan (`d3-zoom`), DEXPI SVG P&ID viewer, Cytoscape.js, and `@relate/relate-wasm` running in a dedicated Web Worker.
- **AI matcher.** Uses Perplexity Decider v1.3 via OpenRouter's Decisions API (`DECIDER_API_KEY`) plus Inkling 2 Mini for one-sentence fact summaries. Runs offline on recorded fixtures or deterministic rules when `DECIDER_API_KEY` is unset.

## Repository layout

```text
apps/impactweb/     IMPACT Web API, CMMS module, React UI, and Dockerfile
apps/twin/          Digital Twin API, Neo4j SHACL store, React UI (Relate WASM), and Dockerfile
deploy/             Caddy reverse proxy config, landing page, and Neo4j + n10s + APOC Dockerfile
jobs/               Scenario generator, DEXPI loader, matcher evaluator, late-scope simulator
data/scenario/      Synthetic Unit 200 DEXPI sheets, plot plan, equipment master, work list, fixtures
specs/              SHACL shapes and Quint workflow specifications
scripts/            Validation checks, paired backup/restore, deploy, and project memory helpers
tests/              Unit, contract, Hypothesis property, Neo4j integration, and Playwright E2E tests
docs/               Design, scenario spec, verification plan, hosting guide, and decision records
compose.yml         Hardened 5-container stack (Postgres, Neo4j, IMPACT Web, Twin, Caddy edge)
```

## Backups and exe.dev VM deployment

See [docs/hosting.md](docs/hosting.md) for the 4 GB exe.dev VM layout, security checks, and restore runbook:

- Deploy to VM: `scripts/deploy.sh main`
- Paired watermark backup: `scripts/backup.sh /opt/tar-twin/backups`
- Paired restore with cutoff check: `scripts/restore.sh /opt/tar-twin/backups/<timestamp>`
- Copy backups off VM: `scripts/pull-backup.sh`

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `AUTH_MODE` | `local` (JWT login) or `exe` (edge headers) | `local` |
| `EDGE_AUTH_SECRET` | Shared secret between Caddy edge and backend services | local dev value |
| `TWIN_SYNC_TOKEN` | Read-only machine token for twin sync and CMMS reads | local dev value |
| `TWIN_RAISE_TOKEN` | Delegated machine token restricted to `POST /api/v1/twin/change-requests` | local dev value |
| `DECIDER_API_KEY` | OpenRouter API key; leave empty for rules plus recorded fixtures | empty |
| `DECIDER_URL` | Decisions endpoint for Perplexity Decider | `https://openrouter.ai/api/alpha/decisions` |
| `DECIDER_MODEL` | Decision model ID | `perplexity/pplx-decider-v1.3:free` |
| `REASON_MODEL` | Summary model for planner-facing fact sentence | `thinkingmachines/inkling-2-mini` |
| `NEO4J_URI` | Twin graph store | `bolt://neo4j:7687` |
| `DATABASE_URL` | IMPACT Web PostgreSQL connection string | Compose Postgres URL |

## Ground rules

- **Synthetic data only.** Unit 200 tags, equipment, personas, costs, and hours are invented.
- **Write-through is demo only.** IMPACT Web stays the system of record ([D9](docs/decisions.md)).
- **Value figures are unvalidated assumptions.** Focus-area brief defaults are labeled as unvalidated everywhere they appear.
- **Release-one scope.** Work packages (4.1) and execution plan/logistics (4.2) are reserved as null schema slots only.
- **Validation and review.** Run `scripts/check.sh` before pushing; every PR receives cross-model review ([CONTRIBUTING.md](CONTRIBUTING.md)).

## Documents

- [docs/design.md](docs/design.md)
- [docs/scenario-spec.md](docs/scenario-spec.md)
- [docs/verification.md](docs/verification.md)
- [docs/matching-showcase.md](docs/matching-showcase.md)
- [docs/interactive-planning.md](docs/interactive-planning.md)
- [docs/hosting.md](docs/hosting.md)
- [docs/decisions.md](docs/decisions.md)
