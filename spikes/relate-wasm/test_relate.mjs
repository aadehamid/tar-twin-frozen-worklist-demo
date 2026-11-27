// W1, W4, W5, W6, W9 and the Node half of W8. Run: node --test test_relate.mjs
// Needs plant.cypher and padded.cypher from `python export_cypher.py`.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, statSync } from "node:fs";
import { initSync, RelateDb } from "@relate/relate-wasm";
import { QUERIES, runNamed, seed, chainResult, walkResult } from "./web/queries.js";

const here = new URL(".", import.meta.url);
const KEY = JSON.parse(readFileSync(new URL("expected.json", here)));
const wasmPath = new URL("node_modules/@relate/relate-wasm/relate_bg.wasm", here);
initSync({ module: readFileSync(wasmPath) });

const plant = readFileSync(new URL("plant.cypher", here), "utf8");

function seeded(script = plant) {
  const db = new RelateDb();
  const errors = seed(db, script);
  assert.deepEqual(errors, []);
  return db;
}

function rows(db, q, params = null) {
  const env = JSON.parse(db.execute(q, params && JSON.stringify(params)));
  assert.equal(env.error, null, `${q}: ${env.error}`);
  return env.rows;
}

test("W1 package and engine version", () => {
  const lock = JSON.parse(readFileSync(new URL("package-lock.json", here)));
  assert.equal(lock.packages["node_modules/@relate/relate-wasm"].version, KEY.relate_version);
  const db = new RelateDb();
  const r = rows(db, "CALL dbms.components() YIELD name, versions WHERE name = 'Relate' RETURN versions[0] AS v");
  assert.equal(r[0].v, KEY.relate_version);
  assert.ok(statSync(wasmPath).size > 0);
});

test("W4 seeding gives the expected counts", () => {
  const db = seeded();
  for (const [label, n] of Object.entries(KEY.nodes)) {
    assert.equal(rows(db, `MATCH (n:${label}) RETURN count(n) AS c`)[0].c, n, label);
  }
  for (const [type, n] of Object.entries(KEY.relationships)) {
    assert.equal(rows(db, `MATCH ()-[r:${type}]->() RETURN count(r) AS c`)[0].c, n, type);
  }
  assert.equal(rows(db, "MATCH (n) RETURN count(n) AS c")[0].c,
    Object.values(KEY.nodes).reduce((a, b) => a + b, 0));
});

test("W5 live envelope walk", () => {
  const db = seeded();
  const walk = walkResult(runNamed(db, "walk", { tag: "E-201B" }));
  assert.deepEqual(walk, KEY["walk_from_E-201B"]);
  const stored = rows(db, `MATCH (env:IsolationEnvelope {id: 'ENV-200-02'})
    OPTIONAL MATCH (env)-[:BOUNDED_BY]->(v:Valve)
    WITH env, collect(v.tag) AS b
    OPTIONAL MATCH (env)-[:CONTAINS]->(e:Equipment)
    RETURN b, collect(e.tag) AS e`)[0];
  assert.deepEqual([...stored.b].sort(), walk.boundary);
  assert.deepEqual([...stored.e].sort(), walk.equipment);
});

test("W5 negative control: HV-2001 as a control valve", () => {
  // Change role inside the one row map whose tag is HV-2001, and nothing else.
  let hits = 0;
  const mutated = plant.replace(/\{[^{}]*tag: 'HV-2001'[^{}]*\}/g, (m) => {
    hits += 1;
    return m.replace("role: 'block'", "role: 'control'");
  });
  assert.equal(hits, 1, "exactly one row carries HV-2001");
  assert.notEqual(mutated, plant, "the mutation must change the script");
  const db = seeded(mutated);
  const walk = walkResult(runNamed(db, "walk", { tag: "E-201B" }));
  assert.deepEqual(walk.boundary, KEY["walk_from_E-201B_with_HV-2001_as_control"].boundary);
});

test("W6 panel chain for WR-200-0147", () => {
  const db = seeded();
  const chain = chainResult(runNamed(db, "chain", { request_id: "WR-200-0147" }));
  assert.deepEqual(chain, KEY["chain_WR-200-0147"]);
  assert.ok(!chain.others.includes("WR-200-0188"));
});

test("W8 Node timings on the padded graph, and padding doesn't leak", () => {
  const padded = readFileSync(new URL("padded.cypher", here), "utf8");
  const t0 = performance.now();
  const db = seeded(padded);
  const seedMs = performance.now() - t0;
  assert.equal(rows(db, "MATCH (n) RETURN count(n) AS c")[0].c, KEY.padded_nodes);
  const times = [];
  let chain, walk;
  for (let i = 0; i < 20; i++) {
    const t = performance.now();
    chain = chainResult(runNamed(db, "chain", { request_id: "WR-200-0147" }));
    walk = walkResult(runNamed(db, "walk", { tag: "E-201B" }));
    times.push(performance.now() - t);
  }
  assert.deepEqual(chain, KEY["chain_WR-200-0147"]);
  assert.deepEqual(walk, KEY["walk_from_E-201B"]);
  times.sort((a, b) => a - b);
  console.log(JSON.stringify({ W8_node: { seed_ms: +seedMs.toFixed(1),
    median_ms: +times[10].toFixed(2), max_ms: +times[19].toFixed(2),
    script_bytes: Buffer.byteLength(padded) } }));
});

test("W9 read-only store and named queries only", () => {
  const ro = new RelateDb(true);
  const w = JSON.parse(ro.execute("CREATE (:A)", null));
  assert.match(w.error, /WriteOnReadOnlyAccessDatabase/);
  assert.equal(rows(ro, "MATCH (n) RETURN count(n) AS c")[0].c, 0);
  const db = seeded();
  assert.throws(() => runNamed(db, "MATCH (n) DETACH DELETE n", {}), /unknown query/);
  assert.deepEqual(Object.keys(QUERIES).sort(), ["chain", "walk"]);
});
