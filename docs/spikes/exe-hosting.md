# Spike: exe.dev hosting checks

Status: run on 26 November 2026. All pass checks passed on the final run, after the checks were tightened in review. Gate H13 is still to run. Raw output is in `spikes/exe-hosting/results.json`.

VM: `tar-frozen-work-list` on Hamid's exe.dev Personal plan. The sandbox reaches it with an SSH key scoped to this one VM (`ssh-key add --vm`), so the spike can't touch other VMs, sharing or billing.

This spike answers the phase 0 hosting questions in [hosting.md](../hosting.md) section 9. It doesn't build the edge. It tests what the exe.dev proxy does, so the edge design rests on observed behavior rather than on the docs alone.

## 1. Method

A small echo server (`spikes/exe-hosting/echo.py`, standard library only) listens on ports 8000, 8001 and 8002 inside the VM. For every request it logs the peer address and all request headers as one JSON line and returns the same JSON. Requests go from the sandbox to `https://tar-frozen-work-list.exe.xyz:<port>/`.

Authenticated requests use a VM token signed locally with the scoped key, namespace `v0@tar-frozen-work-list.exe.xyz`, with `exp` set one hour ahead, sent in `X-Exedev-Authorization`. The token payload carries a `ctx` field so we can see it arrive as `X-ExeDev-Token-Ctx`.

`spikes/exe-hosting/run_checks.py` runs every check and writes `spikes/exe-hosting/results.json`. Each check prints PASS, FAIL or RECORD (for observations with no pass bar).

## 2. Checks and pass conditions

| ID | Check | Pass condition |
|---|---|---|
| H1 | Docker works for the login user | `docker run --rm hello-world` exits 0 without sudo, and `docker compose version` reports v2 |
| H2 | The proxy reaches ports 8000, 8001 and 8002 | An authenticated GET to each port returns 200 and the echo body names that port |
| H3 | Private by default | An unauthenticated GET with curl's default `Accept` returns 401 on each port. The echo log is read successfully before and after, and it gains no lines at all during H3 |
| H4 | Identity headers arrive | The authenticated request carries exactly one `X-ExeDev-Email`, equal to the account email, and one non-empty `X-ExeDev-UserID` |
| H5 | Forged identity headers are replaced | An authenticated request that also sends `X-ExeDev-Email: forged@example.com`, `X-ExeDev-UserID: usr_forged` and `X-ExeDev-Token-Ctx: forged` reaches the server with exactly one of each header, equal to the email, user ID and ctx seen in H4. No header value contains `forged` |
| H6 | The proxy strips the token | No `X-Exedev-Authorization` or `Authorization` header reaches the server |
| H7 | Source address of proxy traffic | RECORD the peer address over 5 requests per port and the `X-Forwarded-For` value. Then RECORD the peer address the server sees for a request from a Docker container on the default bridge. The result decides the edge trust rule (see section 4) |
| H8 | Idle memory of Neo4j and Postgres | Start `neo4j:5-community` with heap 768 MB and page cache 384 MB, and `postgres:16` with `shared_buffers` 128 MB, both with no published ports. After 3 minutes idle, `docker stats` shows Neo4j at or below 1.5 GB and Postgres at or below 300 MB, the hosting.md budget. Also RECORD `free -m` before and after |
| H9 | Database ports stay closed | With H8 running, an authenticated GET through the proxy to 7474, 7687 and 5432 returns 502. `ss -tlnH` shows no listener on any address, loopback included, for 7474, 7687 or 5432, and `docker port` shows no mapping for either database container. Each command must exit 0 for the check to count |
| H11 | Loopback-only listener | Added after H7 showed proxy traffic arrives from 127.0.0.1. A second echo server bound to 127.0.0.1:8003 returns 200 to an authenticated proxy request with peer 127.0.0.1. A control container on the default bridge reaches the VM's 0.0.0.0 echo server at 172.17.0.1:8001 (proving the container and network work), and then gets connection refused (curl exit 7) at 172.17.0.1:8003 |
| H12 | Peer seen behind a published port | RECORD the peer address an echo server inside a container sees when the proxy reaches it through `-p 127.0.0.1:8004:8004`, and when another container on the same bridge calls it directly. This tells us whether bridge mode can tell proxy traffic from container traffic |
| H10 | Clean up | After the run, the named spike containers and their anonymous volumes are gone (`docker rm -fv` by name only, no global prune), the echo processes are stopped and the spike directory is removed. Each verification command must exit 0 |

H13 is a gate, not part of this run. It needs a second exe.dev account, so Hamid runs it before the VM is shared with anyone:

| ID | Check | Pass condition |
|---|---|---|
| H13 | What a Web-only participant can reach | Hamid shares the VM with a second account he controls, with `share add tar-frozen-work-list <email>` and no `--root`. Signed in as that account in a browser: the edge's port returns the landing page, and the IMPACT Web and twin routes under it work, with the participant's own email in `X-ExeDev-Email`. Port 9999 (Shelley) and every other port in 3000 to 9999 is refused. If any other port answers, Shelley is turned off on the VM and the check is repeated before anyone else is invited |

