"""Build all 5 Unit 200 P&ID sheets as DEXPI 2.0.1 XML + SVG with pyDEXPI.

Sheet 200-PID-002 preserves the exact validated Reaction sheet from the Phase 0
spike so all 21 flow edges and all 9 matcher fact claims remain invariant.
Sheets 200-PID-001, 200-PID-003, 200-PID-004, and 200-PID-005 use the same
DEXPI 2.0.1 conceptual + graphical builder with ISO 10628-2 style shapes,
4-nozzle dual-chamber shell-and-tube exchangers, PipeTee manifolds, and
1-to-1 matched cross-sheet off-page connectors (zero self-sheet OPCs).
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
    flt_prims = [
        _rect(-22, -26, 22, 26),
        _pl((-22, 0), (22, 0), dash=DashStyle.DASH),
        _pl((-32, 0), (-22, 0)),
        _pl((22, 0), (32, 0)),
    ]
    hdrum_prims = [
        _pl((-45, -24), (45, -24)),
        _pl((-45, 24), (45, 24)),
        _pl(*_arc(-45, 0, 12, 24, 90, 270)),
        _pl(*_arc(45, 0, 12, 24, -90, 90)),
        _pl((-57, 0), (-67, 0)),
        _pl((57, 0), (67, 0)),
        _pl((0, -24), (0, -34)),
        _pl((0, 24), (0, 34)),
    ]
    vdrum_prims = [
        _pl((-22, -45), (-22, 45)),
        _pl((22, -45), (22, 45)),
        _pl(*_arc(0, -45, 22, 12, 180, 360)),
        _pl(*_arc(0, 45, 22, 12, 0, 180)),
        _pl((-22, 0), (-32, 0)),
        _pl((0, -57), (0, -67)),
        _pl((0, 57), (0, 67)),
    ]
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
    comp_prims = [
        _poly((-22, -20), (22, -12), (22, 12), (-22, 20)),
        _pl((-32, 0), (-22, 0)),
        _pl((22, 0), (32, 0)),
    ]
    turb_prims = [
        _poly((-20, -12), (20, -20), (20, 20), (-20, 12)),
        _pl((-30, 0), (-20, 0)),
        _pl((20, 0), (30, 0)),
    ]
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
        "filter": (_shape("Shape_FILTER", "LIQUID_FILTER", flt_prims), {"in": (-32, 0), "out": (32, 0)}),
        "hdrum": (_shape("Shape_HDRUM", "HORIZONTAL_DRUM", hdrum_prims), {"in": (-67, 0), "out": (67, 0), "top": (0, -34), "bottom": (0, 34)}),
        "vdrum": (_shape("Shape_VDRUM", "VERTICAL_DRUM", vdrum_prims), {"in": (-32, 0), "top": (0, -67), "bottom": (0, 67)}),
        "column": (_shape("Shape_COLUMN", "PROCESS_COLUMN", col_prims), {"in": (-36, 0), "top": (0, -104), "bottom": (0, 104), "side": (36, -50)}),
        "pump": (_shape("Shape_PUMP", "CENTRIFUGAL_PUMP", pump_prims), {"in": (-26, 0), "out": (26, 0)}),
        "comp": (_shape("Shape_COMP", "COMPRESSOR", comp_prims), {"in": (-32, 0), "out": (32, 0)}),
        "turbine": (_shape("Shape_TURBINE", "STEAM_TURBINE", turb_prims), {"in": (-30, 0), "out": (30, 0)}),
        "exchanger": (
            _shape("Shape_EXCH", "SHELL_AND_TUBE_EXCHANGER", exch_prims),
            {"tube_in": (-44, 28), "tube_out": (-44, -28), "shell_in": (30, -28), "shell_out": (30, 28)},
        ),
        "air_cooler": (_shape("Shape_AIR_COOLER", "AIR_COOLED_EXCHANGER", ac_prims), {"in": (-65, 0), "out": (65, 0)}),
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
    tee_defs: dict[str, tuple[tuple[float, float], str]],
    tee_nodes: dict[tuple[str, str], int | tuple[int, int]],
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
        shape, ports = symbols[sym_key]
        track_shape(shape)
        base = _sid(tag)

        chamber_specs: dict[str, tuple[float, float]] = ed.get("chambers") or {"Main": ed["design"]}
        ch_objs: dict[str, Chamber] = {}
        for cname, (p_des, t_des) in chamber_specs.items():
            ch_objs[cname] = Chamber(
                id=_sid(base, "CH", cname),
                subTagName=cname,
                upperLimitDesignPressure=PhysicalQuantity(unit=PressureGaugeUnit.BAR, value=float(p_des)),
                upperLimitDesignTemperature=PhysicalQuantity(unit=TemperatureUnit.DEGREECELSIUS, value=float(t_des)),
            )

        nozzle_objs, nozzle_groups = [], []
        for sub, spec in ed["nozzles"].items():
            if isinstance(spec, tuple):
                port_name, ch_name = spec
            else:
                port_name, ch_name = spec, "Main"
            dx, dy = ports[port_name]
            node, pos = make_node(_sid(base, sub, "node"), cx + dx, cy + dy)
            nz = ProcessNozzle(id=_sid(base, sub), subTagName=sub, chamber=ch_objs[ch_name], nodes=[node])
            nozzle_objs.append(nz)
            ends[("eq", tag, sub)] = [node]
            items[("eq", tag, sub)] = nz
            nrg = RepresentationGroup(id=_sid(base, sub, "node_rg"), represents=node, nodePositions=[pos])
            nozzle_groups.append(RepresentationGroup(id=_sid(base, sub, "rg"), represents=nz, groups=[nrg]))

        prefix, number, suffix = _tag_parts(tag)
        extra = {}
        if cls is TubularHeatExchanger:
            extra["tubeBundle"] = TubeBundle(id=_sid(base, "bundle"), chamber=ch_objs["Tube side"])
        eq = cls(
            id=base,
            tagName=tag,
            tagNamePrefix=prefix,
            tagNameSequenceNumber=number,
            tagNameSuffix=suffix,
            equipmentDescription=_mls(desc),
            chambers=list(ch_objs.values()),
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

    for tname, ((cx, cy), _owner) in tee_defs.items():
        shape, _ = symbols["tee"]
        track_shape(shape)
        base = _sid("Tee", tname)
        tnodes, tgroups = [], []
        for i in range(3):
            nd, pos = make_node(_sid(base, "n", i), cx, cy)
            tnodes.append(nd)
            tgroups.append(RepresentationGroup(id=_sid(base, "n", i, "rg"), represents=nd, nodePositions=[pos]))
        tee = PipeTee(id=base, nodes=tnodes)
        ends[("tee", tname)] = tnodes
        items[("tee", tname)] = tee
        groups.append(
            RepresentationGroup(
                id=_sid(base, "rg"),
                represents=tee,
                groups=[Static(id=_sid(base, "sym"), elements=[_usage(_sid(base, "use"), shape, cx, cy)]), *tgroups],
            )
        )

    def out_node(end: tuple, lid: str) -> PipingNode:
        if end[0] == "v":
            return ends[end][1]
        if end[0] == "tee":
            spec = tee_nodes[(end[1], lid)]
            return ends[end][spec[1] if isinstance(spec, tuple) else spec]
        return ends[end][0]

    def in_node(end: tuple, lid: str) -> PipingNode:
        if end[0] == "v":
            return ends[end][0]
        if end[0] == "tee":
            spec = tee_nodes[(end[1], lid)]
            return ends[end][spec[0] if isinstance(spec, tuple) else spec]
        return ends[end][0]

    for ld in line_defs:
        lid = ld["id"]
        lno = ld["number"]
        fluid = ld.get("fluid", "HC")
        pclass = ld.get("pclass", "15A1")
        chain = ld["chain"]
        base = _sid(lid)
        nps = lno.split("-")[0].rstrip('"')
        cuts = [0] + [i for i, (end, _) in enumerate(chain) if end[0] == "tee" and 0 < i < len(chain) - 1] + [len(chain) - 1]
        segments, pno = [], 0
        for k, (lo, hi) in enumerate(zip(cuts, cuts[1:])):
            part = chain[lo : hi + 1]
            pipes, seg_items = [], []
            for (src, route), (dst, _) in zip(part, part[1:]):
                pno += 1
                sn, tn = out_node(src, lid), in_node(dst, lid)
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
            for j, (end, _) in enumerate(part):
                if end[0] in ("v", "opc"):
                    seg_items.append(items[end])
                elif end[0] == "tee" and tee_defs[end[1]][1] == lid and not (j == 0 and k > 0):
                    seg_items.append(items[end])
            first, last = part[0][0], part[-1][0]
            segments.append(
                PipingNetworkSegment(
                    id=_sid(base, "seg", k + 1),
                    segmentNumber=f"S{k + 1}",
                    fluidCode=fluid,
                    pipingClassCode=pclass,
                    nominalDiameterRepresentation=f'{nps}"',
                    items=seg_items,
                    connections=pipes,
                    sourceItem=items[first],
                    sourceNode=out_node(first, lid),
                    targetItem=items[last],
                    targetNode=in_node(last, lid),
                )
            )
        systems.append(
            PipingNetworkSystem(
                id=_sid(base, "sys"),
                lineNumber=lno,
                fluidCode=fluid,
                pipingClassCode=pclass,
                nominalDiameterRepresentation=f'{nps}"',
                segments=segments,
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
            {"tag": "D-201", "cls": PressureVessel, "sym": "hdrum", "pos": (540, 310), "desc": "FEED SURGE DRUM", "design": (9.0, 120.0), "nozzles": {"N1": "in", "N2": "out", "N3": "top"}, "label_pos": (540, 255)},
            {"tag": "P-201A", "cls": CentrifugalPump, "sym": "pump", "pos": (840, 220), "desc": "CHARGE PUMP A", "design": (120.0, 130.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (840, 180)},
            {"tag": "P-201B", "cls": CentrifugalPump, "sym": "pump", "pos": (840, 420), "desc": "CHARGE PUMP B", "design": (120.0, 130.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (840, 380)},
        ],
        valve_defs=[
            {"tag": "HV-2011", "cls": GateValve, "pos": (150, 200)},
            {"tag": "HV-2014", "cls": GateValve, "pos": (150, 420)},
            {"tag": "HV-2017", "cls": GateValve, "pos": (740, 220)},
            {"tag": "HV-2018", "cls": GateValve, "pos": (740, 420)},
            {"tag": "HV-2021", "cls": GateValve, "pos": (950, 220)},
            {"tag": "HV-2022", "cls": GateValve, "pos": (950, 420)},
            {"tag": "LV-2021", "cls": GlobeValve, "pos": (400, 200)},
        ],
        opc_defs=[
            {"num": "OPC-11", "dir": "in", "pos": (60, 200), "ref": "TANKAGE", "desc": "DIESEL FEED TRAIN A"},
            {"num": "OPC-12", "dir": "in", "pos": (60, 420), "ref": "TANKAGE", "desc": "DIESEL FEED TRAIN B"},
            {"num": "OPC-21", "dir": "out", "pos": (1120, 220), "ref": "200-PID-002", "desc": "FEED FROM P-201A/B DISCHARGE"},
        ],
        tee_defs={
            "T101": ((660, 310), "L105"),
            "T102": ((1030, 220), "L106"),
        },
        tee_nodes={
            ("T101", "L105"): (0, 1),
            ("T101", "L107"): 2,
            ("T102", "L106"): (0, 1),
            ("T102", "L108"): 2,
        },
        line_defs=[
            {"id": "L101", "number": '8"-P-1001-3A1', "pclass": "3A1", "chain": [(("opc", "OPC-11"), []), (("v", "HV-2011"), []), (("eq", "FL-201A", "N1"), None)]},
            {"id": "L102", "number": '8"-P-1002-3A1', "pclass": "3A1", "chain": [(("eq", "FL-201A", "N2"), []), (("v", "LV-2021"), [(440, 200), (440, 310)]), (("eq", "D-201", "N1"), None)]},
            {"id": "L103", "number": '8"-P-1003-3A1', "pclass": "3A1", "chain": [(("opc", "OPC-12"), []), (("v", "HV-2014"), []), (("eq", "FL-201B", "N1"), None)]},
            {"id": "L104", "number": '8"-P-1004-3A1', "pclass": "3A1", "chain": [(("eq", "FL-201B", "N2"), [(540, 420), (540, 276)]), (("eq", "D-201", "N3"), None)]},
            {"id": "L105", "number": '8"-P-1005-3A1', "pclass": "3A1", "chain": [(("eq", "D-201", "N2"), []), (("tee", "T101"), [(660, 220)]), (("v", "HV-2017"), []), (("eq", "P-201A", "N1"), None)]},
            {"id": "L107", "number": '8"-P-1007-3A1', "pclass": "3A1", "chain": [(("tee", "T101"), [(660, 420)]), (("v", "HV-2018"), []), (("eq", "P-201B", "N1"), None)]},
            {"id": "L106", "number": '8"-P-1006-15A1', "pclass": "15A1", "chain": [(("eq", "P-201A", "N2"), []), (("v", "HV-2021"), []), (("tee", "T102"), []), (("opc", "OPC-21"), None)]},
            {"id": "L108", "number": '8"-P-1008-15A1', "pclass": "15A1", "chain": [(("eq", "P-201B", "N2"), []), (("v", "HV-2022"), [(1030, 420)]), (("tee", "T102"), None)]},
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
            {"tag": "A-201", "cls": HeatExchanger, "sym": "air_cooler", "pos": (240, 220), "desc": "EFFLUENT AIR COOLER", "design": (108.0, 230.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (240, 175)},
            {
                "tag": "E-202",
                "cls": TubularHeatExchanger,
                "sym": "exchanger",
                "pos": (470, 220),
                "desc": "EFFLUENT TRIM COOLER",
                "chambers": {"Tube side": (10.0, 80.0), "Shell side": (105.0, 180.0)},
                "nozzles": {"N1": ("tube_in", "Tube side"), "N2": ("tube_out", "Tube side"), "N3": ("shell_in", "Shell side"), "N4": ("shell_out", "Shell side")},
                "label_pos": (470, 165),
            },
            {"tag": "D-202", "cls": PressureVessel, "sym": "vdrum", "pos": (700, 250), "desc": "COLD HP SEPARATOR", "design": (102.0, 110.0), "nozzles": {"N1": "in", "N2": "top", "N3": "bottom"}, "label_pos": (700, 165)},
            {"tag": "D-203", "cls": PressureVessel, "sym": "hdrum", "pos": (920, 420), "desc": "LP SEPARATOR", "design": (22.0, 110.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (920, 365)},
            {"tag": "P-204A", "cls": CentrifugalPump, "sym": "pump", "pos": (300, 520), "desc": "WASH WATER PUMP A", "design": (108.0, 100.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (300, 480)},
            {"tag": "P-204B", "cls": CentrifugalPump, "sym": "pump", "pos": (300, 620), "desc": "WASH WATER PUMP B", "design": (108.0, 100.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (300, 580)},
        ],
        valve_defs=[
            {"tag": "HV-2041", "cls": GateValve, "pos": (360, 220)},
            {"tag": "HV-2043", "cls": GateValve, "pos": (840, 150)},
            {"tag": "HV-2044", "cls": GateValve, "pos": (700, 370)},
            {"tag": "LV-2031", "cls": GlobeValve, "pos": (765, 420)},
            {"tag": "HV-2081", "cls": GateValve, "pos": (820, 420)},
            {"tag": "HV-2087", "cls": GateValve, "pos": (1035, 420)},
            {"tag": "HV-2083", "cls": GateValve, "pos": (210, 520)},
            {"tag": "HV-2084", "cls": GateValve, "pos": (400, 520)},
            {"tag": "HV-2085", "cls": GateValve, "pos": (210, 620)},
            {"tag": "HV-2086", "cls": GateValve, "pos": (400, 620)},
        ],
        opc_defs=[
            {"num": "OPC-24", "dir": "in", "pos": (60, 220), "ref": "200-PID-002", "desc": "REACTOR EFFLUENT FROM E-201A"},
            {"num": "OPC-32", "dir": "out", "pos": (1120, 150), "ref": "200-PID-004", "desc": "HP GAS TO C-202"},
            {"num": "OPC-33", "dir": "out", "pos": (1120, 420), "ref": "200-PID-005", "desc": "LP LIQUID TO C-201"},
            {"num": "OPC-34", "dir": "in", "pos": (60, 520), "ref": "UTILITIES", "desc": "WASH WATER SUPPLY"},
            {"num": "OPC-36", "dir": "out", "pos": (560, 520), "ref": "WW-HEADER", "desc": "WASH WATER INJECTION HDR"},
            {"num": "OPC-37", "dir": "in", "pos": (360, 310), "ref": "CW-SUPPLY", "desc": "COOLING WATER TO E-202"},
            {"num": "OPC-38", "dir": "out", "pos": (360, 120), "ref": "CW-RETURN", "desc": "COOLING WATER FROM E-202"},
        ],
        tee_defs={
            "T301": ((140, 520), "L307"),
            "T302": ((480, 520), "L308"),
        },
        tee_nodes={
            ("T301", "L307"): (0, 1),
            ("T301", "L309"): 2,
            ("T302", "L308"): (0, 1),
            ("T302", "L310"): 2,
        },
        line_defs=[
            {"id": "L301", "number": '10"-P-3001-15A1', "chain": [(("opc", "OPC-24"), []), (("eq", "A-201", "N1"), None)]},
            {"id": "L302", "number": '10"-P-3002-15A1', "chain": [(("eq", "A-201", "N2"), []), (("v", "HV-2041"), [(400, 220), (400, 150), (500, 150)]), (("eq", "E-202", "N3"), None)]},
            {"id": "L303", "number": '10"-P-3003-15A1', "chain": [(("eq", "E-202", "N4"), [(500, 270), (610, 270), (610, 250)]), (("eq", "D-202", "N1"), None)]},
            {"id": "L311", "number": '6"-W-3011-1A1', "fluid": "CW", "pclass": "1A1", "chain": [(("opc", "OPC-37"), [(426, 310)]), (("eq", "E-202", "N1"), None)]},
            {"id": "L312", "number": '6"-W-3012-1A1', "fluid": "CW", "pclass": "1A1", "chain": [(("eq", "E-202", "N2"), [(426, 120)]), (("opc", "OPC-38"), None)]},
            {"id": "L304", "number": '8"-G-3004-15A1', "fluid": "H2", "chain": [(("eq", "D-202", "N2"), [(700, 150)]), (("v", "HV-2043"), []), (("opc", "OPC-32"), None)]},
            {"id": "L305", "number": '8"-P-3005-3A1', "pclass": "3A1", "chain": [(("eq", "D-202", "N3"), [(675, 317), (675, 370)]), (("v", "HV-2044"), [(730, 370), (730, 420)]), (("v", "LV-2031"), []), (("v", "HV-2081"), []), (("eq", "D-203", "N1"), None)]},
            {"id": "L306", "number": '8"-P-3006-3A1', "pclass": "3A1", "chain": [(("eq", "D-203", "N2"), []), (("v", "HV-2087"), []), (("opc", "OPC-33"), None)]},
            {"id": "L307", "number": '3"-W-3007-15A1', "fluid": "WW", "chain": [(("opc", "OPC-34"), []), (("tee", "T301"), []), (("v", "HV-2083"), []), (("eq", "P-204A", "N1"), None)]},
            {"id": "L309", "number": '3"-W-3009-15A1', "fluid": "WW", "chain": [(("tee", "T301"), [(140, 620)]), (("v", "HV-2085"), []), (("eq", "P-204B", "N1"), None)]},
            {"id": "L308", "number": '3"-W-3008-15A1', "fluid": "WW", "chain": [(("eq", "P-204A", "N2"), []), (("v", "HV-2084"), []), (("tee", "T302"), []), (("opc", "OPC-36"), None)]},
            {"id": "L310", "number": '3"-W-3010-15A1', "fluid": "WW", "chain": [(("eq", "P-204B", "N2"), []), (("v", "HV-2086"), [(480, 620)]), (("tee", "T302"), None)]},
        ],
    )


def _build_sheet_004() -> EngineeringModel:
    return _build_generic_sheet(
        sheet_no="200-PID-004",
        sheet_idx="4",
        title="Recycle and makeup gas",
        equipment_defs=[
            {"tag": "C-202", "cls": ProcessColumn, "sym": "column", "pos": (240, 220), "desc": "AMINE SCRUBBER", "design": (98.0, 110.0), "nozzles": {"N1": "in", "N2": "top"}, "label_pos": (240, 100)},
            {"tag": "D-204", "cls": PressureVessel, "sym": "vdrum", "pos": (490, 220), "desc": "RECYCLE GAS KO DRUM", "design": (96.0, 100.0), "nozzles": {"N1": "in", "N2": "top"}, "label_pos": (490, 130)},
            {"tag": "K-201", "cls": CentrifugalCompressor, "sym": "comp", "pos": (730, 180), "desc": "RECYCLE COMPRESSOR", "design": (118.0, 130.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (730, 135)},
            {"tag": "KT-201", "cls": SteamTurbine, "sym": "turbine", "pos": (920, 320), "desc": "STEAM TURBINE DRIVER", "design": (52.0, 440.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (920, 278)},
            {"tag": "D-206", "cls": PressureVessel, "sym": "vdrum", "pos": (280, 520), "desc": "MAKEUP GAS KO DRUM", "design": (32.0, 100.0), "nozzles": {"N1": "in", "N2": "top"}, "label_pos": (280, 430)},
            {"tag": "K-202A", "cls": ReciprocatingCompressor, "sym": "comp", "pos": (640, 460), "desc": "MAKEUP COMP A", "design": (118.0, 160.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (640, 420)},
            {"tag": "K-202B", "cls": ReciprocatingCompressor, "sym": "comp", "pos": (640, 580), "desc": "MAKEUP COMP B", "design": (118.0, 160.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (640, 540)},
        ],
        valve_defs=[
            {"tag": "HV-2051", "cls": GateValve, "pos": (140, 220)},
            {"tag": "HV-2055", "cls": GateValve, "pos": (620, 180)},
            {"tag": "HV-2056", "cls": GateValve, "pos": (860, 180)},
            {"tag": "HV-2071", "cls": GateValve, "pos": (160, 520)},
            {"tag": "HV-2073", "cls": GateValve, "pos": (500, 460)},
            {"tag": "HV-2074", "cls": GateValve, "pos": (800, 460)},
            {"tag": "HV-2075", "cls": GateValve, "pos": (500, 580)},
            {"tag": "HV-2076", "cls": GateValve, "pos": (800, 580)},
        ],
        opc_defs=[
            {"num": "OPC-32", "dir": "in", "pos": (60, 220), "ref": "200-PID-003", "desc": "HP GAS FROM D-202"},
            {"num": "OPC-22", "dir": "out", "pos": (1120, 180), "ref": "200-PID-002", "desc": "RECYCLE GAS TO E-201A"},
            {"num": "OPC-23", "dir": "out", "pos": (1120, 240), "ref": "200-PID-002", "desc": "QUENCH GAS TO R-202"},
            {"num": "OPC-43", "dir": "in", "pos": (60, 520), "ref": "H2-HEADER", "desc": "MAKEUP H2 SUPPLY"},
            {"num": "OPC-46", "dir": "in", "pos": (790, 320), "ref": "STEAM-HDR", "desc": "HP STEAM TO KT-201"},
            {"num": "OPC-47", "dir": "out", "pos": (1120, 320), "ref": "STEAM-HDR", "desc": "MP STEAM EXHAUST"},
        ],
        tee_defs={
            "T401": ((940, 180), "L404"),
            "T402": ((1020, 180), "L404"),
            "T403": ((410, 460), "L408"),
            "T404": ((920, 460), "L409"),
        },
        tee_nodes={
            ("T401", "L404"): (0, 1),
            ("T401", "L412"): 2,
            ("T402", "L404"): (0, 1),
            ("T402", "L409"): 2,
            ("T403", "L408"): (0, 1),
            ("T403", "L410"): 2,
            ("T404", "L409"): (0, 1),
            ("T404", "L411"): 2,
        },
        line_defs=[
            {"id": "L401", "number": '8"-G-4001-15A1', "fluid": "H2", "chain": [(("opc", "OPC-32"), []), (("v", "HV-2051"), []), (("eq", "C-202", "N1"), None)]},
            {"id": "L402", "number": '8"-G-4002-15A1', "fluid": "H2", "chain": [(("eq", "C-202", "N2"), [(240, 80), (420, 80), (420, 220)]), (("eq", "D-204", "N1"), None)]},
            {"id": "L403", "number": '8"-G-4003-15A1', "fluid": "H2", "chain": [(("eq", "D-204", "N2"), [(490, 180)]), (("v", "HV-2055"), []), (("eq", "K-201", "N1"), None)]},
            {"id": "L404", "number": '8"-G-4004-15A1', "fluid": "H2", "chain": [(("eq", "K-201", "N2"), []), (("v", "HV-2056"), []), (("tee", "T401"), []), (("tee", "T402"), []), (("opc", "OPC-22"), None)]},
            {"id": "L412", "number": '3"-G-4012-15A1', "fluid": "H2", "chain": [(("tee", "T401"), [(940, 240)]), (("opc", "OPC-23"), None)]},
            {"id": "L405", "number": '6"-S-4005-6A1', "fluid": "STM", "pclass": "6A1", "chain": [(("opc", "OPC-46"), []), (("eq", "KT-201", "N1"), None)]},
            {"id": "L406", "number": '8"-S-4006-3A1', "fluid": "STM", "pclass": "3A1", "chain": [(("eq", "KT-201", "N2"), []), (("opc", "OPC-47"), None)]},
            {"id": "L407", "number": '6"-G-4007-6A1', "fluid": "H2", "pclass": "6A1", "chain": [(("opc", "OPC-43"), []), (("v", "HV-2071"), []), (("eq", "D-206", "N1"), None)]},
            {"id": "L408", "number": '6"-G-4008-6A1', "fluid": "H2", "pclass": "6A1", "chain": [(("eq", "D-206", "N2"), [(280, 460)]), (("tee", "T403"), []), (("v", "HV-2073"), []), (("eq", "K-202A", "N1"), None)]},
            {"id": "L410", "number": '6"-G-4010-6A1', "fluid": "H2", "pclass": "6A1", "chain": [(("tee", "T403"), [(410, 580)]), (("v", "HV-2075"), []), (("eq", "K-202B", "N1"), None)]},
            {"id": "L409", "number": '4"-G-4009-15A1', "fluid": "H2", "chain": [(("eq", "K-202A", "N2"), []), (("v", "HV-2074"), []), (("tee", "T404"), [(1020, 460)]), (("tee", "T402"), None)]},
            {"id": "L411", "number": '4"-G-4011-15A1', "fluid": "H2", "chain": [(("eq", "K-202B", "N2"), []), (("v", "HV-2076"), [(920, 580)]), (("tee", "T404"), None)]},
        ],
    )


def _build_sheet_005() -> EngineeringModel:
    return _build_generic_sheet(
        sheet_no="200-PID-005",
        sheet_idx="5",
        title="Product stripping",
        equipment_defs=[
            {"tag": "C-201", "cls": ProcessColumn, "sym": "column", "pos": (240, 340), "desc": "PRODUCT STRIPPER", "design": (15.0, 290.0), "nozzles": {"N1": "in", "N2": "top", "N3": "bottom", "N4": "side"}, "label_pos": (240, 215)},
            {
                "tag": "E-203",
                "cls": TubularHeatExchanger,
                "sym": "exchanger",
                "pos": (520, 140),
                "desc": "OVERHEAD CONDENSER",
                "chambers": {"Tube side": (10.0, 80.0), "Shell side": (15.0, 200.0)},
                "nozzles": {"N1": ("tube_in", "Tube side"), "N2": ("tube_out", "Tube side"), "N3": ("shell_in", "Shell side"), "N4": ("shell_out", "Shell side")},
                "label_pos": (520, 90),
            },
            {"tag": "D-205", "cls": PressureVessel, "sym": "hdrum", "pos": (800, 140), "desc": "OVERHEAD DRUM", "design": (15.0, 110.0), "nozzles": {"N1": "in", "N2": "out", "N3": "bottom"}, "label_pos": (800, 88)},
            {"tag": "P-202A", "cls": CentrifugalPump, "sym": "pump", "pos": (600, 300), "desc": "REFLUX PUMP A", "design": (22.0, 110.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (600, 260)},
            {"tag": "P-202B", "cls": CentrifugalPump, "sym": "pump", "pos": (600, 390), "desc": "REFLUX PUMP B", "design": (22.0, 110.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (600, 350)},
            {"tag": "P-203A", "cls": CentrifugalPump, "sym": "pump", "pos": (460, 510), "desc": "BOTTOMS PUMP A", "design": (24.0, 285.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (460, 470)},
            {"tag": "P-203B", "cls": CentrifugalPump, "sym": "pump", "pos": (460, 610), "desc": "BOTTOMS PUMP B", "design": (24.0, 285.0), "nozzles": {"N1": "in", "N2": "out"}, "label_pos": (460, 570)},
            {
                "tag": "E-204",
                "cls": TubularHeatExchanger,
                "sym": "exchanger",
                "pos": (820, 530),
                "desc": "PRODUCT COOLER",
                "chambers": {"Tube side": (10.0, 80.0), "Shell side": (20.0, 240.0)},
                "nozzles": {"N1": ("tube_in", "Tube side"), "N2": ("tube_out", "Tube side"), "N3": ("shell_in", "Shell side"), "N4": ("shell_out", "Shell side")},
                "label_pos": (820, 475),
            },
        ],
        valve_defs=[
            {"tag": "HV-2091", "cls": GateValve, "pos": (140, 340)},
            {"tag": "HV-2095", "cls": GateValve, "pos": (710, 300), "flow": "left"},
            {"tag": "HV-2096", "cls": GateValve, "pos": (500, 300), "flow": "left"},
            {"tag": "HV-2097", "cls": GateValve, "pos": (710, 390), "flow": "left"},
            {"tag": "HV-2098", "cls": GateValve, "pos": (500, 390), "flow": "left"},
            {"tag": "FV-2051", "cls": GlobeValve, "pos": (380, 290), "flow": "left"},
            {"tag": "HV-2099", "cls": GateValve, "pos": (360, 510)},
            {"tag": "HV-2100", "cls": GateValve, "pos": (570, 510)},
            {"tag": "HV-2101", "cls": GateValve, "pos": (360, 610)},
            {"tag": "HV-2102", "cls": GateValve, "pos": (570, 610)},
            {"tag": "HV-2104", "cls": GateValve, "pos": (990, 560)},
        ],
        opc_defs=[
            {"num": "OPC-33", "dir": "in", "pos": (60, 340), "ref": "200-PID-003", "desc": "LP LIQUID FROM D-203"},
            {"num": "OPC-52", "dir": "out", "pos": (1120, 140), "ref": "NAPHTHA", "desc": "WILD NAPHTHA OUT"},
            {"num": "OPC-53", "dir": "out", "pos": (1120, 560), "ref": "TANKAGE", "desc": "ULSD PRODUCT TO TANKS"},
            {"num": "OPC-57", "dir": "in", "pos": (380, 190), "ref": "CW-SUPPLY", "desc": "CW TO E-203"},
            {"num": "OPC-58", "dir": "out", "pos": (380, 60), "ref": "CW-RETURN", "desc": "CW FROM E-203"},
            {"num": "OPC-59", "dir": "in", "pos": (700, 610), "ref": "CW-SUPPLY", "desc": "CW TO E-204"},
            {"num": "OPC-60", "dir": "out", "pos": (700, 440), "ref": "CW-RETURN", "desc": "CW FROM E-204"},
        ],
        tee_defs={
            "T501": ((800, 300), "L505"),
            "T502": ((440, 300), "L506"),
            "T503": ((290, 510), "L508"),
            "T504": ((650, 510), "L509"),
        },
        tee_nodes={
            ("T501", "L505"): (0, 1),
            ("T501", "L513"): 2,
            ("T502", "L506"): (0, 1),
            ("T502", "L514"): 2,
            ("T503", "L508"): (0, 1),
            ("T503", "L510"): 2,
            ("T504", "L509"): (0, 1),
            ("T504", "L511"): 2,
        },
        line_defs=[
            {"id": "L501", "number": '8"-P-5001-3A1', "pclass": "3A1", "chain": [(("opc", "OPC-33"), []), (("v", "HV-2091"), []), (("eq", "C-201", "N1"), None)]},
            {"id": "L502", "number": '8"-P-5002-3A1', "pclass": "3A1", "chain": [(("eq", "C-201", "N2"), [(240, 60), (550, 60)]), (("eq", "E-203", "N3"), None)]},
            {"id": "L503", "number": '8"-P-5003-3A1', "pclass": "3A1", "chain": [(("eq", "E-203", "N4"), [(550, 195), (690, 195), (690, 140)]), (("eq", "D-205", "N1"), None)]},
            {"id": "L504", "number": '6"-P-5004-3A1', "pclass": "3A1", "chain": [(("eq", "D-205", "N2"), []), (("opc", "OPC-52"), None)]},
            {"id": "L515", "number": '6"-W-5015-1A1', "fluid": "CW", "pclass": "1A1", "chain": [(("opc", "OPC-57"), [(476, 190)]), (("eq", "E-203", "N1"), None)]},
            {"id": "L516", "number": '6"-W-5016-1A1', "fluid": "CW", "pclass": "1A1", "chain": [(("eq", "E-203", "N2"), [(476, 60)]), (("opc", "OPC-58"), None)]},
            {"id": "L505", "number": '4"-P-5005-3A1', "pclass": "3A1", "chain": [(("eq", "D-205", "N3"), []), (("tee", "T501"), []), (("v", "HV-2095"), [(650, 300), (650, 330), (560, 330), (560, 300)]), (("eq", "P-202A", "N1"), None)]},
            {"id": "L513", "number": '4"-P-5013-3A1', "pclass": "3A1", "chain": [(("tee", "T501"), [(800, 390)]), (("v", "HV-2097"), [(650, 390), (650, 420), (560, 420), (560, 390)]), (("eq", "P-202B", "N1"), None)]},
            {"id": "L506", "number": '4"-P-5006-3A1', "pclass": "3A1", "chain": [(("eq", "P-202A", "N2"), [(635, 300), (635, 270), (530, 270), (530, 300)]), (("v", "HV-2096"), []), (("tee", "T502"), [(440, 290)]), (("v", "FV-2051"), []), (("eq", "C-201", "N4"), None)]},
            {"id": "L514", "number": '4"-P-5014-3A1', "pclass": "3A1", "chain": [(("eq", "P-202B", "N2"), [(635, 390), (635, 360), (530, 360), (530, 390)]), (("v", "HV-2098"), [(440, 390)]), (("tee", "T502"), None)]},
            {"id": "L508", "number": '8"-P-5008-3A1', "pclass": "3A1", "chain": [(("eq", "C-201", "N3"), [(240, 510)]), (("tee", "T503"), []), (("v", "HV-2099"), []), (("eq", "P-203A", "N1"), None)]},
            {"id": "L510", "number": '8"-P-5010-3A1', "pclass": "3A1", "chain": [(("tee", "T503"), [(290, 610)]), (("v", "HV-2101"), []), (("eq", "P-203B", "N1"), None)]},
            {"id": "L509", "number": '8"-P-5009-3A1', "pclass": "3A1", "chain": [(("eq", "P-203A", "N2"), []), (("v", "HV-2100"), []), (("tee", "T504"), [(650, 470), (850, 470)]), (("eq", "E-204", "N3"), None)]},
            {"id": "L511", "number": '8"-P-5011-3A1', "pclass": "3A1", "chain": [(("eq", "P-203B", "N2"), []), (("v", "HV-2102"), [(650, 610)]), (("tee", "T504"), None)]},
            {"id": "L512", "number": '8"-P-5012-3A1', "pclass": "3A1", "chain": [(("eq", "E-204", "N4"), [(850, 560)]), (("v", "HV-2104"), []), (("opc", "OPC-53"), None)]},
            {"id": "L517", "number": '6"-W-5017-1A1', "fluid": "CW", "pclass": "1A1", "chain": [(("opc", "OPC-59"), [(776, 610)]), (("eq", "E-204", "N1"), None)]},
            {"id": "L518", "number": '6"-W-5018-1A1', "fluid": "CW", "pclass": "1A1", "chain": [(("eq", "E-204", "N2"), [(776, 440)]), (("opc", "OPC-60"), None)]},
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
