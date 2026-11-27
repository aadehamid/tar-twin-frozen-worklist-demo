# Spike: the plant graph in Relate WASM, in a browser page

Status: passed on 2026-11-27. All nine checks pass, so decision D4 stands and the fallback isn't needed.

This spike answers a phase 0 question in [design.md](../design.md) section 10. Can the twin UI load the plant graph into Relate in the browser from a Cypher script, and then run the graph panel's traversal there? Decision D4 says what we fall back to if seeding or queries are too slow at about 5,000 nodes. The panel then calls the twin API instead.

## 1. What Relate gives us

Read from the `@relate/relate-wasm` 1.3.0 package and its [WebAssembly API reference](https://relatedb.ai/docs/reference/api/wasm/) before writing the checks.

- Relate is Neo4j's embedded Cypher engine, written in Rust and licensed Apache-2.0. The browser build is an ES module plus a WebAssembly file of about 7 MB.
- `new RelateDb()` opens an empty in-memory store. `execute` runs one statement and `executeScript` runs a script of statements split on `;`. Each statement commits on its own, and there's no `BEGIN`.
- A statement can be up to 4 MB of text. Parameters carry JSON values.
- It can't open a saved store file or a URL. It can keep a store in the browser's private file system, from a dedicated worker. The spike doesn't need that.
- `new RelateDb(true)` is read-only, but it starts empty and nothing can be loaded into it. So the design's "the browser copy opens read-only after seeding" can't work as written. A first probe confirmed it: a write on a read-only store fails. Section 4 says what the worker does instead.
- Quantified path patterns work, which is what the envelope walk needs. A probe found one form of the pattern that returned no rows where Neo4j should return one, so the walk uses the plain form and a check compares it with Python.

## 2. What gets loaded

`spikes/relate-wasm/export_cypher.py` reads sheet 200-PID-002 from the DEXPI XML that the [DEXPI sheet spike](dexpi-sheet.md) wrote, using pyDEXPI. It writes `plant.cypher`, following the graph model in design.md section 4.3:

- `Equipment` nodes with tag, DEXPI ID, class and description, and `HAS_NOZZLE` to `Nozzle` nodes.
- `Valve` nodes with tag, type and role. Gate valves are `block` and globe valves are `control`. `PipeTee` and `OffPageConnector` nodes for the other piping items.
- `CONNECTED_TO` for each DEXPI pipe, from its source item to its target item, carrying the line number.
- A `PidSheet` node, with `ON_SHEET` from each equipment item and valve.
- Isolation envelope ENV-200-02, with `CONTAINS` to equipment and `BOUNDED_BY` to block valves. The exporter computes it in Python by walking the piping from each piece of equipment until every path ends at a block valve or an off-page connector. Equipment is walked through, so tube and shell side count as one loop. That's right for the HP loop, which is isolated as one envelope.
- Five synthetic `ScopeItem` nodes standing in for IMPACT Web requests. Four resolve to equipment on this sheet. WR-200-0188 doesn't resolve to anything yet.

On this sheet ENV-200-02 contains all six pieces of equipment, and it's bounded by HV-2001, HV-2003, HV-2015 and HV-2002. The scenario spec's full envelope has 38 boundary valves across several sheets, and phase 1 joins the sheets through their off-page connectors.

The script loads in batches: `UNWIND` over a literal list of rows, a few hundred rows per statement, with indexes created first. That keeps every statement well under the 4 MB limit.

For the speed check, `export_cypher.py --pad 104` adds 104 copies of the sheet, each with its own sheet number, tag suffix, envelope and scope items. With the real sheet that's 105 times 48 nodes, or 5,040. The copies aren't connected to the real sheet. They exist only to make the store the size D4 talks about.

## 3. The graph panel queries

Clicking WR-200-0147 runs two fixed queries.

1. The chain. From the request, its resolved equipment and that equipment's nozzles, the envelope that contains it, the envelope's boundary valves, and the other requests that resolve to equipment in the same envelope.
2. The live walk. From the resolved equipment, a quantified path pattern over `CONNECTED_TO` and `HAS_NOZZLE` that doesn't pass through a block valve or an off-page connector, returning the block valves it reaches and the equipment it passes. This recomputes the envelope in the browser, so the audience sees the boundary come from the piping and not from a stored answer.

## 4. Checks and pass conditions

The answer key is `spikes/relate-wasm/expected.json`, written by hand from section 2 and the DEXPI sheet spike's answer key. The exporter doesn't read it.

| ID | Check | Pass condition |
|---|---|---|
| W1 | Package | `@relate/relate-wasm` is pinned at 1.3.0 in the lock file, and the engine reports Relate 1.3.0. RECORD the license and the size of the WebAssembly file |
| W2 | Deterministic, loadable script | Two exports give byte-identical scripts. Every statement is under 4,194,304 bytes, and the script has no `BEGIN` or `COMMIT` |
| W3 | The script matches the sheet | The exported rows, counted in Python, give the node counts by label and relationship counts by type in the answer key. `CONNECTED_TO` reduced to tagged items, walking through tees, nozzles and equipment sides, gives the DEXPI sheet spike's 21 flow edges |
| W4 | Seeding in Node | The same WebAssembly build, run in Node, executes the script with no error in any statement. Counting in Cypher gives the W3 numbers |
| W5 | Envelope walk | The live walk from E-201B returns exactly the expected boundary valves and contained equipment. They also match the stored ENV-200-02. Negative control: in a copy of the script with HV-2001's role changed to `control`, the walk no longer returns HV-2001. Stop rules: with the sentinels in `sentinels.json` added, both the Python and the Cypher walk still give the expected answer. A mutant of each walk that ignores block valves reaches the sentinel beyond HV-2003, and one that ignores off-page connectors reaches the sentinel beyond a test-only connector off FV-2011 |
| W6 | Panel chain | The chain query for WR-200-0147 returns exactly the expected request, equipment, nozzles, envelope, boundary valves and other requests. WR-200-0188 isn't among them |
| W7 | In the browser | Headless Chromium loads a static page over HTTP. A module worker fetches the WebAssembly file and the script, seeds, and runs both queries for WR-200-0147. The results equal W5 and W6 exactly. The page shows the query text and the tags, and logs no console errors |
| W8 | Speed at about 5,000 nodes | With the padded script in the browser, seeding takes at most 3 seconds and the median of 20 chain-plus-walk runs is at most 50 ms. RECORD the node count, script size, seed time, and median and worst query times, in the browser and in Node. The padded results for WR-200-0147 equal the unpadded ones |
| W9 | Read-only | `new RelateDb(true)` refuses a write and holds no nodes, which is why seeding can't use it. The worker answers only the named queries it knows, and refuses any other query text. It seeds once, from a named source on its own list, and refuses a URL or a second seed |

## 5. Results

Run with `PYTHON=/tmp/dexvenv/bin/python node spikes/relate-wasm/run_spike.mjs` after `npm ci` in `spikes/relate-wasm`. It writes `results.json` and `panel.png`. The Python, Node and pass conditions were written before the code. The browser test was written after the page, against the W7 and W8 conditions in the table above.

| ID | Result |
|---|---|
| W1 | Pass. `@relate/relate-wasm` 1.3.0, Apache-2.0, and the engine reports 1.3.0. The WebAssembly file is 6,967,206 bytes |
| W2 | Pass. Two exports are byte-identical, at both sizes. The largest statement is well under the limit, since the whole padded script is about 1 MB |
| W3 | Pass. 48 nodes and 72 relationships, matching the answer key by label and type. `CONNECTED_TO` reduced to tagged items gives exactly the DEXPI sheet spike's 21 flow edges |
| W4 | Pass. Every statement ran without error in Node, and Cypher counts match W3 |
| W5 | Pass. The live walk from E-201B reaches HV-2001, HV-2002, HV-2003 and HV-2015 and passes all six pieces of equipment. That's the same as the stored ENV-200-02. With HV-2001 changed to a control valve, the walk goes on to OPC-21 and HV-2001 drops out of the boundary. All four stop-rule mutants reach their sentinels, two in Python and two in Cypher. The first review caught that without sentinels the stop rules went untested. On this sheet nothing sits past a boundary valve, and every off-page connector is already behind one |
| W6 | Pass. The chain for WR-200-0147 gives E-201B, nozzles N1 to N4, ENV-200-02, the four block valves, and WR-200-0152, WR-200-0160 and WR-200-0171. WR-200-0188 isn't there |
| W7 | Pass. Headless Chromium seeded the 48-node graph in a module worker in about 130 ms and showed the same results as W5 and W6, with the query text. No console errors and no failed requests |
| W8 | Pass. See the table below |
| W9 | Pass. `new RelateDb(true)` refuses `CREATE` with `WriteOnReadOnlyAccessDatabase` and holds no nodes. The worker refuses `MATCH (n) DETACH DELETE n` as an unknown query, refuses an extra parameter, and still answers the chain afterwards. A page asked to seed from another site fails with `unknown seed source`, and a second seed request fails with `already seeded` |

Speed at 5,040 nodes, padded script 1,038,837 bytes, 20 runs of chain plus walk:

| | Seed | Median query | Worst query |
|---|---|---|---|
| Headless Chromium | 1,365 ms | 26 ms | 49 ms |
| Node 20 | 1,374 ms | 31 ms | 34 ms |
| Limit | 3,000 ms | 50 ms | none |

The engine itself took about 60 ms to initialise in the browser, and fetching the script about 10 ms. The worst browser time is the first run. The first query after seeding costs about 110 ms, even on the small graph, and later runs settle around 25 ms. So the worker should warm each named query once after seeding, before the audience clicks. Times come from one run on the sandbox and will move a little between runs. Six earlier runs gave browser seed times from 1.36 to 1.61 seconds, medians from 24 to 26 ms, and worst times from 49 to 69 ms.

### Limits of this result

- The padded copies aren't connected to each other or to the real sheet. Both queries start from one tag, so they only ever touch one 48-node component. The 5,040-node figure tests seeding cost and index lookups at that size, not a walk across a large connected envelope. The scenario spec's target envelope has 38 boundary valves over several sheets, and phase 1 has to measure the walk on that.
- The page runs the queries on load, not on a click. The click handler in the real panel calls the same worker messages.
- Seeding trusts the script it's given. The worker only takes scripts from its own list, but it runs whatever Cypher is in them. In phase 1 the source is the twin's own export endpoint on the same origin. The worker has no connection to Neo4j, so nothing in the browser can change the master graph.

## 6. What changes in the design

- Design section 5.7 said the browser copy opens read-only after seeding. Relate can't do that, because its read-only store is always empty. The store now stays private to the worker, which runs only named queries with string parameters. Design 5.7 and decision D4 are updated.
- The walk uses the plain quantified path form, `(e)(()-[..]-(n) WHERE ..)*()-[:CONNECTED_TO]-(v)`. The probe's other form returned no rows, and W5 would catch a regression when Relate is upgraded.
- Phase 1 swaps the hand-run exporter for `GET /api/v1/graph/export.cypher`, built from Neo4j, and joins sheets through their off-page connectors. Each new sheet should get its own expected boundary in a check like W5.
