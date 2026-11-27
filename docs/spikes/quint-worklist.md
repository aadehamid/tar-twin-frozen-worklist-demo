# Spike: a first Quint model of freeze, sync and review

Status: passed on 2026-11-27. All seven checks pass. Decision D10 stands as written, with two limits on how far the checkers go, set out in section 6.

This spike answers the phase 0 question in [design.md](../design.md) section 10, and the plan in [verification.md](../verification.md) section 4. Can we write the sync, review and freeze workflow as a Quint spec, and have a model checker show that it never reaches a bad state? And does the checker catch it when one step is wrong?

## 1. What the model covers

`specs/worklist.qnt` is one state machine with two sides.

IMPACT Web, the system of record, has the live hours and version of each request, the DRB decision, the freeze flag, the frozen copy, the change requests raised after freeze, and the change feed the twin reads. Its steps follow [interactive-planning.md](../interactive-planning.md) sections 3.4 and 3.5:

- Before freeze a planner edits a request. Every committed edit bumps its version and clears its DRB decision.
- The DRB accepts a request.
- Freeze copies only the requests whose current version is DRB-accepted. One step does it, which stands in for the per-exercise lock: no edit can land between "look at the requests" and "write the copy". It doesn't look at the twin's gate.
- After freeze, a change request records the request's current version as its base. Approval commits only if the request is still at that version. If another change landed first, the change stays pending and can't be approved. Approval appends the change to the feed. Rejection does nothing else.

The twin's side has its baseline, its cursor into the feed, the change events, scope growth, the syncs in flight, the match state of each item, and the "ready for use" flag. Its steps:

- A sync starts. It reads the feed length and the frozen copy at that moment. Several syncs can be in flight at once.
- A sync finishes. It takes the baseline from the copy it read, if it doesn't have one yet. It turns each feed entry between its start point and the length it read into a change event keyed by change ID, so two syncs that read the same entry make one event. The cursor only moves forward.
- The matcher proposes a match for a frozen item, by one of four methods: exact, high-scoring rule, low-scoring rule, or AI.
- Code accepts on its own only exact and high-scoring rule matches. Everything else waits for a reviewer, who accepts or rejects.
- The twin marks the baseline ready when the match rate on frozen items passes the gate.

A few ghost variables record who took the last step and what IMPACT Web and the baseline looked like before it. They exist only so that step rules such as "a twin step never changes IMPACT Web" can be written as plain invariants.

## 2. The rules

These are the seven rules from verification.md section 4. `AllRules` is all of them together.

| Rule | What the model checks |
|---|---|
| ReadOnly | After any twin step, IMPACT Web's whole state equals what it was before the step |
| BaselineFixed | Once the twin has a baseline, no step changes it or takes it away |
| FreezeExact | If the twin has a baseline, IMPACT Web is frozen and the baseline equals its frozen copy |
| NothingMissed | The feed holds each approved change exactly once. The twin has exactly one event for each feed entry up to its cursor and none for anything else. So once a sync catches up, every approved change is one event |
| HumansDecide | Every accepted match was accepted by a reviewer, or by code on an exact or high-scoring rule match |
| GrowthAddsUp | Twin growth is the sum of the deltas of the changes it has events for, all of them approved. In IMPACT Web each request's live hours equal its hours at freeze plus its approved deltas, so pending and rejected changes add nothing |
| Gate | The baseline is marked ready only if the gate passes |

A rule that holds because the step that would break it never runs proves nothing. So the spec also has seven witnesses, states we expect to reach: two syncs in flight at once, a late add synced as an event for a request that wasn't in the frozen copy, negative growth, a stale change blocked by its base version, an AI match accepted by a reviewer, a ready baseline, and a frozen but not ready baseline with growth.

## 3. Bounds

Two requests, two change requests, hours from {0, 4, 8}, change deltas of -4 or +4, at most three syncs, at most three edits or approvals per request, and a gate of 50%.

The model has a second, smaller instance: one request, hours from {0, 4}, and at most two syncs. TLC can walk all of its states. The run script builds it from the same file by swapping the bound lines, so there's one spec.

## 4. The checks

`spikes/quint-worklist/run_spike.py` runs everything from a clean folder. It installs Quint 0.34.0 from npm and checks the package's integrity hash. It downloads Apalache 0.62.4 and checks its SHA-256 against the digest GitHub publishes for the release. TLC comes with the Apalache download. Nothing uses Docker. The script writes `results.json`.

| Check | Passes when |
|---|---|
| Q1 | Quint and Apalache are the pinned versions with matching hashes, Java 21 is present, and Docker isn't needed |
| Q2 | The full and small instances both typecheck |
| Q3 | Apalache finds no trace of up to 10 steps in the full instance that breaks any rule |
| Q4 | TLC explores every reachable state of the small instance and no rule breaks |
| Q5 | The simulator runs 20,000 random traces of up to 30 steps on the full instance and no rule breaks |
| Q6 | TLC reaches every witness in the small instance, and the simulator reaches every witness in the full instance. The late-add trace with one frozen request is saved |
| Q7 | Each of nine seeded bugs typechecks, and both TLC on the small instance and Apalache on the full instance report that its rule breaks |

