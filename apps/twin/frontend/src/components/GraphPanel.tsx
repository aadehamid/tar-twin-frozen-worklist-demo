import React, { useEffect, useMemo, useRef, useState } from "react";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import { apiPrefix } from "../api";
import type { NamedQueryId } from "../relateQueries";
import type { EquipmentDetail, IsolationEnvelope, ScopeItem } from "../types";

interface GraphPanelProps {
  exerciseId: string;
  equipment: EquipmentDetail[];
  envelopes: IsolationEnvelope[];
  scopeItems: ScopeItem[];
  initialMode?: NamedQueryId;
  selectedTag: string;
  selectedEnvelopeId: string;
  selectedRequestId: string;
  onSelectTag: (tag: string) => void;
  onSelectEnvelope: (envId: string) => void;
  onSelectRequest: (reqId: string) => void;
  onNavigateToTrace: (reqId: string) => void;
  onNavigateToPlot: (tag: string) => void;
}

interface WorkerStats {
  nodes: number;
  script_bytes: number;
  init_ms: number;
  fetch_ms: number;
  seed_ms: number;
  warmup_ms: number;
  errors: string[];
}

interface QueryRunOutput {
  name: NamedQueryId;
  displayCypher: string;
  resultSets: Record<string, unknown>[][];
  ms: number;
}

