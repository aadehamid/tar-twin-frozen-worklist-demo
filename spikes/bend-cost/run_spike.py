"""Phase 0 spike 6: prove the cluster cost rules in Bend 2 and check Python agrees.

Checks, each recorded in results.json:
  B1  Bend 2.0.40 for linux-x64 is the pinned archive (sha256 from the release's install
      script), installed into the work folder with telemetry off.
  B2  The gate works both ways: LAWS.bend alone reports its laws open (SOME PROOFS FAIL),
      and PROOF.bend reports ALL PROOFS CHECK. Neither file uses @unsafe or ?TODO.
  B3  `bend PROOF.bend --verdict` rechecks the proofs with the BendTT kernel in Lean.
      Needs Lean 4.34.0 on PATH. Recorded as not run if Lean is missing, and doesn't fail
      the spike, because the plan made this kernel optional.
  B4  Bend's compiled JavaScript and the Python in cost.py give the same standalone and
      cluster cost on 5,000 seeded random clusters, and the proven saving holds on each.
  B5  Each seeded bug in cost.bend makes `bend PROOF.bend` fail, and the error names a proof.

Run from the repo root:
  python3 spikes/bend-cost/run_spike.py --work /tmp/bendrun
"""

import argparse
import hashlib
import json
import os
import pathlib
import platform
import random
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cost  # noqa: E402

VERSION = "2.0.40"
URL = f"https://github.com/bendlang/bend/releases/download/v{VERSION}/bend-{VERSION}-linux-x64.tar.gz"
SHA256 = "c9ff8d67bd903fb6ad9a26b43d8a62c01021de82a44d55ce4a3dcd4732113d6b"
SOURCES = ["nat.bend", "cost.bend", "LAWS.bend", "PROOF.bend"]

# Each bug changes one line of cost.bend's cluster function.
CLUSTER_LINE = "      Nat.add(Nat.add(h, own(t)), s)\n"
MUTANTS = [
    {"id": "B-M1", "what": "every item in the cluster pays the setup, as if done alone",
     "new": "      Nat.add(Nat.add(h, s), standalone(s, t))\n"},
    {"id": "B-M2", "what": "the shared setup is left out of the cluster",
     "new": "      Nat.add(h, own(t))\n"},
    {"id": "B-M3", "what": "the shared setup is counted twice",
     "new": "      Nat.add(Nat.add(Nat.add(h, own(t)), s), s)\n"},
    {"id": "B-M4", "what": "the first item's own cost is dropped",
     "new": "      Nat.add(own(t), s)\n"},
]

results = {"checks": {}, "runs": []}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def check(name, ok, **info):
    results["checks"][name] = {"pass": bool(ok), **info}
    log(f"{name} {'PASS' if ok else 'FAIL'} {json.dumps(info)[:300]}")
    return ok


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class Bend:
    def __init__(self, work):
        self.home = work / "bend-home"
        self.bin = self.home / "bin" / "bend"
        # HOME too, because bend builds and caches the Lean kernel under ~/.bend/bendtt.
        # ELAN_HOME, if set, still points at the Lean install.
        self.env = dict(os.environ, BEND_HOME=str(self.home), BEND_NO_TELEMETRY="1",
                        HOME=str(work / "home"))
        (work / "home").mkdir(exist_ok=True)
        if "ELAN_HOME" not in os.environ:
            self.env["ELAN_HOME"] = str(pathlib.Path.home() / ".elan")

    def run(self, label, cwd, *args, timeout=900):
        t0 = time.monotonic()
        try:
            p = subprocess.run([str(self.bin), *args], cwd=cwd, env=self.env, text=True,
                               capture_output=True, timeout=timeout)
            out, code = p.stdout + p.stderr, p.returncode
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            out, code = out + "\n[timeout]", -1
        secs = round(time.monotonic() - t0, 1)
        verdict = ("check" if "ALL PROOFS CHECK" in out else
                   "fail" if "SOME PROOFS FAIL" in out else "error")
        res = {"label": label, "args": list(args), "exit": code, "seconds": secs,
               "verdict": verdict, "locations": sorted(set(re.findall(r"^Location: (\S+)", out, re.M))),
               "tail": out.strip().splitlines()[-8:]}
        results["runs"].append(res)
        log(f"  {label}: {verdict} in {secs}s")
        return res


