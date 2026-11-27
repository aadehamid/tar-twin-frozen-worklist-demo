"""Run the full-stack FastAPI template's CI steps with no Docker, and record checks T1 to T11.

    python3 run_spike.py [--keep] [--work DIR] [--repeats N]

The run happens in a new folder. With --work it's a new child of DIR, otherwise a new folder
under the system temp dir. Only that new folder is deleted at the end.

Needs git, uv, curl, Postgres 18 binaries and network access. Writes results.json next to this
file and exits non-zero if any check fails. See docs/spikes/template-no-docker.md.
"""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import checks  # noqa: E402

TEMPLATE = "https://github.com/fastapi/full-stack-fastapi-template"
PIN = "f8c6c147b12bb1c4d3253cc1b06f8b5ef81b10dd"
BUN = "1.3.12"
MAILPIT = "1.34.0"
# SHA-256 GitHub records for mailpit-linux-amd64.tar.gz in release v1.34.0, read 2026-11-27.
MAILPIT_SHA256 = "af236b42f171b1c74f0ac5ff444f44d36f2f2ecc0134f5a2f1d4e307e56a0d2c"
PG_BIN = Path(os.environ.get("PG_BIN", "/usr/lib/postgresql/18/bin"))
PG_PORT = 55432
PG_PASSWORD = "changethis"
SUPERUSER = "admin@example.com"
SUPERUSER_PASSWORD = "changethis"

results = {"template": {"repo": TEMPLATE, "commit": PIN}, "checks": {}, "steps": {}}
procs = []
REPEATS = 0
# The reset spec's two tests that call signUpNewUser and then wait for the reset email.
SIGNUP_TESTS = ("reset-password.spec.ts › User can reset password successfully using the link",
                "reset-password.spec.ts › Weak new password validation")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def check(cid, ok, **evidence):
    results["checks"][cid] = {"pass": bool(ok), **evidence}
    log(f"{cid} {'PASS' if ok else 'FAIL'} {json.dumps(evidence)[:300]}")


def run(name, args, cwd, env=None, timeout=1800):
    """Run a step, log its output to logs/<name>.log, and record exit code and time."""
    t = time.monotonic()
    p = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    secs = round(time.monotonic() - t, 1)
    out = p.stdout + p.stderr
    (LOGS / f"{name}.log").write_text(out)
    results["steps"][name] = {"exit": p.returncode, "seconds": secs}
    log(f"step {name}: exit {p.returncode} in {secs}s")
    return p.returncode, out


def start(name, args, cwd, env=None):
    f = open(LOGS / f"{name}.log", "w")
    p = subprocess.Popen(args, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT,
                         start_new_session=True)
    procs.append(p)
    return p


def wait_for(fn, seconds):
    end = time.monotonic() + seconds
    t0 = time.monotonic()
    while time.monotonic() < end:
        try:
            if fn():
                return round(time.monotonic() - t0, 1)
        except Exception:
            pass
        time.sleep(0.5)
    return None


