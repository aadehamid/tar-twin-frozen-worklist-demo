# Interactive planning mode

Version 0.1, for review.

The system runs in two modes on the same code:

- **Demo mode.** The 10-minute scripted walkthrough in the scenario spec. Seeded data, the same result every time.
- **Planning mode.** A team rehearses getting Unit 200 ready for a turnaround. People log in with their own roles, raise and challenge real work requests in IMPACT Web, watch the twin respond, and take the list through DRB and freeze. A facilitator runs the clock and adds surprises.

Planning mode is a rehearsal and training tool on a synthetic unit. It is not a planning system for a real turnaround.

## 1. Who takes part

| Role | Works in | Can do |
|---|---|---|
| Facilitator | Facilitator console | Create and reset exercises, move the clock, inject events, see every team |
| TA manager | IMPACT Web | Set the budget target, run the challenge and DRB, freeze the list |
| Planner | IMPACT Web and twin | Raise and edit requests, review tag matches, use the cut line |
| Source group (fixed equipment, rotating, inspection, operations, projects, instrumentation) | IMPACT Web | Raise requests for their area, defend them at the challenge |
| DRB member | IMPACT Web and twin | Accept, defer or reject at the DRB |
| Viewer | Twin | Look, with no edits |

The roles come from the template's user model, with per-exercise role assignment added.

## 2. How an exercise runs

1. **Set up.** The facilitator creates an exercise from a starting point:
   - **Seeded.** The full Unit 200 candidate list of 200 requests, with all the planted problems.
   - **Partial.** About half the list, with the team raising the rest from an inspection and reliability brief.
   - **Blank.** An empty list, with briefing packs per source group listing what their area needs this turnaround.
2. **Invite.** The facilitator assigns people to roles. Each exercise is isolated, so two teams can run the same scenario side by side and compare.
3. **Play the phases.** The facilitator moves the exercise clock through the steps in the scenario spec: candidate list, fit to frame, challenge, DRB, freeze, and the months after freeze. Each step opens and closes actions in IMPACT Web. For example, after freeze a new request can only go in as a late add with a reason.
4. **Work with the twin.** Every change in IMPACT Web reaches the twin on the next sync (under a minute, or on "sync now"). Planners see the match rate, clusters, cut line and mapping trace update as they work.
5. **Injects.** The facilitator can drop in events from a library, or write new ones:
   - An inspection finding that adds a job late, for example "UT shows thinning on line 200-P-0412 near E-201C"
   - A budget cut before DRB
   - A source group resubmitting a duplicate under a different description
   - A retired tag turning up in a request
   - Operations asking to defer the stripper tray work
6. **Debrief.** The exercise ends with a debrief report: the match rate over time, shared costs found and missed, what the cut line removed, scope growth after freeze in man-hours, and a timeline of decisions with who made them.

## 3. What the twin adds while planning

- A planner raising a request on E-201B sees straight away that it sits in the HP reaction loop envelope with other jobs, and which scaffold or crane setup it could share.
- A source group defending an item at the challenge can show it on the plot plan and P&ID.
- The TA manager can try cut lines as named what-ifs in the twin before deciding at DRB. A what-if is saved in the twin only. The decision itself is made in IMPACT Web.
- After freeze, everyone sees each late add's effect on hours and on the clusters it breaks or joins.

## 4. Rules that still hold

- The twin never writes to IMPACT Web, in either mode. Planning decisions are made in IMPACT Web and flow to the twin.
- Estimates, rates and plant data stay synthetic. A team can change hours on their own requests, and the engineering rules still check every change (for example, a bundle pull can't be raised on a pump).
- Value figures stay labeled as the brief's unvalidated defaults.

## 5. Validation for this mode (decided before any code)

Following [CONTRIBUTING.md](../CONTRIBUTING.md), these checks are written before planning mode is built.

| Acceptance criterion | Check |
|---|---|
| Two exercises never see each other's data | API tests across two exercises. Quint invariant: no step reads or changes another exercise's state |
| Actions follow the exercise clock, for example no normal adds after freeze | Quint invariant over clock steps. API tests for each phase gate |
| Two people editing the same request don't lose an edit | Optimistic locking with a version field. Quint model with two concurrent editors. API test for a stale write getting a 409 |
| Freezing while someone is editing gives a defined result | Quint model of freeze racing an edit. Playwright test |
| Each role can only do its own actions | Permission matrix tests generated from the role table above |
| An inject produces exactly the change it describes | Scenario tests per inject in the library |
| Resetting an exercise restores the starting point exactly | Snapshot comparison test after reset |
| The debrief numbers agree with the change log | Hypothesis property: debrief totals equal the sums over the event history |
| A team change that breaks an engineering rule is refused with a clear message | SHACL rule tests, plus a Playwright check of the message |

## 6. Hosting

On one laptop the whole team can't reach it. For team exercises it needs to run on a small cloud VM or a host inside the client's network, with HTTPS and named logins. Where to host it is an open question for Hamid.

## 7. Build placement

Planning mode is a new phase after the demo works end to end:

- **Phase 8. Planning mode.** Exercises, roles per exercise, the exercise clock, the facilitator console, the inject library, reset and the debrief report.

The Quint model gets exercises, the clock and concurrent editors from phase 4 onward, so the workflow is checked for multi-user play before the UI exists.
