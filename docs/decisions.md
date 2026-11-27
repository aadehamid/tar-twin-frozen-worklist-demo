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
- **Status.** The template at `f8c6c14` builds and passes its lint, migrations and backend tests with no Docker, using local Postgres 18 and the Mailpit binary. Its Playwright suite passed in six of eight runs. Both failures were reset password tests. The template's signup test helper has a race that fits them, and we patch it when we fork the template. See the [template spike](spikes/template-no-docker.md).

## D3. Neo4j is the twin's master store

- **Decision.** The twin graph lives in Neo4j Community.
- **Why.** The twin's work is traversal: job to equipment to piping to valves to envelope to other jobs. Cypher states that directly. Neo4j Browser also lets architects check the graph themselves.
- **Revisit if.** The client standard for the graph store is different. The graph model doesn't depend on Neo4j-only features.

## D4. Relate in the browser for the graph panel

- **Decision.** The twin UI loads a copy of the graph into Relate, Neo4j's embedded Cypher engine, compiled to WebAssembly and running in a browser worker.
- **Why.** The audience sees real Cypher run against the real graph when they click a job, with no round trip. It shows the connection rather than a picture of it.
- **Known limits.** In the browser, Relate can't open a saved database file or URL, and there are no multi-statement transactions, so we seed it from a Cypher script. Neo4j stays the master.
- **Revisit if.** The phase 0 spike shows seeding or query speed is not good enough at about 5,000 nodes. The fallback is the same panel calling the twin API.
- **Status.** The phase 0 spike passed on 2026-11-27 ([spike](spikes/relate-wasm.md)). At 5,040 nodes, headless Chromium seeded the store in about 1.4 seconds and ran the chain and the walk in a median of 26 ms, so the fallback isn't needed. Relate's read-only mode can't hold seeded data, so the worker answers only named queries instead.

## D5. DEXPI through pyDEXPI

