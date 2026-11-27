"""W2 and W3: the exported Cypher script. Run with pytest from a directory other than /tmp."""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "dexpi-sheet"))

import expected as SHEET  # noqa: E402  the DEXPI sheet spike's answer key
import export_cypher  # noqa: E402

KEY = json.loads((HERE / "expected.json").read_text())
MAX_STATEMENT = 4_194_304


def _statements(script):
    # The exporter never puts ';' inside strings, so a plain split is exact here. W2 checks that.
    return [s.strip() for s in script.split(";\n") if s.strip()]


def test_w2_deterministic():
    assert export_cypher.build() == export_cypher.build()
    assert export_cypher.build(pad=3) == export_cypher.build(pad=3)


def test_w2_statements_fit_and_no_transactions():
    for pad in (0, KEY["pad_copies"]):
        script = export_cypher.build(pad=pad)
        stmts = _statements(script)
        assert stmts
        for s in stmts:
            assert len(s.encode()) < MAX_STATEMENT
            assert not re.match(r"(?i)^(BEGIN|COMMIT|ROLLBACK)\b", s)
        # No ';' inside any statement, so splitting on ';' can't cut a string in two.
        assert all(";" not in s for s in stmts)


def test_w3_counts():
    g = export_cypher.plant_graph()
    assert Counter(n["label"] for n in g["nodes"]) == KEY["nodes"]
    assert Counter(r["type"] for r in g["rels"]) == KEY["relationships"]


def test_w3_padded_count():
    g = export_cypher.plant_graph(pad=KEY["pad_copies"])
    assert len(g["nodes"]) == KEY["padded_nodes"]
    keys = [n["key"] for n in g["nodes"]]
    assert len(keys) == len(set(keys))


def test_w3_valve_roles_and_scope():
    g = export_cypher.plant_graph()
    roles = {n["props"]["tag"]: n["props"]["role"] for n in g["nodes"] if n["label"] == "Valve"}
    assert roles == KEY["valve_roles"]
    by_key = {n["key"]: n for n in g["nodes"]}
    resolved = {by_key[r["from"]]["props"]["request_id"]: by_key[r["to"]]["props"]["tag"]
                for r in g["rels"] if r["type"] == "RESOLVES_TO"}
    scope = {n["props"]["request_id"] for n in g["nodes"] if n["label"] == "ScopeItem"}
    assert scope == set(KEY["scope"])
    assert resolved == {k: v for k, v in KEY["scope"].items() if v is not None}


def test_w3_envelope_stored():
    g = export_cypher.plant_graph()
    by_key = {n["key"]: n for n in g["nodes"]}
    contains = sorted(by_key[r["to"]]["props"]["tag"] for r in g["rels"] if r["type"] == "CONTAINS")
    bounded = sorted(by_key[r["to"]]["props"]["tag"] for r in g["rels"] if r["type"] == "BOUNDED_BY")
    assert contains == KEY["walk_from_E-201B"]["equipment"]
    assert bounded == KEY["walk_from_E-201B"]["boundary"]


def _tag_of(node):
    p = node["props"]
    if node["label"] in ("Equipment", "Valve"):
        return p["tag"]
    if node["label"] == "OffPageConnector":
        return p["number"]
    return None


def test_w3_flow_edges_match_the_sheet():
    # Reduce CONNECTED_TO to tagged items with sides, walking through tees. A nozzle stands for
    # its equipment and chamber. This must give the DEXPI sheet spike's 21 flow edges.
    g = export_cypher.plant_graph()
    by_key = {n["key"]: n for n in g["nodes"]}
    owner = {}
    for r in g["rels"]:
        if r["type"] == "HAS_NOZZLE":
            eq, nz = by_key[r["from"]], by_key[r["to"]]
            owner[r["to"]] = f'{eq["props"]["tag"]}[{nz["props"]["chamber"]}]'

    def name(k):
        return owner.get(k) or _tag_of(by_key[k])

    succ = defaultdict(list)
    for r in g["rels"]:
        if r["type"] == "CONNECTED_TO":
            succ[r["from"]].append(r["to"])
    edges = set()
    for k in by_key:
        if name(k) is None:
            continue
        stack, seen = list(succ[k]), set()
        while stack:
            j = stack.pop()
            if j in seen:
                continue
            seen.add(j)
            if name(j) is not None:
                edges.add((name(k), name(j)))
            else:
                stack.extend(succ[j])
    assert edges == SHEET.FLOW_EDGES