def install(work):
    tgz = work / "bend.tar.gz"
    with urllib.request.urlopen(URL, timeout=120) as r, open(tgz, "wb") as f:
        shutil.copyfileobj(r, f)
    ok = sha256(tgz) == SHA256
    if ok:
        with tarfile.open(tgz) as t:
            t.extractall(work, filter="data")
        b = Bend(work)
        (b.home / "bin").mkdir(parents=True)
        shutil.move(str(work / "bend" / "bin" / "bend"), b.bin)
        for d in ("bend2", "guide"):
            shutil.move(str(work / "bend" / d), b.home / d)
    return ok


def copy_sources(dest, cost_text=None):
    dest.mkdir(parents=True, exist_ok=True)
    for name in SOURCES:
        shutil.copy(HERE / name, dest / name)
    if cost_text is not None:
        (dest / "cost.bend").write_text(cost_text)
    return dest


def evaluate(b, d, cases):
    """Compile d/cost.bend to JavaScript and run it on the cases."""
    js = b.run("compile js", d, "cost.bend", "-o", "cost.mjs")
    p = subprocess.run(["node", str(HERE / "eval_bend.mjs"), str(d / "cost.mjs")],
                       input=json.dumps(cases), capture_output=True, text=True, timeout=300)
    ok = js["exit"] == 0 and p.returncode == 0
    return ok, json.loads(p.stdout) if ok else []


def false_laws(cases, got):
    """The laws in LAWS.bend that some case breaks, from Bend's own results."""
    bad = set()
    for (s, xs), (sa, cl, own, n) in zip(cases, got):
        if cl > sa:
            bad.add("never_more")
        if xs and cl != own + s:
            bad.add("shared_once")
        if xs and sa != cl + (n - 1) * s:
            bad.add("saving")
    return sorted(bad)


