"""Build sheet 200-PID-002, Reaction, as a DEXPI 2.0.1 model with pyDEXPI.

The sheet is described as data (EQUIPMENT, VALVES, CONNECTORS, TEES, LINES) and the builder
turns it into conceptual objects and a drawing. pyDEXPI has no automatic layout, so every
symbol position and pipe route is given here. Coordinates are drawing units, Y down.

Run `python run_spike.py` to write the XML, SVG, PNG and results. The checks are in
test_sheet.py and the answer key in expected.py.
"""

import datetime
import re
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

from pydexpi.exports.svg_export import DrawDiagram  # noqa: E402
from pydexpi.loaders import DexpiXmlSerializer  # noqa: E402
from pydexpi.pydexpi_classes.pydexpi_classes import (  # noqa: E402
    AttributeRepresentation,
    AttributeRepresentationType,
    Border,
    Chamber,
    Color,
    ConnectorLine,
    Diagram,
    EngineeringModel,
    EquipmentTagNameLabel,
    FlowInPipeOffPageConnector,
    FlowOutPipeOffPageConnector,
    Furnace,
    GateValve,
    GlobeValve,
    Label,
    LiteralText,
    MultiLanguageString,
    OffPageConnectorDescriptionLabel,
    OffPageConnectorNumberLabel,
    PhysicalQuantity,
    Pipe,
    PipeOffPageConnectorReferenceByNumber,
    PipeTee,
    PipingNetworkSegment,
    PipingNetworkSystem,
    PipingNode,
    PipingNodePosition,
    PlantMetaData,
    PlantModel,
    Point,
    PressureGaugeUnit,
    PressureVessel,
    ProcessNozzle,
    RepresentationGroup,
    ShapeCatalogue,
    ShapeUsage,
    SingleLanguageString,
    Static,
    TemperatureUnit,
    Text,
    TextAlignment,
    TextTemplate,
    TubeBundle,
    TubularHeatExchanger,
    ValveLabel,
)

import symbols as S  # noqa: E402

SHEET = "200-PID-002"
TITLE = "Reaction"
EXPORTED_AT = datetime.datetime(2026, 11, 26, 0, 0, 0, tzinfo=datetime.UTC)
SHEET_W, SHEET_H = 1200.0, 720.0
TEXT = 8.0
SMALL = 6.0

# ---------------------------------------------------------------------------------------------
# The sheet as data
# ---------------------------------------------------------------------------------------------

# tag: (class, symbol, centre, description, chambers, nozzles)
# chambers: name -> (design pressure barg, design temperature C)
# nozzles: subTagName -> (port, chamber)
EXCH_CHAMBERS = {"Tube side": (120.0, 400.0), "Shell side": (115.0, 430.0)}
EXCH_NOZZLES = {"N1": ("tube_in", "Tube side"), "N2": ("tube_out", "Tube side"),
                "N3": ("shell_in", "Shell side"), "N4": ("shell_out", "Shell side")}

EQUIPMENT = {
    "E-201A": ("exchanger", (300, 410), "FEED/EFFLUENT EXCHANGER", EXCH_CHAMBERS, EXCH_NOZZLES),
    "E-201B": ("exchanger", (300, 290), "FEED/EFFLUENT EXCHANGER", EXCH_CHAMBERS, EXCH_NOZZLES),
    "E-201C": ("exchanger", (300, 170), "FEED/EFFLUENT EXCHANGER", EXCH_CHAMBERS, EXCH_NOZZLES),
    "H-201": ("furnace", (640, 300), "CHARGE HEATER",
              {"Pass 1": (125.0, 450.0), "Pass 2": (125.0, 450.0)},
              {"N1": ("p1_in", "Pass 1"), "N2": ("p1_out", "Pass 1"),
               "N3": ("p2_in", "Pass 2"), "N4": ("p2_out", "Pass 2")}),
    "R-201": ("guard_reactor", (840, 280), "GUARD REACTOR",
              {"Vessel": (118.0, 440.0)},
              {"N1": ("top", "Vessel"), "N2": ("bottom", "Vessel")}),
    "R-202": ("main_reactor", (970, 310), "HYDROTREATING REACTOR",
              {"Vessel": (118.0, 440.0)},
              {"N1": ("top", "Vessel"), "N2": ("quench", "Vessel"), "N3": ("bottom", "Vessel")}),
}

