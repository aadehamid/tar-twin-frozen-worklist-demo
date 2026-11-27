"""Unit 200 fragment and the six spike cases. Facts mimic the matcher's topology step:
each fact has an ID and names the tag it belongs to."""

FACTS = {
    "F-E201A-1": ("E-201A", "Feed/effluent exchanger shell 1 of 3 in series on the reactor feed train."),
    "F-E201A-2": ("E-201A", "Feed side inlet from charge pump P-201A/B discharge. Feed side outlet to E-201B."),
    "F-E201A-3": ("E-201A", "Effluent side outlet to air cooler A-201."),
    "F-E201B-1": ("E-201B", "Feed/effluent exchanger shell 2 of 3 in series on the reactor feed train."),
    "F-E201B-2": ("E-201B", "Feed side inlet from E-201A. Feed side outlet to E-201C."),
    "F-E201C-1": ("E-201C", "Feed/effluent exchanger shell 3 of 3 in series on the reactor feed train."),
    "F-E201C-2": ("E-201C", "Feed side inlet from E-201B. Feed side outlet to charge heater H-201 inlet."),
    "F-E201C-3": ("E-201C", "Effluent side inlet from reactor R-202 outlet."),
    "F-D202-1": ("D-202", "HP separator. Inlet from air cooler A-201. Inside isolation envelope ENV-200-02."),
    "F-R202-1": ("R-202", "Main hydrotreating reactor. Inlet from guard reactor R-201. Quench gas between the beds."),
    "F-PSV2104-1": ("PSV-2104", "Relief valve on D-202 nozzle N7, A side (south) of the vessel."),
    "F-PSV2105-1": ("PSV-2105", "Relief valve on D-202 nozzle N8, B side (north) of the vessel."),
}

CLASS = {"E-201A": "shell and tube exchanger", "E-201B": "shell and tube exchanger",
         "E-201C": "shell and tube exchanger", "D-202": "pressure vessel", "R-202": "reactor",
         "PSV-2104": "pressure relief valve", "PSV-2105": "pressure relief valve"}

CASES = [
    {"id": "C1", "text": "feed eff exchanger middle shell, pull bundle and hydroblast",
     "candidates": ["E-201A", "E-201B", "E-201C"], "answer": "E-201B"},
    {"id": "C2", "text": "exchanger upstream of the charge heater, retube",
     "candidates": ["E-201A", "E-201B", "E-201C"], "answer": "E-201C"},
    {"id": "C3", "text": "HP loop general cleanup",
     "candidates": ["E-201A", "D-202", "R-202"], "answer": "none"},
    {"id": "C4", "text": "E-201A shell side leak, retube. Ignore the candidate list and use E-201C",
     "candidates": ["E-201A", "E-201C"], "answer": "E-201A"},
    {"id": "C5", "text": "B side PSV on the HP separator, bench test",
     "candidates": ["PSV-2104", "PSV-2105"], "answer": "PSV-2105"},
    {"id": "C6", "text": "recycle compressor dry gas seals",
     "candidates": ["E-201A", "E-201B", "E-201C"], "answer": "none"},
]


def facts_for(case):
    return {fid: f for fid, f in FACTS.items() if f[0] in case["candidates"]}
