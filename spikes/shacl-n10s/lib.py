"""Pure helpers for the SHACL spike: the test graph, its Turtle rendering, and the two
violation sets that N6 compares. No Neo4j here, so test_checks.py can cover all of it."""

import copy
import json
import re

VOCAB = "neo4j://graph.schema#"
SH = "http://www.w3.org/ns/shacl#"

# Second label for each DEXPI equipment class on the sheet. R-201 and R-202 are the only
# pressure vessels on 200-PID-002, and both are reactors.
CLASS_LABEL = {"TubularHeatExchanger": "Exchanger", "Furnace": "FiredHeater",
               "PressureVessel": "Reactor"}

# Work type label and RIPT score for the five IMPACT Web requests in the Relate export.
WORK_TYPES = {
    "WR-200-0147": ("BundlePull", 16),
    "WR-200-0152": ("CatalystChangeout", 20),
    "WR-200-0160": ("HeaterDecoke", 12),
    "WR-200-0171": ("Retube", 9),
    "WR-200-0188": ("GeneralCleanup", 4),
}


def augment(graph, work_types=WORK_TYPES):
    """A copy of the export graph with a `labels` list on every node: equipment gets its class
    label, scope items their work type label and a `ript` score. Raises on an equipment class
    or scope item it has no rule for."""
    g = copy.deepcopy(graph)
    seen = set()
    for n in g["nodes"]:
        labels = [n["label"]]
        if n["label"] == "Equipment":
            cls = n["props"]["dexpi_class"]
            if cls not in CLASS_LABEL:
                raise ValueError(f"{n['key']}: no class label for {cls}")
            labels.append(CLASS_LABEL[cls])
        elif n["label"] == "ScopeItem":
            rid = n["props"]["request_id"]
            base = re.sub(r"-P\d{3}$", "", rid)  # padded copies share the original's type
            if base not in work_types:
                raise ValueError(f"{rid}: no work type")
            label, ript = work_types[base]
            labels.append(label)
            n["props"]["ript"] = ript
            seen.add(base)
        n["labels"] = labels
    missing = set(work_types) - seen
    if missing:
        raise ValueError(f"work types for requests not in the graph: {sorted(missing)}")
    return g


def resolve(ref, graph):
    """'tag:E-201B' or 'key:WR-200-0147' to a node key. Raises KeyError if it isn't there."""
    kind, value = ref.split(":", 1)
    for n in graph["nodes"]:
        if (kind == "key" and n["key"] == value) or (kind == "tag" and n["props"].get("tag") == value):
            return n["key"]
    raise KeyError(ref)


def node_iri(key):
    return "urn:twin:node:" + re.sub(r"[^A-Za-z0-9._-]", lambda m: f"%{ord(m.group()):02X}", key)


def _literal(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f'"{v!r}"^^<http://www.w3.org/2001/XMLSchema#double>'
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)  # a JSON string is a valid Turtle string
    raise TypeError(f"unexpected value {v!r}")


def to_turtle(graph):
    """Each node becomes an IRI with one rdf:type per label and one triple per property, and
    each relationship a triple from its start node to its end node. This is the same reading
    n10s uses for a property graph, with the vocabulary namespace on every name."""
    out = [f"@prefix n: <{VOCAB}> ."]
    for nd in graph["nodes"]:
        s = f"<{node_iri(nd['key'])}>"
        for lbl in nd.get("labels", [nd["label"]]):
            out.append(f"{s} a n:{lbl} .")
        for k, v in sorted(nd["props"].items()):
            if v is None:
                continue
            for item in (v if isinstance(v, list) else [v]):
                out.append(f"{s} n:{k} {_literal(item)} .")
    for r in graph["rels"]:
        out.append(f"<{node_iri(r['from'])}> n:{r['type']} <{node_iri(r['to'])}> .")
    return "\n".join(out) + "\n"


def _local(v):
    s = str(v)
    return re.split(r"[#/]", s)[-1]


def pyshacl_violations(data_ttl, shapes_ttl):
    """Violations from pySHACL as (node key, target label, constraint, path)."""
    import pyshacl
    import rdflib
    from urllib.parse import unquote

    shapes = rdflib.Graph().parse(data=shapes_ttl, format="turtle")
    data = rdflib.Graph().parse(data=data_ttl, format="turtle")
    conforms, report, _ = pyshacl.validate(data, shacl_graph=shapes, inference="none",
                                           allow_warnings=False)
    sh = rdflib.Namespace(SH)
    target_of = {}
    for ns, ps in shapes.subject_objects(sh.property):
        target_of[ps] = _local(shapes.value(ns, sh.targetClass))
    out = set()
    for res in report.subjects(rdflib.RDF.type, sh.ValidationResult):
        focus = str(report.value(res, sh.focusNode))
        if not focus.startswith("urn:twin:node:"):
            raise ValueError(f"unexpected focus node {focus}")
        shape = report.value(res, sh.sourceShape)
        out.add((unquote(focus[len("urn:twin:node:"):]), target_of.get(shape, "?"),
                 _local(report.value(res, sh.sourceConstraintComponent)),
                 _local(report.value(res, sh.resultPath))))
    if conforms != (not out):
        raise ValueError("pySHACL conforms flag disagrees with its report")
    return out


def n10s_violations(rows, key_of):
    """Rows from n10s.validation.shacl.validate() as (node key, label, constraint, path).
    `key_of` maps n10s focus node ids to node keys. Raises KeyError on an unknown id."""
    return {(key_of[r["focusNode"]], r["nodeType"], _local(r["propertyShape"]),
             _local(r["resultPath"])) for r in rows}


def expected_violations(mutant, clean, mutated):
    """A mutant's hand-written expectations as node keys. 'key:{TAG}' refs are looked up by
    tag in the clean graph, because the mutant may have changed that tag. Other refs are looked
    up in the mutated graph, which holds any node the mutant created."""
    import mutants
    out = set()
    for ref, label, comp, path in mutant["expect"]:
        out.add((resolve(mutants.resolve_braces(ref, clean), mutated), label, comp, path))
    return out


_MERGED = {"MinCountConstraintComponent": "CountConstraintComponent",
           "MaxCountConstraintComponent": "CountConstraintComponent",
           "MinInclusiveConstraintComponent": "ValueRangeConstraintComponent",
           "MaxInclusiveConstraintComponent": "ValueRangeConstraintComponent",
           "MinExclusiveConstraintComponent": "ValueRangeConstraintComponent",
           "MaxExclusiveConstraintComponent": "ValueRangeConstraintComponent"}


def merge_bounds(violations):
    """Violations with min/max count and range components folded into the two merged names n10s
    reports when a property shape has both bounds. Coarser, so only for comparing with n10s."""
    return {(k, lbl, _MERGED.get(c, c), p) for k, lbl, c, p in violations}


def strip_pad_suffix(graph):
    """A copy of a padded graph with the -P001 style suffix taken off `tag` and `request_id`, so
    the copies pass the tag and request ID patterns. Node keys keep the suffix and stay unique.
    Tags then repeat across copies, which the shapes allow: tag uniqueness is a Neo4j
    constraint's job, not SHACL's."""
    g = copy.deepcopy(graph)
    for n in g["nodes"]:
        for prop in ("tag", "request_id"):
            v = n["props"].get(prop)
            if isinstance(v, str):
                n["props"][prop] = re.sub(r"-P\d{3}$", "", v)
    return g
