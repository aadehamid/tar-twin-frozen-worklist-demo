"""Run SHACL shapes through n10s on a Neo4j started from the release tarball, and record
checks N1 to N8. See docs/spikes/shacl-n10s.md.

    uv run --no-project --with neo4j --with pyshacl --with rdflib python run_spike.py \\
        [--keep] [--work DIR] [--dexpi-python PATH]

--dexpi-python is a Python with pyDEXPI 2.1.0, used to export the test graph from the DEXPI
sheet with spikes/relate-wasm/export_cypher.py. Needs Java 21, curl and network access.
The run happens in a new folder, a new child of DIR when --work is given, and only that
folder is deleted at the end. Writes results.json next to this file.
"""

import argparse
import hashlib
import json
import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lib  # noqa: E402
import mutants  # noqa: E402

NEO4J = "5.26.34"
NEO4J_URL = f"https://dist.neo4j.org/neo4j-community-{NEO4J}-unix.tar.gz"
# Published at NEO4J_URL + ".sha256", read 2026-11-27.
NEO4J_SHA256 = "a7dff070b505b1df7508df50b13bf15fe523cf7e0d2e344618e88be61b01a9eb"
N10S = "5.26.0"
N10S_URL = (f"https://github.com/neo4j-labs/neosemantics/releases/download/{N10S}/"
            f"neosemantics-{N10S}.jar")
# The digest GitHub records for the release asset, read 2026-11-27 with gh api.
N10S_SHA256 = "509bec192befce6224a7e3bf78a0e6b74aeb8bf61eb7a1e009b7b62e0737900b"
BOLT, HTTP = 57687, 57474
PASSWORD = "spike-only-password"
SHAPES = (HERE / "shapes.ttl").read_text()
RELATE = HERE.parent / "relate-wasm"
TRIGGER = ("CALL n10s.validation.shacl.validateTransaction($createdNodes, $createdRelationships, "
           "$assignedLabels, $removedLabels, $assignedNodeProperties, $removedNodeProperties, "
           "$deletedRelationships, $deletedNodes)")
# Constraint predicates in shapes.ttl and the param name n10s lists them under.
N10S_PARAM = {"minCount": "minCount", "maxCount": "maxCount", "datatype": "datatype",
              "pattern": "pattern", "in": "in", "class": "class", "nodeKind": "NodeKind",
              "minInclusive": "minInclusive", "maxInclusive": "maxInclusive"}

# n10s keeps the compiled shapes in this node, in the same database as the data.
CONFIG = "_n10sValidatorConfig"
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)  # id() deprecation notices

results = {"inputs": {"neo4j": NEO4J, "n10s": N10S}, "checks": {}, "steps": {}}
procs = []


class Stop(Exception):
    """A failed precondition. The check is already recorded."""


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def check(cid, ok, **evidence):
    results["checks"][cid] = {"pass": bool(ok), **evidence}
    log(f"{cid} {'PASS' if ok else 'FAIL'} {json.dumps(evidence, default=str)[:400]}")
    return ok


def fetch(url):
    with urllib.request.urlopen(url, timeout=300) as r:
        return r.read()


def docker_commands(text):
    sys.path.insert(0, str(HERE.parent / "template-no-docker"))
    import checks
    return checks.docker_commands(text)


def set_conf(path, values):
    """Set each key once: comment out any line already setting it, then append ours."""
    lines = path.read_text().splitlines() if path.exists() else []
    out = [("#" + ln if ln.split("=", 1)[0].strip() in values else ln) for ln in lines]
    out += [f"{k}={v}" for k, v in values.items()]
    path.write_text("\n".join(out) + "\n")


def tree_rss_mb(pid):
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
    return round(total / 1024, 1)


def export_graph(py, pad, out):
    """The Relate spike's export as node and relationship rows, from the DEXPI sheet."""
    code = ("import json, sys; sys.path.insert(0, %r); import export_cypher as x; "
            "json.dump(x.plant_graph(pad=%d), open(%r, 'w'))" % (str(RELATE), pad, str(out)))
    t = time.monotonic()
    subprocess.run([py, "-c", code], check=True, cwd=RELATE)
    results["steps"][f"export_pad{pad}"] = round(time.monotonic() - t, 1)
    return json.loads(out.read_text())


# Neo4j side.

