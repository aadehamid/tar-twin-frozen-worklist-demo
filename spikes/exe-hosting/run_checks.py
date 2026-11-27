"""Run the exe.dev hosting spike checks H1 to H10 from the sandbox.

Usage: python run_checks.py <vm-name> <ssh-key> <expected-email>
Writes results.json next to this file. Exit code 1 if any check fails.
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

VM, KEY, EMAIL = sys.argv[1], sys.argv[2], sys.argv[3]
HOST = f"{VM}.exe.xyz"
HERE = os.path.dirname(os.path.abspath(__file__))
PORTS = [8000, 8001, 8002]
REMOTE_DIR = "/home/exedev/spike-exe-hosting"
LOG = f"{REMOTE_DIR}/echo.jsonl"
results = {}


def ssh(cmd, check=False):
    p = subprocess.run(["ssh", "-i", KEY, "-o", "BatchMode=yes", HOST, cmd],
                       capture_output=True, text=True, timeout=600)
    if check and p.returncode != 0:
        raise RuntimeError(f"ssh failed: {cmd}\n{p.stderr}")
    return p


def b64url(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def make_token():
    perms = json.dumps({"exp": int(time.time()) + 3600, "ctx": {"spike": "exe-hosting"}},
                       separators=(",", ":"))
    sig = subprocess.run(["ssh-keygen", "-Y", "sign", "-f", KEY, "-n", f"v0@{HOST}"],
                         input=perms, capture_output=True, text=True, check=True).stdout
    blob = "".join(sig.strip().splitlines()[1:-1])
    blob = b64url(base64.b64decode(blob))
    return f"exe0.{b64url(perms.encode())}.{blob}"


def get(port, headers=None, path="/"):
    req = urllib.request.Request(f"https://{HOST}:{port}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:  # connection refused, timeout
        return None, repr(e)


def remote_log():
    out = ssh(f"cat {LOG} 2>/dev/null").stdout
    return [json.loads(l) for l in out.splitlines() if l.strip()]


def hdrs(rec, name):
    return [v for k, v in rec["headers"] if k.lower() == name.lower()]


def record(cid, status, detail):
    results[cid] = {"status": status, "detail": detail}
    print(f"{cid} {status} {json.dumps(detail)[:300]}")


# Setup: copy echo server and start it.
ssh(f"mkdir -p {REMOTE_DIR} && rm -f {LOG}", check=True)
subprocess.run(["scp", "-q", "-i", KEY, os.path.join(HERE, "echo.py"), f"{HOST}:{REMOTE_DIR}/echo.py"], check=True)
ssh("pkill -f '[s]pike-exe-hosting/echo.py'")  # own call: the kill pattern must not match this shell
ssh(f"setsid nohup python3 {REMOTE_DIR}/echo.py {LOG} "
    f"{' '.join(map(str, PORTS))} >/dev/null 2>&1 < /dev/null & sleep 3; ss -tln | grep -c ':800[012] '", check=True)

try:
    # H1
    p1 = ssh("docker run --rm hello-world >/dev/null && echo RUN_OK; docker compose version --short")
    ok = "RUN_OK" in p1.stdout and p1.stdout.strip().splitlines()[-1].startswith("2.")
    record("H1", "PASS" if ok else "FAIL", {"out": p1.stdout.strip(), "err": p1.stderr.strip()[-200:]})

    token = make_token()
    auth = {"X-Exedev-Authorization": f"Bearer {token}"}

    # H3 first, so the log holds no authenticated requests yet.
    h3 = {}
    for port in PORTS:
        h3[port] = get(port)[0]
    time.sleep(1)
    leaked = [r for r in remote_log() if not hdrs(r, "X-ExeDev-Email")]
    ok = all(s == 401 for s in h3.values()) and not leaked
    record("H3", "PASS" if ok else "FAIL", {"status": h3, "requests_reaching_server": len(leaked)})

    # H2 and H4, H6 from the same requests.
    h2, recs = {}, {}
    for port in PORTS:
        s, body = get(port, auth, path=f"/h2?port={port}")
        h2[port] = s
        recs[port] = json.loads(body) if s == 200 else None
    ok = all(h2[p] == 200 and recs[p] and recs[p]["port"] == p for p in PORTS)
    record("H2", "PASS" if ok else "FAIL", {"status": h2})

    good = [r for r in recs.values() if r]
    emails = [hdrs(r, "X-ExeDev-Email") for r in good]
    uids = [hdrs(r, "X-ExeDev-UserID") for r in good]
    ok = bool(good) and all(e == [EMAIL] for e in emails) and all(len(u) == 1 and u[0] for u in uids)
    record("H4", "PASS" if ok else "FAIL", {"emails": emails, "userids": uids,
            "ctx": [hdrs(r, "X-ExeDev-Token-Ctx") for r in good]})

    tok_seen = [hdrs(r, "X-Exedev-Authorization") + hdrs(r, "Authorization") for r in good]
    ok = bool(good) and all(not t for t in tok_seen)
    record("H6", "PASS" if ok else "FAIL", {"token_headers_seen": tok_seen})

    # H5 forged headers.
    forged = dict(auth)
    forged.update({"X-ExeDev-Email": "forged@example.com", "X-ExeDev-UserID": "usr_forged",
                   "X-ExeDev-Token-Ctx": "forged"})
    h5 = {}
    for port in PORTS:
        s, body = get(port, forged, path="/h5")
        r = json.loads(body) if s == 200 else None
        h5[port] = {"status": s,
                    "email": hdrs(r, "X-ExeDev-Email") if r else None,
                    "userid": hdrs(r, "X-ExeDev-UserID") if r else None,
                    "ctx": hdrs(r, "X-ExeDev-Token-Ctx") if r else None,
                    "any_forged": any("forged" in v for _, v in r["headers"]) if r else None}
    ok = all(v["status"] == 200 and v["email"] == [EMAIL] and not v["any_forged"] for v in h5.values())
    record("H5", "PASS" if ok else "FAIL", h5)

    # H7 source addresses.
    for port in PORTS:
        for _ in range(5):
            get(port, auth, path="/h7")
    time.sleep(1)
    proxy = [r for r in remote_log() if r["path"] == "/h7"]
    peers = sorted({r["peer"] for r in proxy})
    xff = sorted({v for r in proxy for v in hdrs(r, "X-Forwarded-For")})
    c = ssh("docker run --rm --entrypoint sh curlimages/curl -c "
            "'curl -s http://172.17.0.1:8001/h7-container'")
    cpeer = json.loads(c.stdout)["peer"] if c.returncode == 0 and c.stdout.startswith("{") else c.stderr[-200:]
    vm_addrs = ssh("ip -4 -o addr show | awk '{print $2, $4}'").stdout.strip().splitlines()
    record("H7", "RECORD", {"proxy_peers": peers, "x_forwarded_for": xff,
                            "container_peer": cpeer, "vm_addresses": vm_addrs,
                            "overlap": cpeer in peers})

    # H11 loopback-only listener.
    ssh(f"setsid nohup python3 {REMOTE_DIR}/echo.py {LOG}.lo 8003 --bind 127.0.0.1 >/dev/null 2>&1 < /dev/null & sleep 3")
    s11, b11 = get(8003, auth, path="/h11")
    peer11 = json.loads(b11)["peer"] if s11 == 200 else None
    c11 = ssh("docker run --rm --entrypoint sh curlimages/curl -c "
              "'curl -s -m 5 -o /dev/null -w %{http_code} http://172.17.0.1:8003/; echo \" rc=$?\"'")
    container_blocked = "rc=0" not in c11.stdout
    ok = s11 == 200 and peer11 == "127.0.0.1" and container_blocked
    record("H11", "PASS" if ok else "FAIL", {"proxy_status": s11, "proxy_peer": peer11,
                                             "container_attempt": c11.stdout.strip()})

    # H12 peer behind a published port, echo inside a container.
    ssh(f"docker rm -f spike-echo >/dev/null 2>&1; docker run -d --name spike-echo -p 127.0.0.1:8004:8004 "
        f"-v {REMOTE_DIR}:/s:ro python:3.12-slim python3 /s/echo.py /tmp/e.jsonl 8004 >/dev/null; sleep 4", check=True)
    s12, b12 = get(8004, auth, path="/h12")
    peer12 = json.loads(b12)["peer"] if s12 == 200 else b12[:200]
    eip = ssh("docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' spike-echo").stdout.strip()
    c12 = ssh(f"docker run --rm --entrypoint sh curlimages/curl -c 'curl -s -m 5 http://{eip}:8004/h12c'")
    cpeer12 = json.loads(c12.stdout)["peer"] if c12.stdout.startswith("{") else c12.stdout[:200]
    record("H12", "RECORD", {"proxy_status": s12, "proxy_peer_in_container": peer12,
                             "container_to_container_peer": cpeer12, "echo_container_ip": eip,
                             "overlap": peer12 == cpeer12, "complete": bool(eip) and cpeer12.count(".") == 3})
    ssh("docker rm -f spike-echo >/dev/null 2>&1; true")

    # H8 idle memory.
    free_before = ssh("free -m").stdout
    ssh("docker rm -f spike-neo4j spike-pg >/dev/null 2>&1; "
        "docker run -d --name spike-neo4j -e NEO4J_AUTH=neo4j/spike-password-123 "
        "-e NEO4J_server_memory_heap_initial__size=768m -e NEO4J_server_memory_heap_max__size=768m "
        "-e NEO4J_server_memory_pagecache_size=384m neo4j:5-community >/dev/null && "
        "docker run -d --name spike-pg -e POSTGRES_PASSWORD=spike postgres:16 "
        "-c shared_buffers=128MB >/dev/null", check=True)
    ready = ssh("for i in $(seq 1 60); do docker logs spike-neo4j 2>&1 | grep -q Started && "
                "docker exec spike-pg pg_isready -q && echo READY && break; sleep 3; done").stdout
    time.sleep(180)
    stats = ssh("docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' spike-neo4j spike-pg").stdout
    free_after = ssh("free -m").stdout

    def mib(name):
        for line in stats.splitlines():
            if line.startswith(name):
                v = line.split()[1]
                n = float(v[:-3])
                return n * 1024 if v.endswith("GiB") else n
        return None

    neo, pg = mib("spike-neo4j"), mib("spike-pg")
    ok = "READY" in ready and neo is not None and pg is not None and neo <= 1536 and pg <= 300
    record("H8", "PASS" if ok else "FAIL", {"neo4j_mib": neo, "postgres_mib": pg, "ready": "READY" in ready,
                                            "free_before": free_before, "free_after": free_after})

    # H9 database ports closed.
    p7474 = get(7474, auth)
    p5432 = get(5432, auth)
    listeners = ssh("ss -tln | awk '{print $4}' | grep -E '^(0\\.0\\.0\\.0|\\[::\\]|\\*):(7474|7687|5432)$' || true").stdout.strip()
    neo_reached = p7474[0] == 200 and "neo4j" in p7474[1].lower()
    ok = not neo_reached and p5432[0] != 200 and not listeners
    record("H9", "PASS" if ok else "FAIL", {"proxy_7474": p7474[0], "proxy_5432": p5432[0],
                                            "open_listeners": listeners})
finally:
    # H10 cleanup.
    ssh("docker rm -f spike-neo4j spike-pg spike-echo >/dev/null 2>&1; docker volume prune -f >/dev/null; "
        "docker image rm hello-world >/dev/null 2>&1; rm -rf ~/spike-exe-hosting; true")
    ssh("pkill -f '[s]pike-exe-hosting/echo.py'")
    left = ssh("docker ps -aq --filter name=spike-; docker volume ls -q; pgrep -f '[s]pike-exe-hosting/echo.py'").stdout.strip()
    record("H10", "PASS" if not left else "FAIL", {"leftover": left})
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=2)

sys.exit(1 if any(v["status"] == "FAIL" for v in results.values()) else 0)
