"""Checks X1 to X10 for sheet 200-PID-002. See docs/spikes/dexpi-sheet.md section 3.

Every check runs on the XML the builder wrote, reloaded from disk, except X2, which compares
two builds. The answer key is expected.py, which doesn't import the builder.
"""

import copy
import importlib.metadata
import math
import re
import sys
import warnings
from itertools import combinations
from pathlib import Path

import pytest
from lxml import etree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "decider-matcher"))

warnings.filterwarnings("ignore", category=DeprecationWarning)

import pydexpi  # noqa: E402
from pydexpi.loaders import DexpiXmlSerializer  # noqa: E402
from pydexpi.toolkits.diagram_toolkit import (  # noqa: E402
    get_representation_group_of_object,
    symbol_extent,
)
from pydexpi.toolkits.routing import polyline_of, snap_axis  # noqa: E402
from pydexpi.validation import validate  # noqa: E402

import build_sheet  # noqa: E402
import cases  # noqa: E402
import expected as X  # noqa: E402
import sheet_graph as G  # noqa: E402

XSD = HERE / "vendor" / "DEXPI_XML_Schema.xsd"
ID_RE = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")


@pytest.fixture(scope="module")
def written(tmp_path_factory):
    out = tmp_path_factory.mktemp("sheet")
    model = build_sheet.build_model()
    path = build_sheet.write_xml(model, out)
    return path


@pytest.fixture(scope="module")
def reloaded(written):
    return DexpiXmlSerializer().load(written.parent, written.stem)


def _schema():
    parser = etree.XMLParser(load_dtd=True, resolve_entities=True)
    return etree.XMLSchema(etree.parse(str(XSD), parser))


# X1
def test_x1_library_version():
    assert importlib.metadata.version("pydexpi") == "2.1.0"
    assert pydexpi.DEXPI_SPEC_VERSION == "2.0.1"


# X2
def test_x2_deterministic_build(tmp_path):
    a = build_sheet.write_xml(build_sheet.build_model(), tmp_path / "a")
    b = build_sheet.write_xml(build_sheet.build_model(), tmp_path / "b")
    assert a.read_bytes() == b.read_bytes()


# X3
def test_x3_schema_valid(written):
    schema = _schema()
    ok = schema.validate(etree.parse(str(written)))
    assert ok, str(schema.error_log)


def test_x3_schema_negative_control(written):
    tree = etree.parse(str(written))
    el = next(e for e in tree.iter() if e.get("id"))
    el.set("id", "9" + el.get("id"))
    assert not _schema().validate(tree)


# X4
def test_x4_validator_clean(reloaded):
    issues = validate(reloaded)
    assert issues == [], [(i.level_of_recommendation, i.short_description) for i in issues]


def test_x4_negative_control(reloaded):
    broken = copy.deepcopy(reloaded)
    seg_pipe = next(c for _s, c in G.connections(broken) if type(c).__name__ == "Pipe")
    seg_pipe.targetNode = None
    assert validate(broken) or G.structural_problems(broken)


# X5
def test_x5_round_trip(written, reloaded, tmp_path):
    again = build_sheet.write_xml(reloaded, tmp_path)
    assert again.read_bytes() == written.read_bytes()


# X6
def test_x6_inventory(reloaded):
    want = {**X.EQUIPMENT, **X.VALVES, **{k: v[0] for k, v in X.CONNECTORS.items()}}
    assert G.inventory(reloaded) == want
    assert G.chambers(reloaded) == X.CHAMBERS


def test_x6_connectors(reloaded):
    got = G.connectors(reloaded)
    assert set(got) == set(X.CONNECTORS)
    for number, (cls, drawing, words) in X.CONNECTORS.items():
        g_cls, g_drawing, g_desc = got[number]
        assert (g_cls, g_drawing) == (cls, drawing), number
        assert words.lower() in g_desc.lower(), (number, g_desc)


def test_x6_ids_unique_and_schema_safe(written):
    ids = [e.get("id") for e in etree.parse(str(written)).iter() if e.get("id")]
    assert len(ids) == len(set(ids))
    bad = [i for i in ids if not ID_RE.match(i)]
    assert not bad, bad[:5]


def test_x6_sheet_metadata(reloaded):
    meta = reloaded.conceptualModel.metaData
    assert meta.drawingNumber == X.SHEET
    assert X.TITLE.lower() in (meta.drawingName or "").lower()


# X7
def test_x7_piping_is_wired_consistently(reloaded):
    assert G.structural_problems(reloaded) == []


def test_x7_flow_edges(reloaded):
    got = G.flow_edges(reloaded)
    assert got - X.FLOW_EDGES == set(), "unexpected edges"
    assert X.FLOW_EDGES - got == set(), "missing edges"


def test_x7_conceptual_graph_agrees(reloaded):
    want = {(G.strip_side(a), G.strip_side(b)) for a, b in X.FLOW_EDGES}
    # Inside one tag, a side-to-side edge would be a contraction artefact; there are none.
    assert all(a != b for a, b in want)
    assert G.conceptual_edges(reloaded) == want


