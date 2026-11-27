# Spike: SHACL through n10s on a local Neo4j

Status: passed on 2026-11-27. All eight checks pass, with two findings that change how the loader uses n10s (section 6).

This spike answers a phase 0 question in [design.md](../design.md) section 10. [verification.md](../verification.md) section 2 says the twin checks its plant and scope data with SHACL shapes run inside Neo4j by neosemantics (n10s), and that the twin loader writes inside a transaction that rolls back when a change breaks a rule. Three things are unproven:

1. Does n10s load and run our kind of shapes on a plain property graph, without the graph having been imported from RDF?
2. Does the transaction check really refuse a bad write and leave the graph as it was?
3. Which of the rules in verification.md can SHACL in n10s express at all, and which need Cypher or Python?

It also covers the other half of design section 3.3's no-Docker development, a local Neo4j run from the release tarball. The [template spike](template-no-docker.md) covered Postgres and Mailpit.

## 1. What n10s supports

Read from the n10s 5.26.0 source and docs before writing the shapes ([validation.adoc](https://github.com/neo4j-labs/neosemantics/blob/5.26.0/docs/modules/ROOT/pages/validation.adoc), [SHACLValidator.java](https://github.com/neo4j-labs/neosemantics/blob/5.26.0/src/main/java/n10s/validation/SHACLValidator.java)).

- Shapes are Turtle, loaded with `n10s.validation.shacl.import.inline` or `.fetch`. On a property graph only the local name of each IRI counts, so `neo4j:Equipment` means the label `Equipment` and `neo4j:tag` means the property or relationship type `tag`.
- Targets are `sh:targetClass`, which means a label. Paths are a single property or relationship type, optionally `sh:inversePath`.
- Constraints: `sh:minCount`, `sh:maxCount`, `sh:datatype`, `sh:pattern`, `sh:minLength`, `sh:maxLength`, `sh:minInclusive`, `sh:maxInclusive`, `sh:minExclusive`, `sh:maxExclusive`, `sh:in`, `sh:hasValue`, `sh:class`, `sh:nodeKind`, and `sh:closed` with `sh:ignoredProperties`. n10s also reads two forms of its own, `sh:in` wrapped in `sh:not` and `sh:class` wrapped in `sh:not`.
- Not supported: `sh:or`, `sh:and`, `sh:xone`, general `sh:not` and `sh:node`, qualified value shapes, property pair constraints such as `sh:lessThan`, longer property paths, and SPARQL constraints.
- `validate()` checks the whole graph, `validateSet(nodes)` checks a set of nodes, and `validateTransaction(...)` runs from an APOC trigger in the `before` phase and throws, which rolls the transaction back.

So a rule that says "if this, then that" needs a way to pick out the "if" nodes. The portable way is a label, and that is what this spike's shapes use. For example, "a bundle pull only goes on an exchanger" becomes a `BundlePull` label on the scope item and a shape saying its `RESOLVES_TO` target has the label `Exchanger`. n10s 5.26 also reads its own `sh:targetQuery`, a Cypher target, which could pick out the "if" nodes without a label. pySHACL and other SHACL engines don't read it, so the spike stays with labels to keep the cross-check. Rules that walk paths or add up numbers can't be shapes at all.

## 2. The test graph

The same sheet as the Relate spike, 200-PID-002, exported by `spikes/relate-wasm/export_cypher.py`: 48 nodes and 72 relationships, with the isolation envelope ENV-200-02 and five IMPACT Web scope items. The spike adds what the shapes need and the export doesn't have yet:

- A second label on each piece of equipment from its DEXPI class: `Exchanger` for `TubularHeatExchanger`, `FiredHeater` for `Furnace`, `Reactor` for the pressure vessels R-201 and R-202.
- On each scope item, a work type label and a RIPT score from 1 to 25. WR-200-0147 `BundlePull`, WR-200-0152 `CatalystChangeout`, WR-200-0160 `HeaterDecoke`, WR-200-0171 `Retube`, WR-200-0188 `GeneralCleanup`.

## 3. Shapes

`spikes/shacl-n10s/shapes.ttl`, written to use only constructs that n10s and standard SHACL read the same way.

| Shape | Target | Rule |
|---|---|---|
| S1 | `Equipment` | Exactly one `tag`, a string matching the Unit 200 major equipment pattern `^(FL\|D\|P\|R\|E\|H\|A\|C\|K\|KT)-2[0-9]{2}[A-Z]?$` |
| S2 | `Equipment` | Exactly one `ON_SHEET` to a `PidSheet`. Every `HAS_NOZZLE` goes to a `Nozzle` |
| S3 | `Valve` | Exactly one `tag` matching `^(HV\|XV\|FV\|LV\|PV\|PSV)-2[0-9]{3}$`. Exactly one `role`, one of block, control, check, relief |
| S4 | `ScopeItem` | Exactly one `request_id` matching `^WR-200-[0-9]{4}$`. Exactly one `exercise_id`. One `ript` from 1 to 25. At most one `RESOLVES_TO`, and it goes to `Equipment` |
| S5 | `BundlePull`, `Retube` | `RESOLVES_TO` goes to an `Exchanger` |
| S6 | `CatalystChangeout` | `RESOLVES_TO` goes to a `Reactor` |
| S7 | `HeaterDecoke` | `RESOLVES_TO` goes to a `FiredHeater` |
| S8 | `IsolationEnvelope` | At least one `CONTAINS` to `Equipment` and at least one `BOUNDED_BY` to a `Valve` |

## 4. How it runs

`spikes/shacl-n10s/run_spike.py` does the whole run in a new temporary folder and writes `results.json`. It never calls `docker`.

1. Fetch the Neo4j Community 5.26.34 tarball and n10s 5.26.0, and check both against pinned SHA-256 values. Stop before unpacking if either differs.
2. Unpack Neo4j, copy n10s into `plugins/`, and use the APOC core jar that ships in the tarball's `labs/` folder. Set heap 768 MB and page cache 384 MB, the [hosting.md](../hosting.md) budget, bind to localhost on spare ports, and allow the `n10s.*` and `apoc.*` procedures. Enable APOC triggers.
3. Start Neo4j, load the test graph, load the shapes, and run the checks below through the Python driver.
4. Stop Neo4j and delete the folder.

## 5. Checks and pass conditions

Before the run script uses them, `test_checks.py` unit-tests the pure parts: the Turtle rendering of the graph, the mutants and the comparison of violation sets.

| ID | Check | Pass condition |
|---|---|---|
| N1 | No Docker, pinned inputs | The run script has no `docker` command. Neo4j matches the SHA-256 that dist.neo4j.org publishes for it, n10s matches the digest GitHub records for the release asset, and both match the values pinned in the script. RECORD the Java, Neo4j, n10s and APOC versions |
| N2 | Start | Within 60 seconds Neo4j answers on Bolt, and `SHOW PROCEDURES` lists `n10s.validation.shacl.validate`, `n10s.validation.shacl.validateTransaction` and `apoc.trigger.install` |
| N3 | Test graph | Node and relationship counts by label and type equal the Relate spike's `expected.json`, plus the labels and properties from section 2 |
| N4 | Shapes load | `import.inline` succeeds, `listShapes()` covers every target, path and constraint in section 3, and its counts, bounds and patterns equal the values rdflib reads from `shapes.ttl`. The checked rows, values included, become the pinned set the readiness check in N7 compares against. RECORD the rows |
| N5 | Clean graph | `validate()` returns no rows on the test graph |
| N6 | Mutants | For each mutant in `mutants.py`, applied to a fresh copy of the test graph, `validate()` returns the violations written down for it by hand, as (node key, label, constraint, path). Every shape has at least one mutant. The same graph and shapes are also checked with pySHACL, an independent SHACL engine, on a Turtle rendering of the graph, and pySHACL must report exactly the same set. n10s must agree once min and max count are folded into `CountConstraintComponent` and the range constraints into `ValueRangeConstraintComponent`, the two names n10s uses when a shape has both bounds (finding 1). RECORD how many agree without folding |
| N7 | Transaction guard | With the trigger installed, each mutant run as a write fails with `TransactionHookFailed` and a `SHACLValidationException` in the message, and afterwards the graph reads back identical. A valid write, a new scope item with a correct `RESOLVES_TO`, commits. The loader's readiness check (`lib.guard_ready`) needs exactly one shapes node, shapes equal to the pinned set from N4 with values, and exactly one trigger named `shacl` whose query is the expected `validateTransaction` call, in the `before` phase, with `installed` true and `paused` false given explicitly. It says yes with the guard in place and no while the trigger is paused or the shapes node is missing. Deleting the shapes node succeeds and leaves none, and then M01 commits with no error, which is finding 2. After shapes and graph are restored, the readiness check says yes again and M01 is refused again |
| N8 | Scale | The 5,040 node padded graph from the Relate spike gives its copies tags like `E-201A-P007`, which break the S1, S3 and S4 patterns. On that graph n10s and pySHACL must report the same, non-empty set of violations. With the `-P007` suffix taken off `tag` and `request_id` (node keys keep it), `validate()` returns no rows, and the guarded database accepts the whole graph in one transaction. RECORD the times, whether a batched load gets through the trigger, and Neo4j's resident memory |

N6 is the check that keeps the rest honest. A shape that never fires would pass N5 for the wrong reason, and the hand-written expectations could be wrong in the same way as the shapes. pySHACL comes from a different code base, so if it agrees with n10s and with the expectations on every mutant, all three would have to be wrong in the same way for a bad rule to slip through.

If n10s can't do something the twin needs, the doc records it and names the fallback. The general fallback is to run the same shapes with pySHACL in the loader, on the rows about to be written, and to put rules SHACL can't express in Cypher checks that run in the same transaction.

## 6. Results

One clean run on 2026-11-27 took 75 seconds from download check to cleanup. `results.json` holds the full record. Neo4j Community 5.26.34 with n10s 5.26.0 and APOC 5.26.34 core ran on OpenJDK 21.0.13.1 with no Docker on the machine.

| ID | Result | What happened |
|---|---|---|
| N1 | PASS | Both downloads matched their pinned SHA-256 values, and Neo4j's matched the value dist.neo4j.org publishes. No `docker` command in the script and none on the path |
| N2 | PASS | Bolt answered after 9.8 seconds, with all three procedures listed |
| N3 | PASS | 48 nodes and 72 relationships, the counts in the Relate spike's `expected.json`, plus 3 `Exchanger`, 1 `FiredHeater`, 2 `Reactor` and one of each work type label |
| N4 | PASS | `listShapes()` returned 44 rows, the same (target, path, constraint) set that rdflib reads out of `shapes.ttl`, and all 22 counts, bounds and patterns had the same values |
| N5 | PASS | No violations from n10s or from pySHACL on the clean graph |
| N6 | PASS | pySHACL matched the hand-written expectations on all 18 mutants. n10s matched them exactly on 14, and on all 18 once min and max results are folded into n10s's merged name for the shapes that have both bounds (finding 1). The fold touches only those shapes. Every mutant changed at least one thing in the graph |
| N7 | PASS | All 18 mutants were refused by the SHACL trigger, and the graph read back identical after each one. The valid write committed. The readiness check gave yes, no (trigger paused), no (shapes missing) and yes (restored), as expected. With the shapes gone, M01 committed. After the restore, M01 was refused again. The trigger was active 0.5 s after install |
| N8 | PASS | Raw padded graph: n10s and pySHACL both reported the same 1,872 pattern violations. Fixed copy: no violations, and after the guarded load the stored graph had all 5,040 nodes and 7,560 relationships and still no violations. `validate()` took 1.7 s, loading took 0.8 s without the trigger and 2.8 s with it in one transaction. Neo4j's resident memory read 1.45 GB at the end of the run, one reading rather than a peak, against the 1.5 GB that [hosting.md](../hosting.md) section 2 allows. The fixed copy repeats each tag 105 times, so the timings are a rough size check, not a benchmark |

### What n10s got right

The questions the spike was written for came out well. n10s reads shapes against a property graph that never came from RDF, as long as the shapes use the `neo4j://graph.schema#` namespace. It catches removed properties (M02, M12) and deleted relationships (M05, M17), not only bad values. Under the trigger it refused every bad write in the test and left nothing behind, as long as the shapes node was there and the trigger was running (finding 2). On every mutant and on the 1,872 violations at scale it agreed with pySHACL, which shares no code with it.

### Findings

1. **Merged result names.** When a property shape has both `sh:minCount` and `sh:maxCount`, n10s reports a violation of either as `sh:CountConstraintComponent`. With both a lower and upper bound on a number it reports `sh:ValueRangeConstraintComponent`. Neither name is in SHACL Core. The detection is right, and only the label differs. That is why M02, M05, M09 and M12 didn't match exactly ([SHACLValidator.java](https://github.com/neo4j-labs/neosemantics/blob/5.26.0/src/main/java/n10s/validation/SHACLValidator.java), around lines 568 and 740). The review queue should show the twin's own message for each shape, not the n10s constraint name.
2. **The guard fails open.** With the shapes node `_n10sValidatorConfig` deleted and the trigger still installed, M01 (a tag with its dash removed) committed with no error. n10s keeps the shapes as a node in the same database, so `MATCH (n) DETACH DELETE n` takes them out too and quietly switches the guard off. A paused or removed trigger does the same. So the guard holds only while three things are true: the shapes are loaded, the trigger is running, and nobody is changing either. The loader handles it this way:
   - Before each sync it runs the readiness check from N7 and refuses to write if it fails.
   - Syncs, resets and shape changes take one lock, so only one runs at a time. A readiness check means nothing if a reset can start between the check and the write.
   - A reset or restore that stops the trigger runs with that lock held and the twin API in maintenance mode, then runs `validate()` on the result before the trigger comes back. A safer form loads into a second database and swaps it in only when `validate()` is clean. Neo4j Community has one user database, so that form needs a second Neo4j or Enterprise.
   - Any reset script keeps the shapes node, as the spike's does.
3. **Every write must leave the graph valid.** The trigger checks each transaction on its own. A batched load that creates nodes in one transaction and their relationships in the next fails at the first batch, because equipment without `ON_SHEET` breaks S2. The loader writes each sync as one transaction. At 5,040 nodes that took 2.8 seconds. If later syncs grow much bigger, the fallback is the staged load from finding 2.
4. **Accepted matches need their own relationship.** design.md section 4.2 puts proposed, accepted and rejected matches all on `RESOLVES_TO`, with a `status` property. n10s paths are a relationship type only, with no filter on a property, so "at most one accepted match" can't be a shape over that design. Either proposals stay on `MatchProposal` nodes and `RESOLVES_TO` holds only accepted matches, which is what S4 assumes, or the rule becomes a Cypher check. I'd go with the first. It also makes the twin's own queries simpler.
5. **Smaller points.** n10s returns `focusNode` as the old numeric node id, which Neo4j 5 deprecates, so the spike maps both `id(n)` and `elementId(n)` back to node keys. Tags repeat across the padded copies, and no shape notices, because SHACL in n10s has no uniqueness check. Tag uniqueness belongs in a Neo4j uniqueness constraint. A Neo4j config file with a key set twice stops the server from starting, so the run script comments out the shipped line before it sets its own.

### What SHACL can and can't hold

Each rule in [verification.md](../verification.md) section 2, sorted by where it can live, given what n10s supports (section 1).

| Rule | Where it lives |
|---|---|
| Tag matches the Unit 200 pattern | n10s shape (S1, S3) |
| Tag exists in the CMMS master | Cypher check in the sync transaction. The master is a separate list, and a shape can't look it up |
| Relief path from each vessel, column, reactor and exchanger shell to a PSV | Python or Cypher path query. Paths longer than one hop aren't supported |
| Every PSV protects at least one item | n10s shape, if protection is a direct relationship |
| Exchanger nozzles on both sides, in and out | Cypher count. All nozzles hang off one `HAS_NOZZLE` type, and an n10s path can't filter by the nozzle's label, so a shape can't ask for one of each kind. It could be four shapes if the exporter wrote four relationship types, such as `HAS_SHELL_INLET` |
| Pump and compressor block valves | Cypher path query |
| Isolation envelope is closed | Python graph walk. It is a property of every path leaving the envelope |
| Plot position inside the area, no footprint overlap | Python geometry check |
| Scope item has driver, source group, RIPT score, craft split | n10s shape (S4 covers RIPT and exercise ID, and the rest follow the same form) |
| Craft hours add up, cost fits hours and rates | Python check. SHACL in n10s has no arithmetic |
| Work type fits equipment class | n10s shape, using a work type label on the scope item and a class label on the equipment (S5 to S7) |
| Every frozen item has one of four outcomes | Cypher check. S4's "at most one `RESOLVES_TO`" works as a shape only if `RESOLVES_TO` holds accepted matches alone (finding 4) |
| Every accepted AI match has a named reviewer | Cypher check, or an n10s shape if accepted AI matches get their own label |

About half the rules fit n10s, and the rest need a Cypher or Python check. All of them can still run before the sync commits. The Cypher checks run in the same transaction and throw to roll it back. The Python checks run on the rows before they are written.

### What this changes

- D10 keeps SHACL through n10s, with the readiness check, the lock and the staged restore from finding 2, and one transaction per sync (finding 3).
- The rules that can't be shapes run as Cypher or Python checks in the loader, per the table above.
- Phase 1 should settle finding 4 before the matcher writes anything.
- Local Neo4j from the tarball works without Docker. That covers the last piece of design section 3.3's no-Docker path.
