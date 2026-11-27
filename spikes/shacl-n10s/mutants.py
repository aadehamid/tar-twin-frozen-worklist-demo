"""Mutants for checks N6 and N7. Each is one Cypher write that breaks one rule, with the
violations a correct SHACL engine must report for it, written by hand from shapes.ttl.

Expectations are (ref, label, constraint, path), where ref is 'tag:<tag>' or 'key:<node key>'
and label is the target class of the shape that fires. Every write is parameterised and
checked by run_spike.py to touch at least one node or relationship.
"""

PATTERN = "PatternConstraintComponent"
MIN = "MinCountConstraintComponent"
MAX = "MaxCountConstraintComponent"
CLASS = "ClassConstraintComponent"
IN = "InConstraintComponent"
DATATYPE = "DatatypeConstraintComponent"
MAXINC = "MaxInclusiveConstraintComponent"

MUTANTS = [
    {"id": "M01", "shape": "S1", "what": "equipment tag without its dash",
     "cypher": "MATCH (e:Equipment {tag: $tag}) SET e.tag = $value",
     "params": {"tag": "E-201B", "value": "E201B"},
     "expect": [("key:{E-201B}", "Equipment", PATTERN, "tag")]},
    {"id": "M02", "shape": "S1", "what": "equipment tag removed",
     "cypher": "MATCH (e:Equipment {tag: $tag}) REMOVE e.tag",
     "params": {"tag": "R-202"},
     "expect": [("key:{R-202}", "Equipment", MIN, "tag")]},
    {"id": "M03", "shape": "S1", "what": "equipment tag stored as a number",
     "cypher": "MATCH (e:Equipment {tag: $tag}) SET e.tag = $value",
     "params": {"tag": "E-201C", "value": 201},
     # SHACL checks sh:pattern against the string form of any literal, so 201 also fails it.
     "expect": [("key:{E-201C}", "Equipment", DATATYPE, "tag"),
                ("key:{E-201C}", "Equipment", PATTERN, "tag")]},
    {"id": "M04", "shape": "S2", "what": "nozzle link to a valve",
     "cypher": "MATCH (e:Equipment {tag: $tag}), (v:Valve {tag: $valve}) CREATE (e)-[:HAS_NOZZLE]->(v)",
     "params": {"tag": "E-201A", "valve": "HV-2001"},
     "expect": [("tag:E-201A", "Equipment", CLASS, "HAS_NOZZLE")]},
    {"id": "M05", "shape": "S2", "what": "equipment taken off its sheet",
     "cypher": "MATCH (e:Equipment {tag: $tag})-[r:ON_SHEET]->() DELETE r",
     "params": {"tag": "H-201"},
     "expect": [("tag:H-201", "Equipment", MIN, "ON_SHEET")]},
    {"id": "M06", "shape": "S3", "what": "valve role outside the list",
     "cypher": "MATCH (v:Valve {tag: $tag}) SET v.role = $value",
     "params": {"tag": "HV-2002", "value": "isolation"},
     "expect": [("tag:HV-2002", "Valve", IN, "role")]},
    {"id": "M07", "shape": "S3", "what": "valve tag without its dash",
     "cypher": "MATCH (v:Valve {tag: $tag}) SET v.tag = $value",
     "params": {"tag": "FV-2011", "value": "FV2011"},
     "expect": [("key:{FV-2011}", "Valve", PATTERN, "tag")]},
    {"id": "M08", "shape": "S4", "what": "request ID in the wrong format",
     "cypher": "MATCH (s:ScopeItem {request_id: $rid}) SET s.request_id = $value",
     "params": {"rid": "WR-200-0160", "value": "WR-0160"},
     "expect": [("key:WR-200-0160", "ScopeItem", PATTERN, "request_id")]},
    {"id": "M09", "shape": "S4", "what": "RIPT score above 25",
     "cypher": "MATCH (s:ScopeItem {request_id: $rid}) SET s.ript = $value",
     "params": {"rid": "WR-200-0152", "value": 30},
     "expect": [("key:WR-200-0152", "ScopeItem", MAXINC, "ript")]},
    {"id": "M10", "shape": "S4", "what": "second equipment match",
     "cypher": "MATCH (s:ScopeItem {request_id: $rid}), (e:Equipment {tag: $tag}) CREATE (s)-[:RESOLVES_TO]->(e)",
     "params": {"rid": "WR-200-0147", "tag": "E-201C"},
     "expect": [("key:WR-200-0147", "ScopeItem", MAX, "RESOLVES_TO")]},
    {"id": "M11", "shape": "S4", "what": "match to something that isn't equipment",
     "cypher": "MATCH (s:ScopeItem {request_id: $rid}), (p:PidSheet) CREATE (s)-[:RESOLVES_TO]->(p)",
     "params": {"rid": "WR-200-0188"},
     "expect": [("key:WR-200-0188", "ScopeItem", CLASS, "RESOLVES_TO")]},
    {"id": "M12", "shape": "S4", "what": "exercise ID removed",
     "cypher": "MATCH (s:ScopeItem {request_id: $rid}) REMOVE s.exercise_id",
     "params": {"rid": "WR-200-0171"},
     "expect": [("key:WR-200-0171", "ScopeItem", MIN, "exercise_id")]},
    {"id": "M13", "shape": "S5", "what": "bundle pull moved to a reactor",
     "cypher": "MATCH (s:ScopeItem {request_id: $rid})-[r:RESOLVES_TO]->(), (e:Equipment {tag: $tag}) "
               "DELETE r CREATE (s)-[:RESOLVES_TO]->(e)",
     "params": {"rid": "WR-200-0147", "tag": "R-202"},
     "expect": [("key:WR-200-0147", "BundlePull", CLASS, "RESOLVES_TO")]},
    {"id": "M14", "shape": "S5", "what": "retube moved to the heater",
     "cypher": "MATCH (s:ScopeItem {request_id: $rid})-[r:RESOLVES_TO]->(), (e:Equipment {tag: $tag}) "
               "DELETE r CREATE (s)-[:RESOLVES_TO]->(e)",
     "params": {"rid": "WR-200-0171", "tag": "H-201"},
     "expect": [("key:WR-200-0171", "Retube", CLASS, "RESOLVES_TO")]},
    {"id": "M15", "shape": "S6", "what": "catalyst changeout moved to an exchanger",
     "cypher": "MATCH (s:ScopeItem {request_id: $rid})-[r:RESOLVES_TO]->(), (e:Equipment {tag: $tag}) "
               "DELETE r CREATE (s)-[:RESOLVES_TO]->(e)",
     "params": {"rid": "WR-200-0152", "tag": "E-201A"},
     "expect": [("key:WR-200-0152", "CatalystChangeout", CLASS, "RESOLVES_TO")]},
    {"id": "M16", "shape": "S7", "what": "heater decoke moved to a reactor",
     "cypher": "MATCH (s:ScopeItem {request_id: $rid})-[r:RESOLVES_TO]->(), (e:Equipment {tag: $tag}) "
               "DELETE r CREATE (s)-[:RESOLVES_TO]->(e)",
     "params": {"rid": "WR-200-0160", "tag": "R-201"},
     "expect": [("key:WR-200-0160", "HeaterDecoke", CLASS, "RESOLVES_TO")]},
    {"id": "M17", "shape": "S8", "what": "envelope loses its boundary valves",
     "cypher": "MATCH (:IsolationEnvelope {id: $env})-[r:BOUNDED_BY]->() DELETE r",
     "params": {"env": "ENV-200-02"},
     "expect": [("key:ENV-200-02", "IsolationEnvelope", MIN, "BOUNDED_BY")]},
    {"id": "M18", "shape": "S1", "what": "a new piece of equipment with a Unit 300 tag",
     "cypher": "MATCH (p:PidSheet) CREATE (e:Equipment:Exchanger {key: $key, tag: $tag, dexpi_class: $cls})"
               "-[:ON_SHEET]->(p)",
     "params": {"key": "NEW-E-301", "tag": "E-301", "cls": "TubularHeatExchanger"},
     "expect": [("key:NEW-E-301", "Equipment", PATTERN, "tag")]},
]


def resolve_braces(ref, graph):
    """'key:{E-201B}' means the key of the node whose tag is E-201B in the clean graph. It's used
    when the mutant changes or removes the tag itself, so the tag can't find the node after."""
    kind, value = ref.split(":", 1)
    if kind == "key" and value.startswith("{") and value.endswith("}"):
        tag = value[1:-1]
        for n in graph["nodes"]:
            if n["props"].get("tag") == tag:
                return "key:" + n["key"]
        raise KeyError(ref)
    return ref
