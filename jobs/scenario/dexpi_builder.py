"""Build all 5 Unit 200 P&ID sheets as DEXPI 2.0.1 XML + SVG with pyDEXPI.

Sheet 200-PID-002 preserves the exact validated Reaction sheet from the Phase 0
spike so all 21 flow edges and all 9 matcher fact claims remain invariant.
Sheets 200-PID-001, 200-PID-003, 200-PID-004, and 200-PID-005 use the same
DEXPI 2.0.1 conceptual + graphical builder with ISO 10628-2 style shapes.
"""

from __future__ import annotations

import datetime
import math
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

from pydexpi.exports.svg_export import DrawDiagram  # noqa: E402
from pydexpi.loaders import DexpiXmlSerializer  # noqa: E402
from pydexpi.pydexpi_classes.pydexpi_classes import (  # noqa: E402
    AttributeRepresentation,
    AttributeRepresentationType,
    Border,
    CentrifugalCompressor,
    CentrifugalPump,
    Chamber,
    Color,
    ConnectorLine,
    DashStyle,
    Diagram,
    Ellipse,
    EngineeringModel,
    EquipmentTagNameLabel,
    FillStyle,
    FlowInPipeOffPageConnector,
    FlowOutPipeOffPageConnector,
    Furnace,
    GateValve,
    GlobeValve,
    HeatExchanger,
    Label,
    LiquidFilter,
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
    Polygon,
    PolyLine,
    PressureGaugeUnit,
    PressureVessel,
    ProcessColumn,
    ProcessNozzle,
    ReciprocatingCompressor,
    RepresentationGroup,
    Shape,
    ShapeCatalogue,
    ShapeUsage,
    SingleLanguageString,
    Static,
    SteamTurbine,
    Stroke,
    TemperatureUnit,
    Text,
    TextAlignment,
    TextTemplate,
    TubeBundle,
    TubularHeatExchanger,
    ValveLabel,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SPIKE_DEXPI_DIR = REPO_ROOT / "spikes" / "dexpi-sheet"

EXPORTED_AT = datetime.datetime(2026, 11, 27, 0, 0, 0, tzinfo=datetime.UTC)
SHEET_W, SHEET_H = 1200.0, 720.0
TEXT = 8.0
SMALL = 6.0
BLACK = Color(r=0, g=0, b=0)
_RANDOM_ID = re.compile(r"^id_[0-9a-f]{32}$")


def _stroke(width: float = 0.7, dash: DashStyle = DashStyle.SOLID) -> Stroke:
    return Stroke(color=BLACK, dashStyle=dash, width=width)


def _pl(*pts: tuple[float, float], dash: DashStyle = DashStyle.SOLID, width: float = 0.7) -> PolyLine:
    return PolyLine(points=[Point(x=float(x), y=float(y)) for x, y in pts], stroke=_stroke(width, dash))


def _poly(*pts: tuple[float, float], fill: FillStyle = FillStyle.TRANSPARENT) -> Polygon:
    return Polygon(points=[Point(x=float(x), y=float(y)) for x, y in pts], stroke=_stroke(), fillStyle=fill)


def _rect(x0: float, y0: float, x1: float, y1: float, dash: DashStyle = DashStyle.SOLID) -> PolyLine:
    return _pl((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0), dash=dash)


def _dot(cx: float, cy: float, r: float) -> Ellipse:
    return Ellipse(
        center=Point(x=float(cx), y=float(cy)),
        horizontalSemiAxis=float(r),
        verticalSemiAxis=float(r),
        rotation=0.0,
        stroke=_stroke(0.3),
        fillStyle=FillStyle.SOLID,
    )


def _arc(cx: float, cy: float, rx: float, ry: float, a0: float, a1: float, n: int = 16) -> list[tuple[float, float]]:
    out = []
    for i in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * i / n)
        out.append((round(cx + rx * math.cos(a), 4), round(cy + ry * math.sin(a), 4)))
    return out


def _shape(shape_id: str, name: str, prims: list) -> Shape:
    return Shape(id=shape_id, name=name, symbolRegistrationNumber="TAR-TWIN-DEMO", primitives=prims)


