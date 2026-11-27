"""Read tags and flow edges out of any pyDEXPI model. Check-side code: it reads the reloaded
XML, never the builder's objects, and must not import the builder."""

from collections import defaultdict

import pydexpi
from pydexpi.toolkits.model_toolkit import get_all_instances_in_model

EQUIPMENT_CLASSES = {"TubularHeatExchanger", "Furnace", "PressureVessel"}
VALVE_CLASSES = {"GateValve", "GlobeValve"}
CONNECTOR_CLASSES = {"FlowInPipeOffPageConnector", "FlowOutPipeOffPageConnector"}
NOZZLE_CLASSES = {"Nozzle", "ProcessNozzle"}


def text_of(mls):
    """Plain text of a DEXPI MultiLanguageString, or of a plain string."""
    if mls is None:
        return ""
    if isinstance(mls, str):
        return mls
    return " ".join(s.value for s in mls.singleLanguageStrings)


def tag_of(obj):
    """The tag an object is known by on the sheet, or None for untagged piping parts."""
    name = type(obj).__name__
    if name in EQUIPMENT_CLASSES:
        return obj.tagName
    if name in VALVE_CLASSES:
        return obj.pipingComponentName
    if name in CONNECTOR_CLASSES:
        return obj.pipeConnectorNumber
    return None


def objects(model):
    return list(get_all_instances_in_model(model))


def inventory(model):
    """tag -> class name for every tagged object. Raises if a tag repeats."""
    found = {}
    for obj in objects(model):
        tag = tag_of(obj)
        if tag is None:
            continue
        if tag in found:
            raise ValueError(f"tag {tag} appears twice")
        found[tag] = type(obj).__name__
    return found


def chambers(model):
    """equipment tag -> set of chamber subTagNames."""
    out = {}
    for obj in objects(model):
        if type(obj).__name__ in EQUIPMENT_CLASSES:
            out[obj.tagName] = {c.subTagName for c in obj.chambers}
    return out


def _end_names(model):
    """id(item) -> flow end name for tagged items and nozzles; untagged items are absent."""
    names = {}
    for obj in objects(model):
        if type(obj).__name__ in EQUIPMENT_CLASSES:
            for nz in obj.nozzles:
                if nz.chamber is None:
                    raise ValueError(f"nozzle {nz.id} on {obj.tagName} has no chamber")
                names[id(nz)] = f"{obj.tagName}[{nz.chamber.subTagName}]"
        else:
            tag = tag_of(obj)
            if tag is not None:
                names[id(obj)] = tag
    return names


def connections(model):
    """Every Pipe and DirectPipingConnection, with its segment."""
    out = []
    for obj in objects(model):
        if type(obj).__name__ == "PipingNetworkSegment":
            for c in obj.connections:
                out.append((obj, c))
    return out


def structural_problems(model):
    """Pipes whose nodes don't belong to their items, and valve or nozzle ends that aren't
    used exactly once. An empty list means the piping is wired consistently."""
    problems = []
    used = defaultdict(int)
    for _seg, c in connections(model):
        for item, node, role in ((c.sourceItem, c.sourceNode, "source"),
                                 (c.targetItem, c.targetNode, "target")):
            if item is None or node is None:
                problems.append(f"{c.id} has no {role}")
                continue
            if not any(n is node for n in item.nodes):
                problems.append(f"{c.id} {role} node {node.id} is not on {item.id}")
            used[id(node)] += 1
    for obj in objects(model):
        name = type(obj).__name__
        if name in VALVE_CLASSES or name in CONNECTOR_CLASSES or name in NOZZLE_CLASSES:
            for n in obj.nodes:
                if used[id(n)] != 1:
                    problems.append(f"{obj.id} node {n.id} used {used[id(n)]} times")
        if name == "PipeTee":
            for n in obj.nodes:
                if used[id(n)] != 1:
                    problems.append(f"{obj.id} node {n.id} used {used[id(n)]} times")
    return problems


def _contract(succ, names, start):
    """Tagged ends reached from `start` by walking through untagged items."""
    seen, stack, hits = set(), list(succ[start]), set()
    while stack:
        k = stack.pop()
        if k in seen:
            continue
        seen.add(k)
        if k in names:
            hits.add(names[k])
        else:
            stack.extend(succ[k])
    return hits


def flow_edges(model):
    """Directed edges between flow ends, following each pipe from source to target."""
    names = _end_names(model)
    succ = defaultdict(list)
    for _seg, c in connections(model):
        succ[id(c.sourceItem)].append(id(c.targetItem))
    edges = set()
    for k, name in names.items():
        for hit in _contract(succ, names, k):
            edges.add((name, hit))
    return edges


def conceptual_edges(model):
    """The same edges from pyDEXPI's own conceptual graph, with chamber sides dropped."""
    g = pydexpi.get_graph(model, graph_level="conceptual")
    names = {}
    for n, d in g.nodes(data=True):
        tag = d.get("tagName") or d.get("pipingComponentName") or d.get("pipeConnectorNumber")
        if tag:
            names[n] = tag
    succ = defaultdict(list)
    for a, b in g.edges():
        succ[a].append(b)
    edges = set()
    for n, name in names.items():
        for hit in _contract(succ, names, n):
            edges.add((name, hit))
    return edges


def strip_side(end):
    return end.split("[", 1)[0]


def upstream(edges, end):
    return {a for a, b in edges if b == end}


def downstream(edges, end):
    return {b for a, b in edges if a == end}


def _through_valves(edges, end, step, is_stop):
    """Follow edges in one direction, skipping valves, until equipment or a connector."""
    out, frontier, seen = set(), [end], set()
    while frontier:
        e = frontier.pop()
        for nxt in step(edges, e):
            if nxt in seen:
                continue
            seen.add(nxt)
            if is_stop(nxt):
                out.add(nxt)
            else:
                frontier.append(nxt)
    return out


def equipment_from(edges, end, valve_tags):
    return _through_valves(edges, end, upstream, lambda e: strip_side(e) not in valve_tags)


def equipment_to(edges, end, valve_tags):
    return _through_valves(edges, end, downstream, lambda e: strip_side(e) not in valve_tags)


def connectors(model):
    """connector number -> (class, referenced drawing number, description)."""
    out = {}
    for obj in objects(model):
        if type(obj).__name__ in CONNECTOR_CLASSES:
            ref = obj.connectorReference
            out[obj.pipeConnectorNumber] = (
                type(obj).__name__,
                getattr(ref, "referencedDrawingNumber", None),
                text_of(obj.pipeConnectorDescription),
            )
    return out
