"""Phase 0 spike 5: model-check the freeze, sync, change and review workflow in Quint.

Runs in a new temporary folder (a child of --work if given) and deletes only that folder. It
installs Quint from npm and Apalache from its GitHub release, both checked against pinned
digests, runs checks Q1 to Q7 from docs/spikes/quint-worklist.md and writes results.json next to
this file. No Docker.
"""

import argparse
import hashlib
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPEC = ROOT / "specs" / "worklist.qnt"
sys.path.insert(0, str(HERE))
import mutants  # noqa: E402

QUINT = "0.34.0"
QUINT_INTEGRITY = "sha512-+lErYsupIixqctj52iu1ddw+0zQ5P9JUff66XjgNvxCVGht+SXT9OFuHVRbW5Wv25jYSe/A+w/lEar+Tu3SJbg=="
APALACHE = "0.62.4"
APALACHE_URL = f"https://github.com/apalache-mc/apalache/releases/download/v{APALACHE}/apalache.tgz"
# The digest GitHub records for the release asset apalache.tgz.
APALACHE_TGZ_SHA256 = "8ac8488422c30d552735bae11b92a2d014d8e02e8608702acc08f9a2d8a9abb2"

RULES = ["WorkflowOnly", "ReadOnlyMode", "BaselineFixed", "FreezeExact", "NothingMissed", "HumansDecide",
         "GrowthAddsUp", "Gate"]
WITNESSES = ["ObsOverlap", "ObsOverlapSameChange", "ObsStaleDrbExcluded", "ObsLateAddSynced", "ObsNegativeGrowth", "ObsStaleChangeBlocked",
             "ObsAiReviewed", "ObsReady", "ObsFrozenNotReadyWithGrowth",
             "ObsTwinRaisedSynced", "ObsReadOnlyGrowth"]
# The small instance TLC can search completely: one request, two hour values, two syncs.
SMALL = [("pure val ITEMS = Set(1, 2)", "pure val ITEMS = Set(1)"),
         ("pure val HOURS = Set(0, 4, 8)", "pure val HOURS = Set(0, 4)"),
         ("pure val MAX_SYNCS = 3", "pure val MAX_SYNCS = 2"),
         ("module worklist {", "module small {")]

results = {"inputs": {"quint": QUINT, "apalache": APALACHE}, "checks": {}, "runs": []}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def check(cid, ok, **evidence):
    results["checks"][cid] = {"pass": bool(ok), **evidence}
    log(f"{cid} {'PASS' if ok else 'FAIL'} {json.dumps(evidence, default=str)[:600]}")
    return ok


class Stop(Exception):
    pass


def small_instance(text):
    for old, new in SMALL:
        if text.count(old) != 1:
            raise ValueError(f"small instance: {old!r} found {text.count(old)} times")
        text = text.replace(old, new)
    return text


def outcome(out):
    """'ok', 'violation' or 'error' from quint's last status line."""
    if "[ok]" in out:
        return "ok"
    if "[violation]" in out:
        return "violation"
    return "error"


class Quint:
    def __init__(self, work):
        self.work = work
        self.env = dict(os.environ, HOME=str(work / "home"), npm_config_cache=str(work / "npm-cache"))
        self.bin = work / "q" / "node_modules" / ".bin" / "quint"

    def run(self, label, *args, timeout=1800):
        t0 = time.monotonic()
        try:
            p = subprocess.run([str(self.bin), *args], cwd=self.work, env=self.env, text=True,
                               capture_output=True, timeout=timeout)
            out, code = p.stdout + p.stderr, p.returncode
        except subprocess.TimeoutExpired as e:
            out, code = (e.stdout or "") + (e.stderr or "") + "\n[timeout]", -1
            out = out if isinstance(out, str) else out.decode()
        secs = round(time.monotonic() - t0, 1)
        res = {"label": label, "args": list(args), "exit": code, "seconds": secs,
               "outcome": outcome(out), "tail": out.strip().splitlines()[-6:]}
        m = re.search(r"([\d,]+) distinct states found, 0 states left on queue", out)
        if m:
            res["distinct_states"] = int(m.group(1).replace(",", ""))
        m = re.search(r"depth of the complete state graph search is (\d+)", out)
        if m:
            res["depth"] = int(m.group(1))
        states = re.findall(r"^State (\d+):", out, re.M)
        if states:
            res["trace_states"] = max(int(x) for x in states)
        results["runs"].append(res)
        log(f"  {label}: {res['outcome']} in {secs}s")
        return res