def _make_symbols() -> dict[str, tuple[Shape, dict[str, tuple[float, float]]]]:
    # Filter
    flt_prims = [
        _rect(-22, -26, 22, 26),
        _pl((-22, 0), (22, 0), dash=DashStyle.DASH),
        _pl((-32, 0), (-22, 0)),
        _pl((22, 0), (32, 0)),
    ]
    flt_ports = {"in": (-32, 0), "out": (32, 0)}

    # Horizontal drum
    hdrum_prims = [
        _pl((-45, -24), (45, -24)),
        _pl((-45, 24), (45, 24)),
        _pl(*_arc(-45, 0, 12, 24, 90, 270)),
        _pl(*_arc(45, 0, 12, 24, -90, 90)),
        _pl((-57, 0), (-67, 0)),
        _pl((57, 0), (67, 0)),
        _pl((0, -24), (0, -34)),
    ]
    hdrum_ports = {"in": (-67, 0), "out": (67, 0), "top": (0, -34)}

    # Vertical drum
    vdrum_prims = [
        _pl((-22, -45), (-22, 45)),
        _pl((22, -45), (22, 45)),
        _pl(*_arc(0, -45, 22, 12, 180, 360)),
        _pl(*_arc(0, 45, 22, 12, 0, 180)),
        _pl((-22, 0), (-32, 0)),
        _pl((0, -57), (0, -67)),
        _pl((0, 57), (0, 67)),
    ]
    vdrum_ports = {"in": (-32, 0), "top": (0, -67), "bottom": (0, 67)}

    # Column
    col_prims = [
        _pl((-26, -80), (-26, 80)),
        _pl((26, -80), (26, 80)),
        _pl(*_arc(0, -80, 26, 14, 180, 360)),
        _pl(*_arc(0, 80, 26, 14, 0, 180)),
        _pl((-22, -40), (22, -40), dash=DashStyle.DASH),
        _pl((-22, 0), (22, 0), dash=DashStyle.DASH),
        _pl((-22, 40), (22, 40), dash=DashStyle.DASH),
        _pl((-26, 0), (-36, 0)),
        _pl((0, -94), (0, -104)),
        _pl((0, 94), (0, 104)),
        _pl((26, -50), (36, -50)),
    ]
    col_ports = {"in": (-36, 0), "top": (0, -104), "bottom": (0, 104), "side": (36, -50)}

    # Pump
    pump_prims = [
        Ellipse(
            center=Point(x=0.0, y=0.0),
            horizontalSemiAxis=16.0,
            verticalSemiAxis=16.0,
            rotation=0.0,
            stroke=_stroke(),
            fillStyle=FillStyle.TRANSPARENT,
        ),
        _poly((-6, -10), (12, 0), (-6, 10)),
        _pl((-26, 0), (-16, 0)),
        _pl((16, 0), (26, 0)),
    ]
    pump_ports = {"in": (-26, 0), "out": (26, 0)}

    # Compressor
    comp_prims = [
        _poly((-22, -20), (22, -12), (22, 12), (-22, 20)),
        _pl((-32, 0), (-22, 0)),
        _pl((22, 0), (32, 0)),
    ]
    comp_ports = {"in": (-32, 0), "out": (32, 0)}

    # Steam turbine
    turb_prims = [
        _poly((-20, -12), (20, -20), (20, 20), (-20, 12)),
        _pl((-30, 0), (-20, 0)),
        _pl((20, 0), (30, 0)),
    ]
    turb_ports = {"in": (-30, 0), "out": (30, 0)}

    # Exchanger
    exch_prims = [
        _rect(-50, -18, -36, 18),
        _pl((-36, -18), (40, -18)),
        _pl((-36, 18), (40, 18)),
        _pl(*_arc(40, 0, 10, 18, -90, 90)),
        _pl((-36, 0), (36, 0), dash=DashStyle.DASH, width=0.4),
        _pl((-44, 18), (-44, 28)),
        _pl((-44, -18), (-44, -28)),
        _pl((30, -18), (30, -28)),
        _pl((30, 18), (30, 28)),
    ]
    exch_ports = {"in": (-44, 28), "out": (-44, -28), "in2": (30, -28), "out2": (30, 28)}

    # Air cooler
    ac_prims = [
        _rect(-55, -20, 55, 20),
        _pl((-45, 0), (45, 0)),
        Ellipse(
            center=Point(x=0.0, y=30.0),
            horizontalSemiAxis=12.0,
            verticalSemiAxis=6.0,
            rotation=0.0,
            stroke=_stroke(),
            fillStyle=FillStyle.TRANSPARENT,
        ),
        _pl((-65, 0), (-55, 0)),
        _pl((55, 0), (65, 0)),
    ]
    ac_ports = {"in": (-65, 0), "out": (65, 0)}

    # Gate & control valves
    gate_prims = [_poly((-10, -6), (10, 6), (10, -6), (-10, 6))]
    ctrl_prims = [
        _poly((-10, -6), (10, 6), (10, -6), (-10, 6)),
        _dot(0, 0, 2.2),
        _pl((0, 0), (0, -12)),
        _pl((-8, -12), (8, -12)),
        _pl(*_arc(0, -12, 8, 7, 180, 360)),
    ]
    opc_r_prims = [_poly((-20, -8), (10, -8), (20, 0), (10, 8), (-20, 8))]
    opc_l_prims = [_poly((20, -8), (-10, -8), (-20, 0), (-10, 8), (20, 8))]
    tee_prims = [_dot(0, 0, 2.0)]

    return {
        "filter": (_shape("Shape_FILTER", "LIQUID_FILTER", flt_prims), flt_ports),
        "hdrum": (_shape("Shape_HDRUM", "HORIZONTAL_DRUM", hdrum_prims), hdrum_ports),
        "vdrum": (_shape("Shape_VDRUM", "VERTICAL_DRUM", vdrum_prims), vdrum_ports),
        "column": (_shape("Shape_COLUMN", "PROCESS_COLUMN", col_prims), col_ports),
        "pump": (_shape("Shape_PUMP", "CENTRIFUGAL_PUMP", pump_prims), pump_ports),
        "comp": (_shape("Shape_COMP", "COMPRESSOR", comp_prims), comp_ports),
        "turbine": (_shape("Shape_TURBINE", "STEAM_TURBINE", turb_prims), turb_ports),
        "exchanger": (_shape("Shape_EXCH", "SHELL_AND_TUBE_EXCHANGER", exch_prims), exch_ports),
        "air_cooler": (_shape("Shape_AIR_COOLER", "AIR_COOLED_EXCHANGER", ac_prims), ac_ports),
        "gate": (_shape("Shape_GATE_VALVE", "GATE_VALVE", gate_prims), {"a": (-10, 0), "b": (10, 0)}),
        "control": (_shape("Shape_CONTROL_VALVE", "GLOBE_CONTROL_VALVE", ctrl_prims), {"a": (-10, 0), "b": (10, 0)}),
        "opc_right": (_shape("Shape_OPC_RIGHT", "PIPE_OFF_PAGE_CONNECTOR", opc_r_prims), {"tip": (20, 0), "tail": (-20, 0)}),
        "opc_left": (_shape("Shape_OPC_LEFT", "PIPE_OFF_PAGE_CONNECTOR", opc_l_prims), {"tip": (-20, 0), "tail": (20, 0)}),
        "tee": (_shape("Shape_TEE", "PIPE_TEE_JUNCTION", tee_prims), {"c": (0, 0)}),
    }


def _sid(*parts: object) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", "_".join(str(p) for p in parts))


def _mls(text: str) -> MultiLanguageString:
    return MultiLanguageString(singleLanguageStrings=[SingleLanguageString(language="en", value=text)])


def _pt(x: float, y: float) -> Point:
    return Point(x=float(x), y=float(y))


def _text(tid: str, s: str, x: float, y: float, size: float = TEXT, align: TextAlignment = TextAlignment.CENTERCENTER, template=None) -> Text:
    return Text(id=tid, text=s, position=_pt(x, y), size=size, alignment=align, color=BLACK, font="Arial", rotation=0.0, template=template)