- **Decision.** The plant model is authored as DEXPI P&IDs with [pyDEXPI](https://github.com/process-intelligence-research/pyDEXPI) and loaded into Neo4j from its graph export.
- **Why.** DEXPI is the open standard for P&ID data exchange, and the client's P&IDs could reach the twin in this form. pyDEXPI reads and writes it, renders SVG and exports to NetworkX.
- **Revisit if.** The SVG render of generated sheets fails in the phase 0 spike. We then render our own SVG from the DEXPI topology and keep DEXPI as the data source.
- **Status.** The phase 0 spike passed on 2026-11-26. pyDEXPI built, validated and rendered sheet 200-PID-002 ([spike](spikes/dexpi-sheet.md)), so the fallback isn't needed.

## D6. A separate plot-plan layer

- **Decision.** Equipment positions and elevations live in a separate file keyed by tag, not in DEXPI.
- **Why.** DEXPI describes connectivity, not plot location. Scaffold and access clusters need location. Keeping it separate lets a 3D model or GIS layer replace it later.

## D7. AI through OpenRouter, Inkling 2 Mini by default

Superseded by D16 on 26 November 2026. Kept for the record.

- **Decision.** The AI matcher calls an OpenAI-compatible endpoint, OpenRouter by default, with `thinkingmachines/inkling-2-mini` as the default model.
- **Why.** Inkling 2 Mini is open-weight under Apache 2.0, cheap on OpenRouter, and small enough to run locally if a client won't send data out. OpenRouter lets us try any other model by changing one setting.
- **Guardrails.** The model chooses only from candidate tags, returns schema-checked JSON, and every proposal goes to a planner for review.
- **Revisit if.** A client requires a specific approved endpoint. Only the base URL and model setting change.

## D8. 2D first

- **Decision.** The demo is 2D: plot plan, P&ID sheets and graph panel.
- **Why.** The 3.1 features are about location, connectivity and scope, which 2D shows clearly. 3D adds build time without changing the argument for release one.
- **Revisit if.** The 4.2 demo needs a 4D view of logistics, which would read the same plot-plan layer.

## D9. Write through IMPACT Web's workflow (demo only)

- **Decision.** The twin reads IMPACT Web through its service account, which has a read-only role. The one write it makes is raising a change request after freeze, for the signed-in planner, through a delegate token that reaches one endpoint and runs IMPACT Web's normal change request handler (design section 5.8). IMPACT Web, not the twin, checks the user's role, the freeze and the switch, and marks the request as raised from the twin. The request is pending until the DRB decides in IMPACT Web. The twin can't approve, edit a request, or touch the freeze or the frozen copy. Each exercise has a switch that turns write-through off, and then the twin is read only.
- **Why.** The workshop said two things that pull against each other: IMPACT Web is under a code freeze and can't be changed now, and the room wanted changes made in the system of record with the twin feeling like one tool. Raising the request through IMPACT Web's existing workflow does both. The change still lands in the system of record and the DRB still decides. In the mock, IMPACT Web needs the delegated endpoint. For a real scope tool the story only works if its existing API already lets an integration raise a request for a named user, which is a question to confirm rather than an assumption to build on. That closes the loop in the demo: the planner sees the issue in the twin, raises it there, the DRB approves in IMPACT Web, and growth updates after the next sync.
- **Scope.** This is a demo choice, made on 2026-11-27. The proposal deck is unchanged. Where real write-back stops is still an open workshop question, which leaned towards starting conservative, and the read-only switch shows that option in the same demo.
- **Checks.** The Quint rules `WorkflowOnly` and `ReadOnlyMode`, and the write-through contract tests in design section 9.
- **Earlier version.** Until 2026-11-27 this decision was "read only from IMPACT Web": the twin never wrote to it.

## D10. Layered verification, with Quint for the workflow

- **Decision.** Check data with Pydantic and SHACL (through n10s), calculations with Hypothesis property tests, and the sync, review and freeze workflow with a Quint spec checked by Apalache or TLC. Bend 2 is an optional spike for proving the cost rules.
- **Why.** Each tool fits one kind of mistake. SHACL catches bad plant and scope data, property tests catch bad maths, and model checking catches workflow states nobody thought to test. Quint reads more like code than TLA+ and still compiles to TLA+. Bend 2 is promising but young, and it can't run inside the Python services yet.
- **Status.** The SHACL half passed its phase 0 spike on 2026-11-27 ([spike](spikes/shacl-n10s.md)). n10s found the same violations as pySHACL on 18 mutants and at 5,040 nodes, and its trigger refused every bad write. Two things change. The guard lets writes through if the shapes node is missing or the trigger is paused, so the loader checks both before each sync, under a lock that resets and shape changes also take. The trigger checks each transaction on its own, so each sync is one transaction. Rules that walk paths or do arithmetic run as Cypher or Python checks in the loader. The Quint half passed its spike the same day ([spike](spikes/quint-worklist.md)). Apalache to 10 steps, TLC on a smaller instance and 20,000 simulated traces found no broken rule, and both checkers caught all twelve seeded bugs, three of them added after review found two rules too weak. After the write-through change (D9) they caught all eighteen. TLC can't cover the full instance on this hardware, so CI runs Apalache at 6 steps and a nightly job runs the rest. The optional Bend 2 spike also passed ([spike](spikes/bend-cost.md)). It proved the cluster cost rule for one shared setup, and the Lean kernel accepted the proof. Bend stays out of the build path until it has a Python target.
- **Revisit if.** Bend 2 gains a Python target and a stable checker, or the client wants TLA+ itself, which Quint can produce.

## D11. Validation first, and cross-model PR review

- **Decision.** Every change starts with acceptance criteria and checks that fail before the code exists. Every PR is reviewed by a different AI model from its author before merge.
- **Why.** Hamid's rule for this repo. Writing the checks first stops the tests from being shaped to fit whatever the code does. A second model tends to catch mistakes the author model misses.

## D12. One codebase, two modes

- **Decision.** Demo mode and planning mode share the same services. Planning mode adds exercises, per-exercise roles, an exercise clock and a facilitator console.
- **Why.** A team rehearsal uses the exact system the demo shows, so the demo shows the same system a team would use.
- **Revisit if.** Planning-mode needs, such as many teams at once, start to slow the demo down.

## D13. Host team exercises on one exe.dev VM

- **Decision.** One exe.dev VM on Hamid's Personal plan (2 vCPU, 4 GB) runs the whole system with Docker Compose. Sign-in comes through exe.dev, and roles come from our own membership table.
- **Why.** It gives private HTTPS, sign-in by email and persistent disks for $15 a month, with no server to run. The data is synthetic, so a host outside the client's network is fine.
- **Revisit if.** The 15-user soak test goes over the memory budget (move to 4 vCPU and 8 GB), the team needs SSO or sharing controls (Work plan), or real client data comes in (a client-approved host).

## D14. Trust identity from loopback only

- **Decision.** The edge runs in host network mode, listens on 127.0.0.1:8000 only, routes both apps by path, and passes the exe.dev identity headers only when the peer is 127.0.0.1. The apps stay on the Compose bridge network with loopback-only Docker mappings outside the proxy's range.
- **Why.** The phase 0 spike showed the exe.dev proxy connects over loopback and replaces client-sent `X-ExeDev-*` headers, and that containers can't reach the host's loopback ([spike results](spikes/exe-hosting.md)). A peer-address rule on loopback is simple to test. One port avoids depending on how exe.dev handles alternate ports for Web shares, after its over-sharing incident ([exe.dev security note](https://exe.dev/security/over-sharing)).
- **Revisit if.** exe.dev changes how the proxy connects, the site goes public, or anything other than our stack and exe.dev's agent runs on the host.

## D15. Code first, AI only to tell names apart

- **Decision.** Deterministic code normalizes, parses tags, applies aliases, scores with rapidfuzz and gathers DEXPI facts. The AI only chooses among code's candidates when names are ambiguous, code checks its answer, and only code or a planner can accept a match. The demo shows the split and compares it with code alone and AI on everything.
- **Why.** Code is repeatable and testable, and it handles most of the field. Telling E-201A, B and C apart from "middle shell" needs plant context, which is where a model helps. Checking the model with code keeps it from inventing tags or evidence.
- **Revisit if.** The live evaluation shows the AI adds little on the sibling and process-context classes, or a client won't allow a model in the loop. Offline mode already runs without it.

## D16. Perplexity Decider instead of a reasoning model

- **Decision.** The AI matcher calls Perplexity Decider v1.3 through OpenRouter's Decisions API, pinned as `perplexity/pplx-decider-v1.3:free` until the `~perplexity/pplx-decider-latest` alias serves v1.3. Inkling 2 Mini no longer picks tags and only writes reasons. This replaces D7.
- **Why.** The matcher only asks the AI to choose among code's candidates, which is the question a decision model answers. Decider returns a probability for each candidate, can't name an option it wasn't given, and has no free text to parse. In the phase 0 spike it got all 18 calls right, including the planted instruction, gave the same answer every run, and took about 0.3 seconds median against 2.9 seconds for Inkling ([spike](spikes/decider-matcher.md)).
- **Reasons.** Decider writes no reason. Inkling 2 Mini, through OpenRouter chat completions, writes the one-line reason a planner reads. It runs only after the checker has passed a Decider pick, sees only that pick and its facts, and never changes the outcome. If Inkling is slow, fails or isn't configured, the queue shows the candidate probabilities and the evidence fact without a reason. The phase 0 spike already showed Inkling returns schema-valid JSON through OpenRouter, at 2.9 seconds median, so reasons are written in the background and appear when ready. OpenRouter doesn't offer Decider's `locate` feature yet, so evidence is a second choice question over fact IDs.
- **Hosting.** exe.dev stays the host (D13). FastAPI Cloud was considered and set aside, because it has no Neo4j and no sign-in gate for invited participants.
- **Revisit if.** The free v1.3 endpoint gets rate limited or withdrawn (fall back to the paid v1.2 endpoint, then rerun the evaluation), the 200-request evaluation shows weak results on the sibling or process-context classes, or a client wants the model hosted in its own network.

## D17. Shared Relate memory for every coding agent

- **Decision.** Every coding agent on this repository shares one Relate graph as long-term memory. `scripts/memory.sh` is the only way to save to it. The store is the git-ignored `.relate-memory/` folder at the root of the main checkout, so every worktree shares it. The graph follows Relate's `relate-agent-memory` model: entities, episodes, and facts with a slot, two time ranges and a link to the episode they came from. A correction closes the old fact and keeps it in the history. Recall uses full-text search over current facts. The skill at `.agents/skills/project-memory/SKILL.md` says when to read and how to save, `AGENTS.md` points to it, a Claude Code `SessionStart` hook prints the newest facts, and `.gemini/settings.json` makes Gemini CLI read `AGENTS.md`.
- **Why.** Hamid asked for it on 2026-11-27: "can you set it up for my project at /Users/hamidadesokan/Dropbox/1_PROJECTS/tar-twin-frozen-worklist-demo". The setup copies one he approved for another of his repositories on the same day. Each agent otherwise keeps notes in its own folder, where the others cannot read them. The store stays out of `.git` because Codex's workspace sandbox blocks every write there.
- **Dropbox.** Dropbox syncs the store to Hamid's other machines, but Relate's write lock holds only on one machine. Agents save from one machine at a time. `scripts/memory.sh` refuses to save, and `check` fails, when Dropbox leaves conflicted copies in the store.
- **Revisit if.** All agents share one embedding model, which would make vector recall worth adding, or saves from two machines at once become common.