# X8
def _series_order(edges):
    """Exchangers in feed-side order, following feed edges between exchangers only."""
    feed = {f"{t}[{X.FEED_SIDE}]" for t, c in X.EQUIPMENT.items()
            if c == "TubularHeatExchanger"}
    nxt = {}
    for a, b in edges:
        if a in feed and b in feed:
            assert a not in nxt, "feed side branches"
            nxt[a] = b
    first = [f for f in feed if f not in nxt.values()]
    assert len(first) == 1
    order = [first[0]]
    while order[-1] in nxt:
        order.append(nxt[order[-1]])
    return [G.strip_side(e) for e in order]


def _check_claim(claim, edges, conns):
    kind = claim[0]
    valves = set(X.VALVES)
    if kind == "series":
        _, tag, pos, of = claim
        order = _series_order(edges)
        return len(order) == of and order[pos - 1] == tag
    _, tag, side, arg = claim
    end = X.at(tag, side)
    if kind == "from":
        return G.equipment_from(edges, end, valves) == arg
    if kind == "to":
        return G.equipment_to(edges, end, valves) == arg
    if kind in ("from_mentions", "to_mentions"):
        ends = (G.equipment_from if kind == "from_mentions" else G.equipment_to)(
            edges, end, valves)
        descs = [conns[e][2] for e in ends if e in conns]
        return any(arg.lower() in d.lower() for d in descs)
    raise ValueError(kind)


def test_x8_every_fact_on_this_sheet_has_claims():
    on_sheet = {fid for fid, (tag, _text) in cases.FACTS.items() if tag in X.ALL_TAGS}
    assert on_sheet == set(X.FACT_CLAIMS)


@pytest.mark.parametrize("fid", sorted(X.FACT_CLAIMS))
def test_x8_fact_holds(fid, reloaded):
    edges = G.flow_edges(reloaded)
    conns = G.connectors(reloaded)
    for claim in X.FACT_CLAIMS[fid]:
        assert _check_claim(claim, edges, conns), (fid, claim, cases.FACTS[fid][1])


def test_x8_claim_checker_catches_a_wrong_fact(reloaded):
    edges = G.flow_edges(reloaded)
    conns = G.connectors(reloaded)
    # The old F-R202-1 said R-202 is fed from the heater. That must fail.
    wrong = ("from", "R-202", "Vessel", {X.at("H-201", X.PASS1), X.at("H-201", X.PASS2)})
    assert not _check_claim(wrong, edges, conns)
    assert not _check_claim(("series", "E-201B", 1, 3), edges, conns)


# X9
@pytest.fixture(scope="module")
def svg(reloaded, tmp_path_factory):
    out = tmp_path_factory.mktemp("svg") / f"{X.SHEET}.svg"
    build_sheet.render_svg(reloaded, out)
    return etree.parse(str(out))


def test_x9_svg_parses_with_finite_view_box(svg):
    root = svg.getroot()
    vb = [float(v) for v in root.get("viewBox").split()]
    assert len(vb) == 4 and all(math.isfinite(v) for v in vb)
    assert vb[2] > 0 and vb[3] > 0


def test_x9_every_tag_labelled_once(svg):
    texts = ["".join(t.itertext()).strip() for t in svg.iter("{*}text")]
    for tag in X.ALL_TAGS:
        assert texts.count(tag) == 1, (tag, texts.count(tag))


def _tagged_objects(model):
    return [o for o in G.objects(model) if G.tag_of(o) is not None]


def test_x9_every_tagged_item_is_drawn(reloaded):
    for obj in _tagged_objects(reloaded):
        group = get_representation_group_of_object(reloaded, obj)
        assert group is not None and symbol_extent(group) is not None, G.tag_of(obj)


def test_x9_symbols_do_not_overlap(reloaded):
    boxes = {}
    for obj in _tagged_objects(reloaded):
        boxes[G.tag_of(obj)] = symbol_extent(get_representation_group_of_object(reloaded, obj))
    for (a, ba), (b, bb) in combinations(boxes.items(), 2):
        overlap = (min(ba.max_x, bb.max_x) > max(ba.min_x, bb.min_x)
                   and min(ba.max_y, bb.max_y) > max(ba.min_y, bb.min_y))
        assert not overlap, (a, b)


def test_x9_pipe_lines_join_their_ends(reloaded):
    for _seg, pipe in G.connections(reloaded):
        group = get_representation_group_of_object(reloaded, pipe)
        assert group is not None, pipe.id
        lines = [e for s in group.groups for e in getattr(s, "elements", [])
                 if type(e).__name__ == "ConnectorLine"]
        assert len(lines) == 1, pipe.id
        line = lines[0]
        assert line.source.node is pipe.sourceNode, pipe.id
        assert line.target.node is pipe.targetNode, pipe.id
        pts = polyline_of(line)
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            assert snap_axis(x1 - x0, y1 - y0) is not None, (pipe.id, "diagonal leg")


# X10
def test_x10_neo4j_records(reloaded):
    from pydexpi.exports.neo4j_export import get_neo4j_records

    recs = get_neo4j_records(reloaded, graph_level="conceptual")
    nodes, rels = recs.nodes, recs.relationships
    ids = {n[":ID"] for n in nodes}
    tags = [n.get("tagName") or n.get("pipingComponentName") or n.get("pipeConnectorNumber")
            for n in nodes]
    for tag in X.ALL_TAGS:
        assert tags.count(tag) == 1, tag
    for r in rels:
        assert r[":START_ID"] in ids and r[":END_ID"] in ids
