# Agent instructions

This repository holds the 3.1 Frozen Work List turnaround digital twin demo (synthetic Unit 200 diesel hydrotreater).

## Standing rules

- **Writing.** Before writing anything a person will read, load the `clear-writing` skill and follow it. This covers every reply, status update, email, doc, README, commit and PR description, post, and any text the user asks to edit. It applies to subagents too. Use periods and commas instead of em dashes or en dashes.
- **Working on a repository.** Before changing anything, load the `way-of-working` skill and follow it. It covers how decisions get recorded, the pull request every change goes through, the checks before each push, the independent review before a PR opens, watching an open PR until it merges, and the retro that improves the standard.

## Session start

1. Read [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/decisions.md](docs/decisions.md). Where this repository states a project rule, follow it.
2. Wire the pre-push hook on a fresh clone with `git config core.hooksPath scripts/hooks`, and run `scripts/check.sh` to confirm the baseline passes.
3. Check for open pull requests (`gh pr list --state open`) and finish watching them before starting unrelated work.
4. Confirm available cross-model reviewers before the first push. The author model and reviewer model must differ ([CONTRIBUTING.md](CONTRIBUTING.md)).
5. Confirm you are on a feature branch off current `main`. Commit directly to branches and merge through reviewed PRs.

## Project boundaries

- **Synthetic data only.** Invent every Unit 200 tag, equipment name, scenario persona, cost, and hour estimate. Keep client, consultant, real site, and workshop participant names out of code, data, docs, and commits. Governance references to the repository owner in project docs are allowed.
- **Validation before code.** Write acceptance criteria and failing checks before writing implementation code ([CONTRIBUTING.md](CONTRIBUTING.md)).
- **Write-through is demo only.** IMPACT Web stays the system of record. The twin writes only through `POST /api/v1/twin/change-requests` under `TWIN_RAISE_TOKEN` when the exercise `twin_write_through` switch is on ([docs/decisions.md](docs/decisions.md) D9, [docs/design.md](docs/design.md) section 5.8).
- **Release-one scope.** Keep 4.1 (work packages) and 4.2 (execution plan and logistics) to schema slots only. Label focus-area brief value figures as unvalidated assumptions.
- **Dates.** Record dated notes using the local date in `America/Chicago` (`YYYY-MM-DD`).

## Context pointers

Load only the document matching the current task:

- **Architecture, data model, APIs, write-through contracts, build phases:** [docs/design.md](docs/design.md)
- **Unit 200 equipment, P&ID sheets, work list counts, planted problems, walkthrough:** [docs/scenario-spec.md](docs/scenario-spec.md)
- **Schemas, SHACL/n10s rules, Hypothesis properties, Quint invariants:** [docs/verification.md](docs/verification.md)
- **Deterministic vs AI matching split, difficulty classes, evaluation fixtures:** [docs/matching-showcase.md](docs/matching-showcase.md)
- **Planning mode roles, exercise clock, injects, debrief:** [docs/interactive-planning.md](docs/interactive-planning.md)
- **exe.dev VM hosting, auth headers, 4 GB memory budget:** [docs/hosting.md](docs/hosting.md)
- **Recorded architecture choices (D1 to D16):** [docs/decisions.md](docs/decisions.md)
- **Phase 0 spike results and rerun commands:** [docs/spikes/](docs/spikes/)
- **PR body checklist:** [.github/pull_request_template.md](.github/pull_request_template.md)