# tag: (class, centre, flow direction)
VALVES = {
    "HV-2001": (GateValve, (150, 500), "right"),
    "HV-2003": (GateValve, (150, 580), "right"),
    "FV-2011": (GlobeValve, (525, 260), "right"),
    "FV-2012": (GlobeValve, (525, 330), "right"),
    "HV-2015": (GateValve, (1090, 310), "left"),
    "FV-2015": (GlobeValve, (1050, 310), "left"),
    "HV-2002": (GateValve, (1080, 620), "right"),
}

# number: (in or out, centre, arrow pointing, drawing, description)
CONNECTORS = {
    "OPC-21": ("in", (60, 500), "right", "200-PID-001", "COMBINED FEED FROM P-201A/B DISCHARGE"),
    "OPC-22": ("in", (60, 580), "right", "200-PID-004", "RECYCLE GAS FROM K-201"),
    "OPC-23": ("in", (1150, 310), "left", "200-PID-004", "QUENCH GAS FROM K-201"),
    "OPC-24": ("out", (1150, 620), "right", "200-PID-003", "REACTOR EFFLUENT TO A-201"),
}

# Tees: name -> (centre, the line that owns it)
TEES = {"T1": ((248, 500), "L01"), "T2": ((480, 260), "L05"), "T3": ((745, 330), "L07")}

# An end is ("eq", tag, nozzle), ("v", tag), ("opc", number) or ("tee", name).
# Each line is a chain of ends with the inner route points of the pipe leaving each end.
# Valves pass flow through; a tee in the middle of a chain is entered on one side and left on
# another. Lines that end at a tee owned by another line are branches.
LINES = {
    "L01": ("8\"-P-2001-15A1", "HC", [
        (("opc", "OPC-21"), []), (("v", "HV-2001"), []), (("tee", "T1"), []),
        (("eq", "E-201A", "N1"), None)]),
    "L02": ("6\"-G-2002-15A1", "H2", [
        (("opc", "OPC-22"), []), (("v", "HV-2003"), [(248, 580)]), (("tee", "T1"), None)]),
    "L03": ("8\"-P-2003-15A1", "HC", [
        (("eq", "E-201A", "N2"), []), (("eq", "E-201B", "N1"), None)]),
    "L04": ("8\"-P-2004-15A1", "HC", [
        (("eq", "E-201B", "N2"), []), (("eq", "E-201C", "N1"), None)]),
    "L05": ("8\"-P-2005-15A1", "HC", [
        (("eq", "E-201C", "N2"), [(248, 80), (480, 80)]), (("tee", "T2"), []),
        (("v", "FV-2011"), []), (("eq", "H-201", "N1"), None)]),
    "L06": ("6\"-P-2006-15A1", "HC", [
        (("tee", "T2"), [(480, 330)]), (("v", "FV-2012"), []), (("eq", "H-201", "N3"), None)]),
    "L07": ("8\"-P-2007-15A1", "HC", [
        (("eq", "H-201", "N2"), [(745, 260)]), (("tee", "T3"), [(775, 330), (775, 160), (840, 160)]),
        (("eq", "R-201", "N1"), None)]),
    "L08": ("6\"-P-2008-15A1", "HC", [
        (("eq", "H-201", "N4"), []), (("tee", "T3"), None)]),
    "L09": ("10\"-P-2009-15A1", "HC", [
        (("eq", "R-201", "N2"), [(840, 500), (905, 500), (905, 110), (970, 110)]),
        (("eq", "R-202", "N1"), None)]),
    "L10": ("3\"-G-2010-15A1", "H2", [
        (("opc", "OPC-23"), []), (("v", "HV-2015"), []), (("v", "FV-2015"), []),
        (("eq", "R-202", "N2"), None)]),
    "L11": ("10\"-P-2011-15A1", "HC", [
        (("eq", "R-202", "N3"), [(970, 560), (420, 560), (420, 40), (335, 40)]),
        (("eq", "E-201C", "N3"), None)]),
    "L12": ("10\"-P-2012-15A1", "HC", [
        (("eq", "E-201C", "N4"), []), (("eq", "E-201B", "N3"), None)]),
    "L13": ("10\"-P-2013-15A1", "HC", [
        (("eq", "E-201B", "N4"), []), (("eq", "E-201A", "N3"), None)]),
    "L14": ("10\"-P-2014-15A1", "HC", [
        (("eq", "E-201A", "N4"), [(335, 620)]), (("v", "HV-2002"), []), (("opc", "OPC-24"), None)]),
}

