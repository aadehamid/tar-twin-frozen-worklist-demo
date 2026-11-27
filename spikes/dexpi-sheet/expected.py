"""What sheet 200-PID-002 must contain, written by hand from docs/scenario-spec.md.

This file is the answer key for the checks. It must not import the builder, so the builder
can't grade itself. If the sheet changes on purpose, change this file in the same PR and say
why in the PR description.
"""

SHEET = "200-PID-002"
TITLE = "Reaction"

# Chamber names. An exchanger carries feed in its tubes and effluent in its shell. The heater
# has two coil passes.
TUBE = "Tube side"
SHELL = "Shell side"
PASS1 = "Pass 1"
PASS2 = "Pass 2"
FEED_SIDE = TUBE
EFFLUENT_SIDE = SHELL

# Tag -> DEXPI class. Equipment is identified by tagName.
EQUIPMENT = {
    "E-201A": "TubularHeatExchanger",
    "E-201B": "TubularHeatExchanger",
    "E-201C": "TubularHeatExchanger",
    "H-201": "Furnace",
    "R-201": "PressureVessel",
    "R-202": "PressureVessel",
}

# Valves are identified by pipingComponentName.
VALVES = {
    "HV-2001": "GateValve",   # combined feed inlet block valve
    "HV-2003": "GateValve",   # recycle gas to combined feed
    "FV-2011": "GlobeValve",  # heater pass 1 flow control
    "FV-2012": "GlobeValve",  # heater pass 2 flow control
    "HV-2015": "GateValve",   # quench gas block valve
    "FV-2015": "GlobeValve",  # quench gas flow control to R-202 interbed
    "HV-2002": "GateValve",   # reactor effluent outlet block valve
}

# Off-page connectors are identified by pipeConnectorNumber.
# number -> (class, drawing it links to, words its description must contain)
CONNECTORS = {
    "OPC-21": ("FlowInPipeOffPageConnector", "200-PID-001", "P-201A/B"),
    "OPC-22": ("FlowInPipeOffPageConnector", "200-PID-004", "recycle gas"),
    "OPC-23": ("FlowInPipeOffPageConnector", "200-PID-004", "quench"),
    "OPC-24": ("FlowOutPipeOffPageConnector", "200-PID-003", "A-201"),
}

ALL_TAGS = set(EQUIPMENT) | set(VALVES) | set(CONNECTORS)

# Chambers each piece of equipment must have, by subTagName. Vessels have one.
CHAMBERS = {
    "E-201A": {TUBE, SHELL},
    "E-201B": {TUBE, SHELL},
    "E-201C": {TUBE, SHELL},
    "H-201": {PASS1, PASS2},
    "R-201": {"Vessel"},
    "R-202": {"Vessel"},
}


def at(tag, side=None):
    """Name of a flow end. Exchangers and the heater name the chamber, the rest don't."""
    return f"{tag}[{side}]" if side else tag


# Directed flow edges between tagged items, through untagged piping and tees.
FLOW_EDGES = {
    # Combined feed in, and recycle gas joining it.
    ("OPC-21", "HV-2001"),
    ("OPC-22", "HV-2003"),
    ("HV-2001", at("E-201A", FEED_SIDE)),
    ("HV-2003", at("E-201A", FEED_SIDE)),
    # Feed side through the three shells in series.
    (at("E-201A", FEED_SIDE), at("E-201B", FEED_SIDE)),
    (at("E-201B", FEED_SIDE), at("E-201C", FEED_SIDE)),
    # Split into the two heater passes, rejoin, then the two reactors.
    (at("E-201C", FEED_SIDE), "FV-2011"),
    (at("E-201C", FEED_SIDE), "FV-2012"),
    ("FV-2011", at("H-201", PASS1)),
    ("FV-2012", at("H-201", PASS2)),
    (at("H-201", PASS1), at("R-201", "Vessel")),
    (at("H-201", PASS2), at("R-201", "Vessel")),
    (at("R-201", "Vessel"), at("R-202", "Vessel")),
    # Interbed quench.
    ("OPC-23", "HV-2015"),
    ("HV-2015", "FV-2015"),
    ("FV-2015", at("R-202", "Vessel")),
    # Effluent back through the shells, counter-current, and off the sheet.
    (at("R-202", "Vessel"), at("E-201C", EFFLUENT_SIDE)),
    (at("E-201C", EFFLUENT_SIDE), at("E-201B", EFFLUENT_SIDE)),
    (at("E-201B", EFFLUENT_SIDE), at("E-201A", EFFLUENT_SIDE)),
    (at("E-201A", EFFLUENT_SIDE), "HV-2002"),
    ("HV-2002", "OPC-24"),
}

# What each matcher fact in spikes/decider-matcher/cases.py claims about this sheet, as
# checks over the flow edges. "Upstream" and "downstream" skip valves and tees and stop at the
# first equipment or off-page connector. Every fact whose tag is on this sheet must be listed.
#
# Claim kinds:
#   ("series", tag, position, of)              tag is shell `position` of `of` on the feed side
#   ("from", tag, side, {ends})                the side's inlet comes from exactly these ends
#   ("to", tag, side, {ends})                  the side's outlet goes to exactly these ends
#   ("from_mentions", tag, side, words)        an upstream connector's description has the words
#   ("to_mentions", tag, side, words)          a downstream connector's description has the words
FACT_CLAIMS = {
    "F-E201A-1": [("series", "E-201A", 1, 3)],
    "F-E201A-2": [("from_mentions", "E-201A", FEED_SIDE, "P-201A/B"),
                  ("to", "E-201A", FEED_SIDE, {at("E-201B", FEED_SIDE)})],
    "F-E201A-3": [("to_mentions", "E-201A", EFFLUENT_SIDE, "A-201")],
    "F-E201B-1": [("series", "E-201B", 2, 3)],
    "F-E201B-2": [("from", "E-201B", FEED_SIDE, {at("E-201A", FEED_SIDE)}),
                  ("to", "E-201B", FEED_SIDE, {at("E-201C", FEED_SIDE)})],
    "F-E201C-1": [("series", "E-201C", 3, 3)],
    "F-E201C-2": [("from", "E-201C", FEED_SIDE, {at("E-201B", FEED_SIDE)}),
                  ("to", "E-201C", FEED_SIDE, {at("H-201", PASS1), at("H-201", PASS2)})],
    "F-E201C-3": [("from", "E-201C", EFFLUENT_SIDE, {at("R-202", "Vessel")})],
    "F-R202-1": [("from", "R-202", "Vessel", {at("R-201", "Vessel"), "OPC-23"})],
}