def load(session, graph, batch=500, one_tx=False):
    """Create nodes grouped by label set, then relationships grouped by type and end labels,
    so each MATCH uses the key index on the end node's first label. With one_tx the data goes
    in one explicit transaction, which is the only way a guarded database accepts it: in
    batched autocommits each node batch is checked before its relationships exist."""
    first = {n["key"]: n["labels"][0] for n in graph["nodes"]}
    for lbl in sorted(set(first.values())):
        session.run(f"CREATE INDEX key_{lbl.lower()} IF NOT EXISTS FOR (n:{lbl}) ON (n.key)").consume()
    session.run("CALL db.awaitIndexes(60)").consume()
    tx = session.begin_transaction() if one_tx else None
    run = tx.run if tx else session.run
    groups = {}
    for n in graph["nodes"]:
        groups.setdefault(tuple(n["labels"]), []).append(dict(n["props"], key=n["key"]))
    for labels, rows in groups.items():
        for i in range(0, len(rows), batch):
            run(f"UNWIND $rows AS r CREATE (n:{':'.join(labels)}) SET n = r",
                        rows=rows[i:i + batch]).consume()
    by_type = {}
    for r in graph["rels"]:
        by_type.setdefault((r["type"], first[r["from"]], first[r["to"]]), []).append(
            {"f": r["from"], "t": r["to"], "p": r.get("props", {})})
    for (typ, a, b), rows in sorted(by_type.items()):
        for i in range(0, len(rows), batch):
            run(f"UNWIND $rows AS r MATCH (a:{a} {{key: r.f}}) MATCH (b:{b} {{key: r.t}}) "
                f"CREATE (a)-[x:{typ}]->(b) SET x = r.p", rows=rows[i:i + batch]).consume()
    if tx:
        try:
            tx.commit()
        finally:
            tx.close()


def read_graph(session):
    """The whole graph back out of Neo4j, in the export's row form, sorted."""
    nodes = [{"key": r["k"], "label": sorted(r["l"])[0], "labels": sorted(r["l"]),
              "props": {k: v for k, v in r["p"].items() if k != "key"}}
             for r in session.run(f"MATCH (n) WHERE NOT n:{CONFIG} "
                                 "RETURN n.key AS k, labels(n) AS l, properties(n) AS p")]
    rels = [{"type": r["t"], "from": r["a"], "to": r["b"], "props": r["p"]}
            for r in session.run("MATCH (a)-[x]->(b) RETURN a.key AS a, type(x) AS t, b.key AS b, "
                                 "properties(x) AS p")]
    nodes.sort(key=lambda n: n["key"])
    rels.sort(key=lambda r: (r["from"], r["type"], r["to"], json.dumps(r["props"], sort_keys=True)))
    return {"nodes": nodes, "rels": rels}


def counts(graph):
    labels, types = {}, {}
    for n in graph["nodes"]:
        for lbl in n["labels"]:
            labels[lbl] = labels.get(lbl, 0) + 1
    for r in graph["rels"]:
        types[r["type"]] = types.get(r["type"], 0) + 1
    return dict(sorted(labels.items())), dict(sorted(types.items()))


def n10s_validate(session):
    key_of = {}
    for r in session.run("MATCH (n) RETURN id(n) AS i, elementId(n) AS e, n.key AS k"):
        key_of[r["i"]] = r["k"]
        key_of[r["e"]] = r["k"]
    rows = [r.data() for r in session.run(
        "CALL n10s.validation.shacl.validate() YIELD focusNode, nodeType, propertyShape, "
        "offendingValue, resultPath, severity RETURN *")]
    return lib.n10s_violations(rows, key_of), rows


def reset(session, graph):
    session.run(f"MATCH (n) WHERE NOT n:{CONFIG} DETACH DELETE n").consume()
    load(session, graph)


def expected_shape_rows():
    """(target, path, param) for every constraint in shapes.ttl, read with rdflib."""
    import rdflib
    g = rdflib.Graph().parse(data=SHAPES, format="turtle")
    sh = rdflib.Namespace(lib.SH)
    out = set()
    for ns, ps in g.subject_objects(sh.property):
        target = lib._local(g.value(ns, sh.targetClass))
        path = lib._local(g.value(ps, sh.path))
        for p, _ in g.predicate_objects(ps):
            name = lib._local(p)
            if name in N10S_PARAM:
                out.add((target, path, N10S_PARAM[name]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--work")
    ap.add_argument("--dexpi-python", default=os.environ.get("DEXPI_PYTHON", sys.executable))
    a = ap.parse_args()
    parent = None
    if a.work:
        parent = Path(a.work)
        parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="shacl-spike-", dir=parent))
    log(f"work dir {work}")
    t_all = time.monotonic()
    try:
        _run_all(work, a.dexpi_python)
    except Stop as e:
        results["stopped"] = str(e)
        log(f"stopped: {e}")
    finally:
        for p in reversed(procs):
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.wait(30)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
        results["total_seconds"] = round(time.monotonic() - t_all, 1)
        (HERE / "results.json").write_text(json.dumps(results, indent=2, default=str) + "\n")
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)
    failed = [k for k, v in results["checks"].items() if not v["pass"]]
    log(f"failed checks: {failed or 'none'}")
    sys.exit(1 if failed or "stopped" in results else 0)


