# Verification and validation plan

Version 0.1, for review.

The data is synthetic, but it has to hold up in front of turnaround planners and engineers. Every piece is checked as it is written, not at the end. There are four layers, from cheapest to strongest, plus a person reviewing it.

| Layer | What it checks | Tool | When it runs |
|---|---|---|---|
| 1. Schemas | Every record has the right fields, types and formats | Pydantic models, DEXPI checks through pyDEXPI | On every write, in the generator and the APIs |
| 2. Engineering rules | The plant and work list make engineering sense | SHACL shapes run in Neo4j through neosemantics (n10s), plus Python rule checks for the Postgres side | After every load, and inside the load transaction for the twin |
| 3. Properties | The calculations obey their rules for any input, not just the seeded data | Hypothesis property-based tests in pytest | In CI on every push |
| 4. Formal specs | The workflow (sync, review, freeze, change log) can't reach a bad state | Quint (TLA), checked with Apalache or TLC | In CI, and the spec's traces drive tests against the real APIs |
| Human review | The scenario reads like a real hydrotreater turnaround | Hamid, plus any SME he brings in | At the end of phase 1 and before each demo |

## 1. Schemas

- Pydantic models for every work request, equipment record, plot-plan entry and API payload. A bad record fails at the point it is written ([D10](decisions.md), [D11](decisions.md)).
- DEXPI sheets are built with pyDEXPI and re-read after writing. A sheet that doesn't read back the same way fails the build ([D5](decisions.md), [D10](decisions.md)).

## 2. Engineering rules (SHACL)

SHACL runs on the twin's graph, so it can refuse a bad twin load but not an IMPACT Web save that already happened. The two sides split the work. IMPACT Web checks its own fields when they're saved. The twin checks everything that needs the plant model, such as work type against equipment class, and holds a failing item in the review queue with a clear message instead of matching it.