def http(method, url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read().decode()


def fetch(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def published_sha(sums_url, name):
    for line in fetch(sums_url).decode().splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0]
    raise ValueError(f"{name} not in {sums_url}")


def tree_rss_kb(pid):
    """Resident memory of a process and all its descendants, from /proc."""
    children = {}
    for d in Path("/proc").iterdir():
        if d.name.isdigit():
            try:
                fields = (d / "stat").read_text().rsplit(")", 1)[1].split()
                children.setdefault(int(fields[1]), []).append(int(d.name))
            except OSError:
                pass
    total, stack = 0, [pid]
    while stack:
        p = stack.pop()
        try:
            for line in Path(f"/proc/{p}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1])
        except OSError:
            pass
        stack.extend(children.get(p, []))
    return total


def main():
    global LOGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--work")
    ap.add_argument("--repeats", type=int, default=20,
                    help="repeats of the reset spec for T11, 0 to skip")
    a = ap.parse_args()
    global REPEATS
    REPEATS = a.repeats
    parent = None
    if a.work:
        parent = Path(a.work)
        parent.mkdir(parents=True, exist_ok=True)
    # A fresh folder the script owns, so cleanup can never remove anything it didn't create.
    work = Path(tempfile.mkdtemp(prefix="tpl-spike-", dir=parent))
    LOGS = work / "logs"
    LOGS.mkdir(exist_ok=True)
    tools = work / "tools"
    tools.mkdir(exist_ok=True)
    src = work / "template"
    log(f"work dir {work}")
    t_all = time.monotonic()
    try:
        _run_all(work, tools, src)
    except RuntimeError as e:  # a failed precondition, already recorded as a failed check
        results["stopped"] = str(e)
        log(f"stopped: {e}")
    finally:
        for p in reversed(procs):
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
        subprocess.run([str(PG_BIN / "pg_ctl"), "-D", str(work / "pgdata"), "-m", "fast", "stop"],
                       capture_output=True)
        results["total_seconds"] = round(time.monotonic() - t_all, 1)
        (HERE / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)
    failed = [k for k, v in results["checks"].items() if not v["pass"]]
    log(f"failed checks: {failed or 'none'}")
    sys.exit(1 if failed or "stopped" in results else 0)


def _serve_checks(base, ev):
    s, page = http("GET", f"{base}/")
    ev["root_status"] = s
    ev["root_has_app"] = '<div id="root">' in page and "<script" in page
    form = f"username={SUPERUSER}&password={SUPERUSER_PASSWORD}".replace("@", "%40").encode()
    s, body = http("POST", f"{base}/api/v1/login/access-token", form,
                   {"Content-Type": "application/x-www-form-urlencoded"})
    token = json.loads(body).get("access_token", "")
    s, me = http("GET", f"{base}/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    ev["me"] = json.loads(me).get("email")
    return ev["root_status"] == 200 and ev["root_has_app"] and bool(token) and ev["me"] == SUPERUSER


def _run_all(work, tools, src):
    # T1. The scan is the same one test_checks.py runs.
    hits = checks.docker_commands(Path(__file__).read_text())
    check("T1", hits == [], docker_commands=hits, docker_on_path=shutil.which("docker") is not None)

    # T2. Pinned template and tools.
    src.mkdir()
    run("clone_init", ["git", "init", "-q"], src)
    run("clone_fetch", ["git", "fetch", "-q", "--depth", "1", TEMPLATE, PIN], src)
    run("clone_checkout", ["git", "checkout", "-q", "FETCH_HEAD"], src)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src, capture_output=True,
                          text=True).stdout.strip()
    if head != PIN:
        check("T2", False, commit=head, reason="template checkout is not at the pinned commit")
        raise RuntimeError("T2 failed, stopping before running any template code")
    rel = f"https://github.com/oven-sh/bun/releases/download/bun-v{BUN}"
    bun_zip = fetch(f"{rel}/bun-linux-x64.zip")
    bun_ok = hashlib.sha256(bun_zip).hexdigest() == published_sha(f"{rel}/SHASUMS256.txt",
                                                                 "bun-linux-x64.zip")
    if not bun_ok:
        check("T2", False, commit=head, bun_sha256_ok=False, reason="bun hash mismatch")
        raise RuntimeError("T2 failed, stopping before unpacking bun")
    (tools / "bun.zip").write_bytes(bun_zip)
    with zipfile.ZipFile(tools / "bun.zip") as z:
        (tools / "bun").write_bytes(z.read("bun-linux-x64/bun"))
    (tools / "bun").chmod(0o755)
    (tools / "bunx").unlink(missing_ok=True)
    (tools / "bunx").symlink_to(tools / "bun")
    rel = f"https://github.com/axllent/mailpit/releases/download/v{MAILPIT}"
    mp_tgz = fetch(f"{rel}/mailpit-linux-amd64.tar.gz")
    # Mailpit publishes no checksum file. GitHub records a SHA-256 for each release asset. The
    # script pins it, and cross-checks the pin against the API when the API answers. The
    # unauthenticated API allows 60 calls an hour, so it can't be the check itself.
    mp_ok = hashlib.sha256(mp_tgz).hexdigest() == MAILPIT_SHA256
    try:
        api = json.loads(fetch(f"https://api.github.com/repos/axllent/mailpit/releases/tags/v{MAILPIT}"))
        digest = next(x["digest"] for x in api["assets"] if x["name"] == "mailpit-linux-amd64.tar.gz")
        mp_api = "agrees" if digest == f"sha256:{MAILPIT_SHA256}" else f"differs: {digest}"
        mp_ok = mp_ok and mp_api == "agrees"
    except Exception as e:
        mp_api = f"unavailable ({type(e).__name__})"
    if not mp_ok:
        check("T2", False, commit=head, bun_sha256_ok=bun_ok, mailpit_sha256_ok=False,
              mailpit_api_digest=mp_api, reason="Mailpit hash mismatch")
        raise RuntimeError("T2 failed, stopping before unpacking Mailpit")
    (tools / "mailpit.tgz").write_bytes(mp_tgz)
    subprocess.run(["tar", "xzf", "mailpit.tgz", "mailpit"], cwd=tools, check=True)

    env = dict(os.environ)
    env["PATH"] = f"{tools}:{env['PATH']}"
    env.pop("VIRTUAL_ENV", None)

    def version(args):
        p = subprocess.run(args, capture_output=True, text=True, env=env)
        return (p.stdout or p.stderr).strip().splitlines()[0] if (p.stdout or p.stderr) else ""

    versions = {"uv": version(["uv", "--version"]), "bun": version(["bun", "--version"]),
                "postgres": version([str(PG_BIN / "postgres"), "--version"]),
                "mailpit": version([str(tools / "mailpit"), "version"]),
                "os": platform.platform()}
    check("T2", head == PIN and bun_ok and mp_ok, commit=head, bun_sha256_ok=bun_ok,
          mailpit_sha256_ok=mp_ok, mailpit_api_digest=mp_api, versions=versions)

    # T3. Postgres in a temporary folder, and Mailpit.
    pwfile = work / "pw"
    pwfile.write_text(PG_PASSWORD + "\n")
    sock = work / "pgsock"
    sock.mkdir()
    run("initdb", [str(PG_BIN / "initdb"), "-D", str(work / "pgdata"), "-U", "postgres",
                   "--auth=scram-sha-256", f"--pwfile={pwfile}"], work)
    run("pg_start", [str(PG_BIN / "pg_ctl"), "-D", str(work / "pgdata"), "-l",
                     str(LOGS / "postgres.log"), "-o",
                     f"-p {PG_PORT} -k {sock} -c listen_addresses=localhost", "start"], work)
    t = time.monotonic()
    pg_up = wait_for(lambda: subprocess.run(
        [str(PG_BIN / "pg_isready"), "-h", "localhost", "-p", str(PG_PORT)],
        capture_output=True).returncode == 0, 30)
    pg_env = dict(env, PGPASSWORD=PG_PASSWORD)
    run("createdb", [str(PG_BIN / "createdb"), "-h", "localhost", "-p", str(PG_PORT),
                     "-U", "postgres", "app"], work, env=pg_env)
    mailpit = start("mailpit", [str(tools / "mailpit"), "--smtp", "127.0.0.1:1025",
                                "--listen", "127.0.0.1:8025"], work, env=env)
    mp_up = wait_for(lambda: http("GET", "http://127.0.0.1:8025/livez")[0] == 200, 30)
    check("T3", pg_up is not None and mp_up is not None, postgres_ready_s=pg_up,
          mailpit_ready_s=mp_up, started_in_s=round(time.monotonic() - t, 1))

    # The template's .env, pointed at the local Postgres.
    dotenv = (src / ".env").read_text()
    url = f"postgresql://postgres:{PG_PASSWORD}@localhost:{PG_PORT}/app"
    dotenv, n = re.subn(r"^DATABASE_URL=.*$", f"DATABASE_URL={url}", dotenv, flags=re.M)
    if n != 1:
        raise RuntimeError("template .env has no single DATABASE_URL line")
    (src / ".env").write_text(dotenv)

    be = src / "backend"
    run("uv_sync", ["uv", "sync"], be, env=env)
    _, py = run("python_version", ["uv", "run", "python", "--version"], be, env=env)
    results["checks"]["T2"]["versions"]["python"] = next(
        (ln for ln in py.splitlines() if ln.startswith("Python ")), py.strip())

    def psql(sql):
        p = subprocess.run([str(PG_BIN / "psql"), "-h", "localhost", "-p", str(PG_PORT), "-U",
                            "postgres", "-d", "app", "-At", "-c", sql], capture_output=True,
                           text=True, env=pg_env)
        return p.stdout.strip().splitlines()

    # T4. Migrations and the first superuser, run twice.
    c1, _ = run("prestart_1", ["uv", "run", "bash", "scripts/prestart.sh"], be, env=env)
    tables = sorted(psql("select tablename from pg_tables where schemaname = 'public'"))

    def alembic(cmd):
        _, out = run(f"alembic_{cmd}", ["uv", "run", "alembic", cmd], be, env=env)
        return sorted(set(re.findall(r"\b([0-9a-f]{12})\b", out)))

    current, heads = alembic("current"), alembic("heads")
    users_1 = psql('select email, is_superuser from "user" order by email')
    c2, _ = run("prestart_2", ["uv", "run", "bash", "scripts/prestart.sh"], be, env=env)
    users_2 = psql('select email, is_superuser from "user" order by email')
    check("T4", c1 == 0 and c2 == 0 and {"user", "item"} <= set(tables) and current == heads
          and current != [] and users_1 == [f"{SUPERUSER}|t"] and users_2 == users_1,
          tables=tables, alembic_current=current, alembic_heads=heads, users=users_2)

    # T5. Lint.
    c, out = run("lint", ["uv", "run", "bash", "scripts/lint.sh"], be, env=env)
    check("T5", c == 0, exit=c, tail=out.strip().splitlines()[-3:])

    # T6. Backend tests with the template's coverage gate.
    c, out = run("tests", ["uv", "run", "bash", "scripts/tests-start.sh", "spike"], be, env=env)
    try:
        counts, cover = checks.pytest_summary(out), checks.coverage_total(out)
    except ValueError as e:
        counts, cover = {"parse_error": str(e)}, None
    check("T6", c == 0 and counts.get("failed") == 0 and counts.get("errors") == 0
          and counts.get("passed", 0) > 0 and cover is not None and cover >= 90,
          exit=c, counts=counts, coverage=cover)

    # T7. Client generation leaves the committed client alone, and the build works.
    fe = src / "frontend"
    c_ci, _ = run("bun_ci", ["bun", "ci"], fe, env=env)
    c_gen, _ = run("generate_client", ["bash", "scripts/generate-client.sh"], src, env=env)
    client_diff = subprocess.run(["git", "status", "--porcelain", "--", "frontend/src/client"],
                                 cwd=src, capture_output=True, text=True).stdout.splitlines()
    other_diff = subprocess.run(["git", "status", "--porcelain"], cwd=src, capture_output=True,
                                text=True).stdout.splitlines()
    c_build, _ = run("build", ["bun", "run", "build"], fe, env=env)
    built = (be / "app" / "frontend" / "index.html").exists()
    check("T7", c_ci == 0 and c_gen == 0 and client_diff == [] and c_build == 0 and built,
          bun_ci=c_ci, generate_client=c_gen, client_changes=client_diff, build=c_build,
          index_html=built, all_changes=other_diff)

    # The template's test fixture deletes every user when the tests end, superuser included.
    # Its CI runs Playwright in a separate job on a fresh database, so do the same here.
    users_after_tests = psql('select count(*) from "user"')
    run("dropdb", [str(PG_BIN / "dropdb"), "-h", "localhost", "-p", str(PG_PORT), "-U",
                   "postgres", "app"], work, env=pg_env)
    run("createdb_2", [str(PG_BIN / "createdb"), "-h", "localhost", "-p", str(PG_PORT), "-U",
                       "postgres", "app"], work, env=pg_env)
    c3, _ = run("prestart_3", ["uv", "run", "bash", "scripts/prestart.sh"], be, env=env)
    results["fresh_database_for_e2e"] = {"users_left_by_tests": users_after_tests,
                                         "prestart_exit": c3,
                                         "users": psql('select email from "user"')}

    # T8. Serve the API and the built front end.
    backend = start("backend", ["uv", "run", "fastapi", "run", "--port", "8000"], be, env=env)
    base = "http://localhost:8000"
    t_up = wait_for(lambda: http("GET", f"{base}/api/v1/utils/health-check/")[1].strip() == "true",
                    20)
    ok = t_up is not None
    ev = {"ready_s": t_up}
    try:
        ok = ok and _serve_checks(base, ev)
    except Exception as e:  # an HTTP error is a failed check, not a crash
        ev["error"] = f"{type(e).__name__}: {e}"
        ok = False
    check("T8", ok, **ev)

    # T9. The template's Playwright suite against the served app.
    run("playwright_install", ["bunx", "playwright", "install", "chromium"], fe, env=env)
    pw_env = dict(env, CI="1", PLAYWRIGHT_BASE_URL=base, VITE_API_URL=base,
                  MAILPIT_HOST="http://localhost:8025", FIRST_SUPERUSER=SUPERUSER,
                  FIRST_SUPERUSER_PASSWORD=SUPERUSER_PASSWORD)
    c, out = run("playwright", ["bunx", "playwright", "test", "--fail-on-flaky-tests",
                                "--reporter=list"], fe, env=pw_env)
    try:
        pw = checks.playwright_summary(out)
    except ValueError as e:
        pw = {"parse_error": str(e)}
    try:
        total = checks.running_total(out)
    except ValueError:
        total = None
    per_test = checks.test_results(out)
    signup = {k: per_test.get(k) for k in SIGNUP_TESTS}
    # Every test ran and passed first time, and both tests that read Mailpit after a signup
    # are among them.
    check("T9", c == 0 and total is not None and pw.get("passed") == total
          and pw.get("failed") == 0 and pw.get("flaky") == 0 and pw.get("skipped") == 0
          and pw.get("did_not_run") == 0
          and all(v == {"passed": 1, "failed": 0, "skipped": 0} for v in signup.values()),
          exit=c, total=total, counts=pw, signup_tests=signup,
          seconds=results["steps"]["playwright"]["seconds"])

    # T11. The signup race behind the flaky reset test. Run the reset spec many times without
    # retries, first as the template has it, then with signUpNewUser waiting for the signup
    # response before it navigates away.
    if REPEATS:
        helper = fe / "tests" / "utils" / "user.ts"
        original = helper.read_text()
        old = '  await page.getByRole("button", { name: "Sign Up" }).click()\n  await page.goto("/login")\n'
        new = ('  const signedUp = page.waitForResponse(\n'
               '    (r) => r.url().includes("/api/v1/users/signup") && r.request().method() === "POST",\n'
               '  )\n'
               '  await page.getByRole("button", { name: "Sign Up" }).click()\n'
               '  if (!(await signedUp).ok()) throw new Error("signup request failed")\n'
               '  await page.goto("/login")\n')
        if original.count(old) != 1:
            raise RuntimeError("signUpNewUser no longer has the expected click-then-goto lines")
        race = {}
        for label, text in (("as_is", original), ("patched", original.replace(old, new))):
            helper.write_text(text)
            c, out = run(f"race_{label}", ["bunx", "playwright", "test", "tests/reset-password.spec.ts",
                                           f"--repeat-each={REPEATS}", "--retries=0",
                                           "--reporter=list"], fe, env=pw_env)
            arm = {"exit": c}
            try:
                arm["counts"] = checks.playwright_summary(out)
                arm["total"] = checks.running_total(out)
            except ValueError as e:
                arm["parse_error"] = str(e)
            per_test = checks.test_results(out)
            arm["signup_tests"] = {k: per_test.get(k) for k in SIGNUP_TESTS}
            race[label] = arm
        helper.write_text(original)
        p = race["patched"]
        n = p.get("counts", {})
        # The patched arm ran every repeat, with no skips, and each signup test passed every time.
        check("T11", p["exit"] == 0 and p.get("total") is not None and n.get("passed") == p["total"]
              and n.get("failed") == 0 and n.get("skipped") == 0 and n.get("did_not_run") == 0
              and all(v == {"passed": REPEATS, "failed": 0, "skipped": 0}
                      for v in p["signup_tests"].values()),
              repeats=REPEATS, **race)

    # T10. Footprint, recorded only.
    pg_pid = int((work / "pgdata" / "postmaster.pid").read_text().split()[0])
    check("T10", True, rss_mb={
        "postgres": round(tree_rss_kb(pg_pid) / 1024, 1),
        "mailpit": round(tree_rss_kb(mailpit.pid) / 1024, 1),
        "backend": round(tree_rss_kb(backend.pid) / 1024, 1)},
        step_seconds={k: v["seconds"] for k, v in results["steps"].items()})


if __name__ == "__main__":
    main()