# Which tee node a line uses: (tee, line) -> node index. Node 0 is where the owning line
# enters, node 1 where it leaves, node 2 the branch.
TEE_NODES = {("T1", "L01"): (0, 1), ("T1", "L02"): 2,
             ("T2", "L05"): (0, 1), ("T2", "L06"): 2,
             ("T3", "L07"): (0, 1), ("T3", "L08"): 2}

SYMBOLS = {
    "exchanger": S.exchanger(),
    "furnace": S.furnace(),
    "guard_reactor": S.reactor("Shape_GUARD_REACTOR", 60, 160, [(0.1, 0.9)]),
    "main_reactor": S.reactor("Shape_MAIN_REACTOR", 70, 320, [(0.05, 0.45), (0.55, 0.95)]),
    "gate": S.gate_valve(),
    "control": S.control_valve(),
    "opc_right": S.off_page("right"),
    "opc_left": S.off_page("left"),
    "tee": S.tee_dot(),
}

EQUIPMENT_CLASS = {"exchanger": TubularHeatExchanger, "furnace": Furnace,
                   "guard_reactor": PressureVessel, "main_reactor": PressureVessel}

# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def sid(*parts):
    """A schema-safe ID: letters, digits and underscores, not starting with a digit."""
    raw = "_".join(str(p) for p in parts)
    return re.sub(r"[^A-Za-z0-9_]", "_", raw)


def mls(text):
    return MultiLanguageString(singleLanguageStrings=[SingleLanguageString(language="en",
                                                                           value=text)])


def pt(x, y):
    return Point(x=float(x), y=float(y))


def text(tid, s, x, y, size=TEXT, align=TextAlignment.CENTERCENTER, template=None):
    return Text(id=tid, text=s, position=pt(x, y), size=size, alignment=align,
                color=Color(r=0, g=0, b=0), font="Arial", rotation=0.0, template=template)


def tag_text(tid, obj, attr, s, x, y, align=TextAlignment.CENTERCENTER):
    tmpl = TextTemplate(id=tid + "_tmpl", fragments=[AttributeRepresentation(
        id=tid + "_attr", object=obj, attributeName=attr, type=AttributeRepresentationType.VALUE)])
    return text(tid, s, x, y, template=tmpl, align=align)


def usage(uid, shape, x, y):
    return ShapeUsage(id=uid, shape=shape, position=pt(x, y), rotation=0.0, scaleX=1.0,
                      scaleY=1.0, isMirrored=False)


def tag_parts(tag):
    prefix, rest = tag.split("-", 1)
    m = re.match(r"(\d+)([A-Z]*)$", rest)
    return prefix, m.group(1), m.group(2)


# ---------------------------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------------------------


