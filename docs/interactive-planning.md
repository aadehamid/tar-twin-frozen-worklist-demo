# Interactive planning mode

Version 0.2, for review. Revised after the first cross-model review on PR #1.

The system runs in two modes on the same code:

- **Demo mode.** The 10-minute scripted walkthrough in the scenario spec. Seeded data, the same result every time.
- **Planning mode.** A team rehearses getting Unit 200 ready for a turnaround. People log in with their own roles, raise and challenge synthetic work requests in IMPACT Web, watch the twin respond, and take the list through DRB and freeze. A facilitator runs the clock and drops in events.

Planning mode is a rehearsal and training tool on a synthetic unit. It is not a planning system for a real turnaround.

## 1. Premise

Unit 200's catalyst is near end of run. The site has set a 28-day turnaround, TAR-200-2028, with feed out in 18 months. The team owns the work list from the first candidate requests to the months after freeze. Their goal is a frozen list that fits the budget, has every item tied to equipment, bundles shared setups, and grows as little as possible after freeze, without cutting work that has to be done.

## 2. Roles and authority

Roles are held per exercise. The template only has a superuser flag, so the IMPACT Web service adds `exercise_membership` (user, exercise, role) and checks it on every request. The twin reads the same membership through the IMPACT Web API.

| Role | Main job |
|---|---|
| Facilitator | Runs the exercise: setup, membership, clock, injects, reset, debrief. Doesn't make scope decisions |
| TA manager | Owns the list. Chairs the challenge, chairs the DRB and records its final decision, freezes the list, approves or rejects changes after freeze |
| Planner | Screens requests at fit to frame, raises general and prep work, reviews tag matches in the twin, prepares cut-line options |
| Source group lead (fixed equipment, rotating, inspection, operations, projects, instrumentation) | Raises and edits requests for their group, defends them at the challenge and DRB, raises late changes |
| DRB member | Records a recommendation on each item at the DRB. The TA manager records the board's final decision |
| Viewer | Looks at both systems, with no edits |

### What each role can do in each phase

R = can do, O = own group's items only, V = view only, blank = not allowed.

| Action | Phase allowed | Facilitator | TA manager | Planner | Source group | DRB member | Viewer |
|---|---|---|---|---|---|---|---|
| Raise a request | Candidate list | | R | R | O | | |
| Edit a request | Candidate list to DRB | | R | R | O | | |
| Fit-to-frame decision | Fit to frame | | R | R | | | |
| Challenge decision (keep, merge duplicate, remove, bundle) | Challenge | | R | | | | |
| Comment and defend | Challenge, DRB | | R | R | O | R | |
| DRB recommendation | DRB | | | | | R | |
| DRB final decision | DRB | | R | | | | |
| Freeze the list | Freeze step | | R | | | | |
| Raise a change after freeze | After freeze | | R | R | O | | |
| Approve or reject a change after freeze | After freeze | | R | | | | |
| Review tag matches (twin) | Any | | R | R | | | |
| Save a cut-line option (twin) | Candidate list to DRB | | R | R | | | |
| View twin | Any | R | R | R | R | R | R |
| Move the clock, inject, reset, manage members | Any | R | | | | | |

## 3. How an exercise runs

### 3.1 Setup

The facilitator creates an exercise from one of three starting points. Each starting point is a versioned fixture in `data/scenario/fixtures/`:

- **Seeded.** All 200 candidate requests, with every planted problem from the scenario spec.
- **Partial.** 100 of them, plus briefing packs per source group listing the rest of their area's needs.
- **Blank.** No requests, just the briefing packs.

Every row and node carries an `exercise_id`. Request IDs are unique within an exercise, so two exercises can both hold `WR-200-0147` without clashing.

### 3.2 Membership

The facilitator adds and removes people and sets their roles. Removing someone ends their access on the next request. Their past actions stay in the log under their name.

### 3.3 The clock

The clock moves forward only, in steps: candidate list, fit to frame, challenge, DRB, freeze, and four post-freeze checkpoints (T-9, T-6, T-3, T-1). The facilitator can skip ahead, which is logged. There's no rewind. Reset (3.7) is the way to go back.

The clock controls which actions are open (section 2). Reaching the freeze step makes the freeze action available. It doesn't freeze anything by itself. Only the TA manager freezes.

