# Hosting on exe.dev

Version 0.2, for review. Revised after the first cross-model review on PR #2.

Team exercises and shared demos run on one exe.dev VM on Hamid's Personal plan: 2 vCPU and 4 GB of memory, 100 GB of disk and 200 GB of outbound bandwidth a month, shared by every VM on the account ([exe.dev Personal plan](https://exe.dev/docs/billing/personal)). Local development stays on laptops with the normal template setup.

The data is synthetic, so a hosted service outside the client's network is fine. Anything with real client data would need a host the client approves.

## 1. What runs on the VM

One VM, `tar-twin`, running Docker Compose. exe.dev VMs support `docker` and `docker-compose` directly ([exe.dev docs](https://exe.dev/docs/all.md)).

| Container | Published on the host | Reachable by |
|---|---|---|
| Edge (Caddy) | 8000, 8001, 8002 | People the VM is shared with, through the exe.dev proxy. 8000 is a landing page, 8001 forwards to IMPACT Web, 8002 to the twin |
| IMPACT Web (API plus built UI) | nothing | The edge, and the twin over the Docker network |
| Twin (API plus built UI) | nothing | The edge |
| PostgreSQL | nothing | IMPACT Web only |
| Neo4j (Bolt and Browser) | nothing | The twin only |

The exe.dev proxy serves `https://tar-twin.exe.xyz/` and forwards ports 3000 to 9999 ([exe.dev proxy](https://exe.dev/docs/proxy)). So the only host ports in use are the edge's three. Nothing else publishes a port, not even on loopback. Neo4j's 7474 and 7687 sit inside the forwarded range, which is why they stay inside Docker.

For owner access to the graph, Hamid uses `cypher-shell` through `ssh` and `docker compose exec`. For Neo4j Browser he opens an SSH tunnel from his machine straight to the Neo4j container's address on the Docker network, for both 7474 and 7687, so nothing is published on the VM.

## 2. Memory budget for 4 GB

| Part | Setting | Expected use |
|---|---|---|
| OS, Docker, edge | | about 400 MB |
| Neo4j with n10s | heap 768 MB, page cache 384 MB | about 1.5 GB |
| PostgreSQL | `shared_buffers` 128 MB | about 300 MB |
| IMPACT Web API | one Uvicorn worker | about 200 MB |
| Twin API with pyDEXPI | one Uvicorn worker | about 350 MB |
| Sync and match jobs | in the twin process, one at a time | about 200 MB at peak |
| Total | | about 3 GB, leaving about 1 GB spare |

Rules that keep it inside 4 GB:

- Front ends are built in GitHub Actions, not on the VM. Vite builds use more memory than the running system.
- Images are built in CI, pushed to GitHub's container registry, and pulled on the VM. exe.dev can pull private ghcr.io images through its registry integration, using a classic GitHub token scoped to reading packages ([exe.dev docs](https://exe.dev/docs/all.md)).
- No local model. Inkling 2 Mini needs about 20 GB, so on this VM the AI matcher uses OpenRouter or runs rules-only. In planning mode, participant text is matched rules-only by default. The facilitator can turn on OpenRouter for an exercise.
- Other VMs on the account share the same 4 GB, so they stay stopped during exercises.

If the soak test in section 6 fails, capacity can go to 4 vCPU and 8 GB with `billing capacity --cpu=4`, at $35 a month, prorated and immediate ([exe.dev Personal plan](https://exe.dev/docs/billing/personal)).

## 3. Who can get in

- The VM stays private. Hamid adds each participant with `share add tar-twin <email>`, which gives web access only, no shell ([exe.dev sharing](https://exe.dev/docs/sharing)).
- exe.dev adds `X-ExeDev-Email` and `X-ExeDev-UserID` headers to requests from signed-in users ([exe.dev docs](https://exe.dev/docs/all.md)). exe.dev's own deploy guides show the proxy replacing any such headers a client sends, and phase 0 confirms it on our VM.

### Trusting the identity headers

- **Threat model.** The exe.dev proxy is the only path from outside to the edge's ports. Only Hamid has root on the VM, and only our containers run on it. Anyone with root could fake a header, so root is never shared.
- **Only the edge can carry a user identity.** The edge is the only container with published ports. The apps publish nothing, so the only way to reach them is through the edge or from another container on the Docker network.
- **Requests that skip the edge carry no user identity.** The edge adds an `X-Edge-Auth` secret to every request it forwards. The apps read `X-ExeDev-Email` only when that secret is present. A request from any other container, for example the twin calling IMPACT Web, has its identity headers ignored and must use a machine token instead.
- **Owner-only until verified.** Until the identity checks in section 6 pass on the VM, the VM is shared with Hamid only.

### People

- Both services get an auth adapter with two modes:
  - `AUTH_MODE=local` uses the template's normal JWT login, for development and tests.
  - `AUTH_MODE=exe` reads `X-ExeDev-Email` (from the edge only), finds the person's `exercise_membership`, and refuses anyone without one. Demo logins and password login are turned off.
- The facilitator console is open only to emails listed in `FACILITATOR_EMAILS`.

### Machines

- The twin's scheduled sync and its membership lookups don't come from a person. They use a machine token for the twin's IMPACT Web service account, sent in `Authorization` over the Docker network.
- That account has a read-only role, so it can read the change feed, frozen copies and memberships and nothing else.
- The twin container holds no Postgres credentials, and Postgres accepts connections only from the IMPACT Web container's database user.

## 4. Secrets

- The OpenRouter key and database passwords live in `/opt/tar-twin/.env` on the VM, owned by root with mode 600. They are never committed.
- Each participant's exe.dev email is stored only in `exercise_membership`.

## 5. Deploying and backups

- `scripts/deploy.sh` runs from Hamid's machine or GitHub Actions. It connects over SSH, pulls the tagged images, runs database migrations, restarts with `docker compose up -d`, and runs the smoke test.
- Every deploy is tagged with the Git commit, and takes a `pg_dump` before running migrations.

### Database changes and rollback

- **Expand, then contract.** A release may add tables, columns or nodes. It may not drop or rename anything the previous release still uses. Drops happen in a later release, once nothing reads them.
- **Rollback.** Going back means redeploying the previous tag. Because migrations only expand, the previous release still runs against the new schema.
- **If a migration must break compatibility,** the PR says so. Its rollback is to restore the pre-deploy dump, and the rollback test exercises that path.

### What gets backed up

The data lives in two places, and both are backed up:

- **IMPACT Web (Postgres).** Nightly `pg_dump`.
- **Twin-only state (Neo4j).** This is the data that exists only in the twin: reviewed matches, AI proposals, findings, saved cut-line options, baseline readiness flags and sync cursors. A nightly export from the twin API writes it to JSON. Everything else in the twin rebuilds from the DEXPI files and an IMPACT Web sync.
- **Restore** rebuilds the plant graph, resyncs from IMPACT Web, then imports the twin-only export.
- **Off the VM.** Copies on the same VM don't protect against losing the VM. `scripts/pull-backup.sh`, run from Hamid's machine, copies the latest dumps off the VM. exe.dev S3 backups need an S3 bucket and a Workload Identity Federation integration ([exe.dev docs](https://exe.dev/docs/all.md)), so they're an option for later.
- **Before each team exercise,** Hamid stops the stack, copies the whole VM with exe.dev's `cp` ([exe.dev docs](https://exe.dev/docs/all.md)), starts the stack again, and checks that the copy boots.

## 6. Validation for hosting (decided before any code)

| Acceptance criterion | Check |
|---|---|
| Only the edge publishes ports | Post-deploy checks of `docker compose config`, `docker ps` port mappings and `ss -tlnp`. Any listener in 3000 to 9999 other than 8000, 8001 and 8002 fails the deploy |
| Neo4j and Postgres can't be reached through the proxy | Smoke test as a web-shared, low-privilege user: `:7474`, `:7687` and `:5432` through `tar-twin.exe.xyz` fail |
| Only shared users get in | Test with an unshared exe.dev account on `:8000`, `:8001` and `:8002`. Each gets the exe.dev login and no app content |
| A forged identity header doesn't work | From outside: a client-sent `X-ExeDev-Email` on both app ports doesn't change who the app sees. From inside: a container calling an app directly with `X-ExeDev-Email` and no edge secret is treated as anonymous |
| Users without a membership are refused | API test in `AUTH_MODE=exe` with a known email and no membership |
| Machine sync works without a person and can't write | Test that the twin sync runs on its token with no user session, and that every IMPACT Web write endpoint refuses that token |
| The twin has no database access to IMPACT Web | Check that the twin container's environment holds no Postgres credentials, and that Postgres refuses a connection from the twin container |
| Demo logins are off when hosted | Test that password login returns 404 in `AUTH_MODE=exe` |
| The system fits in 4 GB | Soak test: 15 simulated users through a full exercise, including a cold start, the DEXPI load with SHACL checks, concurrent edits, matching, graph exports and a reset. Peak memory stays below 3.5 GB on the VM, `docker stats` peaks are logged per container, and there are no out-of-memory kills, container restarts or 5xx errors. Twin freshness stays inside the targets in [interactive-planning.md](interactive-planning.md) section 7 |
| Disk stays in budget | Deploy check of VM disk use against the account's 100 GB, with image pruning |
| Deploys can be reversed | Test deploying tag N, then N-1, then N again with data intact, using a release that adds a real column |
| A breaking migration can be undone | Test restoring the pre-deploy dump after a breaking migration, then deploying forward again |
| Backups restore the whole state | Monthly restore into a scratch stack from the off-VM copies: Postgres row counts match, and a sample of reviewed matches, findings and saved cut-line options come back exactly |
| A pre-exercise copy is usable | Boot the copied VM and run the smoke test on it |
| Secrets stay off Git | CI secret scan, plus a check that `.env` is mode 600 on the VM |

## 7. Phase placement

- **Phase 0.** Create the VM, check Docker and the proxy ports, run the forged-header spike, and run Neo4j and Postgres together to measure idle memory.
- **Phase 7.** Edge, deploy script, CI image builds, machine token, the post-deploy port checks, backups with restore test, and the first soak test. The VM stays shared with Hamid only.
- **Phase 8.** `AUTH_MODE=exe`, membership by email, the facilitator list, the identity-header checks, and the 15-user soak test. Only after these pass is the VM shared with the team.
