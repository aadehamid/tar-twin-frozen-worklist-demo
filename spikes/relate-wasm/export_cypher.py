"""Export sheet 200-PID-002 from the DEXPI XML into a Cypher script that Relate can run.

    python export_cypher.py            writes plant.cypher and padded.cypher

The graph follows design.md section 4.3. The isolation envelope is computed here, from the
piping, and stored. The browser recomputes it with a live walk, and the checks compare the two.
"""

import sys
import warnings
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHEET_DIR = HERE.parent / "dexpi-sheet"
sys.path.insert(0, str(SHEET_DIR))

warnings.filterwarnings("ignore")
from pydexpi.loaders import DexpiXmlSerializer  # noqa: E402

import sheet_graph as sg  # noqa: E402  check-side reader from the DEXPI sheet spike

SHEET = "200-PID-002"
ENVELOPE = "ENV-200-02"
PAD_COPIES = 104
BATCH = 300
VALVE_ROLE = {"GateValve": "block", "GlobeValve": "control"}

# Synthetic IMPACT Web requests. Four resolve to equipment on this sheet, one doesn't yet.
SCOPE = [
    ("WR-200-0147", "E-201B", "Pull bundle and hydroblast, feed/effluent exchanger E-201B"),
    ("WR-200-0152", "R-202", "Catalyst changeout and bed inspection, main reactor"),
    ("WR-200-0160", "H-201", "Decoke and inspect radiant tubes, reactor charge heater"),
    ("WR-200-0171", "E-201C", "Retube feed/effluent exchanger E-201C"),
    ("WR-200-0188", None, "General cleanup of the HP loop exchangers"),
]


def load_model():
    return DexpiXmlSerializer().load(SHEET_DIR, SHEET)


def _sheet_graph(model):
    """One copy of the sheet as node and relationship rows, keyed by DEXPI ID."""
    nodes, rels = [], []
    meta = model.conceptualModel.metaData
    if meta.drawingNumber != SHEET:
        raise ValueError(f"expected sheet {SHEET}, got {meta.drawingNumber}")
    title = meta.drawingName
    nodes.append({"key": SHEET, "label": "PidSheet", "props": {"number": SHEET, "title": title}})
    for obj in sg.objects(model):
        cls = type(obj).__name__
        if cls in sg.EQUIPMENT_CLASSES:
            nodes.append({"key": obj.id, "label": "Equipment", "props": {
                "tag": obj.tagName, "dexpi_id": obj.id, "dexpi_class": cls,
                "description": sg.text_of(obj.equipmentDescription)}})
            rels.append({"type": "ON_SHEET", "from": obj.id, "to": SHEET})
            for nz in obj.nozzles:
                nodes.append({"key": nz.id, "label": "Nozzle", "props": {
                    "sub_tag": nz.subTagName, "dexpi_id": nz.id,
                    "chamber": nz.chamber.subTagName}})
                rels.append({"type": "HAS_NOZZLE", "from": obj.id, "to": nz.id})
        elif cls in sg.VALVE_CLASSES:
            nodes.append({"key": obj.id, "label": "Valve", "props": {
                "tag": obj.pipingComponentName, "dexpi_id": obj.id, "dexpi_class": cls,
                "role": VALVE_ROLE[cls]}})
            rels.append({"type": "ON_SHEET", "from": obj.id, "to": SHEET})
        elif cls in sg.CONNECTOR_CLASSES:
            ref = obj.connectorReference
            nodes.append({"key": obj.id, "label": "OffPageConnector", "props": {
                "number": obj.pipeConnectorNumber, "dexpi_id": obj.id, "dexpi_class": cls,
                "to_sheet": getattr(ref, "referencedDrawingNumber", None) or "",
                "description": sg.text_of(obj.pipeConnectorDescription)}})
        elif cls == "PipeTee":
            nodes.append({"key": obj.id, "label": "PipeTee", "props": {"dexpi_id": obj.id}})
    line_of = {id(seg): sys_.lineNumber for sys_ in sg.objects(model)
               if type(sys_).__name__ == "PipingNetworkSystem" for seg in sys_.segments}
    for seg, c in sg.connections(model):
        if type(c).__name__ != "Pipe":
            raise ValueError(f"{c.id}: only Pipe connections are expected on this sheet")
        rels.append({"type": "CONNECTED_TO", "from": c.sourceItem.id, "to": c.targetItem.id,
                     "props": {"line": line_of[id(seg)], "dexpi_id": c.id}})
    return nodes, rels


def is_stop(node):
    """Walks end at block valves and off-page connectors. Control valves and equipment are
    walked through."""
    return node["label"] == "OffPageConnector" or (
        node["label"] == "Valve" and node["props"]["role"] == "block")


def walk(nodes, rels, start, stop=is_stop):
    """From node key `start`, walk CONNECTED_TO and HAS_NOZZLE undirected, not passing any
    node where `stop` is true. Returns (equipment keys passed, block valve keys reached)."""
    by_key = {n["key"]: n for n in nodes}
    adj = defaultdict(set)
    for r in rels:
        if r["type"] in ("CONNECTED_TO", "HAS_NOZZLE"):
            adj[r["from"]].add(r["to"])
            adj[r["to"]].add(r["from"])
    seen, stack = {start}, [start]
    while stack:
        k = stack.pop()
        for j in adj[k]:
            if j in seen:
                continue
            seen.add(j)
            if not stop(by_key[j]):
                stack.append(j)

    def block(k):
        n = by_key[k]
        return n["label"] == "Valve" and n["props"]["role"] == "block"

    return ({k for k in seen if by_key[k]["label"] == "Equipment"},
            {k for k in seen if block(k)})