def setup(work):
    """Q1. Quint from npm and Apalache from GitHub, both checked against pinned digests."""
    (work / "q").mkdir()
    (work / "home" / ".quint").mkdir(parents=True)
    q = Quint(work)
    subprocess.run(["npm", "init", "-y"], cwd=work / "q", env=q.env, check=True, capture_output=True)
    subprocess.run(["npm", "install", "--no-audit", "--no-fund", f"@informalsystems/quint@{QUINT}"],
                   cwd=work / "q", env=q.env, check=True, capture_output=True)
    lock = json.loads((work / "q" / "package-lock.json").read_text())
    integrity = lock["packages"]["node_modules/@informalsystems/quint"]["integrity"]
    version = subprocess.run([str(q.bin), "--version"], env=q.env, text=True,
                             capture_output=True).stdout.strip()

    tgz = work / "apalache.tgz"
    with urllib.request.urlopen(APALACHE_URL, timeout=120) as r:
        tgz.write_bytes(r.read())
    tgz_sha = hashlib.sha256(tgz.read_bytes()).hexdigest()
    jar_sha = None
    if tgz_sha == APALACHE_TGZ_SHA256:
        dest = work / "home" / ".quint" / f"apalache-dist-{APALACHE}"
        dest.mkdir()
        with tarfile.open(tgz) as tf:
            tf.extractall(dest, filter="data")
        jar_sha = hashlib.sha256((dest / "apalache" / "lib" / "apalache.jar").read_bytes()).hexdigest()
    java = subprocess.run(["java", "-version"], text=True, capture_output=True).stderr.splitlines()[0]
    script = pathlib.Path(__file__).read_text()
    results["inputs"].update(java=java, os=platform.platform(), node=subprocess.run(
        ["node", "--version"], text=True, capture_output=True).stdout.strip(), apalache_jar_sha256=jar_sha)
    ok = check("Q1", integrity == QUINT_INTEGRITY and version == QUINT and tgz_sha == APALACHE_TGZ_SHA256
               and not re.search(r"[\"']" + "dock" + r"er[\"' ]", script)
               and shutil.which("dock" + "er") is None,
               quint_version=version, quint_integrity_ok=integrity == QUINT_INTEGRITY,
               apalache_tgz_sha256_ok=tgz_sha == APALACHE_TGZ_SHA256, java=java,
               docker_on_path=shutil.which("dock" + "er") is not None)
    if not ok:
        raise Stop("Q1 failed")
    return q


def stop_servers(work):
    """Stop the Apalache server quint started from this run's folder. It stays up otherwise."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            cmd = (pathlib.Path("/proc") / pid / "cmdline").read_bytes().replace(b"\0", b" ").decode()
        except OSError:
            continue
        if str(work) in cmd and "java" in cmd:
            try:
                os.kill(int(pid), 15)
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", help="parent folder for the run folder")
    ap.add_argument("--apalache-steps", type=int, default=10)
    ap.add_argument("--sim-samples", type=int, default=20000)
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    parent = pathlib.Path(a.work) if a.work else None
    if parent:
        parent.mkdir(parents=True, exist_ok=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="quint-spike-", dir=parent))
    log(f"work dir {work}")
    t0 = time.monotonic()
    try:
        run_all(work, a)
    except Stop as e:
        log(f"stopped: {e}")
    finally:
        results["total_seconds"] = round(time.monotonic() - t0, 1)
        (HERE / "results.json").write_text(json.dumps(results, indent=1, default=str) + "\n")
        failed = [k for k, v in results["checks"].items() if not v["pass"]]
        log(f"failed checks: {failed or 'none'}")
        stop_servers(work)
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)
    sys.exit(1 if failed or len(results["checks"]) < 7 else 0)


def ends_with_late_add(path):
    """The trace's last state has a frozen request in the baseline and a synced change event for
    a request that wasn't in the frozen copy, with a positive delta."""
    def m(v):
        return {int(k["#bigint"]): x for k, x in v["#map"]}
    def n(v):
        return int(v["#bigint"]) if isinstance(v, dict) else v
    states = json.loads(path.read_text()).get("states", [])
    if len(states) < 2:
        return False
    s = states[-1]
    base, copy, events, changes = m(s["tw_baseline"]), m(s["iw_copy"]), m(s["tw_events"]), m(s["iw_changes"])
    frozen_item = any(n(h) > 0 for h in base.values())
    late = any(n(events[c]) == 1 and n(ch["delta"]) > 0 and n(copy[n(ch["item"])]) == 0
               for c, ch in changes.items())
    return bool(s["tw_has_baseline"]) and frozen_item and late


