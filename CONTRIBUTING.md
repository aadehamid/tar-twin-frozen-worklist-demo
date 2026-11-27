# How work gets done in this repo

Two rules apply to every change, including documentation.

## Rule 1. Decide how to validate it before writing it

No code is written until the checks that will prove it works are written down. For each change, in this order:

1. **Acceptance criteria.** Plain sentences saying what must be true when the change is done. They go in the issue or the PR description.
2. **Checks.** The tests, rules or specs that will prove each criterion. Write them first, so they fail before the code exists. Depending on the change, that means:
   - Pydantic models or JSON schemas for new records and payloads
   - SHACL shapes for new graph data or engineering rules
   - Hypothesis property tests for calculations
   - Updates to the Quint workflow spec for any change to sync, review, freeze, roles or concurrency
   - pytest API and contract tests
   - Playwright tests for user flows
   - Expected counts in the scenario tests for data changes
3. **Code.** Write the change until the checks pass.
4. **Evidence.** The PR shows the checks failing before and passing after, or explains why a check could not fail first. Docs-only PRs are the one standing exception: their evidence is the cross-model review plus a scan for dashes and broken links.

See [docs/verification.md](docs/verification.md) for the layers and tools.

## Rule 2. A different model reviews every PR before merge

- Each PR is reviewed by a different AI model from the one that wrote the change. The reviewer gets the PR diff, the acceptance criteria and the relevant docs, and checks correctness, the validation evidence, realism against the scenario spec, and the ground rules (synthetic data only, no writes to IMPACT Web, value figures labeled unvalidated).
- The reviewer's findings are posted on the PR as a comment, with the reviewing model named.
- Blocking findings are fixed, or answered with a reason, before merge.
- Hamid can review or block any PR. Changes to scope, the scenario numbers or the ground rules need his approval as well as the model review.

## Branches and commits

- Work on a branch, open a PR into `main`, and merge after review. No direct pushes to `main`.
- One topic per PR. Keep PRs small enough to review properly.