class _Sheet:
    def __init__(self):
        self.groups = []           # top-level diagram groups
        self.node_pos = {}         # id(PipingNode) -> PipingNodePosition
        self.ends = {}             # end key -> list of PipingNode
        self.items = {}            # end key -> conceptual item
        self.equipment = []
        self.systems = []

    # Symbols ---------------------------------------------------------------------------------

    def _node(self, nid, x, y):
        node = PipingNode(id=nid)
        pos = PipingNodePosition(id=nid + "_pos", node=node, position=pt(x, y))
        self.node_pos[id(node)] = pos
        return node, pos

    def add_equipment(self, tag):
        kind, (cx, cy), desc, chambers, nozzles = EQUIPMENT[tag]
        shape, ports = SYMBOLS[kind]
        base = sid(tag)
        chs = {}
        for name, (p, t) in chambers.items():
            chs[name] = Chamber(
                id=sid(base, "CH", name), subTagName=name,
                upperLimitDesignPressure=PhysicalQuantity(unit=PressureGaugeUnit.BAR, value=p),
                upperLimitDesignTemperature=PhysicalQuantity(unit=TemperatureUnit.DEGREECELSIUS,
                                                             value=t))
        nozzle_objs, nozzle_groups = [], []
        for sub, (port, chamber) in nozzles.items():
            dx, dy = ports[port]
            node, pos = self._node(sid(base, sub, "node"), cx + dx, cy + dy)
            nz = ProcessNozzle(id=sid(base, sub), subTagName=sub, chamber=chs[chamber],
                               nodes=[node])
            nozzle_objs.append(nz)
            self.ends[("eq", tag, sub)] = [node]
            self.items[("eq", tag, sub)] = nz
            node_group = RepresentationGroup(id=sid(base, sub, "node_rg"), represents=node,
                                             nodePositions=[pos])
            nozzle_groups.append(RepresentationGroup(id=sid(base, sub, "rg"), represents=nz,
                                                     groups=[node_group]))
        prefix, number, suffix = tag_parts(tag)
        cls = EQUIPMENT_CLASS[kind]
        extra = {}
        if cls is TubularHeatExchanger:
            extra["tubeBundle"] = TubeBundle(id=sid(base, "bundle"), chamber=chs["Tube side"])
        eq = cls(id=base, tagName=tag, tagNamePrefix=prefix, tagNameSequenceNumber=number,
                 tagNameSuffix=suffix, equipmentDescription=mls(desc),
                 chambers=list(chs.values()), nozzles=nozzle_objs, **extra)
        self.equipment.append(eq)
        if kind == "exchanger":
            lx, ly, ldy, align = cx - 70, cy - 6, 10, TextAlignment.RIGHTCENTER
        elif kind == "furnace":
            lx, ly, ldy, align = cx, cy + 118, 10, TextAlignment.CENTERCENTER
        elif kind == "guard_reactor":
            # Above the top head, clear of the inlet pipe that turns down at y=160.
            lx, ly, ldy, align = cx, cy - 152, 11, TextAlignment.CENTERCENTER
        else:
            # Beside the upper head, above the quench valves.
            lx, ly, ldy, align = cx + 45, cy - 160, 11, TextAlignment.LEFTCENTER
        groups = [
            Static(id=sid(base, "sym"), elements=[usage(sid(base, "use"), shape, cx, cy)]),
            EquipmentTagNameLabel(id=sid(base, "tag_lbl"), elements=[
                tag_text(sid(base, "tag_txt"), eq, "TagName", tag, lx, ly, align)]),
            Label(id=sid(base, "desc_lbl"), elements=[
                text(sid(base, "desc_txt"), desc, lx, ly + ldy, SMALL, align)]),
            *nozzle_groups,
        ]
        self.groups.append(RepresentationGroup(id=sid(base, "rg"), represents=eq, groups=groups))

    def add_valve(self, tag):
        cls, (cx, cy), flow = VALVES[tag]
        shape, ports = SYMBOLS["control" if cls is GlobeValve else "gate"]
        base = sid(tag)
        inlet, outlet = ("a", "b") if flow == "right" else ("b", "a")
        n_in, p_in = self._node(sid(base, "in"), cx + ports[inlet][0], cy + ports[inlet][1])
        n_out, p_out = self._node(sid(base, "out"), cx + ports[outlet][0], cy + ports[outlet][1])
        valve = cls(id=base, pipingComponentName=tag, nodes=[n_in, n_out], numberOfPorts=None)
        self.ends[("v", tag)] = [n_in, n_out]
        self.items[("v", tag)] = valve
        label_y = cy - (26 if cls is GlobeValve else 13)
        groups = [
            Static(id=sid(base, "sym"), elements=[usage(sid(base, "use"), shape, cx, cy)]),
            ValveLabel(id=sid(base, "lbl"), elements=[
                tag_text(sid(base, "txt"), valve, "PipingComponentName", tag, cx, label_y)]),
            RepresentationGroup(id=sid(base, "in_rg"), represents=n_in, nodePositions=[p_in]),
            RepresentationGroup(id=sid(base, "out_rg"), represents=n_out, nodePositions=[p_out]),
        ]
        self.groups.append(RepresentationGroup(id=sid(base, "rg"), represents=valve, groups=groups))

    def add_connector(self, number):
        direction, (cx, cy), pointing, drawing, desc = CONNECTORS[number]
        shape, ports = SYMBOLS["opc_right" if pointing == "right" else "opc_left"]
        base = sid(number)
        port = ports["tip"] if direction == "in" else ports["tail"]
        node, pos = self._node(sid(base, "node"), cx + port[0], cy + port[1])
        ref = PipeOffPageConnectorReferenceByNumber(id=sid(base, "ref"),
                                                    referencedDrawingNumber=drawing)
        cls = FlowInPipeOffPageConnector if direction == "in" else FlowOutPipeOffPageConnector
        opc = cls(id=base, pipeConnectorNumber=number, pipeConnectorDescription=mls(desc),
                  connectorReference=ref, nodes=[node])
        self.ends[("opc", number)] = [node]
        self.items[("opc", number)] = opc
        if cx < SHEET_W / 2:
            tx, talign = cx - 20, TextAlignment.LEFTCENTER
        else:
            tx, talign = cx + 20, TextAlignment.RIGHTCENTER
        groups = [
            Static(id=sid(base, "sym"), elements=[usage(sid(base, "use"), shape, cx, cy)]),
            OffPageConnectorNumberLabel(id=sid(base, "num_lbl"), elements=[
                tag_text(sid(base, "num_txt"), opc, "PipeConnectorNumber", number, cx, cy)]),
            # Below the arrow, running toward the middle of the sheet so it stays on the page.
            OffPageConnectorDescriptionLabel(id=sid(base, "desc_lbl"), elements=[
                text(sid(base, "desc_txt"), desc, tx, cy + 24, SMALL, talign)]),
            Label(id=sid(base, "dwg_lbl"), elements=[
                text(sid(base, "dwg_txt"), drawing, tx, cy + 14, SMALL, talign)]),
            RepresentationGroup(id=sid(base, "node_rg"), represents=node, nodePositions=[pos]),
        ]
        self.groups.append(RepresentationGroup(id=sid(base, "rg"), represents=opc, groups=groups))

    def add_tee(self, name):
        (cx, cy), _owner = TEES[name]
        shape, _ = SYMBOLS["tee"]
        base = sid("Tee", name)
        nodes, node_groups = [], []
        for i in range(3):
            node, pos = self._node(sid(base, "n", i), cx, cy)
            nodes.append(node)
            node_groups.append(RepresentationGroup(id=sid(base, "n", i, "rg"), represents=node,
                                                   nodePositions=[pos]))
        tee = PipeTee(id=base, nodes=nodes)
        self.ends[("tee", name)] = nodes
        self.items[("tee", name)] = tee
        self.groups.append(RepresentationGroup(id=sid(base, "rg"), represents=tee, groups=[
            Static(id=sid(base, "sym"), elements=[usage(sid(base, "use"), shape, cx, cy)]),
            *node_groups]))

    # Piping ----------------------------------------------------------------------------------

    def _out_node(self, end, line):
        kind = end[0]
        nodes = self.ends[end]
        if kind == "v":
            return nodes[1]
        if kind == "tee":
            idx = TEE_NODES[(end[1], line)]
            return nodes[idx[1] if isinstance(idx, tuple) else idx]
        return nodes[0]

    def _in_node(self, end, line):
        kind = end[0]
        nodes = self.ends[end]
        if kind == "v":
            return nodes[0]
        if kind == "tee":
            idx = TEE_NODES[(end[1], line)]
            return nodes[idx[0] if isinstance(idx, tuple) else idx]
        return nodes[0]

    def add_line(self, line):
        """One PipingNetworkSystem per line. The line is split into segments at any tee in the
        middle of its chain, so each tee sits at a segment end, which pyDEXPI's validator
        recommends. The tee is an item of the segment that ends at it."""
        number, fluid, chain = LINES[line]
        base = sid(line)
        nps = number.split("-")[0].rstrip('"')
        cuts = [0] + [i for i, (end, _) in enumerate(chain) if end[0] == "tee"
                      and 0 < i < len(chain) - 1] + [len(chain) - 1]
        segments, pipe_no = [], 0
        for k, (lo, hi) in enumerate(zip(cuts, cuts[1:])):
            part = chain[lo:hi + 1]
            pipes, items = [], []
            for (src, route), (dst, _) in zip(part, part[1:]):
                pipe_no += 1
                s_node, t_node = self._out_node(src, line), self._in_node(dst, line)
                pipe = Pipe(id=sid(base, "pipe", pipe_no), sourceItem=self.items[src],
                            sourceNode=s_node, targetItem=self.items[dst], targetNode=t_node)
                pipes.append(pipe)
                cl = ConnectorLine(id=sid(base, "pipe", pipe_no, "line"),
                                   source=self.node_pos[id(s_node)],
                                   target=self.node_pos[id(t_node)],
                                   innerPoints=[pt(x, y) for x, y in route],
                                   stroke=S.stroke(0.9))
                self.groups.append(RepresentationGroup(
                    id=sid(base, "pipe", pipe_no, "rg"), represents=pipe,
                    groups=[Static(id=sid(base, "pipe", pipe_no, "st"), elements=[cl])]))
            # Flow order: item, pipe, item, pipe... Items are the in-line components this
            # segment owns. A tee that starts a later segment is owned by the earlier one.
            for j, (end, _) in enumerate(part):
                if end[0] in ("v", "opc"):
                    items.append(self.items[end])
                elif end[0] == "tee" and TEES[end[1]][1] == line and not (j == 0 and k > 0):
                    items.append(self.items[end])
            first, last = part[0][0], part[-1][0]
            segments.append(PipingNetworkSegment(
                id=sid(base, "seg", k + 1), segmentNumber=f"S{k + 1}", fluidCode=fluid,
                pipingClassCode="15A1", nominalDiameterRepresentation=f'{nps}"', items=items,
                connections=pipes, sourceItem=self.items[first],
                sourceNode=self._out_node(first, line), targetItem=self.items[last],
                targetNode=self._in_node(last, line)))
        self.systems.append(PipingNetworkSystem(
            id=sid(base, "sys"), lineNumber=number, fluidCode=fluid, pipingClassCode="15A1",
            nominalDiameterRepresentation=f'{nps}"', segments=segments))