function buildGraphElements(output: QueryRunOutput): ElementDefinition[] {
  const nodes = new Map<string, ElementDefinition>();
  const edges = new Map<string, ElementDefinition>();

  const addNode = (id: string, label: string, kind: string) => {
    if (!nodes.has(id)) {
      nodes.set(id, { data: { id, label, kind } });
    }
  };
  const addEdge = (source: string, target: string, label: string) => {
    const eid = `${source}__${label}__${target}`;
    if (!edges.has(eid)) {
      edges.set(eid, { data: { id: eid, source, target, label } });
    }
  };

  if (output.name === "equipment_neighborhood") {
    const [eqRows = [], nzRows = [], envRows = [], valveRows = [], scopeRows = [], peerRows = []] = output.resultSets;
    const eq = eqRows[0];
    if (eq && eq.tag) {
      const eqId = `eq:${String(eq.tag)}`;
      addNode(eqId, String(eq.tag), "equipment");

      for (const nz of nzRows.slice(0, 8)) {
        const nid = `nz:${String(eq.tag)}:${String(nz.sub_tag)}`;
        addNode(nid, String(nz.sub_tag), "nozzle");
        addEdge(eqId, nid, "HAS_NOZZLE");
      }
      for (const env of envRows) {
        const envId = `env:${String(env.env_id)}`;
        addNode(envId, String(env.env_id), "envelope");
        addEdge(envId, eqId, "CONTAINS");
      }
      for (const v of valveRows.slice(0, 14)) {
        const envId = `env:${String(v.env_id)}`;
        const vid = `v:${String(v.valve_tag)}`;
        addNode(envId, String(v.env_id), "envelope");
        addNode(vid, String(v.valve_tag), "valve");
        addEdge(envId, vid, "BOUNDED_BY");
      }
      for (const s of scopeRows.slice(0, 12)) {
        const sid = `wr:${String(s.request_id)}`;
        addNode(sid, String(s.request_id), "scope");
        addEdge(sid, eqId, "RESOLVES_TO");
      }
      for (const p of peerRows.slice(0, 10)) {
        const envId = `env:${String(p.env_id)}`;
        const pid = `eq:${String(p.peer_tag)}`;
        addNode(envId, String(p.env_id), "envelope");
        addNode(pid, String(p.peer_tag), "peer_equipment");
        addEdge(envId, pid, "CONTAINS");
      }
    }
  } else if (output.name === "work_request_chain") {
    const [baseRows = [], nzRows = [], envRows = [], valveRows = [], peerRows = []] = output.resultSets;
    const b = baseRows[0];
    if (b && b.request_id && b.tag) {
      const sid = `wr:${String(b.request_id)}`;
      const eqId = `eq:${String(b.tag)}`;
      addNode(sid, String(b.request_id), "scope");
      addNode(eqId, String(b.tag), "equipment");
      addEdge(sid, eqId, "RESOLVES_TO");

      for (const nz of nzRows.slice(0, 8)) {
        const nid = `nz:${String(b.tag)}:${String(nz.sub_tag)}`;
        addNode(nid, String(nz.sub_tag), "nozzle");
        addEdge(eqId, nid, "HAS_NOZZLE");
      }
      for (const env of envRows) {
        const envId = `env:${String(env.env_id)}`;
        addNode(envId, String(env.env_id), "envelope");
        addEdge(envId, eqId, "CONTAINS");
      }
      for (const v of valveRows.slice(0, 12)) {
        const envId = `env:${String(v.env_id)}`;
        const vid = `v:${String(v.valve_tag)}`;
        addNode(envId, String(v.env_id), "envelope");
        addNode(vid, String(v.valve_tag), "valve");
        addEdge(envId, vid, "BOUNDED_BY");
      }
      for (const p of peerRows.slice(0, 10)) {
        const pid = `eq:${String(p.peer_tag)}`;
        const psid = `wr:${String(p.peer_request)}`;
        addNode(pid, String(p.peer_tag), "peer_equipment");
        addNode(psid, String(p.peer_request), "peer_scope");
        addEdge(psid, pid, "RESOLVES_TO");
        if (envRows[0]) {
          addEdge(`env:${String(envRows[0].env_id)}`, pid, "CONTAINS");
        }
      }
    }
  } else if (output.name === "envelope_subgraph") {
    const [eqRows = [], valveRows = [], scopeRows = []] = output.resultSets;
    const envName = eqRows[0]?.env_id ? String(eqRows[0].env_id) : "";
    if (envName) {
      const envId = `env:${envName}`;
      addNode(envId, envName, "envelope");
      for (const e of eqRows) {
        const eqId = `eq:${String(e.tag)}`;
        addNode(eqId, String(e.tag), "equipment");
        addEdge(envId, eqId, "CONTAINS");
      }
      for (const v of valveRows.slice(0, 16)) {
        const vid = `v:${String(v.valve_tag)}`;
        addNode(vid, String(v.valve_tag), "valve");
        addEdge(envId, vid, "BOUNDED_BY");
      }
      for (const s of scopeRows.slice(0, 18)) {
        const sid = `wr:${String(s.request_id)}`;
        const eqId = `eq:${String(s.tag)}`;
        addNode(sid, String(s.request_id), "scope");
        addEdge(sid, eqId, "RESOLVES_TO");
      }
    }
  }

  return [...nodes.values(), ...edges.values()];
}