### 3.4 Freeze

1. The TA manager presses Freeze. IMPACT Web takes a lock on the exercise's list, writes a `freeze` record with a new list version, and copies every open request at its current version into `freeze_item` rows. That copy is the frozen list and never changes.
2. Any edit that committed before the lock is in the frozen list. Any edit that arrives after it gets refused with a message saying the list is frozen and pointing to the change process.
3. The twin builds its baseline from the frozen copy (`GET /freezes/{id}/items`), not from the live rows. Its baseline therefore always matches what IMPACT Web froze, even if edits arrive between two syncs.
4. The twin's readiness check is separate from the freeze. The twin marks the baseline "ready for 3.1 use" only when the match rate on frozen items passes the gate. If it doesn't, the twin shows the gap and the items to fix. The freeze still stands, as it would at a real site.

### 3.5 Changes after freeze

After freeze, no request is added or deleted directly. A change goes through a change request in IMPACT Web:

1. A source group lead, planner or TA manager raises it: add, delete, or material change (hours or cost up more than 10%, or a change of work type). It records whether it is mandatory (safety, environmental, regulatory, integrity finding) or discretionary, the risk if it isn't done, hours and cost, and the evidence.
2. It sits as pending. Pending changes don't count toward scope growth. The twin shows them in their own layer.
3. The TA manager approves or rejects with a reason. Only approved changes become change events in the twin and count toward growth. Rejected ones stay in the log as rejected.

### 3.6 Injects

The facilitator drops events in from a library, or writes a custom one. Each inject has the phases it's allowed in, the change it makes, and an ID so it can't be applied twice. Every inject is logged.

An inject creates a starting fact or a pending request. It never makes the decision. Library examples:

- "UT shows thinning on line 200-P-0412 near E-201C." Creates a pending mandatory change request from the inspection group. The TA manager still decides.
- A 10% budget cut before DRB.
- A source group resubmitting a duplicate under a different description.
- A request naming a retired tag.
- Operations asking to defer the stripper tray work.
- Two co-located jobs that can't share a setup, because one needs hot work and the other has the line open to hydrocarbon. The twin's cluster suggestion has to be overruled.

Custom injects are typed by the facilitator. Their text is checked by the synthetic-data filter (section 4) before anything reaches the matcher or an outside model.

The seeded problems from the scenario spec are part of the starting fixture, not injects.

### 3.7 Reset

Reset puts one exercise back to its starting fixture in both stores. It cancels that exercise's in-flight syncs and match jobs first. Other exercises and demo mode are not touched.

### 3.8 Debrief

When the facilitator closes the exercise, the system builds a debrief:

- **Match rate over time.** Matched active items divided by active items at each clock step. Active means not rejected or deleted.
- **Shared costs.** Clusters found, against an answer key built from the fixture's planted clusters. Missed ones are listed.
- **Cut line.** The TA manager's saved cut-line options set against the actual DRB decisions.
- **Growth after freeze.** Approved changes in man-hours, split mandatory and discretionary, with pending and rejected counts shown separately.
- **Decision timeline.** Every decision in order, with who made it and when.
- **Talking points.** Prompts for the facilitator, for example "Which duplicates got past the challenge, and why?" and "Which late adds could have been found before freeze?"

### 3.9 Facilitator agenda (about 3 hours)

| Time | Step | Contested point to drive |
|---|---|---|
| 0:00 | Briefing and roles | |
| 0:15 | Candidate list | Source groups raise requests. Equipment text comes in messy |
| 0:45 | Fit to frame | The planner screens out work that doesn't fit the event |
| 1:00 | Challenge | Duplicates, bundling, and the hot work clash inject |
| 1:30 | DRB | Budget cut inject. Mandatory against discretionary items at the line |
| 2:00 | Freeze | Match-readiness gap shown by the twin |
| 2:15 | After freeze | UT finding and two discretionary late adds |
| 2:40 | Debrief | |

## 4. Rules that still hold