Neosemantics can validate a Neo4j graph against SHACL shapes, either for the whole graph or as a check inside a transaction that rolls back if a change breaks a rule ([Neo4j Labs, n10s validation](https://neo4j.com/labs/neosemantics/4.2/validation/)). The twin loader runs its writes this way. The [phase 0 spike](spikes/shacl-n10s.md) confirmed the trigger refuses bad writes on Neo4j 5.26, but only while the shapes are loaded and the trigger is running. If either is missing, writes go through unchecked. So before each sync the loader checks both. Syncs, resets and shape changes take one lock, and each sync is one transaction. About half the rules below can be n10s shapes. The rest need paths, lookups or arithmetic, so they run as Cypher checks in the same transaction or as Python checks on the rows before the write. The spike's section 6 sorts each rule.

Starting rule set, to be reviewed and extended in phase 1:

- Plant
  - Every equipment tag matches the Unit 200 tag pattern and exists in the CMMS master ([D10](decisions.md)).
  - Every pressure vessel, column, reactor and exchanger shell has at least one relief path to a PSV ([D5](decisions.md), [D10](decisions.md)).
  - Every PSV protects at least one item of equipment ([D5](decisions.md), [D10](decisions.md)).
  - Every shell-and-tube exchanger has shell-side and tube-side inlet and outlet nozzles ([D5](decisions.md), [D10](decisions.md)).
  - Every pump and compressor has suction and discharge block valves ([D5](decisions.md), [D10](decisions.md)).
  - Every isolation envelope is closed: every path leaving it ends at a block valve or blind point on its boundary ([D3](decisions.md), [D10](decisions.md)).
  - Every major item has a plot position inside its area, and equipment footprints don't overlap ([D6](decisions.md), [D10](decisions.md)).
- Scope
  - Every scope item has a driver, a source group, a RIPT score and an estimate split by craft ([D10](decisions.md)).
  - Craft hours add up to the item's total, and cost is consistent with hours at the scenario's labor rates ([D10](decisions.md)).
  - Work type fits equipment class. A bundle pull only goes on an exchanger. A tray inspection only goes on a column. A PSV recertification only goes on a PSV ([D10](decisions.md)).
  - Every frozen item ends in one of four outcomes: matched (exactly one accepted equipment match), unresolved, unit general, or incompatible ([D10](decisions.md), [D15](decisions.md)).
  - Every accepted AI match has a named reviewer ([D15](decisions.md), [D16](decisions.md)).

The checks on the matcher itself, deterministic and AI, are in [matching-showcase.md](matching-showcase.md) section 5.

## 3. Properties (Hypothesis)

The calculations get property tests that run on thousands of generated inputs:

- **Clusters.** A cluster's cost is never more than the sum of its items' standalone costs. Each shared cost is counted exactly once ([D10](decisions.md)).
- **Cut line.** When the budget is feasible, everything above the line fits it. Mandatory items are always above the line. If mandatory items alone exceed the budget, the run is marked infeasible with the shortfall, and nothing discretionary sits above the line. Moving an item from below to above never lowers the total above the line ([D10](decisions.md)).
- **Match rate.** It stays between 0 and 100. Accepting a proposal never lowers it ([D10](decisions.md), [D15](decisions.md)).
- **Baseline.** Scope growth equals the sum of the change events' hour deltas ([D10](decisions.md)).
- **Sync.** Running the same sync twice gives the same graph ([D3](decisions.md), [D10](decisions.md)).

## 4. Formal specs (Quint)

The workflow is where bugs would hurt credibility most: a change slipping past the log, a baseline that moves, or the twin writing to IMPACT Web outside its workflow. It is specified in Quint, which is built on TLA, the same logic as TLA+, and can be checked with the Apalache or TLC model checkers ([Quint FAQ](https://quint.sh/faq)).

`specs/worklist.qnt` models IMPACT Web, the twin, the sync, the review queue and freeze as one state machine. The model checker checks every reachable state, up to a bound, against these rules:

- **Workflow only.** A twin step leaves IMPACT Web as it was, or, with write-through on and the list frozen, raises exactly one pending change request from the twin, against the request's current version and hours, and changes nothing else. The twin never approves, edits a request, or touches the freeze or the frozen copy ([D9](decisions.md), [D10](decisions.md)). The raised request's target can't be negative, the same rule IMPACT Web's own raise applies. The model tracks only approvals on the feed. In the services, IMPACT Web's normal handler puts the pending row on the feed, the twin can't write the feed directly, and a pending row adds no change event or growth.
- **Read-only mode.** With an exercise's write-through switch off, no change request comes from the twin ([D9](decisions.md), [D10](decisions.md)). The model fixes the switch for a whole trace, so this covers exercises that start with it off. Turning it off part way through is left to the contract tests in design.md section 9.
- **Baseline fixed.** After freeze, the baseline never changes ([D10](decisions.md)).
- **Nothing missed.** Every approved change after freeze shows up as exactly one change event once a sync that starts after the approval finishes, however syncs overlap or repeat. A sync that finishes applies the whole window it read. The model doesn't claim that a sync will ever run ([D10](decisions.md)).
- **Freeze is exact.** Freeze copies exactly the requests whose current version the DRB accepted, at their hours at that moment, and the twin baseline always equals that copy, whichever order a freeze and an edit arrive in ([D10](decisions.md)).
- **Humans decide.** No AI proposal becomes accepted without a reviewer step. System acceptance is limited to exact and high-scoring rule matches, and the trace records it ([D10](decisions.md), [D15](decisions.md), [D16](decisions.md)).
- **Growth adds up.** In IMPACT Web, a request's live hours equal its live hours at the moment of freeze plus every approved change delta. That holds for requests left out of the frozen copy too. In the twin, scope growth equals the sum of the deltas of the change events it has applied. The two agree once a sync catches up. Pending and rejected changes add nothing ([D10](decisions.md)).
- **Gate.** The twin can't mark the baseline ready for use if the match rate on frozen items is below the gate. The freeze itself doesn't depend on the gate ([D10](decisions.md)).

The [phase 0 spike](spikes/quint-worklist.md) wrote the first version of this spec. Apalache found no broken rule in any trace up to 10 steps, TLC walked every state of a smaller instance, and both caught all twelve seeded bugs. One seeded bug first slipped through because its rule read the same setting the bug changed, so rules now state what's allowed in their own words. Review by a second model then found that Nothing missed and Freeze is exact were too weak to catch a sync that drops its window or a freeze that copies unaccepted requests. Both rules were tightened, with three more seeded bugs to prove it. The write-through change then replaced Read only with Workflow only and added Read-only mode, with six more seeded bugs, one of them added after review, and the full run passed again with all eighteen caught.

From phase 4 the spec also covers exercises, the clock, roles, concurrent editors and the change process from [interactive-planning.md](interactive-planning.md).

The same spec also produces example traces, such as "add after freeze, sync, review". A small test harness replays them against the real FastAPI services, which ties the spec to the code rather than letting it drift into a separate document. Sync and matching traces are replayed from phase 4, baseline and change traces from phase 6, and planning-mode traces in phase 8, each once the APIs they need exist.

## Where Bend fits

Bend 2 is now a language with dependent types, where you write rules in a laws file and the compiler demands a proof that the code keeps them ([Bend on GitHub](https://github.com/bendlang/bend)). That fits the idea of proving the cost rules. The project's README also says it is young, mostly AI-written and not fully audited, and Python is only a planned target. So it stays out of the main build path. One optional spike: write the cluster-cost and cut-line rules as Bend laws and prove them, then check that the Python results match the Bend version on the same inputs. If it works cleanly it makes a good slide for an architect audience. If not, the Hypothesis properties already cover the same rules.

The [phase 0 spike](spikes/bend-cost.md) proved the cluster rule for a single shared setup: never more than standalone, setup counted once, and the saving equal to the setup times the extra items. The Lean kernel accepted the proof and rejected a tampered one, Bend's JavaScript matched Python on 5,000 cases, and all four seeded bugs failed at a proof. "Never more" alone missed three of the four bugs, so the Hypothesis property for clusters checks both halves.

## What formal methods don't cover

The proofs and model checks show the software follows its rules. They don't show the rules match a real refinery. That part comes from the engineering rule set, the scenario spec and human review, which is why the human review gate stays in the plan.
