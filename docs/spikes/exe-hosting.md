# Spike: exe.dev hosting checks

Status: checks written before code. Results go in section 3 after the run.

VM: `tar-frozen-work-list` on Hamid's exe.dev Personal plan. The sandbox reaches it with an SSH key scoped to this one VM (`ssh-key add --vm`), so the spike can't touch other VMs, sharing or billing.

This spike answers the phase 0 hosting questions in [hosting.md](../hosting.md) section 9. It doesn't build the edge. It tests what the exe.dev proxy does, so the edge design rests on observed behavior rather than on the docs alone.

## 1. Method

A small echo server (`spikes/exe-hosting/echo.py`, standard library only) listens on ports 8000, 8001 and 8002 inside the VM. For every request it logs the peer address and all request headers as one JSON line and returns the same JSON. Requests go from the sandbox to `https://tar-frozen-work-list.exe.xyz:<port>/`.

Authenticated requests use a VM token signed locally with the scoped key, namespace `v0@tar-frozen-work-list.exe.xyz`, with `exp` set one hour ahead, sent in `X-Exedev-Authorization`. The token payload carries a `ctx` field so we can see it arrive as `X-ExeDev-Token-Ctx`.

`spikes/exe-hosting/run_checks.sh` runs every check and writes `spikes/exe-hosting/results.json`. Each check prints PASS, FAIL or RECORD (for observations with no pass bar).

## 2. Checks and pass conditions

| ID | Check | Pass condition |
|---|---|---|
| H1 | Docker works for the login user | `docker run --rm hello-world` exits 0 without sudo, and `docker compose version` reports v2 |
| H2 | The proxy reaches ports 8000, 8001 and 8002 | An authenticated GET to each port returns 200 and the echo body names that port |
| H3 | Private by default | An unauthenticated GET with curl's default `Accept` returns 401 on each port, and the echo server logs no request for it |
| H4 | Identity headers arrive | The authenticated request carries exactly one `X-ExeDev-Email`, equal to the account email, and one non-empty `X-ExeDev-UserID` |
| H5 | Forged identity headers are replaced | An authenticated request that also sends `X-ExeDev-Email: forged@example.com`, `X-ExeDev-UserID: usr_forged` and `X-ExeDev-Token-Ctx: forged` reaches the server with only the real values. No header value contains `forged` |
| H6 | The proxy strips the token | No `X-Exedev-Authorization` or `Authorization` header reaches the server |
| H7 | Source address of proxy traffic | RECORD the peer address over 5 requests per port and the `X-Forwarded-For` value. Then RECORD the peer address the server sees for a request from a Docker container on the default bridge. The result decides the edge trust rule (see section 4) |
| H8 | Idle memory of Neo4j and Postgres | Start `neo4j:5-community` with heap 768 MB and page cache 384 MB, and `postgres:16` with `shared_buffers` 128 MB, both with no published ports. After 3 minutes idle, `docker stats` shows Neo4j at or below 1.5 GB and Postgres at or below 300 MB, the hosting.md budget. Also RECORD `free -m` before and after |
| H9 | Database ports stay closed | With H8 running, an authenticated GET to the proxy on 7474 and 5432 doesn't reach Neo4j or Postgres, and `ss -tlnp` on the VM shows no listener on 0.0.0.0 for 7474, 7687 or 5432 |
| H10 | Clean up | After the run, no spike containers, volumes or echo processes are left on the VM |

Not covered here. A public site (`share set-public`) changes the threat, because anyone can send forged headers without a login. The scoped key can't change sharing, and the plan keeps the VM private until phase 8. Phase 8 repeats H5 against a public share before any wider access.

## 3. Results

To be filled in from `results.json` after the run.

## 4. What the results decide

- If H5 passes, the proxy is a trustworthy source of identity, and the edge rule in hosting.md section 5 stands.
- If H5 fails, the apps can't trust `X-ExeDev-Email` from the proxy, and identity moves to VM tokens with signed `ctx`, or to app sessions.
- If H7 shows proxy traffic arrives from an address no container can use, the edge tells them apart by peer address on the bridge network. If the addresses overlap, the edge runs in host network mode, as hosting.md already allows.
- If H8 fails, the memory budget in hosting.md section 2 changes before phase 2 starts.