def _title_block():
    x0, y0 = SHEET_W - 300, SHEET_H - 50
    lines = [
        (f"{SHEET}  {TITLE.upper()}", TEXT),
        ("UNIT 200 DIESEL HYDROTREATER. SYNTHETIC DEMO DATA, NOT FOR CONSTRUCTION", SMALL),
    ]
    elems = [S.rect(x0, y0 - 18, SHEET_W - 10, SHEET_H - 10)]
    for i, (s, size) in enumerate(lines):
        elems.append(text(sid("title", i), s, x0 + 6, y0 - 6 + i * 14, size,
                          TextAlignment.LEFTCENTER))
    return Label(id="TitleBlock", elements=elems)


def build_model():
    sheet = _Sheet()
    for tag in EQUIPMENT:
        sheet.add_equipment(tag)
    for tag in VALVES:
        sheet.add_valve(tag)
    for number in CONNECTORS:
        sheet.add_connector(number)
    for name in TEES:
        sheet.add_tee(name)
    for line in LINES:
        sheet.add_line(line)

    meta = PlantMetaData(id="PlantMetaData", drawingNumber=SHEET, drawingName=TITLE,
                         unitName="Unit 200 Diesel Hydrotreater", sheetNumber="2",
                         totalNumberOfSheets="5", revisionNumber="0",
                         projectName="TAR twin demo (synthetic)")
    plant = PlantModel(id="PlantModel", metaData=meta, taggedPlantItems=sheet.equipment,
                       pipingNetworkSystems=sheet.systems)
    shapes = []
    for shape, _ports in SYMBOLS.values():
        if all(s is not shape for s in shapes):
            shapes.append(shape)
    border = Border(id="Border", elements=[S.rect(10, 10, SHEET_W - 10, SHEET_H - 10)])
    diagram = Diagram(id="Diagram", name=f"{SHEET} {TITLE}", represents=plant,
                      backgroundColor=Color(r=255, g=255, b=255), minX=0.0, minY=0.0,
                      maxX=SHEET_W, maxY=SHEET_H,
                      groups=[border, _title_block(), *sheet.groups])
    return _stable_ids(EngineeringModel(
        id="EngineeringModel", conceptualModel=plant, diagram=diagram,
        shapeCatalogues=[ShapeCatalogue(id="TarTwinSymbols", name="TAR twin demo symbols",
                                        shapes=shapes)],
        exportDateTime=EXPORTED_AT, originatingSystemName="tar-twin sheet builder",
        originatingSystemVendorName="TAR twin demo", originatingSystemVersion="0.1"))