def _run_all(work, dexpi_python):
    from neo4j import GraphDatabase
    from neo4j.exceptions import Neo4jError

    # N1. No Docker, pinned inputs, checked before anything is unpacked.
    hits = docker_commands(Path(__file__).read_text())
    tgz, jar = fetch(NEO4J_URL), fetch(N10S_URL)
    published = fetch(NEO4J_URL + ".sha256").decode().split()[0]
    neo_sha, n10s_sha = hashlib.sha256(tgz).hexdigest(), hashlib.sha256(jar).hexdigest()
    ok = hits == [] and neo_sha == NEO4J_SHA256 == published and n10s_sha == N10S_SHA256
    java = subprocess.run(["java", "-version"], capture_output=True, text=True).stderr.splitlines()[0]
    if not check("N1", ok, docker_commands=hits, docker_on_path=shutil.which("docker") is not None,
                 neo4j_sha256_ok=neo_sha == NEO4J_SHA256, neo4j_published_ok=published == NEO4J_SHA256,
                 n10s_sha256_ok=n10s_sha == N10S_SHA256, java=java, os=platform.platform()):
        raise Stop("N1 failed, nothing unpacked")
    (work / "neo4j.tgz").write_bytes(tgz)
    with tarfile.open(work / "neo4j.tgz") as t:
        t.extractall(work, filter="data")
    home = work / f"neo4j-community-{NEO4J}"
    (home / "plugins" / f"neosemantics-{N10S}.jar").write_bytes(jar)
    apoc = sorted((home / "labs").glob("apoc-*-core.jar"))
    if len(apoc) != 1:
        raise Stop(f"expected one APOC core jar in labs/, found {[p.name for p in apoc]}")
    shutil.copy(apoc[0], home / "plugins")
    results["inputs"]["apoc"] = apoc[0].name
    set_conf(home / "conf" / "neo4j.conf", {
        "server.default_listen_address": "127.0.0.1",
        "server.bolt.listen_address": f":{BOLT}",
        "server.http.listen_address": f":{HTTP}",
        "server.https.enabled": "false",
        "server.memory.heap.initial_size": "768m",
        "server.memory.heap.max_size": "768m",
        "server.memory.pagecache.size": "384m",
        "dbms.security.procedures.unrestricted": "n10s.*,apoc.*",
    })
    set_conf(home / "conf" / "apoc.conf", {"apoc.trigger.enabled": "true",
                                           "apoc.trigger.refresh": "1000"})
    env = dict(os.environ, NEO4J_HOME=str(home))
    subprocess.run([str(home / "bin" / "neo4j-admin"), "dbms", "set-initial-password", PASSWORD],
                   check=True, capture_output=True, env=env)

    # N2. Start and check the procedures are there.
    logf = open(work / "neo4j-console.log", "w")
    neo = subprocess.Popen([str(home / "bin" / "neo4j"), "console"], stdout=logf,
                           stderr=subprocess.STDOUT, env=env, start_new_session=True)
    procs.append(neo)
    t0 = time.monotonic()
    driver = GraphDatabase.driver(f"bolt://127.0.0.1:{BOLT}", auth=("neo4j", PASSWORD))
    up = None
    while time.monotonic() - t0 < 60 and neo.poll() is None:
        try:
            driver.verify_connectivity()
            up = round(time.monotonic() - t0, 1)
            break
        except Exception:
            time.sleep(0.5)
    procs_found = []
    if up is not None:
        with driver.session() as s:
            procs_found = s.run("SHOW PROCEDURES YIELD name RETURN collect(name) AS n").single()["n"]
            versions = s.run("CALL dbms.components() YIELD versions, edition "
                             "RETURN versions[0] AS v, edition AS e").single().data()
        results["inputs"]["neo4j_running"] = versions
    need = ["n10s.validation.shacl.validate", "n10s.validation.shacl.validateTransaction",
            "apoc.trigger.install"]
    if not check("N2", up is not None and all(p in procs_found for p in need), ready_s=up,
                 missing=[p for p in need if p not in procs_found]):
        raise Stop("N2 failed, Neo4j not usable")

    # N3. The test graph.
    raw = export_graph(dexpi_python, 0, work / "graph.json")
    clean = lib.augment(raw)
    want = json.loads((RELATE / "expected.json").read_text())
    want_labels = dict(want["nodes"])
    for extra in ("Exchanger", "FiredHeater", "Reactor"):
        want_labels[extra] = sum(1 for n in raw["nodes"] if n["label"] == "Equipment"
                                 and lib.CLASS_LABEL[n["props"]["dexpi_class"]] == extra)
    for label, _ in lib.WORK_TYPES.values():
        want_labels[label] = 1
    with driver.session() as s:
        reset(s, clean)
        stored = read_graph(s)
    got_labels, got_types = counts(stored)
    check("N3", got_labels == dict(sorted(want_labels.items()))
          and got_types == dict(sorted(want["relationships"].items()))
          and sum(want["nodes"].values()) == len(stored["nodes"]),
          labels=got_labels, relationships=got_types, nodes=len(stored["nodes"]),
          relationship_count=len(stored["rels"]))

    # N4. Shapes load and cover every constraint in shapes.ttl.
    with driver.session() as s:
        loaded = [r.data() for r in s.run("CALL n10s.validation.shacl.import.inline($t, 'Turtle')",
                                          t=SHAPES)]
        listed = [r.data() for r in s.run("CALL n10s.validation.shacl.listShapes()")]
    got_rows = {(r["target"], r["propertyOrRelationshipPath"], r["param"]) for r in listed}
    want_rows = expected_shape_rows()
    check("N4", got_rows == want_rows and len(loaded) == len(listed), rows=len(listed),
          missing=sorted(want_rows - got_rows), unexpected=sorted(got_rows - want_rows),
          listed=listed)

    # N5. The clean graph has no violations, by n10s and by pySHACL.
    with driver.session() as s:
        got, rows = n10s_validate(s)
    py = lib.pyshacl_violations(lib.to_turtle(stored), SHAPES)
    check("N5", got == set() and py == set(), n10s=sorted(got), pyshacl=sorted(py))

    # N6. Mutants, each on a fresh copy of the graph.
    both = lib.both_bounds(want_rows)
    per = {}
    with driver.session() as s:
        for m in mutants.MUTANTS:
            reset(s, clean)
            summary = s.run(m["cypher"], **m["params"]).consume().counters
            touched = (summary.properties_set + summary.relationships_created
                       + summary.relationships_deleted + summary.nodes_created)
            mutated = read_graph(s)
            want_v = lib.expected_violations(m, stored, mutated)
            got_v, _ = n10s_validate(s)
            py_v = lib.pyshacl_violations(lib.to_turtle(mutated), SHAPES)
            per[m["id"]] = {"shape": m["shape"], "what": m["what"], "touched": touched,
                            "n10s_ok": got_v == want_v, "pyshacl_ok": py_v == want_v,
                            "n10s_ok_merged": lib.merge_bounds(got_v, both) == lib.merge_bounds(want_v, both),
                            "expected": sorted(want_v), "n10s": sorted(got_v),
                            "pyshacl": sorted(py_v)}
            log(f"  {m['id']} touched={touched} n10s={'ok' if got_v == want_v else sorted(got_v)} "
                f"pyshacl={'ok' if py_v == want_v else sorted(py_v)}")
    # n10s names a min-and-max shape's result sh:CountConstraintComponent or
    # sh:ValueRangeConstraintComponent (SHACLValidator.java), which aren't SHACL Core names. N6
    # passes when n10s agrees once both sides use those merged names and pySHACL agrees exactly.
    check("N6", all(v["touched"] > 0 and v["n10s_ok_merged"] and v["pyshacl_ok"] for v in per.values()),
          n10s_agree=sum(v["n10s_ok"] for v in per.values()),
          n10s_agree_merged=sum(v["n10s_ok_merged"] for v in per.values()),
          pyshacl_agree=sum(v["pyshacl_ok"] for v in per.values()), mutants=per)

    # N7. The transaction guard. The graph is reset before the trigger goes in.
    with driver.session() as s:
        reset(s, clean)
    with driver.session(database="system") as s:
        s.run("CALL apoc.trigger.install('neo4j', 'shacl', $q, {phase: 'before'})", q=TRIGGER).consume()
    with driver.session() as s:
        t0 = time.monotonic()
        while time.monotonic() - t0 < 30:
            if any(r["name"] == "shacl" for r in s.run("CALL apoc.trigger.list()")):
                break
            time.sleep(0.5)
        trigger_s = round(time.monotonic() - t0, 1)
        before = read_graph(s)
        ready = {"installed": guard_state(s)}
        guard = {}
        for m in mutants.MUTANTS:
            err = None
            try:
                s.run(m["cypher"], **m["params"]).consume()
            except Neo4jError as e:
                err = e
            after = read_graph(s)
            guard[m["id"]] = {"rejected": shacl_rejected(err), "error": err and err.code,
                              "unchanged": after == before}
            if after != before:  # put the graph back for the next mutant
                _paused_reset(driver, s, clean)
                before = read_graph(s)
            log(f"  guard {m['id']} {guard[m['id']]}")
        good_err = None
        try:
            s.run("MATCH (e:Equipment {tag: $tag}) CREATE (:ScopeItem:BundlePull {key: $rid, "
                  "request_id: $rid, exercise_id: $ex, ript: 7})-[:RESOLVES_TO]->(e)",
                  tag="E-201A", rid="WR-200-0199", ex="EX-1").consume()
        except Neo4jError as e:
            good_err = e.code
        committed = s.run("MATCH (n:ScopeItem {request_id: $rid})-[:RESOLVES_TO]->(e) "
                          "RETURN e.tag AS t", rid="WR-200-0199").value()
        # Fail open or closed? Drop the shapes node, then try the first mutant again.
        _paused_reset(driver, s, clean)
        with driver.session(database="system") as sys_s:
            sys_s.run("CALL apoc.trigger.stop('neo4j', 'shacl')").consume()
        _wait_trigger(s, paused=True)
        ready["trigger_paused"] = guard_state(s)
        with driver.session(database="system") as sys_s:
            sys_s.run("CALL apoc.trigger.start('neo4j', 'shacl')").consume()
        _wait_trigger(s, paused=False)
        drop_err = None
        try:
            s.run(f"MATCH (c:{CONFIG}) DELETE c").consume()
        except Neo4jError as e:
            drop_err = e.code
        shapes_left = s.run(f"MATCH (c:{CONFIG}) RETURN count(c) AS c").single()["c"]
        ready["shapes_missing"] = guard_state(s)
        m = mutants.MUTANTS[0]
        open_err = None
        try:
            s.run(m["cypher"], **m["params"]).consume()
        except Neo4jError as e:
            open_err = e.code
        open_committed = s.run("MATCH (e:Equipment {tag: $v}) RETURN count(e) AS c",
                               v=m["params"]["value"]).single()["c"] == 1
        s.run("CALL n10s.validation.shacl.import.inline($t, 'Turtle')", t=SHAPES).consume()
        _paused_reset(driver, s, clean)
        ready["restored"] = guard_state(s)
        restored_before = read_graph(s)
        restored_err = None
        try:
            s.run(m["cypher"], **m["params"]).consume()
        except Neo4jError as e:
            restored_err = e
        restored = {"mutant": m["id"], "rejected": shacl_rejected(restored_err),
                    "unchanged": read_graph(s) == restored_before}
    check("N7", all(v["rejected"] and v["unchanged"] for v in guard.values())
          and good_err is None and committed == ["E-201A"]
          and open_committed and open_err is None
          and ready == {"installed": True, "trigger_paused": False, "shapes_missing": False,
                        "restored": True}
          and restored["rejected"] and restored["unchanged"],
          guard_ready=ready, after_restore=restored,
          trigger_ready_s=trigger_s, rejected=sum(v["rejected"] for v in guard.values()),
          unchanged=sum(v["unchanged"] for v in guard.values()), mutants=guard,
          valid_write_error=good_err, valid_write_committed=committed,
          without_shapes={"mutant": m["id"], "error": open_err, "write_committed": open_committed,
                          "shapes_drop_error": drop_err, "shapes_nodes_left": shapes_left})

    # N8. Scale, on the padded graph. The padding copies carry a -P001 style suffix on their tags
    # and request IDs, which breaks the S1, S3 and S4 patterns, so the raw padded graph is a
    # scale test of agreement: n10s and pySHACL must report the same violations. The guarded
    # load then uses a copy with the suffix stripped from those properties (node keys stay
    # unique), which must have no violations.
    padded = lib.augment(export_graph(dexpi_python, 104, work / "padded.json"))
    valid = lib.strip_pad_suffix(padded)
    with driver.session() as s:
        _paused_reset(driver, s, {"nodes": [], "rels": []})
    with driver.session(database="system") as s:
        s.run("CALL apoc.trigger.stop('neo4j', 'shacl')").consume()
    with driver.session() as s:
        _wait_trigger(s, paused=True)
        load(s, padded)
        t0 = time.monotonic()
        got_raw, _ = n10s_validate(s)
        validate_s = round(time.monotonic() - t0, 2)
        py_raw = lib.pyshacl_violations(lib.to_turtle(padded), SHAPES)
        s.run(f"MATCH (n) WHERE NOT n:{CONFIG} DETACH DELETE n").consume()
        t0 = time.monotonic()
        load(s, valid)
        load_plain = round(time.monotonic() - t0, 2)
        got_valid, _ = n10s_validate(s)
        s.run(f"MATCH (n) WHERE NOT n:{CONFIG} DETACH DELETE n").consume()
    with driver.session(database="system") as s:
        s.run("CALL apoc.trigger.start('neo4j', 'shacl')").consume()
    with driver.session() as s:
        _wait_trigger(s, paused=False)
        batched_err = None
        try:
            load(s, valid)
        except Neo4jError as e:
            batched_err = e.code
        _paused_reset(driver, s, {"nodes": [], "rels": []})
        t0 = time.monotonic()
        guarded_err = None
        try:
            load(s, valid, one_tx=True)
        except Neo4jError as e:
            guarded_err = e.code
        load_guarded = round(time.monotonic() - t0, 2)
        n_nodes = s.run(f"MATCH (n) WHERE NOT n:{CONFIG} RETURN count(n) AS c").single()["c"]
        n_rels = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        got_final, _ = n10s_validate(s)
    check("N8", got_raw == py_raw and len(got_raw) > 0 and got_valid == set()
          and guarded_err is None and n_nodes == len(valid["nodes"])
          and n_rels == len(valid["rels"]) and got_final == set(),
          stored_nodes=n_nodes, stored_relationships=n_rels, final_violations=len(got_final),
          nodes=len(padded["nodes"]), relationships=len(padded["rels"]),
          raw_violations_n10s=len(got_raw), raw_violations_pyshacl=len(py_raw),
          raw_agree=got_raw == py_raw, valid_violations=len(got_valid), validate_s=validate_s,
          load_s_without_trigger=load_plain, load_s_with_trigger_one_tx=load_guarded,
          guarded_load_error=guarded_err, batched_autocommit_load_error=batched_err,
          neo4j_rss_mb=tree_rss_mb(neo.pid))
    driver.close()


