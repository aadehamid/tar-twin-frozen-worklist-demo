"""Unit tests for the pure parts of the SHACL spike, written before lib.py and mutants.py.

    uv run --no-project --with pytest --with rdflib --with pyshacl python -m pytest -q test_checks.py
"""

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lib  # noqa: E402
import mutants  # noqa: E402

SHAPES = (HERE / "shapes.ttl").read_text()


def tiny():
    """A small graph in the export's shape, before augment()."""
    nodes = [
        {"key": "S", "label": "PidSheet", "props": {"number": "200-PID-002", "title": "t"}},
        {"key": "eq1", "label": "Equipment", "props": {"tag": "E-201B", "dexpi_id": "eq1",
                                                      "dexpi_class": "TubularHeatExchanger"}},
        {"key": "eq2", "label": "Equipment", "props": {"tag": "R-202", "dexpi_id": "eq2",
                                                      "dexpi_class": "PressureVessel"}},
        {"key": "eq3", "label": "Equipment", "props": {"tag": "H-201", "dexpi_id": "eq3",
                                                      "dexpi_class": "Furnace"}},
        {"key": "nz1", "label": "Nozzle", "props": {"sub_tag": "N1"}},
        {"key": "v1", "label": "Valve", "props": {"tag": "HV-2001", "role": "block"}},
        {"key": "ENV", "label": "IsolationEnvelope", "props": {"id": "ENV"}},
        {"key": "WR-200-0147", "label": "ScopeItem", "props": {
            "request_id": "WR-200-0147", "exercise_id": "EX-1", "title": "Pull bundle"}},
        {"key": "WR-200-0188", "label": "ScopeItem", "props": {
            "request_id": "WR-200-0188", "exercise_id": "EX-1", "title": "General cleanup"}},
    ]
    rels = [
        {"type": "ON_SHEET", "from": k, "to": "S"} for k in ("eq1", "eq2", "eq3", "v1")
    ] + [
        {"type": "HAS_NOZZLE", "from": "eq1", "to": "nz1"},
        {"type": "CONTAINS", "from": "ENV", "to": "eq1"},
        {"type": "BOUNDED_BY", "from": "ENV", "to": "v1"},
        {"type": "RESOLVES_TO", "from": "WR-200-0147", "to": "eq1"},
    ]
    return {"nodes": nodes, "rels": rels}


def test_augment_adds_class_and_work_type_labels():
    g = lib.augment(tiny(), work_types={"WR-200-0147": ("BundlePull", 12),
                                        "WR-200-0188": ("GeneralCleanup", 3)})
    labels = {n["key"]: n["labels"] for n in g["nodes"]}
    assert labels["eq1"] == ["Equipment", "Exchanger"]
    assert labels["eq2"] == ["Equipment", "Reactor"]
    assert labels["eq3"] == ["Equipment", "FiredHeater"]
    assert labels["WR-200-0147"] == ["ScopeItem", "BundlePull"]
    assert labels["nz1"] == ["Nozzle"]
    ript = {n["key"]: n["props"].get("ript") for n in g["nodes"]}
    assert ript["WR-200-0147"] == 12 and ript["WR-200-0188"] == 3


def test_augment_refuses_unknown_class_or_missing_work_type():
    g = tiny()
    g["nodes"][1]["props"]["dexpi_class"] = "Pump"
    with pytest.raises(ValueError):
        lib.augment(g, work_types={"WR-200-0147": ("BundlePull", 1),
                                   "WR-200-0188": ("GeneralCleanup", 1)})
    with pytest.raises(ValueError):
        lib.augment(tiny(), work_types={"WR-200-0147": ("BundlePull", 1)})


def test_augment_does_not_change_its_input():
    g = tiny()
    lib.augment(g, work_types={"WR-200-0147": ("BundlePull", 1), "WR-200-0188": ("GeneralCleanup", 1)})
    assert "labels" not in g["nodes"][0]


def clean():
    return lib.augment(tiny(), work_types={"WR-200-0147": ("BundlePull", 12),
                                           "WR-200-0188": ("GeneralCleanup", 3)})


def test_turtle_round_trip_types_and_links():
    import rdflib
    g = rdflib.Graph().parse(data=lib.to_turtle(clean()), format="turtle")
    n = rdflib.Namespace(lib.VOCAB)
    eq1 = rdflib.URIRef(lib.node_iri("eq1"))
    assert (eq1, rdflib.RDF.type, n.Exchanger) in g
    assert (eq1, n.tag, rdflib.Literal("E-201B")) in g
    assert (rdflib.URIRef(lib.node_iri("WR-200-0147")), n.ript, rdflib.Literal(12)) in g
    assert (rdflib.URIRef(lib.node_iri("WR-200-0147")), n.RESOLVES_TO, eq1) in g


def test_turtle_escapes_awkward_strings():
    import rdflib
    g = clean()
    g["nodes"][0]["props"]["title"] = 'a "quoted"\\ line\nnext'
    parsed = rdflib.Graph().parse(data=lib.to_turtle(g), format="turtle")
    titles = [str(o) for o in parsed.objects(predicate=rdflib.URIRef(lib.VOCAB + "title"))]
    assert 'a "quoted"\\ line\nnext' in titles


