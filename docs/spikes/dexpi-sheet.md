# Spike: build and render one DEXPI sheet with pyDEXPI

Status: checks written, not run yet.

This spike answers the phase 0 question in [design.md](../design.md) section 10: can pyDEXPI build a realistic Unit 200 sheet from code, write it as valid DEXPI, read it back, and render it to SVG for the P&ID viewer? If the render fails, decision D4 already names the fallback, which is to draw our own SVG from the DEXPI topology.

The sheet is 200-PID-002, Reaction, from [scenario-spec.md](../scenario-spec.md) section 2.3. It's the sheet the demo highlights when a planner opens a job on E-201B, so it's the one worth proving first.

## 1. What pyDEXPI gives us, and what it doesn't

Read from the pyDEXPI 2.1.0 package and its docs before writing the checks.

- It implements DEXPI 2.0.1 and writes DEXPI XML and JSON.
- It has a model validator (`pydexpi.validation.validate`), a NetworkX graph builder at four levels, an SVG renderer (`DrawDiagram`) and a Neo4j CSV exporter.
- It draws only what the file already contains. It has no automatic layout and chooses no symbols. So the builder has to place every symbol, nozzle, label and pipe route itself.
- It's licensed AGPL-3.0. The demo only uses it unmodified, and inside a private repo, but if a client ever wants the code, that license comes with it. Hamid should know this before the code leaves the team.
- The DEXPI reference P&ID that ships with pyDEXPI passes both the DEXPI XML schema and pyDEXPI's validator with zero issues. So both are fair bars for our sheet.

The symbols are our own, drawn from DEXPI primitives (polylines, polygons, ellipses and arcs) in a small catalogue. That keeps the port positions under our control and means we don't carry the reference drawing around. The DEXPI XML schema is vendored from the pyDEXPI repo, where it's licensed CC BY 4.0 by DEXPI e.V.

## 2. The sheet

Flow follows the process summary in scenario-spec.md section 2.1. Feed and effluent run counter-current through the three feed/effluent shells.

- Combined feed enters from 200-PID-001 (charge pump P-201A/B discharge) through block valve HV-2001. Recycle gas from 200-PID-004 joins it through HV-2003.
- Feed side: E-201A, then E-201B, then E-201C, then a split into the two heater passes, each with a pass flow control valve (FV-2011, FV-2012), into charge heater H-201.
- The two passes rejoin and go to guard reactor R-201, then main reactor R-202.
- Quench gas from 200-PID-004 enters R-202 between the beds, through HV-2015 and FV-2015.
- Effluent side: R-202 outlet, then E-201C, then E-201B, then E-201A, then block valve HV-2002, then off the sheet to air cooler A-201 on 200-PID-003.

The heat exchangers carry feed on the tube side and effluent on the shell side. Each exchanger's two chambers say which is which, so a check can tell the sides apart.

## 3. Checks and pass conditions

The expected inventory and flow edges are written by hand in `spikes/dexpi-sheet/expected.py`, from the list above and the scenario spec. That file doesn't import the builder, so the builder can't grade itself.

| ID | Check | Pass condition |
|---|---|---|
| X1 | Library | pyDEXPI 2.1.0 imports and reports DEXPI 2.0.1. RECORD the license |
| X2 | Deterministic build | Two builds in one process give byte-identical XML |
| X3 | Schema | The written XML validates against the DEXPI 2.0.1 XML schema. Negative control: the same file with one ID changed to start with a digit fails |
| X4 | pyDEXPI validator | `validate()` on the reloaded model returns zero issues at any level. Negative control: removing one pipe's target node from its segment makes the validator or the topology check fail |
| X5 | Round trip | Loading the written XML and saving it again gives byte-identical XML |
| X6 | Inventory | The reloaded model holds exactly the expected tags, each with the expected DEXPI class, and no others. Every object ID is unique and matches the schema's ID pattern |
| X7 | Flow topology, two ways | Walking the reloaded model's piping segments gives exactly the expected directed edges between tagged items, with exchanger sides named. Separately, pyDEXPI's own conceptual graph, reduced to tagged items, gives the same edges with sides dropped. Both must match |
| X8 | Matcher facts | Every fact in `spikes/decider-matcher/cases.py` about a tag on this sheet is true of the sheet's piping |
| X9 | Render | `DrawDiagram` writes an SVG that parses. Its view box is finite and positive. Every tag appears in exactly one text label. No two equipment symbols overlap. Every pipe's drawn line starts and ends on the node positions of the nozzles or valve ends it connects. RECORD a PNG for a visual check |
| X10 | Neo4j records | pyDEXPI's conceptual-level Neo4j export holds one node per tagged item with its tag. Every relationship's ends are nodes in the export. RECORD the node and relationship counts |
| X11 | Speed | RECORD build, write, reload, validate and render times |

X8 is there because the matcher spike wrote its neighbour facts by hand. If the plant graph and those facts disagree, the AI matcher would be shown facts the twin can't back up. Writing this check turned up one such disagreement before any code ran: fact F-R202-1 says R-202's inlet is from the charge heater, but the process summary puts guard reactor R-201 between them. This PR corrects the fact to say R-202's inlet is from R-201.

## 4. Results

Not run yet.