- **The twin never writes to IMPACT Web, in either mode.** Scope decisions are made in IMPACT Web. Tag match review is a twin decision about equipment identity, and it stays in the twin.
- **Cut-line options are twin-local.** A saved option is a `CutLineRun` against a named scope version: a budget, the ranking rule and the above and below sets. It doesn't change any request. It isn't the set-level what-if (31-f3), which changes estimates and stays out of release one.
- **Checks on both sides.** IMPACT Web checks its own fields when they're saved (required fields, craft hours add up, valid driver and source group). It can't check work type against equipment class, because its equipment field is free text. The twin does that after sync. An incompatible item, like a bundle pull on a pump, is held in the review queue as a finding with a clear message. It is not silently matched.
- **Every item ends in one of four match outcomes:** matched, unresolved, unit general, or incompatible.
- **Synthetic data only.** All typed text (requests, comments, custom injects) passes a filter for real company names, real tag patterns and personal details before it is stored or sent to the matcher. A hit blocks the save with a message.
- **Value figures** stay labeled as the brief's unvalidated defaults wherever they appear.

## 5. Validation for this mode (decided before any code)

Following [CONTRIBUTING.md](../CONTRIBUTING.md), these checks are written before planning mode is built.

| Acceptance criterion | Check |
|---|---|
| Each role can do exactly the actions in section 2, in the phases listed | Permission tests generated from the table: every role, action and phase, including the refusals |
| Exercises are isolated in both services | API tests with two exercises seeded with the same request IDs, covering requests, sync, matches, clusters, cut-line options, mapping trace links, graph export, debrief and reset. Quint invariant: no step reads or changes another exercise's state |
| Membership changes take effect at once | Tests for add, role change and removal. The facilitator can see all exercises and can't make scope decisions |
| No lost edits | Version field on each request. A stale write gets a 409. Quint model with two concurrent editors |
| Freeze races have one defined result | API and database tests for both orders: edit commits then freeze, and freeze then edit. Also freeze plus an edit between two twin polls. The twin baseline equals the frozen copy every time |
| Sync is exactly once | Replayed and overlapping syncs give the same graph. Each approved change makes exactly one change event, keyed on request ID and version |
| The clock only moves forward and gates actions | Quint invariant over clock steps. API test for each gate |
| The freeze, the clock and twin readiness are separate | Tests that reaching the freeze step doesn't freeze. Freezing below the match gate succeeds, and the twin then shows "not ready" |
| Only approved changes count as growth | Quint invariant: growth equals the sum over approved changes. Tests for pending and rejected changes |
| An infeasible budget is reported, not hidden | Fixture where mandatory scope alone exceeds the target. The cut line shows "infeasible" and the shortfall |
| Injects are authorized, phase-limited, logged and applied once | Tests per library inject, a replay test, and a refusal outside its phases |
| Reset restores one exercise only | Snapshot comparison of both stores after reset, with a second exercise and demo mode running |
| Cut-line options never touch IMPACT Web | Save, reopen and version tests. A contract test that IMPACT Web state is unchanged after any twin action |
| Debrief numbers are right | A hand-calculated fixture with known match rates, clusters, DRB cuts and growth. A Hypothesis property that debrief totals equal sums over the event history |
| Typed text stays synthetic | Filter tests with real-looking names and tags. Blocked text never reaches the matcher or OpenRouter |
| Unvalidated labels always show | Playwright checks on every screen that shows a value figure |
| Demo mode still works | The demo-mode Playwright suite runs in CI on every planning-mode PR |

## 6. Hosting

On one laptop the whole team can't reach it. Team exercises need a small cloud VM or a host inside the client's network, with HTTPS and named logins. On a shared host, the demo logins are turned off and Neo4j Browser is not exposed. Where to host it is an open question for Hamid.

## 7. Sync freshness

The twin polls every 60 seconds and on "sync now". Matching runs after each sync. So the twin view can trail IMPACT Web by up to about two minutes. Each twin screen shows the time of its last sync, and any item still being matched is marked as pending.

## 8. Build placement

- **Phase 4.** The Quint spec gains exercises, the clock, roles, concurrent editors and the change process. It is checked as a model only at this stage, since the planning APIs don't exist yet.
- **Phase 8. Planning mode.** Exercises, membership, the clock, the change process, the facilitator console, injects, reset and the debrief. The Quint planning traces are replayed against the real APIs here, and all checks in section 5 must pass.
