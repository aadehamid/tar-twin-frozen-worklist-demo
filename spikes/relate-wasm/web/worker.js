// Module worker: holds the Relate store and answers only the panel's named queries.
import init, { RelateDb } from "../node_modules/@relate/relate-wasm/relate.js";
import { QUERIES, seed, seedUrl, runNamed } from "./queries.js";

let db = null;
let seeding = false;

// Seeds once, from a named source only. Any later seed request is refused.
async function doSeed(source) {
  if (seeding) throw new Error("already seeded");
  const url = seedUrl(source, import.meta.url);
  seeding = true;
  const t0 = performance.now();
  await init();
  const t1 = performance.now();
  const script = await (await fetch(url)).text();
  const t2 = performance.now();
  db = new RelateDb();
  const errors = seed(db, script);
  const t3 = performance.now();
  const count = JSON.parse(db.execute("MATCH (n) RETURN count(n) AS c", null)).rows[0].c;
  return { errors, nodes: count, script_bytes: script.length,
    init_ms: t1 - t0, fetch_ms: t2 - t1, seed_ms: t3 - t2 };
}

function doQuery(name, params) {
  if (db === null) throw new Error("not seeded");
  const t = performance.now();
  const rows = runNamed(db, name, params);
  return { rows, ms: performance.now() - t };
}

self.onmessage = async ({ data }) => {
  const { id, type } = data;
  try {
    let result;
    if (type === "seed") result = await doSeed(data.source);
    else if (type === "query") result = doQuery(data.name, data.params);
    else if (type === "texts") result = Object.fromEntries(
      Object.entries(QUERIES).map(([k, q]) => [k, q.statements]));
    else throw new Error(`unknown message: ${String(type).slice(0, 40)}`);
    self.postMessage({ id, ok: true, result });
  } catch (e) {
    self.postMessage({ id, ok: false, error: String(e && e.message || e) });
  }
};
