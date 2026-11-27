# Hosting on exe.dev

Version 0.1, for review.

Team exercises and shared demos run on one exe.dev VM on Hamid's Personal plan: 2 vCPU and 4 GB of memory, 100 GB of disk and 200 GB of outbound bandwidth a month, shared by every VM on the account ([exe.dev Personal plan](https://exe.dev/docs/billing/personal)). Local development stays on laptops with the normal template setup.

The data is synthetic, so a hosted service outside the client's network is fine. Anything with real client data would need a host the client approves.

## 1. What runs on the VM

One VM, `tar-twin`, running Docker Compose. exe.dev VMs support `docker` and `docker-compose` directly ([exe.dev docs](https://exe.dev/docs/all.md)).

| Container | Listens on | Reachable by |
|---|---|---|
| IMPACT Web (API plus built UI) | 8001 | People the VM is shared with, through the exe.dev proxy |
| Twin (API plus built UI) | 8002 | People the VM is shared with, through the exe.dev proxy |
| Landing page with links to both | 8000 | People the VM is shared with. This is the proxy's main port |
| PostgreSQL | Docker network only | The two services |
| Neo4j (Bolt and Browser) | Docker network only | The twin service. Hamid reaches Neo4j Browser through an SSH tunnel |

The exe.dev proxy serves `https://tar-twin.exe.xyz/` and forwards ports 3000 to 9999, so the two UIs sit at `:8001` and `:8002` ([exe.dev proxy](https://exe.dev/docs/proxy)). Neo4j's default ports 7474 and 7687 fall inside that range. That's why Neo4j and Postgres publish no ports on the host at all.

## 2. Memory budget for 4 GB

| Part | Setting | Expected use |
|---|---|---|
| OS, Docker, landing page | | about 400 MB |
| Neo4j with n10s | heap 768 MB, page cache 384 MB | about 1.5 GB |
| PostgreSQL | `shared_buffers` 128 MB | about 300 MB |
| IMPACT Web API | one Uvicorn worker | about 200 MB |
| Twin API with pyDEXPI | one Uvicorn worker | about 350 MB |
| Sync and match jobs | in the twin process, one at a time | about 200 MB at peak |
| Total | | about 3 GB, leaving about 1 GB spare |

Rules that keep it inside 4 GB:

- Front ends are built in GitHub Actions, not on the VM. Vite builds use more memory than the running system.
- Images are built in CI, pushed to GitHub's container registry, and pulled on the VM. exe.dev can pull private ghcr.io images through its registry integration ([exe.dev docs](https://exe.dev/docs/all.md)).
- No local model. Inkling 2 Mini needs about 20 GB, so on this VM the AI matcher uses OpenRouter or runs rules-only. In planning mode, participant text is matched rules-only by default. The facilitator can turn on OpenRouter for an exercise.
- Other VMs on the account share the same 4 GB, so they stay stopped during exercises.

If the soak test in section 6 fails, capacity can go to 4 vCPU and 8 GB with `billing capacity --cpu=4`, at $35 a month, prorated and immediate ([exe.dev Personal plan](https://exe.dev/docs/billing/personal)).

## 3. Who can get in

- The VM stays private. Hamid adds each participant with `share add tar-twin <email>`, which gives web access only, no shell ([exe.dev sharing](https://exe.dev/docs/sharing)).
- exe.dev adds `X-ExeDev-Email` and `X-ExeDev-UserID` headers to requests from signed-in users ([exe.dev docs](https://exe.dev/docs/all.md)).
- Both services get an auth adapter with two modes:
  - `AUTH_MODE=local` uses the template's normal JWT login, for development and tests.
  - `AUTH_MODE=exe` reads `X-ExeDev-Email`, finds the person's `exercise_membership`, and refuses anyone without one. Demo logins and password login are turned off.
- The facilitator console is open only to emails listed in `FACILITATOR_EMAILS`.
- The exe.dev docs don't say whether the proxy overwrites an `X-ExeDev-Email` header sent by the client. Phase 0 tests this. If it doesn't, the services also check a shared secret header added on the VM, or move to exe.dev's documented login redirect flow.

## 4. Secrets

- The OpenRouter key and database passwords live in `/opt/tar-twin/.env` on the VM, owned by root with mode 600. They are never committed.
- Each participant's exe.dev email is stored only in `exercise_membership`.

## 5. Deploying and backups

- `scripts/deploy.sh` runs from Hamid's machine or GitHub Actions. It connects over SSH, pulls the tagged images, runs database migrations, restarts with `docker compose up -d`, and runs the smoke test.
- Every deploy is tagged with the Git commit, so going back means redeploying the previous tag.
- Nightly `pg_dump` of IMPACT Web, kept for 7 days on the VM. The twin graph doesn't need its own backup, because it rebuilds from the DEXPI files and an IMPACT Web sync.
- Before each team exercise, Hamid can copy the whole VM with exe.dev's `cp` ([exe.dev docs](https://exe.dev/docs/all.md)) to keep a fallback.
- S3 backups through exe.dev are possible later if Hamid sets up a bucket.

## 6. Validation for hosting (decided before any code)

| Acceptance criterion | Check |
|---|---|
| Only ports 8000, 8001 and 8002 listen on the host | Post-deploy check with `ss -tlnp`, which fails the deploy on any other listener in 3000 to 9999 |
| Neo4j and Postgres can't be reached through the proxy | Smoke test: requests to `:7474`, `:7687` and `:5432` through `tar-twin.exe.xyz` fail |
| Only shared users get in | Test with an unshared exe.dev account, which gets the exe.dev login and no app content |
| A forged identity header doesn't work | Phase 0 spike: send `X-ExeDev-Email` from a client and confirm what reaches the app. The adapter test covers both outcomes |
| Users without a membership are refused | API test in `AUTH_MODE=exe` with a known email and no membership |
| Demo logins are off when hosted | Test that password login returns 404 in `AUTH_MODE=exe` |
| The system fits in 4 GB | Soak test: 15 simulated users through a full exercise, with peak memory below 3.5 GB, no container restarts, and twin freshness inside the targets in [interactive-planning.md](interactive-planning.md) section 7 |
| Deploys can be reversed | Test deploying tag N, then N-1, then N again, with data intact |
| Backups restore | Monthly restore of the latest `pg_dump` into a scratch database, with row counts compared |
| Secrets stay off Git | CI secret scan, plus a check that `.env` is mode 600 on the VM |

## 7. Phase placement

- **Phase 0.** Create the VM, check Docker and the proxy ports, run the forged-header spike, and run Neo4j and Postgres together to measure idle memory.
- **Phase 7.** Deploy script, CI image builds, the post-deploy port check, backups and the first soak test.
- **Phase 8.** `AUTH_MODE=exe`, membership by email, the facilitator list, and the 15-user soak test.