def _tag_text(tid: str, obj, attr: str, s: str, x: float, y: float, align: TextAlignment = TextAlignment.CENTERCENTER) -> Text:
    tmpl = TextTemplate(
        id=tid + "_tmpl",
        fragments=[AttributeRepresentation(id=tid + "_attr", object=obj, attributeName=attr, type=AttributeRepresentationType.VALUE)],
    )
    return _text(tid, s, x, y, template=tmpl, align=align)


def _usage(uid: str, shape: Shape, x: float, y: float) -> ShapeUsage:
    return ShapeUsage(id=uid, shape=shape, position=_pt(x, y), rotation=0.0, scaleX=1.0, scaleY=1.0, isMirrored=False)


def _tag_parts(tag: str) -> tuple[str, str, str]:
    prefix, rest = tag.split("-", 1)
    m = re.match(r"(\d+)([A-Z]*)$", rest)
    assert m is not None, tag
    return prefix, m.group(1), m.group(2)


def _stable_ids(root: EngineeringModel) -> EngineeringModel:
    seen: set[int] = set()
    counts: dict[str, int] = {}

    def walk(obj: object) -> None:
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
            setattr(obj, "id", f"{name}_{counts[name]}")
        for field in type(obj).model_fields:
            walk(getattr(obj, field, None))

    walk(root)
    return root


