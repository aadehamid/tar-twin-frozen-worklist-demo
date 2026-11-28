// Dedicated module worker hosting the in-browser Relate WASM graph store.
// Seeds once from the Twin API's fixed export endpoint, warms up named queries,
// and refuses any arbitrary Cypher text (docs/design.md section 5.7).

import init, { RelateDb } from "@relate/relate-wasm";
import { NAMED_QUERIES, runNamedQuery } from "./relateQueries";

let db: RelateDb | null = null;
let seeded = false;
let seedingInFlight = false;

const EXERCISE_ID_RE = /^[A-Za-z0-9_-]{1,40}$/;

function buildExportUrl(prefix: string, exerciseId: string): string {
  if (prefix !== "" && prefix !== "/twin") {
    throw new Error("Refused disallowed API prefix");
  }
  if (!EXERCISE_ID_RE.test(exerciseId)) {
    throw new Error("Invalid exercise_id");
  }
  return new URL(
    `${prefix}/api/v1/graph/export.cypher?exercise_id=${encodeURIComponent(exerciseId)}`,
    self.location.origin
  ).href;
}

async function doSeed(prefix: string, exerciseId: string) {
  if (seeded) {
    throw new Error("Relate worker is already seeded; respawn worker to reload");
  }
  if (seedingInFlight) {
    throw new Error("Relate worker seed is already in progress");
  }
  seedingInFlight = true;
  try {
    const t0 = performance.now();
    await init();
    const t1 = performance.now();

    const url = buildExportUrl(prefix, exerciseId);
    const resp = await fetch(url);
    if (!resp.ok) {
      throw new Error(`Export fetch failed (${resp.status})`);
    }
    const script = await resp.text();
    const t2 = performance.now();

    const candidateDb = new RelateDb();
    const out = candidateDb.executeScript(script, null);
    const errors = out
      .map((line: string) => {
        const parsed = JSON.parse(line) as { error?: string | null };
        return parsed.error;
      })
      .filter((e: string | null | undefined): e is string => e != null);
    if (errors.length > 0) {
      throw new Error(`Graph export had ${errors.length} Cypher error(s): ${errors[0]}`);
    }
    const t3 = performance.now();

    const countEnv = JSON.parse(candidateDb.execute("MATCH (n) RETURN count(n) AS c", null)) as {
      rows: { c: number }[];
    };
    const nodeCount = countEnv.rows?.[0]?.c ?? 0;

    // Warm up named queries (docs/design.md section 5.7)
    try {
      runNamedQuery(candidateDb, "equipment_neighborhood", { tag: "E-201B" });
      runNamedQuery(candidateDb, "envelope_subgraph", { envelope_id: "ENV-200-02" });
      runNamedQuery(candidateDb, "work_request_chain", { request_id: "WR-200-0001" });
    } catch {
      // Warmup ignores missing sample keys on empty exercises
    }
    const t4 = performance.now();

    db = candidateDb;
    seeded = true;

    return {
      nodes: nodeCount,
      script_bytes: script.length,
      errors: [],
      init_ms: Math.round(t1 - t0),
      fetch_ms: Math.round(t2 - t1),
      seed_ms: Math.round(t3 - t2),
      warmup_ms: Math.round(t4 - t3),
    };
  } catch (err) {
    db = null;
    seeded = false;
    throw err;
  } finally {
    seedingInFlight = false;
  }
}

function doQuery(name: string, params: Record<string, unknown>) {
  if (db === null) {
    throw new Error("Relate store not seeded");
  }
  const t0 = performance.now();
  const resultSets = runNamedQuery(db, name, params);
  const def = NAMED_QUERIES[name as keyof typeof NAMED_QUERIES];
  return {
    name,
    displayCypher: def.displayCypher,
    resultSets,
    ms: Math.round((performance.now() - t0) * 10) / 10,
  };
}

self.onmessage = async (event: MessageEvent) => {
  const { id, type } = event.data as { id: number; type: string; [k: string]: unknown };
  try {
    let result: unknown;
    if (type === "seed") {
      result = await doSeed(String(event.data.prefix ?? ""), String(event.data.exerciseId ?? "EX-DEMO"));
    } else if (type === "query") {
      result = doQuery(String(event.data.name ?? ""), (event.data.params as Record<string, unknown>) ?? {});
    } else if (type === "texts") {
      result = Object.fromEntries(Object.entries(NAMED_QUERIES).map(([k, v]) => [k, v.displayCypher]));
    } else {
      throw new Error(`Refused disallowed worker command: ${String(type).slice(0, 32)}`);
    }
    self.postMessage({ id, ok: true, result });
  } catch (err) {
    self.postMessage({
      id,
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
};