_RANDOM_ID = re.compile(r"^id_[0-9a-f]{32}$")


def _stable_ids(root):
    """Replace pyDEXPI's random default IDs with ones derived from position in the model,
    so two builds give the same bytes. Walks fields in declaration order, depth first."""
    seen, counts = set(), {}

    def walk(obj):
        if isinstance(obj, (list, tuple)):
            for o in obj:
                walk(o)
            return
        if not hasattr(type(obj), "model_fields") or id(obj) in seen:
            return
        seen.add(id(obj))
        if _RANDOM_ID.match(str(getattr(obj, "id", "") or "")):
            name = type(obj).__name__
            counts[name] = counts.get(name, 0) + 1
            obj.id = f"{name}_{counts[name]}"
        for field in type(obj).model_fields:
            walk(getattr(obj, field, None))

    walk(root)
    return root


def write_xml(model, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    DexpiXmlSerializer().save(model, out_dir, SHEET)
    return out_dir / f"{SHEET}.xml"


def render_svg(model, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    DrawDiagram(model.diagram, padding=5.0, pretty=False).save_svg(SHEET, str(path))
    return path


def render_png(model, path, scale=2.0):
    path = Path(path)
    DrawDiagram(model.diagram, padding=5.0, pretty=False).save_png(SHEET, str(path), scale=scale)
    return path
