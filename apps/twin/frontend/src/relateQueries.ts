// Named read-only Cypher queries for the in-browser Relate WASM worker.
// The worker executes ONLY these queries with validated string parameters; arbitrary Cypher is refused.

export type NamedQueryId = "work_request_chain" | "equipment_neighborhood" | "envelope_subgraph";

export interface NamedQueryDef {
  id: NamedQueryId;
  label: string;
  params: readonly string[];
  displayCypher: string;
  statements: readonly string[];
}

export const NAMED_QUERIES: Record<NamedQueryId, NamedQueryDef> = {
  work_request_chain: {
    id: "work_request_chain",
    label: "Work request to isolation envelope",
    params: ["request_id"],
    displayCypher: `MATCH (s:ScopeItem {request_id: $request_id})-[:RESOLVES_TO]->(e:Equipment)
OPTIONAL MATCH (e)-[:HAS_NOZZLE]->(nz:Nozzle)
OPTIONAL MATCH (env:IsolationEnvelope)-[:CONTAINS]->(e)
OPTIONAL MATCH (env)-[:BOUNDED_BY]->(v:Valve)
OPTIONAL MATCH (env)-[:CONTAINS]->(peer:Equipment)<-[:RESOLVES_TO]-(o:ScopeItem)
RETURN s, e, nz, env, v, peer, o`,
    statements: [
      "MATCH (s:ScopeItem {request_id: $request_id})-[:RESOLVES_TO]->(e:Equipment) RETURN s.request_id AS request_id, s.title AS title, s.area AS area, e.tag AS tag, e.description AS description, e.sheet AS sheet",
      "MATCH (s:ScopeItem {request_id: $request_id})-[:RESOLVES_TO]->(e:Equipment)-[:HAS_NOZZLE]->(nz:Nozzle) RETURN DISTINCT nz.sub_tag AS sub_tag",
      "MATCH (s:ScopeItem {request_id: $request_id})-[:RESOLVES_TO]->(e:Equipment)<-[:CONTAINS]-(env:IsolationEnvelope) RETURN DISTINCT env.id AS env_id, env.name AS env_name",
      "MATCH (s:ScopeItem {request_id: $request_id})-[:RESOLVES_TO]->(e:Equipment)<-[:CONTAINS]-(env:IsolationEnvelope)-[:BOUNDED_BY]->(v:Valve) RETURN DISTINCT env.id AS env_id, v.tag AS valve_tag",
      "MATCH (s:ScopeItem {request_id: $request_id})-[:RESOLVES_TO]->(e:Equipment)<-[:CONTAINS]-(env:IsolationEnvelope)-[:CONTAINS]->(peer:Equipment)<-[:RESOLVES_TO]-(o:ScopeItem) WHERE o.request_id <> s.request_id RETURN DISTINCT peer.tag AS peer_tag, o.request_id AS peer_request, o.title AS peer_title",
    ],
  },
  equipment_neighborhood: {
    id: "equipment_neighborhood",
    label: "Equipment isolation and scope neighborhood",
    params: ["tag"],
    displayCypher: `MATCH (e:Equipment {tag: $tag})
OPTIONAL MATCH (e)-[:HAS_NOZZLE]->(nz:Nozzle)
OPTIONAL MATCH (env:IsolationEnvelope)-[:CONTAINS]->(e)
OPTIONAL MATCH (env)-[:BOUNDED_BY]->(v:Valve)
OPTIONAL MATCH (s:ScopeItem)-[:RESOLVES_TO]->(e)
RETURN e, nz, env, v, s`,
    statements: [
      "MATCH (e:Equipment {tag: $tag}) RETURN e.tag AS tag, e.description AS description, e.area AS area, e.sheet AS sheet, e.equipment_class AS equipment_class",
      "MATCH (e:Equipment {tag: $tag})-[:HAS_NOZZLE]->(nz:Nozzle) RETURN DISTINCT nz.sub_tag AS sub_tag",
      "MATCH (env:IsolationEnvelope)-[:CONTAINS]->(e:Equipment {tag: $tag}) RETURN DISTINCT env.id AS env_id, env.name AS env_name",
      "MATCH (env:IsolationEnvelope)-[:CONTAINS]->(e:Equipment {tag: $tag}), (env)-[:BOUNDED_BY]->(v:Valve) RETURN DISTINCT env.id AS env_id, v.tag AS valve_tag",
      "MATCH (s:ScopeItem)-[:RESOLVES_TO]->(e:Equipment {tag: $tag}) RETURN s.request_id AS request_id, s.title AS title, s.ript AS ript, s.estimate_hours AS hours",
      "MATCH (e:Equipment {tag: $tag})<-[:CONTAINS]-(env:IsolationEnvelope)-[:CONTAINS]->(peer:Equipment) WHERE peer.tag <> $tag RETURN DISTINCT env.id AS env_id, peer.tag AS peer_tag, peer.description AS peer_desc",
    ],
  },
  envelope_subgraph: {
    id: "envelope_subgraph",
    label: "Isolation envelope closure",
    params: ["envelope_id"],
    displayCypher: `MATCH (env:IsolationEnvelope {id: $envelope_id})-[:CONTAINS]->(e:Equipment)
OPTIONAL MATCH (env)-[:BOUNDED_BY]->(v:Valve)
OPTIONAL MATCH (s:ScopeItem)-[:RESOLVES_TO]->(e)
RETURN env, e, v, s`,
    statements: [
      "MATCH (env:IsolationEnvelope {id: $envelope_id})-[:CONTAINS]->(e:Equipment) RETURN env.id AS env_id, env.name AS env_name, e.tag AS tag, e.description AS description, e.area AS area, e.sheet AS sheet",
      "MATCH (env:IsolationEnvelope {id: $envelope_id})-[:BOUNDED_BY]->(v:Valve) RETURN DISTINCT v.tag AS valve_tag",
      "MATCH (env:IsolationEnvelope {id: $envelope_id})-[:CONTAINS]->(e:Equipment)<-[:RESOLVES_TO]-(s:ScopeItem) RETURN e.tag AS tag, s.request_id AS request_id, s.title AS title, s.estimate_hours AS hours",
    ],
  },
};

export function runNamedQuery(
  db: { execute: (cypher: string, params: string | null) => string },
  name: string,
  params: Record<string, unknown>
): Record<string, unknown>[][] {
  if (!Object.prototype.hasOwnProperty.call(NAMED_QUERIES, name)) {
    throw new Error(`Refused unknown query: ${String(name).slice(0, 40)}`);
  }
  const q = NAMED_QUERIES[name as NamedQueryId];
  const keys = Object.keys(params || {}).sort();
  const expected = [...q.params].sort();
  if (JSON.stringify(keys) !== JSON.stringify(expected)) {
    throw new Error(`Query ${name} requires exact params: ${q.params.join(", ")}`);
  }
  for (const k of keys) {
    if (typeof params[k] !== "string") {
      throw new Error(`Parameter ${k} must be a string`);
    }
  }
  const paramJson = JSON.stringify(params);
  return q.statements.map((stmt) => {
    const parsed = JSON.parse(db.execute(stmt, paramJson)) as { error?: string | null; rows?: Record<string, unknown>[] };
    if (parsed.error != null) {
      throw new Error(`${name}: ${parsed.error}`);
    }
    return parsed.rows ?? [];
  });
}
