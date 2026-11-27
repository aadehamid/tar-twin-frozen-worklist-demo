# Decision records

Short records of the choices behind the design. Each one says what we chose, why, and what would make us revisit it.

## D1. Two FastAPI services in one repo

- **Decision.** IMPACT Web mock and the digital twin are separate services with separate databases and front ends, kept in one repository.
- **Why.** The twin should only reach scope through an API, which is how it would reach the real IMPACT Web. One repo keeps the demo easy to clone, run and version.
- **Revisit if.** Either service needs its own release cycle.

## D2. Start from the full-stack FastAPI template

- **Decision.** Both services start from [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template): FastAPI, SQLModel, PostgreSQL, React with TypeScript and Vite, Tailwind with shadcn/ui, JWT auth, Docker Compose, pytest and Playwright.
- **Why.** It gives auth, a generated API client, tests and CI from day one, so the demo looks and behaves like real software.
- **Revisit if.** The template's Postgres coupling gets in the way of the Neo4j-backed twin. The twin then keeps the template's auth and front end and drops SQLModel for its plant data.

## D3. Neo4j is the twin's master store

- **Decision.** The twin graph lives in Neo4j Community.
- **Why.** The twin's work is traversal: job to equipment to piping to valves to envelope to other jobs. Cypher states that directly. Neo4j Browser also lets architects check the graph themselves.
- **Revisit if.** The client standard for the graph store is different. The graph model doesn't depend on Neo4j-only features.

## D4. Relate in the browser for the graph panel

- **Decision.** The twin UI loads a read-only copy of the graph into Relate, Neo4j's embedded Cypher engine, compiled to WebAssembly and running in a browser worker.
- **Why.** The audience sees real Cypher run against the real graph when they click a job, with no round trip. It shows the connection rather than a picture of it.
- **Known limits.** In the browser, Relate can't open a saved database file or URL, and there are no multi-statement transactions, so we seed it from a Cypher script. Neo4j stays the master.
- **Revisit if.** The phase 0 spike shows seeding or query speed is not good enough at about 5,000 nodes. The fallback is the same panel calling the twin API.

## D5. DEXPI through pyDEXPI

- **Decision.** The plant model is authored as DEXPI P&IDs with [pyDEXPI](https://github.com/process-intelligence-research/pyDEXPI) and loaded into Neo4j from its graph export.
- **Why.** DEXPI is the open standard for P&ID data exchange, and the client's P&IDs could reach the twin in this form. pyDEXPI reads and writes it, renders SVG and exports to NetworkX.
- **Revisit if.** The SVG render of generated sheets fails in the phase 0 spike. We then render our own SVG from the DEXPI topology and keep DEXPI as the data source.

## D6. A separate plot-plan layer

- **Decision.** Equipment positions and elevations live in a separate file keyed by tag, not in DEXPI.
- **Why.** DEXPI describes connectivity, not plot location. Scaffold and access clusters need location. Keeping it separate lets a 3D model or GIS layer replace it later.

## D7. AI through OpenRouter, Inkling 2 Mini by default

- **Decision.** The AI matcher calls an OpenAI-compatible endpoint, OpenRouter by default, with `thinkingmachines/inkling-2-mini` as the default model.
- **Why.** Inkling 2 Mini is open-weight under Apache 2.0, cheap on OpenRouter, and small enough to run locally if a client won't send data out. OpenRouter lets us try any other model by changing one setting.
- **Guardrails.** The model chooses only from candidate tags, returns schema-checked JSON, and every proposal goes to a planner for review.
- **Revisit if.** A client requires a specific approved endpoint. Only the base URL and model setting change.

## D8. 2D first

- **Decision.** The demo is 2D: plot plan, P&ID sheets and graph panel.
- **Why.** The 3.1 features are about location, connectivity and scope, which 2D shows clearly. 3D adds build time without changing the argument for release one.
- **Revisit if.** The 4.2 demo needs a 4D view of logistics, which would read the same plot-plan layer.

## D9. Read only from IMPACT Web

- **Decision.** The twin never writes to IMPACT Web. Its service account has a read-only role, and a contract test checks that writes are refused.
- **Why.** This follows the write-back position from the workshop for release one. Changes are made in the system of record and flow to the twin.

## D10. Layered verification, with Quint for the workflow

- **Decision.** Check data with Pydantic and SHACL (through n10s), calculations with Hypothesis property tests, and the sync, review and freeze workflow with a Quint spec checked by Apalache or TLC. Bend 2 is an optional spike for proving the cost rules.
- **Why.** Each tool fits one kind of mistake. SHACL catches bad plant and scope data, property tests catch bad maths, and model checking catches workflow states nobody thought to test. Quint reads more like code than TLA+ and still compiles to TLA+. Bend 2 is promising but young, and it can't run inside the Python services yet.
- **Revisit if.** Bend 2 gains a Python target and a stable checker, or the client wants TLA+ itself, which Quint can produce.

## D11. Validation first, and cross-model PR review

- **Decision.** Every change starts with acceptance criteria and checks that fail before the code exists. Every PR is reviewed by a different AI model from its author before merge.
- **Why.** Hamid's rule for this repo. Writing the checks first stops the tests from being shaped to fit whatever the code does. A second model catches mistakes the author model is blind to.

## D12. One codebase, two modes

- **Decision.** Demo mode and planning mode share the same services. Planning mode adds exercises, per-exercise roles, an exercise clock and a facilitator console.
- **Why.** A team rehearsal uses the exact system the demo shows, so nothing in the demo is staged.
- **Revisit if.** Planning-mode needs, such as many teams at once, start to slow the demo down.