def run_all(work, a):
    ok = install(work)
    lean = shutil.which("lean")
    lean_v = subprocess.run(["lean", "--version"], capture_output=True, text=True).stdout.strip() if lean else None
    check("B1", ok, bend=VERSION, sha256_ok=ok, telemetry_off=True)
    results["inputs"] = {"bend": VERSION, "os": platform.platform(), "python": platform.python_version(),
                         "node": subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip(),
                         "lean": lean_v}
    if not ok:
        raise SystemExit("B1 failed")
    b = Bend(work)

    # B2. LAWS.bend alone leaves every law open; PROOF.bend closes them.
    src = copy_sources(work / "src")
    texts = "".join((HERE / n).read_text() for n in SOURCES)
    clean = "@unsafe" not in texts and "?TODO" not in texts and not re.search(r"\bdef \w+\?\(", texts)
    laws = b.run("laws open", src, "LAWS.bend")
    proof = b.run("proofs", src, "PROOF.bend")
    check("B2", clean and laws["verdict"] == "fail" and proof["verdict"] == "check" and proof["exit"] == 0,
          no_unsafe_or_todo=clean, laws_alone=laws["verdict"], proofs=proof["verdict"], seconds=proof["seconds"])

    # B3. The Lean kernel, if Lean is there.
    if lean:
        v = b.run("verdict", src, "PROOF.bend", "--verdict", timeout=1800)
        # The kernel has to say no on its own as well. bend2 rejects a bad cluster before the
        # kernel sees it, so the test edits the translation the kernel reads: the cluster
        # counts the setup twice and the proofs stay as they were.
        b.run("translate", src, "PROOF.bend", "-o", "PROOF.bendtt")
        kernels = sorted((work / "home" / ".bend" / "bendtt").glob("*/bendtt"))
        tt = (src / "PROOF.bendtt").read_text().splitlines(keepends=True)
        at = [n for n, l in enumerate(tt) if l.startswith("cost_3a_cluster :")]
        body = "(Nat.add (Nat.add x1 (cost_3a_own x2)) x0)"
        kernel_rejects = None
        if kernels and len(at) == 1 and tt[at[0] + 1].count(body) == 1:
            tt[at[0] + 1] = tt[at[0] + 1].replace(body, f"(Nat.add {body} x0)")
            (src / "bad.bendtt").write_text("".join(tt))
            k = subprocess.run([str(kernels[0]), "bad.bendtt"], cwd=src, capture_output=True, text=True, timeout=600)
            good = subprocess.run([str(kernels[0]), "PROOF.bendtt"], cwd=src, capture_output=True, text=True, timeout=600)
            kernel_rejects = ("SOME PROOFS FAIL" in k.stdout + k.stderr and k.returncode != 0
                              and "ALL PROOFS CHECK" in good.stdout and good.returncode == 0)
            results["runs"].append({"label": "kernel on tampered translation", "exit": k.returncode,
                                    "tail": (k.stdout + k.stderr).strip().splitlines()[-4:]})
        check("B3", v["verdict"] == "check" and kernel_rejects is True, ran=True, lean=lean_v,
              seconds=v["seconds"], kernel_rejects_tampered_cluster=kernel_rejects)
    else:
        results["checks"]["B3"] = {"pass": None, "ran": False, "reason": "lean 4.34.0 not on PATH"}
        log("B3 NOT RUN, lean not on PATH")

    # B4. Compile to JavaScript and compare with Python on seeded random clusters.
    rng = random.Random(a.seed)
    cases = [[rng.choice([0, 1, 8, 24, rng.randint(0, 400)]),
              [rng.randint(0, 2000) for _ in range(rng.choice([0, 1, 2, rng.randint(3, 40)]))]]
             for _ in range(a.cases)]
    js_ok, got = evaluate(b, src, cases)
    mism = [[s, xs, r] for (s, xs), r in zip(cases, got)
            if (r[0], r[1]) != (cost.standalone(s, xs), cost.cluster(s, xs))]
    broken = false_laws(cases, got)
    check("B4", js_ok and len(got) == len(cases) and not mism and not broken,
          cases=len(cases), seed=a.seed, mismatches=len(mism), laws_false_on_cases=broken,
          empty=sum(1 for c in cases if not c[1]), first_mismatch=mism[0] if mism else None)

    # B5. Seeded bugs.
    base = (HERE / "cost.bend").read_text()
    if base.count(CLUSTER_LINE) != 1:
        raise SystemExit("cost.bend changed: the cluster line isn't there exactly once")
    per = {}
    for m in MUTANTS:
        d = copy_sources(work / m["id"], base.replace(CLUSTER_LINE, m["new"]))
        r = b.run(m["id"], d, "PROOF.bend")
        # bend stops at the first proof that fails, so it names one law. Running the bugged
        # code on the same cases shows which laws the bug really makes false.
        js_ok, got = evaluate(b, d, cases)
        per[m["id"]] = {"what": m["what"], "verdict": r["verdict"], "failed_at": r["locations"],
                        "laws_false_on_cases": false_laws(cases, got) if js_ok else None}
    # A bug has to break a proof. Failing in the code itself, say because a value is used
    # twice, would mean the bug never reached the laws.
    proofs = set(re.findall(r"^def (\w+(?:\.\w+)*)\(", (HERE / "PROOF.bend").read_text(), re.M))
    check("B5", all(v["verdict"] == "fail" and v["failed_at"] and set(v["failed_at"]) <= proofs
                    and v["laws_false_on_cases"] for v in per.values()), mutants=per, proof_defs=sorted(proofs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=None)
    ap.add_argument("--cases", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=20261127)
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    root = pathlib.Path(a.work or tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="bend-spike-", dir=root))
    log(f"work dir {work}")
    t0 = time.monotonic()
    try:
        run_all(work, a)
    finally:
        results["total_seconds"] = round(time.monotonic() - t0, 1)
        (HERE / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)
    failed = [k for k, v in results["checks"].items() if v["pass"] is False]
    log(f"failed checks: {failed or 'none'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