def _build_generic_sheet(
    sheet_no: str,
    sheet_idx: str,
    title: str,
    equipment_defs: list[dict],
    valve_defs: list[dict],
    opc_defs: list[dict],
    line_defs: list[dict],
) -> EngineeringModel:
    symbols = _make_symbols()
    groups: list = []
    node_pos: dict[int, PipingNodePosition] = {}
    ends: dict[tuple, list[PipingNode]] = {}
    items: dict[tuple, object] = {}
    equipment_objs: list = []
    systems: list = []
    used_shapes: list[Shape] = []

    def track_shape(sh: Shape) -> Shape:
        if all(s is not sh for s in used_shapes):
            used_shapes.append(sh)
        return sh

    def make_node(nid: str, x: float, y: float) -> tuple[PipingNode, PipingNodePosition]:
        node = PipingNode(id=nid)
        pos = PipingNodePosition(id=nid + "_pos", node=node, position=_pt(x, y))
        node_pos[id(node)] = pos
        return node, pos

    for ed in equipment_defs:
        tag = ed["tag"]
        cls = ed["cls"]
        sym_key = ed["sym"]
        cx, cy = ed["pos"]
        desc = ed["desc"]
        p_des, t_des = ed["design"]
        nozzle_ports: dict[str, str] = ed["nozzles"]
        shape, ports = symbols[sym_key]
        track_shape(shape)
        base = _sid(tag)

        ch_main = Chamber(
            id=_sid(base, "CH_Main"),
            subTagName="Main",
            upperLimitDesignPressure=PhysicalQuantity(unit=PressureGaugeUnit.BAR, value=float(p_des)),
            upperLimitDesignTemperature=PhysicalQuantity(unit=TemperatureUnit.DEGREECELSIUS, value=float(t_des)),
        )
        nozzle_objs, nozzle_groups = [], []
        for sub, port_name in nozzle_ports.items():
            dx, dy = ports[port_name]
            node, pos = make_node(_sid(base, sub, "node"), cx + dx, cy + dy)
            nz = ProcessNozzle(id=_sid(base, sub), subTagName=sub, chamber=ch_main, nodes=[node])
            nozzle_objs.append(nz)
            ends[("eq", tag, sub)] = [node]
            items[("eq", tag, sub)] = nz
            nrg = RepresentationGroup(id=_sid(base, sub, "node_rg"), represents=node, nodePositions=[pos])
            nozzle_groups.append(RepresentationGroup(id=_sid(base, sub, "rg"), represents=nz, groups=[nrg]))

        prefix, number, suffix = _tag_parts(tag)
        extra = {}
        if cls is TubularHeatExchanger:
            extra["tubeBundle"] = TubeBundle(id=_sid(base, "bundle"), chamber=ch_main)
        eq = cls(
            id=base,
            tagName=tag,
            tagNamePrefix=prefix,
            tagNameSequenceNumber=number,
            tagNameSuffix=suffix,
            equipmentDescription=_mls(desc),
            chambers=[ch_main],
            nozzles=nozzle_objs,
            **extra,
        )
        equipment_objs.append(eq)
        lx, ly = ed.get("label_pos", (cx, cy - 42))
        groups.append(
            RepresentationGroup(
                id=_sid(base, "rg"),
                represents=eq,
                groups=[
                    Static(id=_sid(base, "sym"), elements=[_usage(_sid(base, "use"), shape, cx, cy)]),
                    EquipmentTagNameLabel(
                        id=_sid(base, "tag_lbl"),
                        elements=[_tag_text(_sid(base, "tag_txt"), eq, "TagName", tag, lx, ly)],
                    ),
                    Label(
                        id=_sid(base, "desc_lbl"),
                        elements=[_text(_sid(base, "desc_txt"), desc, lx, ly + 10, SMALL)],
                    ),
                    *nozzle_groups,
                ],
            )
        )

    for vd in valve_defs:
        tag = vd["tag"]
        cls = vd["cls"]
        cx, cy = vd["pos"]
        flow = vd.get("flow", "right")
        shape, ports = symbols["control" if cls is GlobeValve else "gate"]
        track_shape(shape)
        base = _sid(tag)
        inlet, outlet = ("a", "b") if flow == "right" else ("b", "a")
        n_in, p_in = make_node(_sid(base, "in"), cx + ports[inlet][0], cy + ports[inlet][1])
        n_out, p_out = make_node(_sid(base, "out"), cx + ports[outlet][0], cy + ports[outlet][1])
        valve = cls(id=base, pipingComponentName=tag, nodes=[n_in, n_out], numberOfPorts=None)
        ends[("v", tag)] = [n_in, n_out]
        items[("v", tag)] = valve
        label_y = cy - (24 if cls is GlobeValve else 14)
        groups.append(
            RepresentationGroup(
                id=_sid(base, "rg"),
                represents=valve,
                groups=[
                    Static(id=_sid(base, "sym"), elements=[_usage(_sid(base, "use"), shape, cx, cy)]),
                    ValveLabel(
                        id=_sid(base, "lbl"),
                        elements=[_tag_text(_sid(base, "txt"), valve, "PipingComponentName", tag, cx, label_y)],
                    ),
                    RepresentationGroup(id=_sid(base, "in_rg"), represents=n_in, nodePositions=[p_in]),
                    RepresentationGroup(id=_sid(base, "out_rg"), represents=n_out, nodePositions=[p_out]),
                ],
            )
        )

    for od in opc_defs:
        num = od["num"]
        direction = od["dir"]
        cx, cy = od["pos"]
        pointing = od.get("point", "right")
        ref_dwg = od["ref"]
        desc = od["desc"]
        shape, ports = symbols["opc_right" if pointing == "right" else "opc_left"]
        track_shape(shape)
        base = _sid(num)
        port_key = "tip" if direction == "in" else "tail"
        node, pos = make_node(_sid(base, "node"), cx + ports[port_key][0], cy + ports[port_key][1])
        ref = PipeOffPageConnectorReferenceByNumber(id=_sid(base, "ref"), referencedDrawingNumber=ref_dwg)
        cls = FlowInPipeOffPageConnector if direction == "in" else FlowOutPipeOffPageConnector
        opc = cls(id=base, pipeConnectorNumber=num, pipeConnectorDescription=_mls(desc), connectorReference=ref, nodes=[node])
        ends[("opc", num)] = [node]
        items[("opc", num)] = opc
        tx, align = (cx - 18, TextAlignment.LEFTCENTER) if cx < SHEET_W / 2 else (cx + 18, TextAlignment.RIGHTCENTER)
        groups.append(
            RepresentationGroup(
                id=_sid(base, "rg"),
                represents=opc,
                groups=[
                    Static(id=_sid(base, "sym"), elements=[_usage(_sid(base, "use"), shape, cx, cy)]),
                    OffPageConnectorNumberLabel(
                        id=_sid(base, "num_lbl"),
                        elements=[_tag_text(_sid(base, "num_txt"), opc, "PipeConnectorNumber", num, cx, cy)],
                    ),
                    OffPageConnectorDescriptionLabel(
                        id=_sid(base, "desc_lbl"),
                        elements=[_text(_sid(base, "desc_txt"), desc, tx, cy + 22, SMALL, align)],
                    ),
                    Label(
                        id=_sid(base, "dwg_lbl"),
                        elements=[_text(_sid(base, "dwg_txt"), ref_dwg, tx, cy + 12, SMALL, align)],
                    ),
                    RepresentationGroup(id=_sid(base, "node_rg"), represents=node, nodePositions=[pos]),
                ],
            )
        )

    def out_node(end: tuple) -> PipingNode:
        return ends[end][1] if end[0] == "v" else ends[end][0]

    def in_node(end: tuple) -> PipingNode:
        return ends[end][0]

    for ld in line_defs:
        lid = ld["id"]
        lno = ld["number"]
        fluid = ld.get("fluid", "HC")
        pclass = ld.get("pclass", "15A1")
        chain = ld["chain"]
        base = _sid(lid)
        nps = lno.split("-")[0].rstrip('"')
        pipes = []
        seg_items = []
        for pno, ((src, route), (dst, _)) in enumerate(zip(chain, chain[1:]), start=1):
            sn, tn = out_node(src), in_node(dst)
            pipe = Pipe(
                id=_sid(base, "pipe", pno),
                sourceItem=items[src],
                sourceNode=sn,
                targetItem=items[dst],
                targetNode=tn,
            )
            pipes.append(pipe)
            cl = ConnectorLine(
                id=_sid(base, "pipe", pno, "line"),
                source=node_pos[id(sn)],
                target=node_pos[id(tn)],
                innerPoints=[_pt(x, y) for x, y in route],
                stroke=_stroke(0.9),
            )
            groups.append(
                RepresentationGroup(
                    id=_sid(base, "pipe", pno, "rg"),
                    represents=pipe,
                    groups=[Static(id=_sid(base, "pipe", pno, "st"), elements=[cl])],
                )
            )
        for end, _ in chain:
            if end[0] in ("v", "opc"):
                seg_items.append(items[end])
        first, last = chain[0][0], chain[-1][0]
        seg = PipingNetworkSegment(
            id=_sid(base, "seg_1"),
            segmentNumber="S1",
            fluidCode=fluid,
            pipingClassCode=pclass,
            nominalDiameterRepresentation=f'{nps}"',
            items=seg_items,
            connections=pipes,
            sourceItem=items[first],
            sourceNode=out_node(first),
            targetItem=items[last],
            targetNode=in_node(last),
        )
        systems.append(
            PipingNetworkSystem(
                id=_sid(base, "sys"),
                lineNumber=lno,
                fluidCode=fluid,
                pipingClassCode=pclass,
                nominalDiameterRepresentation=f'{nps}"',
                segments=[seg],
            )
        )

    x0, y0 = SHEET_W - 300, SHEET_H - 50
    tb = Label(
        id="TitleBlock",
        elements=[
            _rect(x0, y0 - 18, SHEET_W - 10, SHEET_H - 10),
            _text("title_0", f"{sheet_no}  {title.upper()}", x0 + 6, y0 - 6, TEXT, TextAlignment.LEFTCENTER),
            _text("title_1", "UNIT 200 DIESEL HYDROTREATER. SYNTHETIC DEMO DATA, NOT FOR CONSTRUCTION", x0 + 6, y0 + 8, SMALL, TextAlignment.LEFTCENTER),
        ],
    )
    meta = PlantMetaData(
        id="PlantMetaData",
        drawingNumber=sheet_no,
        drawingName=title,
        unitName="Unit 200 Diesel Hydrotreater",
        sheetNumber=sheet_idx,
        totalNumberOfSheets="5",
        revisionNumber="0",
        projectName="TAR twin demo (synthetic)",
    )
    plant = PlantModel(id="PlantModel", metaData=meta, taggedPlantItems=equipment_objs, pipingNetworkSystems=systems)
    border = Border(id="Border", elements=[_rect(10, 10, SHEET_W - 10, SHEET_H - 10)])
    diagram = Diagram(
        id="Diagram",
        name=f"{sheet_no} {title}",
        represents=plant,
        backgroundColor=Color(r=255, g=255, b=255),
        minX=0.0,
        minY=0.0,
        maxX=SHEET_W,
        maxY=SHEET_H,
        groups=[border, tb, *groups],
    )
    return _stable_ids(
        EngineeringModel(
            id="EngineeringModel",
            conceptualModel=plant,
            diagram=diagram,
            shapeCatalogues=[ShapeCatalogue(id="TarTwinSymbols", name="TAR twin demo symbols", shapes=used_shapes)],
            exportDateTime=EXPORTED_AT,
            originatingSystemName="tar-twin scenario builder",
            originatingSystemVendorName="TAR twin demo",
            originatingSystemVersion="1.0",
        )
    )