def guard_state(session):
    """What the loader checks before it writes (lib.guard_ready), read from the database."""
    cfg = session.run(f"MATCH (c:{CONFIG}) RETURN count(c) AS c").single()["c"]
    listed = set()
    if cfg:
        listed = {(r["target"], r["propertyOrRelationshipPath"], r["param"])
                  for r in session.run("CALL n10s.validation.shacl.listShapes()")}
    triggers = [r.data() for r in session.run("CALL apoc.trigger.list()")]
    return lib.guard_ready(cfg, listed, expected_shape_rows(), triggers)


def shacl_rejected(err):
    """A write refused by the n10s trigger, not by anything else."""
    return (err is not None and err.code == "Neo.ClientError.Transaction.TransactionHookFailed"
            and "SHACLValidationException" in (err.message or ""))


def _paused_reset(driver, session, graph):
    """Reset the graph with the trigger stopped, then start it again."""
    with driver.session(database="system") as sys_s:
        sys_s.run("CALL apoc.trigger.stop('neo4j', 'shacl')").consume()
    _wait_trigger(session, paused=True)
    reset(session, graph)
    with driver.session(database="system") as sys_s:
        sys_s.run("CALL apoc.trigger.start('neo4j', 'shacl')").consume()
    _wait_trigger(session, paused=False)


def _wait_trigger(session, paused):
    t0 = time.monotonic()
    while time.monotonic() - t0 < 30:
        rows = [r.data() for r in session.run("CALL apoc.trigger.list()")]
        if any(r["name"] == "shacl" and bool(r.get("paused")) == paused for r in rows):
            return
        time.sleep(0.5)
    raise Stop(f"trigger did not become paused={paused}")


if __name__ == "__main__":
    main()