def run_all(work, a):
    q = setup(work)
    text = SPEC.read_text()
    full = work / "worklist.qnt"
    full.write_text(text)
    small = work / "small.qnt"
    small.write_text(small_instance(text))
    steps = str(a.apalache_steps)
    sim = ["--max-samples", str(a.sim_samples), "--max-steps", "30"]

    # Q2. Both instances typecheck.
    t_full = q.run("typecheck full", "typecheck", str(full))
    t_small = q.run("typecheck small", "typecheck", str(small))
    if not check("Q2", t_full["exit"] == 0 and t_small["exit"] == 0):
        raise Stop("Q2 failed")

    # Q3. Apalache, every trace up to the step bound, full instance.
    r3 = q.run("apalache AllRules", "verify", str(full), "--invariant", "AllRules",
               "--max-steps", steps)
    check("Q3", r3["outcome"] == "ok", max_steps=a.apalache_steps, seconds=r3["seconds"])

    # Q4. TLC, the whole state space of the small instance. The full one is too big for TLC here.
    r4 = q.run("tlc AllRules small", "verify", str(small), "--invariant", "AllRules", "--backend", "tlc")
    check("Q4", r4["outcome"] == "ok" and r4.get("distinct_states", 0) > 0,
          small_states=r4.get("distinct_states"), small_depth=r4.get("depth"), small_seconds=r4["seconds"])

    # Q5. Random simulation of the full instance.
    r5 = q.run("simulate AllRules", "run", str(full), "--invariant", "AllRules", *sim)
    check("Q5", r5["outcome"] == "ok", samples=a.sim_samples, max_steps=30, seconds=r5["seconds"])

    # Q6. Every witness is reachable: TLC finds it in the small instance and the simulator in
    # the full one. The late-add trace is kept as the first replay example for phase 4.
    wit = {}
    for w in WITNESSES:
        t = q.run(f"tlc reach {w}", "verify", str(small), "--invariant", f"not({w})", "--backend", "tlc")
        s = q.run(f"simulate reach {w}", "run", str(full), "--invariant", f"not({w})", *sim)
        wit[w] = {"tlc_small": t["outcome"] == "violation", "simulator_full": s["outcome"] == "violation",
                  "tlc_trace_states": t.get("trace_states")}
    # The trace goes to a new file in the run folder, and is published only if this run
    # produced it and it ends where it should.
    fresh = work / "trace-late-add.itf.json"
    tr = q.run("trace late add", "run", str(full), "--invariant", "not(ObsLateAddWithFrozenItem)",
               "--out-itf", str(fresh), *sim)
    trace_ok = tr["outcome"] == "violation" and fresh.exists() and ends_with_late_add(fresh)
    itf = HERE / "trace-late-add.itf.json"
    if trace_ok:
        shutil.copy(fresh, itf)
    check("Q6", all(v["tlc_small"] and v["simulator_full"] for v in wit.values()) and trace_ok,
          witnesses=wit, late_add_trace=itf.name if trace_ok else None)

    # Q7. Every seeded bug breaks the rule it targets, and is caught by TLC on the small
    # instance and by Apalache on the full one.
    per = {}
    for m in mutants.MUTANTS:
        mt = mutants.apply(text, m)
        mf, ms = work / f"{m['id']}.qnt", work / f"{m['id']}-small.qnt"
        mf.write_text(mt.replace("module worklist {", "module " + m["id"].replace("-", "_") + " {"))
        ms.write_text(small_instance(mt).replace("module small {", "module " + m["id"].replace("-", "_") + "_small {"))
        tc = q.run(f"typecheck {m['id']}", "typecheck", str(mf))
        tl = q.run(f"tlc {m['id']}", "verify", str(ms), "--invariant", m["rule"], "--backend", "tlc")
        apl = q.run(f"apalache {m['id']}", "verify", str(mf), "--invariant", m["rule"], "--max-steps", steps)
        per[m["id"]] = {"rule": m["rule"], "what": m["what"], "typechecks": tc["exit"] == 0,
                        "tlc_small": tl["outcome"], "apalache_full": apl["outcome"],
                        "tlc_trace_states": tl.get("trace_states"), "apalache_seconds": apl["seconds"]}
    check("Q7", all(v["typechecks"] and v["tlc_small"] == "violation" and v["apalache_full"] == "violation"
                    for v in per.values()), mutants=per)


if __name__ == "__main__":
    main()