The nine seeded bugs are in `mutants.py`. Each one changes a single snippet of the spec, and `apply` refuses a snippet that appears zero times or more than once. At least one bug targets each rule:

| Bug | Rule | What goes wrong |
|---|---|---|
| Q-M1 | ReadOnly | A twin review step changes the IMPACT Web request it matched |
| Q-M2 | BaselineFixed | A sync applies approved change deltas to the baseline |
| Q-M3 | FreezeExact | A sync builds the baseline from the live requests, not the frozen copy |
| Q-M4 | NothingMissed | A sync moves its cursor to the feed's current end, not the end it read |
| Q-M5 | NothingMissed | Events are counted, not keyed by change ID, so overlapping syncs count one change twice |
| Q-M6 | HumansDecide | Code accepts an AI proposal on its own |
| Q-M7 | GrowthAddsUp | A sync counts pending change requests toward growth |
| Q-M8 | Gate | The baseline is marked ready without the gate |
| Q-M9 | GrowthAddsUp | Approval skips the base-version check, so a stale change overwrites a newer one |

`test_mutants.py` checks the bug list itself without running a checker: every bug applies once, every rule has a bug, IDs are unique, and no bug edits a constant that its own rule reads.

Run it with:

```
python3 spikes/quint-worklist/run_spike.py --work /tmp/quintrun
uv run --no-project --with pytest python -m pytest -q spikes/quint-worklist/test_mutants.py
```

## 5. Results

From the run that produced `results.json`, on a 2-core, 8 GB sandbox. The whole script took 12 minutes. Another spike shared the CPU for part of the run, so the times are a little high. An earlier run with the CPU to itself took 341 s for Q3.

| Check | Result |
|---|---|
| Q1 | Pass. Quint 0.34.0, Apalache 0.62.4, OpenJDK 21, no Docker |
| Q2 | Pass |
| Q3 | Pass. No rule breaks in any trace of up to 10 steps, in 399 s |
| Q4 | Pass. 58,717 distinct states, depth 17, 15 s |
| Q5 | Pass. 20,000 traces in 14 s |
| Q6 | Pass. All seven witnesses reached by both TLC and the simulator. TLC's shortest traces run from 3 to 9 states |
| Q7 | Pass. All nine bugs caught by both TLC and Apalache. Apalache needed 11 to 23 s per bug, and TLC's counterexamples run from 5 to 8 states |

## 6. Findings

1. **The first run caught a weak rule, not a bug in the workflow.** Q-M6 adds `ai` to the methods code may accept on its own. Neither checker reported it. HumansDecide had been written in terms of the same constant, `SYSTEM_METHODS`, so the bug changed the rule along with the code and there was nothing left to find. The rule now spells out the two allowed methods itself, and a unit test fails if any bug edits a constant its own rule reads. The lesson carries into phase 4: rules state what's allowed in their own words and don't reuse the settings the code runs on.
2. **Apalache can't take `range` with bounds that change from state to state.** The first draft kept the feed as a list and read slices of it. Apalache rejected that, so the feed is now a map from change ID to feed position, plus a length. That's closer to the real thing anyway. Design.md section 4.1 has the feed as a table with a sequence number per committed change.
3. **Versions need a cap.** With no limit on edits, versions grow forever and TLC's state space is infinite. The model allows three edits or approvals per request. That's enough to reach every witness, including a stale change.
4. **TLC can't finish the full instance here.** An earlier run on the full instance passed 2.5 million distinct states in about a minute with the queue still growing, and Quint starts TLC with an 8 GB heap on an 8 GB machine. So TLC checks the small instance completely, and the full instance gets Apalache to 10 steps plus the simulator. Apalache at 10 steps takes six to seven minutes, which is fine for a nightly job but slow for every commit. CI can run Apalache at 6 steps (under 30 s in a trial) and keep 10 steps for the nightly run.
5. **The bounds are a choice, not a proof for every size.** Two requests and two changes are enough to show overlapping syncs, a change against a request outside the frozen copy, and a change that loses the race on its base version. They don't show anything about 300 requests. That is the normal trade with model checking, and it's why the same rules come back as property tests on real data in phase 4.

What the model leaves out, on purpose for now: exercises, roles, the clock, deletes and adds as separate change types, cost as well as hours, the material-change flag, and reset. Verification.md section 4 already puts those in from phase 4, as interactive-planning.md lands.

## 7. A trace for phase 4

`spikes/quint-worklist/trace-late-add.itf.json` is a simulator trace in the ITF format. It ends with one request frozen and a late add on the other: a change request against a request that wasn't in the frozen copy, approved, and turned into one change event by the next sync. The spec asks for it with `ObsLateAddWithFrozenItem`. The first version of this trace asked only for the late add, and the simulator returned one where nothing was DRB-accepted, so the frozen copy was empty. That still meets the rule but makes a poor test. Phase 4's harness replays traces like this against the real FastAPI services. Each IMPACT Web step becomes an API call, each twin step a sync or review call, and after each step the harness compares the API state with the trace's state.

## 8. Effect on the plan

- D10 stands. Quint reads well, both checkers work without Docker, and the seeded bugs show the checks have teeth.
- CI runs typecheck, Apalache at 6 steps and the mutant unit tests. A nightly job runs the full script.
- Phase 4 starts from this spec and adds the replay harness.