def test_pyshacl_clean_tiny_graph_conforms():
    assert lib.pyshacl_violations(lib.to_turtle(clean()), SHAPES) == set()


def test_pyshacl_catches_a_bad_tag_and_a_wrong_class():
    g = clean()
    g["nodes"][1]["props"]["tag"] = "E201B"
    for r in g["rels"]:
        if r["type"] == "RESOLVES_TO":
            r["to"] = "eq2"
    got = lib.pyshacl_violations(lib.to_turtle(g), SHAPES)
    assert got == {("eq1", "Equipment", "PatternConstraintComponent", "tag"),
                   ("WR-200-0147", "BundlePull", "ClassConstraintComponent", "RESOLVES_TO")}


def test_n10s_rows_normalise():
    rows = [{"focusNode": 7, "nodeType": "Equipment",
             "propertyShape": "http://www.w3.org/ns/shacl#PatternConstraintComponent",
             "resultPath": "tag", "offendingValue": "E201B", "severity": "x"},
            {"focusNode": 9, "nodeType": "BundlePull", "propertyShape": "ClassConstraintComponent",
             "resultPath": "neo4j://graph.schema#RESOLVES_TO", "offendingValue": 3}]
    assert lib.n10s_violations(rows, {7: "eq1", 9: "WR-200-0147"}) == {
        ("eq1", "Equipment", "PatternConstraintComponent", "tag"),
        ("WR-200-0147", "BundlePull", "ClassConstraintComponent", "RESOLVES_TO")}


def test_n10s_rows_with_unknown_node_raise():
    with pytest.raises(KeyError):
        lib.n10s_violations([{"focusNode": 1, "nodeType": "X", "propertyShape": "P",
                              "resultPath": "p"}], {})


def test_resolve_refs():
    g = clean()
    assert lib.resolve("tag:E-201B", g) == "eq1"
    assert lib.resolve("key:WR-200-0147", g) == "WR-200-0147"
    with pytest.raises(KeyError):
        lib.resolve("tag:E-999", g)


def test_every_shape_has_a_mutant_and_ids_are_unique():
    ids = [m["id"] for m in mutants.MUTANTS]
    assert len(ids) == len(set(ids))
    assert {m["shape"] for m in mutants.MUTANTS} == {f"S{i}" for i in range(1, 9)}
    for m in mutants.MUTANTS:
        assert m["expect"], m["id"]
        for ref, label, comp, path in m["expect"]:
            assert ref.split(":", 1)[0] in ("tag", "key")
            assert comp.endswith("ConstraintComponent")


def test_mutant_cypher_uses_parameters_only():
    for m in mutants.MUTANTS:
        assert "'" not in m["cypher"] and '"' not in m["cypher"], m["id"]


def test_expected_violations_resolve_tags_from_the_clean_graph():
    g = clean()
    m = {"expect": [("key:{E-201B}", "Equipment", "PatternConstraintComponent", "tag")]}
    mutated = copy_with_tag(g, "eq1", "E201B")
    assert lib.expected_violations(m, g, mutated) == {
        ("eq1", "Equipment", "PatternConstraintComponent", "tag")}


def test_expected_violations_find_new_nodes_in_the_mutated_graph():
    g = clean()
    mutated = {"nodes": g["nodes"] + [{"key": "NEW", "label": "Equipment", "props": {"tag": "E-301"}}],
               "rels": g["rels"]}
    m = {"expect": [("key:NEW", "Equipment", "PatternConstraintComponent", "tag")]}
    assert lib.expected_violations(m, g, mutated) == {
        ("NEW", "Equipment", "PatternConstraintComponent", "tag")}
    with pytest.raises(KeyError):
        lib.expected_violations(m, g, g)


def copy_with_tag(g, key, tag):
    import copy
    out = copy.deepcopy(g)
    for n in out["nodes"]:
        if n["key"] == key:
            n["props"]["tag"] = tag
    return out


def test_merge_bounds_folds_only_count_and_range():
    v = {("a", "Equipment", "MinCountConstraintComponent", "tag"),
         ("b", "ScopeItem", "MaxInclusiveConstraintComponent", "ript"),
         ("c", "Valve", "PatternConstraintComponent", "tag")}
    assert lib.merge_bounds(v) == {("a", "Equipment", "CountConstraintComponent", "tag"),
                                   ("b", "ScopeItem", "ValueRangeConstraintComponent", "ript"),
                                   ("c", "Valve", "PatternConstraintComponent", "tag")}


def test_strip_pad_suffix_keeps_keys_and_fixes_patterns():
    g = {"nodes": [{"key": "E_201A-P007", "label": "Equipment", "props": {"tag": "E-201A-P007"}},
                   {"key": "WR-200-0147-P002", "label": "ScopeItem",
                    "props": {"request_id": "WR-200-0147-P002", "title": "Pull E-201A-P9"}}],
         "rels": []}
    out = lib.strip_pad_suffix(g)
    assert [n["key"] for n in out["nodes"]] == ["E_201A-P007", "WR-200-0147-P002"]
    assert out["nodes"][0]["props"]["tag"] == "E-201A"
    assert out["nodes"][1]["props"]["request_id"] == "WR-200-0147"
    assert out["nodes"][1]["props"]["title"] == "Pull E-201A-P9"
    assert g["nodes"][0]["props"]["tag"] == "E-201A-P007"