def _build_sheet_001() -> EngineeringModel:
    return _build_generic_sheet(
        sheet_no="200-PID-001",
        sheet_idx="1",
        title="Feed section",
        equipment_defs=[
            {"tag": "FL-201A", "cls": LiquidFilter, "sym": "filter", "pos": (260, 200), "desc": "FEED FILTER A", "design": (10.0, 120.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (260, 155)},
            {"tag": "FL-201B", "cls": LiquidFilter, "sym": "filter", "pos": (260, 420), "desc": "FEED FILTER B", "design": (10.0, 120.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (260, 375)},
            {"tag": "D-201", "cls": PressureVessel, "sym": "hdrum", "pos": (560, 310), "desc": "FEED SURGE DRUM", "design": (9.0, 120.0), "nozzles": {"N1": "in", "N2": "out", "N3": "top"}, "label_pos": (560, 255)},
            {"tag": "P-201A", "cls": CentrifugalPump, "sym": "pump", "pos": (870, 220), "desc": "CHARGE PUMP A", "design": (120.0, 130.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (870, 180)},
            {"tag": "P-201B", "cls": CentrifugalPump, "sym": "pump", "pos": (870, 420), "desc": "CHARGE PUMP B", "design": (120.0, 130.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (870, 380)},
        ],
        valve_defs=[
            {"tag": "HV-2011", "cls": GateValve, "pos": (150, 200)},
            {"tag": "HV-2014", "cls": GateValve, "pos": (150, 420)},
            {"tag": "HV-2017", "cls": GateValve, "pos": (760, 220)},
            {"tag": "HV-2018", "cls": GateValve, "pos": (760, 420)},
            {"tag": "HV-2021", "cls": GateValve, "pos": (990, 220)},
            {"tag": "HV-2022", "cls": GateValve, "pos": (990, 420)},
            {"tag": "LV-2021", "cls": GlobeValve, "pos": (420, 200)},
        ],
        opc_defs=[
            {"num": "OPC-11", "dir": "in", "pos": (60, 200), "ref": "TANKAGE", "desc": "DIESEL FEED TRAIN A"},
            {"num": "OPC-12", "dir": "in", "pos": (60, 420), "ref": "TANKAGE", "desc": "DIESEL FEED TRAIN B"},
            {"num": "OPC-13", "dir": "out", "pos": (1120, 220), "ref": "200-PID-002", "desc": "CHARGE A TO E-201A"},
            {"num": "OPC-14", "dir": "out", "pos": (1120, 420), "ref": "200-PID-002", "desc": "CHARGE B TO E-201A"},
            {"num": "OPC-15", "dir": "in", "pos": (660, 420), "ref": "200-PID-001", "desc": "D-201 SUCTION B HDR"},
        ],
        line_defs=[
            {"id": "L101", "number": '8"-P-1001-3A1', "pclass": "3A1", "chain": [(("opc", "OPC-11"), []), (("v", "HV-2011"), []), (("eq", "FL-201A", "N1"), None)]},
            {"id": "L102", "number": '8"-P-1002-3A1', "pclass": "3A1", "chain": [(("eq", "FL-201A", "N2"), []), (("v", "LV-2021"), [(460, 200), (460, 310)]), (("eq", "D-201", "N1"), None)]},
            {"id": "L103", "number": '8"-P-1003-3A1', "pclass": "3A1", "chain": [(("opc", "OPC-12"), []), (("v", "HV-2014"), []), (("eq", "FL-201B", "N1"), None)]},
            {"id": "L104", "number": '8"-P-1004-3A1', "pclass": "3A1", "chain": [(("eq", "FL-201B", "N2"), [(560, 420), (560, 276)]), (("eq", "D-201", "N3"), None)]},
            {"id": "L105", "number": '8"-P-1005-3A1', "pclass": "3A1", "chain": [(("eq", "D-201", "N2"), [(680, 310), (680, 220)]), (("v", "HV-2017"), []), (("eq", "P-201A", "N1"), None)]},
            {"id": "L106", "number": '8"-P-1006-15A1', "pclass": "15A1", "chain": [(("eq", "P-201A", "N2"), []), (("v", "HV-2021"), []), (("opc", "OPC-13"), None)]},
            {"id": "L107", "number": '8"-P-1007-15A1', "pclass": "15A1", "chain": [(("opc", "OPC-15"), []), (("v", "HV-2018"), []), (("eq", "P-201B", "N1"), None)]},
            {"id": "L108", "number": '8"-P-1008-15A1', "pclass": "15A1", "chain": [(("eq", "P-201B", "N2"), []), (("v", "HV-2022"), []), (("opc", "OPC-14"), None)]},
        ],
    )


def _build_sheet_002() -> EngineeringModel:
    if str(SPIKE_DEXPI_DIR) not in sys.path:
        sys.path.insert(0, str(SPIKE_DEXPI_DIR))
    import build_sheet as spike_build  # noqa: E402

    return spike_build.build_model()


def _build_sheet_003() -> EngineeringModel:
    return _build_generic_sheet(
        sheet_no="200-PID-003",
        sheet_idx="3",
        title="Effluent cooling and separation",
        equipment_defs=[
            {"tag": "A-201", "cls": HeatExchanger, "sym": "air_cooler", "pos": (260, 220), "desc": "EFFLUENT AIR COOLER", "design": (108.0, 230.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (260, 175)},
            {"tag": "E-202", "cls": TubularHeatExchanger, "sym": "exchanger", "pos": (480, 220), "desc": "EFFLUENT TRIM COOLER", "design": (105.0, 180.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (480, 170)},
            {"tag": "D-202", "cls": PressureVessel, "sym": "vdrum", "pos": (700, 250), "desc": "COLD HP SEPARATOR", "design": (102.0, 110.0), "nozzles": {"N1": "in", "N2": "top", "N3": "bottom"}, "label_pos": (700, 165)},
            {"tag": "D-203", "cls": PressureVessel, "sym": "hdrum", "pos": (940, 420), "desc": "LP SEPARATOR", "design": (22.0, 110.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (940, 365)},
            {"tag": "P-204A", "cls": CentrifugalPump, "sym": "pump", "pos": (260, 520), "desc": "WASH WATER PUMP A", "design": (108.0, 100.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (260, 480)},
            {"tag": "P-204B", "cls": CentrifugalPump, "sym": "pump", "pos": (520, 520), "desc": "WASH WATER PUMP B", "design": (108.0, 100.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (520, 480)},
        ],
        valve_defs=[
            {"tag": "HV-2041", "cls": GateValve, "pos": (375, 220)},
            {"tag": "HV-2043", "cls": GateValve, "pos": (840, 150)},
            {"tag": "LV-2031", "cls": GlobeValve, "pos": (780, 420)},
            {"tag": "HV-2083", "cls": GateValve, "pos": (170, 520)},
            {"tag": "HV-2084", "cls": GateValve, "pos": (360, 520)},
            {"tag": "HV-2085", "cls": GateValve, "pos": (440, 520)},
            {"tag": "HV-2086", "cls": GateValve, "pos": (610, 520)},
        ],
        opc_defs=[
            {"num": "OPC-31", "dir": "in", "pos": (60, 220), "ref": "200-PID-002", "desc": "EFFLUENT FROM E-201A"},
            {"num": "OPC-32", "dir": "out", "pos": (1120, 150), "ref": "200-PID-004", "desc": "HP GAS TO C-202"},
            {"num": "OPC-33", "dir": "out", "pos": (1120, 420), "ref": "200-PID-005", "desc": "LIQUID TO C-201"},
            {"num": "OPC-34", "dir": "in", "pos": (60, 520), "ref": "UTILITIES", "desc": "WASH WATER SUPPLY"},
            {"num": "OPC-35", "dir": "out", "pos": (710, 520), "ref": "200-PID-003", "desc": "WASH WATER TO A-201"},
        ],
        line_defs=[
            {"id": "L301", "number": '10"-P-3001-15A1', "chain": [(("opc", "OPC-31"), []), (("eq", "A-201", "N1"), None)]},
            {"id": "L302", "number": '10"-P-3002-15A1', "chain": [(("eq", "A-201", "N2"), []), (("v", "HV-2041"), [(436, 220)]), (("eq", "E-202", "N1"), None)]},
            {"id": "L303", "number": '10"-P-3003-15A1', "chain": [(("eq", "E-202", "N2"), [(436, 140), (620, 140), (620, 250)]), (("eq", "D-202", "N1"), None)]},
            {"id": "L304", "number": '8"-G-3004-15A1', "fluid": "H2", "chain": [(("eq", "D-202", "N2"), [(700, 150)]), (("v", "HV-2043"), []), (("opc", "OPC-32"), None)]},
            {"id": "L305", "number": '8"-P-3005-3A1', "pclass": "3A1", "chain": [(("eq", "D-202", "N3"), [(700, 420)]), (("v", "LV-2031"), []), (("eq", "D-203", "N1"), None)]},
            {"id": "L306", "number": '8"-P-3006-3A1', "pclass": "3A1", "chain": [(("eq", "D-203", "N2"), []), (("opc", "OPC-33"), None)]},
            {"id": "L307", "number": '3"-W-3007-15A1', "fluid": "WW", "chain": [(("opc", "OPC-34"), []), (("v", "HV-2083"), []), (("eq", "P-204A", "N1"), None)]},
            {"id": "L308", "number": '3"-W-3008-15A1', "fluid": "WW", "chain": [(("eq", "P-204A", "N2"), []), (("v", "HV-2084"), []), (("v", "HV-2085"), []), (("eq", "P-204B", "N1"), None)]},
            {"id": "L309", "number": '3"-W-3009-15A1', "fluid": "WW", "chain": [(("eq", "P-204B", "N2"), []), (("v", "HV-2086"), []), (("opc", "OPC-35"), None)]},
        ],
    )


def _build_sheet_004() -> EngineeringModel:
    return _build_generic_sheet(
        sheet_no="200-PID-004",
        sheet_idx="4",
        title="Recycle and makeup gas",
        equipment_defs=[
            {"tag": "C-202", "cls": ProcessColumn, "sym": "column", "pos": (240, 220), "desc": "AMINE SCRUBBER", "design": (98.0, 110.0), "nozzles": {"N1": "in", "N2": "top"}, "label_pos": (240, 100)},
            {"tag": "D-204", "cls": PressureVessel, "sym": "vdrum", "pos": (520, 220), "desc": "RECYCLE GAS KO DRUM", "design": (96.0, 100.0), "nozzles": {"N1": "in", "N2": "top"}, "label_pos": (520, 130)},
            {"tag": "K-201", "cls": CentrifugalCompressor, "sym": "comp", "pos": (800, 180), "desc": "RECYCLE COMPRESSOR", "design": (118.0, 130.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (800, 135)},
            {"tag": "KT-201", "cls": SteamTurbine, "sym": "turbine", "pos": (960, 290), "desc": "STEAM TURBINE DRIVER", "design": (52.0, 440.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (960, 248)},
            {"tag": "D-206", "cls": PressureVessel, "sym": "vdrum", "pos": (280, 520), "desc": "MAKEUP GAS KO DRUM", "design": (32.0, 100.0), "nozzles": {"N1": "in", "N2": "top"}, "label_pos": (280, 430)},
            {"tag": "K-202A", "cls": ReciprocatingCompressor, "sym": "comp", "pos": (660, 460), "desc": "MAKEUP COMP A", "design": (118.0, 160.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (660, 420)},
            {"tag": "K-202B", "cls": ReciprocatingCompressor, "sym": "comp", "pos": (660, 580), "desc": "MAKEUP COMP B", "design": (118.0, 160.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (660, 540)},
        ],
        valve_defs=[
            {"tag": "HV-2051", "cls": GateValve, "pos": (140, 220)},
            {"tag": "HV-2055", "cls": GateValve, "pos": (670, 180)},
            {"tag": "HV-2056", "cls": GateValve, "pos": (940, 180)},
            {"tag": "HV-2071", "cls": GateValve, "pos": (160, 520)},
            {"tag": "HV-2073", "cls": GateValve, "pos": (520, 460)},
            {"tag": "HV-2074", "cls": GateValve, "pos": (820, 460)},
            {"tag": "HV-2075", "cls": GateValve, "pos": (520, 580)},
            {"tag": "HV-2076", "cls": GateValve, "pos": (820, 580)},
        ],
        opc_defs=[
            {"num": "OPC-41", "dir": "in", "pos": (60, 220), "ref": "200-PID-003", "desc": "HP GAS FROM D-202"},
            {"num": "OPC-42", "dir": "out", "pos": (1120, 180), "ref": "200-PID-002", "desc": "RECYCLE GAS TO E-201A"},
            {"num": "OPC-43", "dir": "in", "pos": (60, 520), "ref": "H2-HEADER", "desc": "MAKEUP H2 SUPPLY"},
            {"num": "OPC-44", "dir": "out", "pos": (1120, 460), "ref": "200-PID-002", "desc": "MAKEUP H2 A TO LOOP"},
            {"num": "OPC-45", "dir": "out", "pos": (1120, 580), "ref": "200-PID-002", "desc": "MAKEUP H2 B TO LOOP"},
            {"num": "OPC-46", "dir": "in", "pos": (820, 290), "ref": "STEAM-HDR", "desc": "HP STEAM TO KT-201"},
            {"num": "OPC-47", "dir": "out", "pos": (1120, 290), "ref": "STEAM-HDR", "desc": "MP STEAM EXHAUST"},
            {"num": "OPC-48", "dir": "in", "pos": (420, 580), "ref": "200-PID-004", "desc": "D-206 SUCTION B HDR"},
        ],
        line_defs=[
            {"id": "L401", "number": '8"-G-4001-15A1', "fluid": "H2", "chain": [(("opc", "OPC-41"), []), (("v", "HV-2051"), []), (("eq", "C-202", "N1"), None)]},
            {"id": "L402", "number": '8"-G-4002-15A1', "fluid": "H2", "chain": [(("eq", "C-202", "N2"), [(240, 80), (440, 80), (440, 220)]), (("eq", "D-204", "N1"), None)]},
            {"id": "L403", "number": '8"-G-4003-15A1', "fluid": "H2", "chain": [(("eq", "D-204", "N2"), [(520, 180)]), (("v", "HV-2055"), []), (("eq", "K-201", "N1"), None)]},
            {"id": "L404", "number": '8"-G-4004-15A1', "fluid": "H2", "chain": [(("eq", "K-201", "N2"), []), (("v", "HV-2056"), []), (("opc", "OPC-42"), None)]},
            {"id": "L405", "number": '6"-S-4005-6A1', "fluid": "STM", "pclass": "6A1", "chain": [(("opc", "OPC-46"), []), (("eq", "KT-201", "N1"), None)]},
            {"id": "L406", "number": '8"-S-4006-3A1', "fluid": "STM", "pclass": "3A1", "chain": [(("eq", "KT-201", "N2"), []), (("opc", "OPC-47"), None)]},
            {"id": "L407", "number": '6"-G-4007-6A1', "fluid": "H2", "pclass": "6A1", "chain": [(("opc", "OPC-43"), []), (("v", "HV-2071"), []), (("eq", "D-206", "N1"), None)]},
            {"id": "L408", "number": '6"-G-4008-6A1', "fluid": "H2", "pclass": "6A1", "chain": [(("eq", "D-206", "N2"), [(280, 460)]), (("v", "HV-2073"), []), (("eq", "K-202A", "N1"), None)]},
            {"id": "L409", "number": '4"-G-4009-15A1', "fluid": "H2", "chain": [(("eq", "K-202A", "N2"), []), (("v", "HV-2074"), []), (("opc", "OPC-44"), None)]},
            {"id": "L410", "number": '6"-G-4010-6A1', "fluid": "H2", "pclass": "6A1", "chain": [(("opc", "OPC-48"), []), (("v", "HV-2075"), []), (("eq", "K-202B", "N1"), None)]},
            {"id": "L411", "number": '4"-G-4011-15A1', "fluid": "H2", "chain": [(("eq", "K-202B", "N2"), []), (("v", "HV-2076"), []), (("opc", "OPC-45"), None)]},
        ],
    )


def _build_sheet_005() -> EngineeringModel:
    return _build_generic_sheet(
        sheet_no="200-PID-005",
        sheet_idx="5",
        title="Product stripping",
        equipment_defs=[
            {"tag": "C-201", "cls": ProcessColumn, "sym": "column", "pos": (260, 320), "desc": "PRODUCT STRIPPER", "design": (15.0, 290.0), "nozzles": {"N1": "in", "N2": "top", "N3": "bottom", "N4": "side"}, "label_pos": (260, 195)},
            {"tag": "E-203", "cls": TubularHeatExchanger, "sym": "exchanger", "pos": (520, 160), "desc": "OVERHEAD CONDENSER", "design": (15.0, 200.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (520, 110)},
            {"tag": "D-205", "cls": PressureVessel, "sym": "hdrum", "pos": (760, 160), "desc": "OVERHEAD DRUM", "design": (15.0, 110.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (760, 108)},
            {"tag": "P-202A", "cls": CentrifugalPump, "sym": "pump", "pos": (600, 300), "desc": "REFLUX PUMP A", "design": (22.0, 110.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (600, 260)},
            {"tag": "P-202B", "cls": CentrifugalPump, "sym": "pump", "pos": (820, 300), "desc": "REFLUX PUMP B", "design": (22.0, 110.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (820, 260)},
            {"tag": "P-203A", "cls": CentrifugalPump, "sym": "pump", "pos": (480, 500), "desc": "BOTTOMS PUMP A", "design": (24.0, 285.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (480, 460)},
            {"tag": "P-203B", "cls": CentrifugalPump, "sym": "pump", "pos": (480, 600), "desc": "BOTTOMS PUMP B", "design": (24.0, 285.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (480, 560)},
            {"tag": "E-204", "cls": TubularHeatExchanger, "sym": "exchanger", "pos": (840, 520), "desc": "PRODUCT COOLER", "design": (20.0, 240.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (840, 470)},
        ],
        valve_defs=[
            {"tag": "HV-2091", "cls": GateValve, "pos": (150, 320)},
            {"tag": "HV-2095", "cls": GateValve, "pos": (520, 300)},
            {"tag": "HV-2096", "cls": GateValve, "pos": (680, 300)},
            {"tag": "FV-2051", "cls": GlobeValve, "pos": (420, 270), "flow": "left"},
            {"tag": "HV-2099", "cls": GateValve, "pos": (380, 500)},
            {"tag": "HV-2100", "cls": GateValve, "pos": (590, 500)},
            {"tag": "HV-2101", "cls": GateValve, "pos": (380, 600)},
            {"tag": "HV-2102", "cls": GateValve, "pos": (590, 600)},
            {"tag": "HV-2104", "cls": GateValve, "pos": (990, 520)},
        ],
        opc_defs=[
            {"num": "OPC-51", "dir": "in", "pos": (60, 320), "ref": "200-PID-003", "desc": "FEED FROM D-203"},
            {"num": "OPC-52", "dir": "out", "pos": (1120, 160), "ref": "NAPHTHA", "desc": "WILD NAPHTHA OUT"},
            {"num": "OPC-53", "dir": "out", "pos": (1120, 520), "ref": "TANKAGE", "desc": "ULSD PRODUCT TO TANKS"},
            {"num": "OPC-54", "dir": "in", "pos": (420, 300), "ref": "200-PID-005", "desc": "D-205 REFLUX SUCTION"},
            {"num": "OPC-55", "dir": "in", "pos": (280, 600), "ref": "200-PID-005", "desc": "C-201 BOTTOMS B HDR"},
            {"num": "OPC-56", "dir": "out", "pos": (700, 600), "ref": "200-PID-005", "desc": "P-203B DISCH TO E-204"},
        ],
        line_defs=[
            {"id": "L501", "number": '8"-P-5001-3A1', "pclass": "3A1", "chain": [(("opc", "OPC-51"), []), (("v", "HV-2091"), []), (("eq", "C-201", "N1"), None)]},
            {"id": "L502", "number": '8"-P-5002-3A1', "pclass": "3A1", "chain": [(("eq", "C-201", "N2"), [(260, 188), (476, 188)]), (("eq", "E-203", "N1"), None)]},
            {"id": "L503", "number": '8"-P-5003-3A1', "pclass": "3A1", "chain": [(("eq", "E-203", "N2"), [(476, 90), (660, 90), (660, 160)]), (("eq", "D-205", "N1"), None)]},
            {"id": "L504", "number": '6"-P-5004-3A1', "pclass": "3A1", "chain": [(("eq", "D-205", "N2"), []), (("opc", "OPC-52"), None)]},
            {"id": "L505", "number": '4"-P-5005-3A1', "pclass": "3A1", "chain": [(("opc", "OPC-54"), []), (("v", "HV-2095"), []), (("eq", "P-202A", "N1"), None)]},
            {"id": "L506", "number": '4"-P-5006-3A1', "pclass": "3A1", "chain": [(("eq", "P-202A", "N2"), []), (("v", "HV-2096"), []), (("eq", "P-202B", "N1"), None)]},
            {"id": "L507", "number": '4"-P-5007-3A1', "pclass": "3A1", "chain": [(("eq", "P-202B", "N2"), [(870, 300), (870, 230), (470, 230), (470, 270)]), (("v", "FV-2051"), []), (("eq", "C-201", "N4"), None)]},
            {"id": "L508", "number": '8"-P-5008-3A1', "pclass": "3A1", "chain": [(("eq", "C-201", "N3"), [(260, 500)]), (("v", "HV-2099"), []), (("eq", "P-203A", "N1"), None)]},
            {"id": "L509", "number": '8"-P-5009-3A1', "pclass": "3A1", "chain": [(("eq", "P-203A", "N2"), []), (("v", "HV-2100"), [(796, 500)]), (("eq", "E-204", "N1"), None)]},
            {"id": "L510", "number": '8"-P-5010-3A1', "pclass": "3A1", "chain": [(("opc", "OPC-55"), []), (("v", "HV-2101"), []), (("eq", "P-203B", "N1"), None)]},
            {"id": "L511", "number": '8"-P-5011-3A1', "pclass": "3A1", "chain": [(("eq", "P-203B", "N2"), []), (("v", "HV-2102"), []), (("opc", "OPC-56"), None)]},
            {"id": "L512", "number": '8"-P-5012-3A1', "pclass": "3A1", "chain": [(("eq", "E-204", "N2"), [(796, 440), (950, 440), (950, 520)]), (("v", "HV-2104"), []), (("opc", "OPC-53"), None)]},
        ],
    )


SHEET_BUILDERS = {
    "200-PID-001": _build_sheet_001,
    "200-PID-002": _build_sheet_002,
    "200-PID-003": _build_sheet_003,
    "200-PID-004": _build_sheet_004,
    "200-PID-005": _build_sheet_005,
}


def generate_all_dexpi_sheets(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    serializer = DexpiXmlSerializer()
    for sheet_no, builder in SHEET_BUILDERS.items():
        model = builder()
        serializer.save(model, out_dir, sheet_no)
        xml_path = out_dir / f"{sheet_no}.xml"
        reloaded = serializer.load(out_dir, sheet_no)
        svg_path = out_dir / f"{sheet_no}.svg"
        DrawDiagram(reloaded.diagram, padding=5.0, pretty=False).save_svg(sheet_no, str(svg_path))
        written.extend([xml_path, svg_path])
    return written
