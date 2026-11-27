# Spike: the full-stack FastAPI template without Docker

Status: done, with one template bug to fix. The template builds and passes its lint, migrations, backend tests and build with no Docker in all eight runs. Its full Playwright suite passed in six of eight runs. Both failures were reset password tests timing out on the Mailpit email. The template's signup test helper has a real race that fits those failures, and with a small patch to the helper the two affected tests passed 120 of 120 targeted repeats.

This spike answers a phase 0 question in [design.md](../design.md) section 10. Design section 3.3 says development without Docker is supported, with a local Postgres, a local Neo4j and `uv run` for each service. Decision D2 starts both services from the [full-stack FastAPI template](https://github.com/fastapi/full-stack-fastapi-template). Does the template, as it stands today, build and pass its own tests with no Docker at all?

The local Neo4j half belongs to the SHACL spike, which runs Neo4j and n10s from the release tarball. This spike covers everything else.

## 1. What the template expects

Read from the template at commit `f8c6c147b12bb1c4d3253cc1b06f8b5ef81b10dd` (2026-11-26), MIT licensed, before writing the checks.

- The backend is FastAPI with SQLModel, Alembic and psycopg, on Python 3.14, managed by uv. The front end is React with Vite, managed by bun. The template's CI pins bun 1.3.12.
- The backend serves the built front end itself. `bun run build` writes to `backend/app/frontend`, and FastAPI serves it at `/`.
- Its development guide still uses Docker Compose for two things, Postgres 18 and Mailpit, which catches the app's email. Everything else already runs on the host with `uv run` and `bun`.
- The CI backend job runs `scripts/prestart.sh` (migrations and the first superuser), then `scripts/tests-start.sh`, and fails under 90% coverage. The Playwright job generates the API client, builds the app, and runs the whole Playwright suite against the backend with `--fail-on-flaky-tests`. The password reset test reads the reset email out of Mailpit.

So the spike replaces the two Compose services with a Postgres 18 cluster in a temporary folder and the Mailpit binary, then runs the template's own CI steps against them.

## 2. How it runs

`spikes/template-no-docker/run_spike.py` does the whole run from an empty temporary folder and writes `results.json`. It never calls `docker`.

1. Clone the template at the pinned commit.
2. Fetch bun 1.3.12 and Mailpit 1.34.0 from their GitHub releases and check each against its published SHA-256.
3. `initdb` a Postgres 18 cluster on port 55432 with password login, and create the `app` database. Start Mailpit on 1025 and 8025.
4. Write the template's `.env` with the local `DATABASE_URL`, then run the CI steps: `uv sync`, `prestart.sh` twice, `lint.sh`, `tests-start.sh`, `bun ci`, `generate-client.sh`, `bun run build`.
5. Start the backend with `uv run fastapi run`, check it by hand, then run the Playwright suite against it, and run the race check T11.
6. Record memory, stop everything and delete the run folder. The script always makes a new folder for the run, as a child of `--work` when that's given, and deletes only that folder.

## 3. Checks and pass conditions

The parsing of test output is unit-tested in `test_checks.py` against sample outputs, including failing ones, before the run script uses it.

| ID | Check | Pass condition |
|---|---|---|
| T1 | No Docker | The run script contains no `docker` command. RECORD whether `docker` is on the machine's PATH |
| T2 | Pinned inputs | The template checkout is at the pinned commit. The bun download matches its release SHASUMS256.txt, and the Mailpit download matches the SHA-256 GitHub records for the release asset. Mailpit publishes no checksum file, so the script pins that value and cross-checks it against the GitHub API when the API answers. If any of these fails, the script stops before it unpacks the mismatched download or runs any template code. RECORD the uv, Python, bun, Postgres and Mailpit versions |
| T3 | Local services | Postgres answers `pg_isready` and Mailpit answers `GET /livez` within 30 seconds of starting |
| T4 | Migrations and first user | `prestart.sh` exits 0. Tables `user` and `item` exist, `alembic current` equals `alembic heads`, and there's exactly one superuser, `admin@example.com`. A second `prestart.sh` exits 0 and still leaves one user |
| T5 | Lint | The template's `lint.sh` (mypy strict, ty, ruff) exits 0 |
| T6 | Backend tests | `tests-start.sh` exits 0 with no failed or errored tests, and coverage is at least 90%, the template's own gate. RECORD the counts |
| T7 | Client and build | `generate-client.sh` exits 0 and leaves the committed client in `frontend/src/client` unchanged. `bun ci` and `bun run build` exit 0, and `backend/app/frontend/index.html` exists |
| T8 | Serving | Within 20 seconds of `fastapi run`, `GET /api/v1/utils/health-check/` returns `true`. `GET /` returns the built page. Logging in as the superuser gives a token, and `GET /api/v1/users/me` with it returns `admin@example.com` |
| T9 | Browser tests | The template's full Playwright suite passes against `http://localhost:8000` with `--fail-on-flaky-tests`: every test in the "Running N tests" header passed, none failed, was flaky or was skipped, and both reset password tests that sign up a user and read the email from Mailpit passed. RECORD the test count and time |
| T11 | Signup race | Added after runs 1 and 5 showed a flaky reset test. Run `tests/reset-password.spec.ts` with `--repeat-each=N --retries=0` twice, first with the template's `signUpNewUser` as it is, then with it waiting for the signup response. Pass if the patched run exits 0, runs every test in its header with no failures or skips, and each of the two signup tests passed all N times. The patched helper also throws if the signup response isn't a success. RECORD both runs, per test |
| T10 | Footprint | RECORD the resident memory of Postgres, Mailpit and the backend after T9, and the wall time of each step. No pass condition. It feeds the 4 GB budget in [hosting.md](../hosting.md) |

If a check fails because of the environment rather than the template, the doc says so and names the fallback. The fallback for every check is the template's own route: Postgres and Mailpit in Docker Compose on the developer's machine.

## 4. Results

Eight full runs on this sandbox, 2 vCPU class, Ubuntu 26.04, no Docker on the PATH. `results.json` is run 8, the first with the stricter T2, T9 and T11 checks asked for in review. `runs.json` summarises all eight. Runs 1 to 7 used the first version of those checks, which counted passes and failures but didn't record which tests failed. One more attempt stopped at T2 because the GitHub API returned 403 for rate limiting. It's not counted, see finding 3.

| Check | Result |
|---|---|
| T1 | Pass in all runs. The script has no `docker` command and `docker` isn't on the PATH |
| T2 | Pass in all runs. Template at `f8c6c14`, bun 1.3.12 matches SHASUMS256.txt, Mailpit 1.34.0 matches the pinned SHA-256. uv 0.13.4, Python 3.14.8, Postgres 18.6 |
| T3 | Pass. Postgres and Mailpit both answer in under a second |
| T4 | Pass. Tables `user`, `item` and `alembic_version`, Alembic at head `fe56fa70289e`, one superuser. The second `prestart.sh` changes nothing |
| T5 | Pass. mypy, ty and ruff are clean |
| T6 | Pass. 58 tests passed, none failed, 92% coverage against the 90% gate |
| T7 | Pass. The regenerated client matches the committed one. The only changed file is `.env`, which the script writes |
| T8 | Pass. Health check answers 1.5 s after `fastapi run`. `/` serves the built page and `/users/me` returns `admin@example.com` |
| T9 | Pass in 6 of 8 runs with 62 tests, including run 8 under the stricter condition. Runs 1 and 5 had one flaky test each, so `--fail-on-flaky-tests` failed them. Both were reset password tests timing out on the Mailpit email |
| T10 | Postgres about 136 to 155 MB resident, Mailpit about 28 to 34 MB, backend about 164 to 171 MB. A full run takes 96 to 118 s without T11, and about 10 minutes with T11 at 60 repeats |
| T11 | Pass in runs 6, 7 and 8. The figures that count are run 8's, the only run that recorded failures per test. As the template has it, the two signup tests failed 7 times in 120 (2 of 60 and 5 of 60), and the other four tests in the spec never failed. Patched, the two signup tests passed 120 of 120 and the whole spec passed 361 of 361. Runs 6 and 7 saw 3 failures in 482 reset spec tests unpatched and none in 482 patched, without the per-test split |

### Findings

1. **The template's signup helper has a race that explains the flaky reset test.** `signUpNewUser` in `frontend/tests/utils/user.ts` clicks Sign Up and then goes straight to `/login` without waiting for anything. The test then asks for a password reset. If the signup request hasn't committed yet, and the server is still hashing the password, the reset finds no user and sends no email, so the Mailpit wait times out. The evidence from run 1: the failing test's user did exist in the database afterwards, the backend logged no email send for it, and the two tests that use the helper each failed once across the runs. None of this depends on Docker. The fix is to wait for the `POST /api/v1/users/signup` response, and check it succeeded, before navigating. That's what T11 patches. In run 8 the unpatched signup tests failed 7 times in 120 and the patched ones 0 in 120. That's what we observed, not a controlled comparison. The two arms ran one after the other, and the unpatched arm partly overlapped with a Neo4j instance starting on the same machine, which may have pushed its rate up. Runs 6 and 7 saw well under 1%. What the source does establish is a real window between the signup click and the reset request, and waiting for a successful signup response closes it. It doesn't prove every flake we saw came from that race. A slower or busier machine makes the race more likely, which is one more reason to fix the helper.
2. **The backend tests empty the database.** The session fixture in `backend/tests/conftest.py` deletes every `Item` and every `User` when it finishes, the superuser included. The template's CI never sees this, because the backend tests and Playwright run in separate jobs with separate databases. On one machine, Playwright then can't log in. The script drops and recreates the `app` database and runs `prestart.sh` again before Playwright, and our fork has to do the same.
3. **Don't depend on the GitHub API for checksums.** The first version of the script read Mailpit's SHA-256 from the GitHub API, because Mailpit publishes no checksum file. Unauthenticated calls hit the rate limit and the run died at T2. The script now pins the hash and only cross-checks it when the API answers.

### What changes when we fork the template

- Patch `signUpNewUser` to wait for the signup response, and keep `--fail-on-flaky-tests` on.
- Give the Playwright step a fresh database, or run it in its own job as the template does.
- Pin bun 1.3.12 and Mailpit 1.34.0 with their hashes in the no-Docker dev script.
- For no-Docker development, use a local Postgres 18 cluster and the Mailpit binary. Neo4j is covered by the SHACL spike.

The fallback didn't come into play. If a developer can't install Postgres 18 locally, Postgres and Mailpit in Docker Compose still work as the template ships them.

The footprint leaves room. Postgres, Mailpit and one backend come to about 360 MB, against the 4 GB budget in [hosting.md](../hosting.md), before Neo4j and the second service.
