"""Our own P&ID symbols, drawn from DEXPI primitives.

Each symbol is a Shape in shape coordinates (Y down, origin at the symbol's centre) plus the
offsets of its ports, where pipes attach. Nozzle stubs are part of the equipment shapes, so a
port is the far end of its stub. Curves are drawn as polylines, which every renderer draws the
same way.

The style loosely follows ISO 10628-2. The symbols are simplified, and fine for a demo.
"""

import math

from pydexpi.pydexpi_classes.pydexpi_classes import (
    Color,
    DashStyle,
    Ellipse,
    FillStyle,
    Point,
    Polygon,
    PolyLine,
    Shape,
    Stroke,
)

BLACK = Color(r=0, g=0, b=0)
LINE_W = 0.7


def stroke(width=LINE_W, dash=DashStyle.SOLID):
    return Stroke(color=BLACK, dashStyle=dash, width=width)


def pl(*pts, dash=DashStyle.SOLID, width=LINE_W):
    return PolyLine(points=[Point(x=float(x), y=float(y)) for x, y in pts],
                    stroke=stroke(width, dash))


def poly(*pts, fill=FillStyle.TRANSPARENT):
    return Polygon(points=[Point(x=float(x), y=float(y)) for x, y in pts],
                   stroke=stroke(), fillStyle=fill)


def dot(cx, cy, r):
    return Ellipse(center=Point(x=float(cx), y=float(cy)), horizontalSemiAxis=float(r),
                   verticalSemiAxis=float(r), rotation=0.0, stroke=stroke(0.3),
                   fillStyle=FillStyle.SOLID)


def arc_pts(cx, cy, rx, ry, a0, a1, n=16):
    """Points on an ellipse from angle a0 to a1 degrees, measured clockwise from +x (Y down)."""
    out = []
    for i in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * i / n)
        out.append((round(cx + rx * math.cos(a), 4), round(cy + ry * math.sin(a), 4)))
    return out


def rect(x0, y0, x1, y1, dash=DashStyle.SOLID):
    return pl((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0), dash=dash)


def _shape(sid, name, prims):
    return Shape(id=sid, name=name, symbolRegistrationNumber="TAR-TWIN-DEMO", primitives=prims)


def exchanger():
    """Shell and tube exchanger, channel on the left, floating head on the right.
    Tube side nozzles on the channel, shell side nozzles on the shell."""
    prims = [
        rect(-60, -20, -44, 20),
        pl((-44, -20), (46, -20)),
        pl((-44, 20), (46, 20)),
        pl(*arc_pts(46, 0, 12, 20, -90, 90)),
        pl((-44, 0), (40, 0), dash=DashStyle.DASH, width=0.4),
        # Nozzle stubs.
        pl((-52, 20), (-52, 30)), pl((-52, -20), (-52, -30)),
        pl((35, -20), (35, -30)), pl((35, 20), (35, 30)),
    ]
    ports = {"tube_in": (-52, 30), "tube_out": (-52, -30),
             "shell_in": (35, -30), "shell_out": (35, 30)}
    return _shape("Shape_EXCHANGER", "SHELL_AND_TUBE_EXCHANGER_FLOATING_HEAD", prims), ports


def _zigzag(x0, x1, y_top, y_bot, steps):
    pts = [(x0, y_top)]
    for i in range(1, steps + 1):
        x = x0 + (x1 - x0) * i / steps
        pts.append((round(x, 4), y_bot if i % 2 else y_top))
    pts[-1] = (x1, y_top)
    return pts


def furnace():
    """Box heater with a convection section and stack, two coil passes, three burners."""
    prims = [
        rect(-60, -50, 60, 100),
        pl((-60, -50), (-30, -90), (30, -90), (60, -50)),
        rect(-30, -120, 30, -90),
        rect(-8, -150, 8, -120),
        pl(*_zigzag(-60, 60, -40, -20, 12)),
        pl(*_zigzag(-60, 60, 30, 50, 12)),
        pl((-70, -40), (-60, -40)), pl((60, -40), (70, -40)),
        pl((-70, 30), (-60, 30)), pl((60, 30), (70, 30)),
    ]
    for x in (-30, 0, 30):
        prims.append(poly((x - 5, 100), (x, 86), (x + 5, 100)))
    ports = {"p1_in": (-70, -40), "p1_out": (70, -40), "p2_in": (-70, 30), "p2_out": (70, 30)}
    return _shape("Shape_FURNACE", "FIRED_HEATER_BOX_TYPE", prims), ports


def reactor(sid, width, height, beds):
    """Vertical vessel with 2:1 heads. `beds` is a list of (top, bottom) fractions of the
    straight shell, drawn as dashed catalyst bed outlines."""
    a = width / 2
    r = a / 2
    y_top, y_bot = -height / 2, height / 2
    s_top, s_bot = y_top + r, y_bot - r
    prims = [
        pl((-a, s_top), (-a, s_bot)),
        pl((a, s_top), (a, s_bot)),
        pl(*arc_pts(0, s_top, a, r, 180, 360)),
        pl(*arc_pts(0, s_bot, a, r, 0, 180)),
        pl((0, y_top), (0, y_top - 10)),
        pl((0, y_bot), (0, y_bot + 10)),
    ]
    span = s_bot - s_top
    for f0, f1 in beds:
        prims.append(rect(-a + 5, s_top + span * f0, a - 5, s_top + span * f1,
                          dash=DashStyle.DASH))
    ports = {"top": (0, y_top - 10), "bottom": (0, y_bot + 10)}
    if len(beds) > 1:
        prims.append(pl((a, 0), (a + 10, 0)))
        ports["quench"] = (a + 10, 0)
    return _shape(sid, "VERTICAL_REACTOR_WITH_CATALYST_BEDS", prims), ports


def gate_valve():
    prims = [poly((-10, -6), (10, 6), (10, -6), (-10, 6))]
    return _shape("Shape_GATE_VALVE", "GATE_VALVE", prims), {"a": (-10, 0), "b": (10, 0)}


def control_valve():
    """Globe valve body with a diaphragm actuator."""
    prims = [
        poly((-10, -6), (10, 6), (10, -6), (-10, 6)),
        dot(0, 0, 2.2),
        pl((0, 0), (0, -12)),
        pl((-8, -12), (8, -12)),
        pl(*arc_pts(0, -12, 8, 7, 180, 360)),
    ]
    return _shape("Shape_CONTROL_VALVE", "GLOBE_CONTROL_VALVE", prims), {"a": (-10, 0), "b": (10, 0)}


def off_page(pointing):
    """Off-page connector arrow. Ports: `tip` where the arrow points, `tail` the other end."""
    if pointing == "right":
        prims = [poly((-20, -8), (10, -8), (20, 0), (10, 8), (-20, 8))]
        ports = {"tip": (20, 0), "tail": (-20, 0)}
        sid = "Shape_OPC_RIGHT"
    else:
        prims = [poly((20, -8), (-10, -8), (-20, 0), (-10, 8), (20, 8))]
        ports = {"tip": (-20, 0), "tail": (20, 0)}
        sid = "Shape_OPC_LEFT"
    return _shape(sid, "PIPE_OFF_PAGE_CONNECTOR", prims), ports


def tee_dot():
    return _shape("Shape_TEE", "PIPE_TEE_JUNCTION", [dot(0, 0, 2)]), {"c": (0, 0)}