Why H13 matters. exe.dev had an incident in which Web share recipients could reach every proxied port, Shelley included, rather than only the shared one. It says the problem is fixed ([exe.dev security note](https://exe.dev/security/over-sharing)). The owner token used in this run can't show what a Web-only user sees, so H2 to H6 say nothing about participants.

Not covered here. A public site (`share set-public`) changes the threat, because anyone can send forged headers without a login. The scoped key can't change sharing, and the plan keeps the VM private until phase 8. Phase 8 repeats H5 against a public share before any wider access.

## 3. Results

| ID | Result | What we saw |
|---|---|---|
| H1 | PASS | `exedev` is in the docker group. Docker 29.1.3, Compose 2.40.3 |
| H2 | PASS | 200 on 8000, 8001 and 8002 |
| H3 | PASS | 401 on all three ports. The echo log read cleanly and gained no lines |
| H4 | PASS | One `X-ExeDev-Email` (aadehamid@gmail.com) and one `X-ExeDev-UserID` per request. The token's `ctx` arrived as `X-ExeDev-Token-Ctx` |
| H5 | PASS | On all three ports the server saw exactly one email, user ID and ctx, each equal to the H4 values. No header value contained `forged` |
| H6 | PASS | No token header reached the server |
| H7 | RECORD | Every proxy request came from 127.0.0.1. `X-Forwarded-For` held the sandbox's public address, listed twice. A container on the default bridge calling the host came from 172.17.0.2 |
| H11 | PASS | A server bound to 127.0.0.1:8003 answered through the proxy with peer 127.0.0.1. The control container reached 172.17.0.1:8001 (curl exit 0) and was refused at 172.17.0.1:8003 (curl exit 7) |
| H12 | RECORD | Behind `-p 127.0.0.1:8004:8004`, the containerized server saw proxy traffic from the bridge gateway 172.17.0.1. A second container calling it directly came from its own address, 172.17.0.3 |
| H8 | PASS | After 3 minutes idle: Neo4j 993 MiB, Postgres 23 MiB. VM memory used went from 280 MiB to 1,288 MiB with 2.6 GB still available |
| H9 | PASS | 502 through the proxy on 7474, 7687 and 5432. `ss` showed no listener on those ports on any address, and `docker port` showed no mapping for either database |
| H10 | PASS | The named spike containers and their anonymous volumes were removed by name, the echo processes stopped and the spike directory removed. All verification commands exited 0. The pulled images stay as a cache |

Two things the run turned up that the checks didn't ask about:

- The VM's own disk is 25 GB with 17 GB free, not the 100 GB account allowance. hosting.md now says so.
- The first runs failed on the harness, not on exe.dev. `pkill -f` matched the SSH shell that ran it, and a stray second copy of the runner removed the databases mid-measurement. Both are fixed in `run_checks.py`.
- Earlier versions of the cleanup ran a global `docker volume prune`. The VM was new and held nothing else, but the runner now removes only the spike's own containers and volumes by name.
- exe.dev's agent, Shelley, listens on 127.0.0.1:9999, inside the proxy's range.

## 4. What the results decide

- H5 passed for requests made with the owner's VM token. The proxy replaced every forged `X-ExeDev-*` header. That supports trusting the proxy's identity headers on a private VM. It says nothing yet about what a Web-only participant can reach, which is gate H13.
- H7 and H11 show the proxy connects over loopback, and a container on the bridge network can't open a connection to the host's loopback. So the edge runs in host network mode, listens on 127.0.0.1:8000 only, and passes identity only when the peer is 127.0.0.1. That rule can't be met by traffic from a bridge-network container. It does trust host processes, which hosting.md's threat model already covers. This replaces the bridge-address rule in hosting.md.
- The edge serves both apps by path on that one port rather than on three ports. Web shares may only reach one port, and an earlier exe.dev incident let them reach all of them ([exe.dev security note](https://exe.dev/security/over-sharing)). One port is correct either way, and H13 confirms which.
- H12 shows bridge mode would also work, since proxy traffic arrives from the gateway and containers come from their own addresses. We don't use it, because any host process reaching the published port also shows up as the gateway, and the loopback rule is simpler to test.
- H8 passed with room to spare. Neo4j sits under its 1.5 GB budget at idle, and Postgres is far below 300 MB. The budget in hosting.md stays, because load, n10s and SHACL will raise Neo4j's use. The phase 7 soak test is the real check.

The decision before the run, kept for the record:

## 4. What the results decide

- If H5 passes, the proxy is a trustworthy source of identity, and the edge rule in hosting.md section 5 stands.
- If H5 fails, the apps can't trust `X-ExeDev-Email` from the proxy, and identity moves to VM tokens with signed `ctx`, or to app sessions.
- If H7 shows proxy traffic arrives from an address no container can use, the edge tells them apart by peer address on the bridge network. If the addresses overlap, the edge runs in host network mode, as hosting.md already allows.
- If H8 fails, the memory budget in hosting.md section 2 changes before phase 2 starts.
