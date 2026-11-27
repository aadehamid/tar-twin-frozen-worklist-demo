# Spike: build and render one DEXPI sheet with pyDEXPI

Status: done. Every check passes. pyDEXPI builds, validates and renders the sheet, so D5's fallback isn't needed.

This spike answers the phase 0 question in [design.md](../design.md) section 10: can pyDEXPI build a realistic Unit 200 sheet from code, write it as valid DEXPI, read it back, and render it to SVG for the P&ID viewer? If the render fails, decision D5 already names the fallback, which is to draw our own SVG from the DEXPI topology.

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
| X2 | Deterministic build | Two builds in one process give byte-identical XML, and the XML committed in the repo is byte-identical to a fresh build |
| X3 | Schema | The written XML validates against the DEXPI 2.0.1 XML schema. Negative control: the same file with one ID changed to start with a digit fails |
| X4 | pyDEXPI validator | `validate()` on the reloaded model returns zero issues at any level. Negative control: removing one pipe's target node from its segment makes the validator or the topology check fail |
| X5 | Round trip | Loading the written XML and saving it again gives byte-identical XML |
| X6 | Inventory | The reloaded model holds exactly the expected tags, each with the expected DEXPI class, and no others. Every object ID is unique and matches the schema's ID pattern |
| X7 | Flow topology, two ways | Walking the reloaded model's piping segments gives exactly the expected directed edges between tagged items, with exchanger sides named. Separately, pyDEXPI's own conceptual graph, reduced to tagged items, gives the same edges with sides dropped. Both must match |
| X8 | Matcher facts | Every fact in `spikes/decider-matcher/cases.py` about a tag on this sheet is true of the sheet's piping |
| X9 | Render | `DrawDiagram` writes an SVG that parses. Its view box is finite and positive. Every tag appears in exactly one text label. No two equipment symbols overlap. Every pipe's drawn line starts and ends on the node positions of the nozzles or valve ends it connects, and every leg is horizontal or vertical. Every text, by an estimated box, stays inside the border, clear of the title block, clear of other text and clear of other items' symbols. Text inside a reactor stays off the catalyst beds. RECORD a PNG for a visual check |
| X10 | Neo4j records | pyDEXPI's conceptual-level Neo4j export holds one node per tagged item with its tag. Every relationship's ends are nodes in the export. RECORD the node and relationship counts |
| X11 | Speed | RECORD build, write, reload, validate and render times |

X8 is there because the matcher spike wrote its neighbour facts by hand. If the plant graph and those facts disagree, the AI matcher would be shown facts the twin can't back up. Writing this check turned up one such disagreement before any code ran: fact F-R202-1 says R-202's inlet is from the charge heater, but the process summary puts guard reactor R-201 between them. This PR corrects the fact to say R-202's inlet is from R-201. X8 also checks that the tags each fact names in its text are the tags its hand-coded claims test, so the text can't drift away from the check.

## 4. Results

Run on 2026-11-26 with pyDEXPI 2.1.0 on Python 3.14. `pytest spikes/dexpi-sheet` runs 46 tests and all pass. `python spikes/dexpi-sheet/run_spike.py` writes the sheet as `200-PID-002.xml`, `200-PID-002.svg` and `200-PID-002.png`, and the recorded values to `results.json`.

| ID | Result | Detail |
|---|---|---|
| X1 | PASS | pyDEXPI 2.1.0, DEXPI 2.0.1. RECORD: GNU Affero General Public License v3 |
| X2 | PASS | Byte-identical across builds, once the builder replaced pyDEXPI's random default IDs with IDs taken from each object's place in the model. The first run failed here |
| X3 | PASS | Valid against the vendored DEXPI 2.0.1 schema. The negative control fails as it should |
| X4 | PASS | Zero validator issues. The first run had three "tee in middle of segment" recommendations, so each line that owns a tee is now split into two segments at the tee |
| X5 | PASS | Load and save again gives the same bytes |
| X6 | PASS | 6 equipment items, 7 valves and 4 off-page connectors, each with the expected class and nothing extra. All IDs unique and schema-safe |
| X7 | PASS | The segment walk and pyDEXPI's conceptual graph both give the 21 expected flow edges |
| X8 | PASS | All 9 facts about tags on this sheet hold. The text check failed on the old F-R202-1 before the fix, as planned |
| X9 | PASS | SVG parses, every tag is labelled once, no symbols overlap and every pipe joins its ends with straight legs. The first render had the title block over HV-2002 and OPC-24, connector text off the sheet and reactor text over the beds. The text checks were added for those, failed, and pass after the layout fix |
| X10 | RECORD | 24 nodes and 28 relationships at the conceptual level, every relationship end a node |
| X11 | RECORD | Build 40 ms, write 39 ms, reload 97 ms, validate 13 ms, SVG 9 ms, PNG 95 ms. The XML is about 430 KB |

Correcting F-R202-1 changed what the Decider matcher sees, so its live run was recorded again on the same day, at no cost. Every verdict is the same. C3 still abstains, at 0.881 confidence instead of 0.870. [decider-matcher.md](decider-matcher.md) has the new numbers.

What this shows and doesn't:

- pyDEXPI is a sound base for the plant model. It wrote, reloaded, validated and rendered a hand-placed sheet with no workarounds inside the library.
- Layout is all ours. Every symbol position and pipe route in `build_sheet.py` is typed in by hand. Phase 1 needs four more sheets, so expect to spend real time there, or write a small router for the straight-line legs.
- The symbols are simplified and the lines have no flow arrows. That's fine for a demo viewer, and a fair thing to improve once the viewer exists.
- The text checks guess at text width from character counts, since the SVG doesn't carry font metrics. They catch the gross faults. Someone still has to look at the PNG.
- The AGPL-3.0 license still matters if the code ever leaves the team. Nothing in this spike changes that.