def envelope(nodes, rels):
    """Equipment inside the envelope and the block valves bounding it. Raises if the sheet
    holds more than one envelope."""
    found = []
    for start in sorted(n["key"] for n in nodes if n["label"] == "Equipment"):
        if any(start in eq for eq, _ in found):
            continue
        found.append(walk(nodes, rels, start))
    if len(found) != 1:
        raise ValueError(f"expected one envelope on {SHEET}, found {len(found)}")
    return found[0]


def _base_graph(model):
    nodes, rels = _sheet_graph(model)
    equipment, boundary = envelope(nodes, rels)
    nodes.append({"key": ENVELOPE, "label": "IsolationEnvelope",
                  "props": {"id": ENVELOPE, "sheet": SHEET}})
    rels += [{"type": "CONTAINS", "from": ENVELOPE, "to": k} for k in sorted(equipment)]
    rels += [{"type": "BOUNDED_BY", "from": ENVELOPE, "to": k} for k in sorted(boundary)]
    tag_key = {n["props"]["tag"]: n["key"] for n in nodes if n["label"] == "Equipment"}
    for rid, tag, title in SCOPE:
        nodes.append({"key": rid, "label": "ScopeItem", "props": {
            "request_id": rid, "title": title, "exercise_id": "EX-1", "source": "IMPACT Web"}})
        if tag is not None:
            rels.append({"type": "RESOLVES_TO", "from": rid, "to": tag_key[tag]})
    return nodes, rels


def _copy(nodes, rels, i):
    """Copy i of the sheet: keys, tags, numbers and request IDs get a -Pnnn suffix."""
    sfx = f"-P{i:03d}"
    renamed = ("tag", "number", "request_id", "id", "sheet", "dexpi_id")
    out_n = [{"key": n["key"] + sfx, "label": n["label"],
              "props": {k: (v + sfx if k in renamed else v) for k, v in n["props"].items()}}
             for n in nodes]
    out_r = [dict(r, **{"from": r["from"] + sfx, "to": r["to"] + sfx}) for r in rels]
    return out_n, out_r


def plant_graph(pad=0, model=None):
    model = model or load_model()
    nodes, rels = _base_graph(model)
    all_n, all_r = list(nodes), list(rels)
    for i in range(1, pad + 1):
        n, r = _copy(nodes, rels, i)
        all_n += n
        all_r += r
    keys = [n["key"] for n in all_n]
    if len(keys) != len(set(keys)):
        raise ValueError("node keys repeat")
    return {"nodes": all_n, "rels": all_r}


def lit(v):
    """A Cypher literal. Strings use single quotes; ';' is written as an escape so no statement
    holds a raw ';' and the script splits cleanly."""
    if isinstance(v, bool) or v is None:
        raise TypeError(f"unexpected value {v!r}")
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v).replace("\\", "\\\\").replace("'", "\\'").replace(";", "\\u003B")
    s = s.replace("\n", "\\n")
    return f"'{s}'"


def _map(d):
    return "{" + ", ".join(f"{k}: {lit(v)}" for k, v in sorted(d.items())) + "}"


def _batches(rows):
    for i in range(0, len(rows), BATCH):
        yield rows[i:i + BATCH]


def to_cypher(graph):
    labels = sorted({n["label"] for n in graph["nodes"]})
    out = [f"CREATE INDEX {lbl.lower()}_key IF NOT EXISTS FOR (n:{lbl}) ON (n.key)"
           for lbl in labels]
    by_label = defaultdict(list)
    for n in graph["nodes"]:
        by_label[n["label"]].append(dict(n["props"], key=n["key"]))
    for lbl in labels:
        for rows in _batches(by_label[lbl]):
            out.append(f"UNWIND [{', '.join(_map(r) for r in rows)}] AS r "
                       f"CREATE (n:{lbl}) SET n = r")
    label_of = {n["key"]: n["label"] for n in graph["nodes"]}
    groups = defaultdict(list)
    for r in graph["rels"]:
        groups[(r["type"], label_of[r["from"]], label_of[r["to"]])].append(
            {"f": r["from"], "t": r["to"], "p": r.get("props", {})})
    for (typ, a, b) in sorted(groups):
        for rows in _batches(groups[(typ, a, b)]):
            items = ", ".join("{f: %s, t: %s, p: %s}" % (lit(x["f"]), lit(x["t"]), _map(x["p"]))
                              for x in rows)
            out.append(f"UNWIND [{items}] AS r MATCH (a:{a} {{key: r.f}}) "
                       f"MATCH (b:{b} {{key: r.t}}) CREATE (a)-[x:{typ}]->(b) SET x = r.p")
    return ";\n".join(out) + ";\n"


def build(pad=0):
    return to_cypher(plant_graph(pad=pad))


def main():
    (HERE / "plant.cypher").write_text(build())
    (HERE / "padded.cypher").write_text(build(pad=PAD_COPIES))


if __name__ == "__main__":
    main()
