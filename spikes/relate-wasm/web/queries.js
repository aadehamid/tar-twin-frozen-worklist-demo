// The graph panel's named queries, shared by the browser worker and the Node checks.
// The worker runs only these. Any other text is refused.

const NOT_STOP = "NOT n:OffPageConnector AND NOT (n:Valve AND n.role = 'block')";

export const QUERIES = {
  chain: {
    params: ["request_id"],
    statements: [`MATCH (s:ScopeItem {request_id: $request_id})-[:RESOLVES_TO]->(e:Equipment)
OPTIONAL MATCH (e)-[:HAS_NOZZLE]->(nz:Nozzle)
WITH s, e, collect(nz.sub_tag) AS nozzles
MATCH (env:IsolationEnvelope)-[:CONTAINS]->(e)
OPTIONAL MATCH (env)-[:BOUNDED_BY]->(v:Valve)
WITH s, e, nozzles, env, collect(DISTINCT v.tag) AS boundary
OPTIONAL MATCH (env)-[:CONTAINS]->(:Equipment)<-[:RESOLVES_TO]-(o:ScopeItem)
WHERE o <> s
RETURN s.request_id AS request, e.tag AS equipment, nozzles, env.id AS envelope,
       boundary, collect(DISTINCT o.request_id) AS others`],
  },
  walk: {
    params: ["tag"],
    statements: [
      `MATCH (e:Equipment {tag: $tag})
MATCH (e)(()-[:CONNECTED_TO|HAS_NOZZLE]-(n) WHERE ${NOT_STOP})*()-[:CONNECTED_TO]-(v:Valve {role: 'block'})
RETURN DISTINCT v.tag AS tag`,
      `MATCH (e:Equipment {tag: $tag})
MATCH (e)(()-[:CONNECTED_TO|HAS_NOZZLE]-(n) WHERE ${NOT_STOP})*(x:Equipment)
RETURN DISTINCT x.tag AS tag`,
    ],
  },
};

// The only scripts the worker may seed from, relative to the worker. Phase 1 replaces these with
// the twin's own export endpoint. The page passes a name, never a URL.
export const SEED_SOURCES = { plant: "../plant.cypher", padded: "../padded.cypher" };

export function seedUrl(name, base) {
  if (!Object.hasOwn(SEED_SOURCES, name)) {
    throw new Error(`unknown seed source: ${String(name).slice(0, 40)}`);
  }
  return new URL(SEED_SOURCES[name], base).href;
}

// Run a script in the store. Returns the error of each failing statement, so [] means all ran.
export function seed(db, script) {
  const out = db.executeScript(script, null);
  return out.map((s) => JSON.parse(s).error).filter((e) => e != null);
}

// Run a named query. Returns one row list per statement. Throws on unknown names, unexpected
// parameters, or an engine error.
export function runNamed(db, name, params) {
  if (!Object.hasOwn(QUERIES, name)) throw new Error(`unknown query: ${String(name).slice(0, 40)}`);
  const q = QUERIES[name];
  const keys = Object.keys(params || {}).sort();
  if (JSON.stringify(keys) !== JSON.stringify([...q.params].sort())) {
    throw new Error(`query ${name} takes ${q.params.join(", ")}`);
  }
  for (const k of keys) if (typeof params[k] !== "string") throw new Error(`${k} must be a string`);
  return q.statements.map((text) => {
    const env = JSON.parse(db.execute(text, JSON.stringify(params)));
    if (env.error != null) throw new Error(`${name}: ${env.error}`);
    return env.rows;
  });
}

const sorted = (xs) => [...xs].sort();

export function chainResult([rows]) {
  if (rows.length !== 1) throw new Error(`chain returned ${rows.length} rows`);
  const r = rows[0];
  return { request: r.request, equipment: r.equipment, nozzles: sorted(r.nozzles),
    envelope: r.envelope, boundary: sorted(r.boundary), others: sorted(r.others) };
}

export function walkResult([valves, equipment]) {
  return { boundary: sorted(valves.map((r) => r.tag)), equipment: sorted(equipment.map((r) => r.tag)) };
}
