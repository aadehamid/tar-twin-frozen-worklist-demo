"""Write sheet 200-PID-002 as DEXPI XML, SVG and PNG, and record the RECORD values.

    python run_spike.py

Writes 200-PID-002.xml, 200-PID-002.svg, 200-PID-002.png and results.json next to this file.
The pass and fail checks are in test_sheet.py; this script only records.
"""

import importlib.metadata as md
import json
import platform
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from pydexpi.exports.neo4j_export import get_neo4j_records  # noqa: E402
from pydexpi.loaders import DexpiXmlSerializer  # noqa: E402
from pydexpi.validation import validate  # noqa: E402

import build_sheet  # noqa: E402

HERE = Path(__file__).resolve().parent


def timed(fn, *args, **kwargs):
    t0 = time.perf_counter()
    out = fn(*args, **kwargs)
    return out, round((time.perf_counter() - t0) * 1000, 1)


def main():
    times = {}
    model, times["build_ms"] = timed(build_sheet.build_model)
    xml, times["write_xml_ms"] = timed(build_sheet.write_xml, model, HERE)
    reloaded, times["reload_ms"] = timed(DexpiXmlSerializer().load, HERE, build_sheet.SHEET)
    issues, times["validate_ms"] = timed(validate, reloaded)
    svg, times["render_svg_ms"] = timed(build_sheet.render_svg, reloaded,
                                        HERE / f"{build_sheet.SHEET}.svg")
    png, times["render_png_ms"] = timed(build_sheet.render_png, reloaded,
                                        HERE / f"{build_sheet.SHEET}.png")
    records = get_neo4j_records(reloaded, graph_level="conceptual")

    meta = md.metadata("pydexpi")
    results = {
        "sheet": build_sheet.SHEET,
        "X1": {"pydexpi": md.version("pydexpi"),
               "license": meta.get("License-Expression") or next(
                   (c.split("::")[-1].strip() for c in meta.get_all("Classifier") or []
                    if c.startswith("License ::")), None),
               "python": platform.python_version()},
        "X4": {"validator_issues": len(issues)},
        "X9": {"svg": svg.name, "svg_bytes": svg.stat().st_size, "png": png.name,
               "png_bytes": png.stat().st_size},
        "X10": {"nodes": len(records.nodes), "relationships": len(records.relationships)},
        "X11": times,
        "xml_bytes": xml.stat().st_size,
    }
    (HERE / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