export const GraphPanel: React.FC<GraphPanelProps> = ({
  exerciseId,
  equipment,
  envelopes,
  scopeItems,
  initialMode = "equipment_neighborhood",
  selectedTag,
  selectedEnvelopeId,
  selectedRequestId,
  onSelectTag,
  onSelectEnvelope,
  onSelectRequest,
  onNavigateToTrace,
  onNavigateToPlot,
}) => {
  const [mode, setMode] = useState<NamedQueryId>(initialMode);
  const [stats, setStats] = useState<WorkerStats | null>(null);
  const [workerError, setWorkerError] = useState<string | null>(null);
  const [queryOutput, setQueryOutput] = useState<QueryRunOutput | null>(null);
  const [clickedNode, setClickedNode] = useState<{ id: string; label: string; kind: string } | null>(null);

  const workerRef = useRef<Worker | null>(null);
  const reqSeqRef = useRef<number>(1);
  const pendingRef = useRef<Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>>(new Map());
  const cyHostRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  useEffect(() => {
    setMode(initialMode);
  }, [initialMode]);

  const callWorker = (payload: Record<string, unknown>): Promise<unknown> => {
    return new Promise((resolve, reject) => {
      if (!workerRef.current) {
        reject(new Error("Relate worker not initialized"));
        return;
      }
      const id = reqSeqRef.current++;
      pendingRef.current.set(id, { resolve, reject });
      workerRef.current.postMessage({ id, ...payload });
    });
  };

  // Spawn dedicated Relate WASM module worker and seed once per exercise
  useEffect(() => {
    let cancelled = false;
    setStats(null);
    setWorkerError(null);
    setQueryOutput(null);

    const w = new Worker(new URL("../relateWorker.ts", import.meta.url), { type: "module" });
    workerRef.current = w;
    const pending = pendingRef.current;

    w.onmessage = (ev: MessageEvent) => {
      const { id, ok, result, error } = ev.data as { id: number; ok: boolean; result?: unknown; error?: string };
      const slot = pending.get(id);
      if (!slot) return;
      pending.delete(id);
      if (ok) slot.resolve(result);
      else slot.reject(new Error(error ?? "Worker error"));
    };

    w.onerror = (ev) => {
      if (!cancelled) {
        setWorkerError(ev.message || "Relate WASM worker failed");
      }
    };

    const seedId = reqSeqRef.current++;
    new Promise<WorkerStats>((resolve, reject) => {
      pending.set(seedId, { resolve: resolve as (v: unknown) => void, reject });
      w.postMessage({ id: seedId, type: "seed", prefix: apiPrefix(), exerciseId });
    })
      .then((res) => {
        if (!cancelled) setStats(res);
      })
      .catch((err) => {
        if (!cancelled) setWorkerError(err instanceof Error ? err.message : String(err));
      });

    return () => {
      cancelled = true;
      pending.clear();
      w.terminate();
      workerRef.current = null;
    };
  }, [exerciseId]);

  const matchedRequests = useMemo(
    () => scopeItems.filter((s) => s.match_status === "accepted" && s.resolved_tag),
    [scopeItems]
  );

  const effectiveRequestId = useMemo(() => {
    if (matchedRequests.some((r) => r.request_id === selectedRequestId)) return selectedRequestId;
    return matchedRequests[0]?.request_id ?? "WR-200-0001";
  }, [matchedRequests, selectedRequestId]);

  // Execute the active named query inside Relate WASM whenever mode or selection changes
  useEffect(() => {
    if (!stats) return;
    let cancelled = false;
    const params =
      mode === "equipment_neighborhood"
        ? { tag: selectedTag }
        : mode === "envelope_subgraph"
          ? { envelope_id: selectedEnvelopeId }
          : { request_id: effectiveRequestId };

    callWorker({ type: "query", name: mode, params })
      .then((res) => {
        if (!cancelled) {
          setQueryOutput(res as QueryRunOutput);
          setWorkerError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setWorkerError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [stats, mode, selectedTag, selectedEnvelopeId, effectiveRequestId]);

  // Render Cytoscape graph whenever queryOutput updates
  useEffect(() => {
    if (!cyHostRef.current || !queryOutput) return;
    const elements = buildGraphElements(queryOutput);

    if (cyRef.current) {
      cyRef.current.destroy();
      cyRef.current = null;
    }

    const cy = cytoscape({
      container: cyHostRef.current,
      elements,
      layout: {
        name: "cose",
        animate: false,
        padding: 28,
        nodeRepulsion: () => 8500,
        idealEdgeLength: () => 85,
      },
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            color: "#edf3fb",
            "font-family": "JetBrains Mono, monospace",
            "font-size": 11,
            "text-valign": "bottom",
            "text-margin-y": 5,
            "background-color": "#1d4ed8",
            "border-width": 1.5,
            "border-color": "#93c5fd",
            width: 28,
            height: 28,
          },
        },
        {
          selector: "node[kind='equipment']",
          style: {
            shape: "round-rectangle",
            "background-color": "#0c4a6e",
            "border-color": "#38bdf8",
            width: 38,
            height: 30,
          },
        },
        {
          selector: "node[kind='peer_equipment']",
          style: {
            shape: "round-rectangle",
            "background-color": "#162a45",
            "border-color": "#64748b",
            width: 34,
            height: 26,
          },
        },
        {
          selector: "node[kind='envelope']",
          style: {
            shape: "hexagon",
            "background-color": "#78350f",
            "border-color": "#f59e0b",
            width: 38,
            height: 34,
          },
        },
        {
          selector: "node[kind='valve']",
          style: {
            shape: "diamond",
            "background-color": "#451a03",
            "border-color": "#fbbf24",
            width: 22,
            height: 22,
          },
        },
        {
          selector: "node[kind='scope']",
          style: {
            shape: "ellipse",
            "background-color": "#064e3b",
            "border-color": "#34d399",
            width: 28,
            height: 28,
          },
        },
        {
          selector: "node[kind='peer_scope']",
          style: {
            shape: "ellipse",
            "background-color": "#11302a",
            "border-color": "#10b981",
            width: 24,
            height: 24,
          },
        },
        {
          selector: "node[kind='nozzle']",
          style: {
            shape: "rectangle",
            "background-color": "#1e293b",
            "border-color": "#94a3b8",
            width: 18,
            height: 18,
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#38527a",
            "target-arrow-color": "#38527a",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            label: "data(label)",
            "font-size": 9,
            color: "#8fa7c5",
            "text-background-color": "#0b1525",
            "text-background-opacity": 0.85,
            "text-background-padding": "2px",
          },
        },
      ],
    });

    cy.on("tap", "node", (evt) => {
      const d = evt.target.data() as { id: string; label: string; kind: string };
      setClickedNode(d);
    });

    cyRef.current = cy;

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [queryOutput]);

  return (
    <div>
      <div className="view-header">
        <div>
          <h1 className="view-title">In-browser plant graph</h1>
          <p className="view-subtitle">
            Relate WASM running locally in a dedicated Web Worker seeded from the Twin Cypher export. Runs named read-only queries only; Neo4j remains master.
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
          <label style={{ fontSize: "var(--text-sm)", color: "var(--ink-secondary)" }}>
            Query
            <select
              aria-label="Graph query mode"
              value={mode}
              onChange={(e) => setMode(e.target.value as NamedQueryId)}
              style={{ marginLeft: "0.45rem" }}
            >
              <option value="equipment_neighborhood">Equipment neighborhood</option>
              <option value="work_request_chain">Work request chain</option>
              <option value="envelope_subgraph">Isolation envelope closure</option>
            </select>
          </label>

          {mode === "equipment_neighborhood" && (
            <select
              aria-label="Select equipment for graph"
              value={selectedTag}
              onChange={(e) => onSelectTag(e.target.value)}
            >
              {equipment.map((eq) => (
                <option key={eq.tag} value={eq.tag}>
                  {eq.tag} ({eq.area})
                </option>
              ))}
            </select>
          )}

          {mode === "envelope_subgraph" && (
            <select
              aria-label="Select isolation envelope for graph"
              value={selectedEnvelopeId}
              onChange={(e) => onSelectEnvelope(e.target.value)}
            >
              {envelopes.map((env) => (
                <option key={env.id} value={env.id}>
                  {env.id} ({env.name})
                </option>
              ))}
            </select>
          )}

          {mode === "work_request_chain" && (
            <select
              aria-label="Select work request for graph"
              value={effectiveRequestId}
              onChange={(e) => onSelectRequest(e.target.value)}
            >
              {matchedRequests.slice(0, 80).map((r) => (
                <option key={r.request_id} value={r.request_id}>
                  {r.request_id} ({r.resolved_tag})
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      {workerError && (
        <div className="notice err" role="alert">
          {workerError}
        </div>
      )}

      <div className="metrics-strip">
        <div>
          <div className="metric-label">Relate WASM store</div>
          <div className="metric-value" style={{ fontSize: "var(--text-body)" }}>
            {stats ? `Relate WASM ready (${stats.nodes} nodes)` : "Seeding in-browser Relate store..."}
          </div>
          <div className="metric-note">
            {stats
              ? `Init ${stats.init_ms} ms · Seed ${stats.seed_ms} ms · Warmup ${stats.warmup_ms} ms`
              : "Fetching /api/v1/graph/export.cypher"}
          </div>
        </div>
        <div>
          <div className="metric-label">Last query execution</div>
          <div className="metric-value" style={{ fontSize: "var(--text-body)" }}>
            {queryOutput ? `${queryOutput.ms} ms (local WASM)` : "Waiting"}
          </div>
          <div className="metric-note">Named queries only; arbitrary Cypher refused</div>
        </div>
        <div>
          <div className="metric-label">Selected node</div>
          <div className="metric-value" style={{ fontSize: "var(--text-body)" }}>
            {clickedNode ? `${clickedNode.label} (${clickedNode.kind})` : "Click any node in graph"}
          </div>
          {clickedNode && (clickedNode.kind === "equipment" || clickedNode.kind === "peer_equipment") && (
            <button
              type="button"
              className="btn-subtle"
              style={{ marginTop: "0.25rem", padding: "0.18rem 0.5rem" }}
              onClick={() => onNavigateToPlot(clickedNode.label)}
            >
              Show on plot plan
            </button>
          )}
          {clickedNode && (clickedNode.kind === "scope" || clickedNode.kind === "peer_scope") && (
            <button
              type="button"
              className="btn-subtle"
              style={{ marginTop: "0.25rem", padding: "0.18rem 0.5rem" }}
              onClick={() => onNavigateToTrace(clickedNode.label)}
            >
              Open mapping trace
            </button>
          )}
        </div>
      </div>

      <div className="split-workspace">
        <div className="surface-panel" style={{ padding: "0.75rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.55rem", flexWrap: "wrap", gap: "0.5rem" }}>
            <div className="plot-legend">
              <span className="legend-item">
                <span className="legend-swatch" style={{ background: "#38bdf8" }} /> Equipment
              </span>
              <span className="legend-item">
                <span className="legend-swatch" style={{ background: "#f59e0b" }} /> Isolation envelope
              </span>
              <span className="legend-item">
                <span className="legend-swatch" style={{ background: "#fbbf24" }} /> Boundary valve
              </span>
              <span className="legend-item">
                <span className="legend-swatch" style={{ background: "#34d399" }} /> Scope item
              </span>
            </div>
            <button type="button" className="btn-subtle" onClick={() => cyRef.current?.fit(undefined, 28)}>
              Fit graph
            </button>
          </div>
          <div ref={cyHostRef} className="cytoscape-canvas" aria-label="Interactive Cytoscape plant graph" />
        </div>

        <aside className="surface-panel" aria-label="Named Cypher query">
          <h2 className="panel-heading">Executed named Cypher</h2>
          <pre className="cypher-code">
            {queryOutput?.displayCypher ?? "Waiting for Relate WASM query..."}
          </pre>
          <hr className="section-divider" />
          <h3 className="panel-heading">Parameters</h3>
          <dl className="kv-list">
            {mode === "equipment_neighborhood" && (
              <>
                <dt>$tag</dt>
                <dd className="mono">{selectedTag}</dd>
              </>
            )}
            {mode === "envelope_subgraph" && (
              <>
                <dt>$envelope_id</dt>
                <dd className="mono">{selectedEnvelopeId}</dd>
              </>
            )}
            {mode === "work_request_chain" && (
              <>
                <dt>$request_id</dt>
                <dd className="mono">{effectiveRequestId}</dd>
              </>
            )}
          </dl>
        </aside>
      </div>
    </div>
  );
};
