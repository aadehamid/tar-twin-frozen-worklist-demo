import React, { useMemo, useState } from "react";
import type { EquipmentDetail, ScopeItem } from "../types";

interface MappingTraceViewProps {
  scopeItems: ScopeItem[];
  equipment: EquipmentDetail[];
  selectedRequestId: string;
  onSelectRequestId: (id: string) => void;
  onHighlightPlot: (tag: string) => void;
  onOpenPid: (sheetNo: string, tag: string) => void;
  onOpenGraph: (requestId: string) => void;
}

export const MappingTraceView: React.FC<MappingTraceViewProps> = ({
  scopeItems,
  equipment,
  selectedRequestId,
  onSelectRequestId,
  onHighlightPlot,
  onOpenPid,
  onOpenGraph,
}) => {
  const [search, setSearch] = useState("");
  const [sideBySide, setSideBySide] = useState(false);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return scopeItems;
    return scopeItems.filter(
      (it) =>
        it.request_id.toLowerCase().includes(q) ||
        it.title.toLowerCase().includes(q) ||
        it.equipment_text.toLowerCase().includes(q) ||
        (it.resolved_tag ?? "").toLowerCase().includes(q)
    );
  }, [scopeItems, search]);

  const item = useMemo(
    () => scopeItems.find((s) => s.request_id === selectedRequestId) ?? scopeItems[0] ?? null,
    [scopeItems, selectedRequestId]
  );

  const resolvedEq = useMemo(
    () => (item?.resolved_tag ? equipment.find((e) => e.tag === item.resolved_tag) ?? null : null),
    [equipment, item]
  );

  if (!item) {
    return <div className="surface-panel">No synced work requests available.</div>;
  }

  const trace = item.mapping_trace;
  const ai = trace.ai_proposal;
  const resolvedTag = item.resolved_tag;

  return (
    <div>
      <div className="view-header">
        <div>
          <h1 className="view-title">Mapping trace</h1>
          <p className="view-subtitle">
            Seven-step audit trail showing how an IMPACT Web free-text work request resolves to Unit 200 equipment, P&ID sheet, plot position, and isolation envelope.
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
          <input
            type="text"
            aria-label="Filter work requests in trace"
            placeholder="Filter WR ID, tag, or text..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: "210px" }}
          />
          <select
            aria-label="Select work request"
            value={item.request_id}
            onChange={(e) => onSelectRequestId(e.target.value)}
            style={{ maxWidth: "320px" }}
          >
            {filtered.map((s) => (
              <option key={s.request_id} value={s.request_id}>
                {s.request_id} ({s.resolved_tag ?? "review"}) - {s.title.slice(0, 42)}
              </option>
            ))}
          </select>
          <label style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem", fontSize: "var(--text-sm)", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={sideBySide}
              onChange={(e) => setSideBySide(e.target.checked)}
            />
            Side-by-side IMPACT Web vs Twin
          </label>
        </div>
      </div>

      {sideBySide && (
        <div className="split-even" style={{ marginBottom: "1rem" }}>
          <section className="surface-panel">
            <h2 className="panel-heading">IMPACT Web record (system of record)</h2>
            <dl className="kv-list">
              <dt>Request ID</dt>
              <dd className="mono">{item.request_id} (v{item.version})</dd>
              <dt>Title</dt>
              <dd>{item.title}</dd>
              <dt>Equipment text</dt>
              <dd className="mono">{trace.raw_equipment_text || "(blank)"}</dd>
              <dt>Description</dt>
              <dd>{trace.raw_description}</dd>
              <dt>Source group</dt>
              <dd>{item.source_group}</dd>
              <dt>Area / RIPT</dt>
              <dd className="mono">
                {item.area} · RIPT {item.ript_score} {item.mandatory ? "(mandatory)" : "(discretionary)"}
              </dd>
              <dt>Estimate</dt>
              <dd className="mono">
                {item.estimate_hours.toLocaleString()} hrs · ${item.estimate_cost_usd.toLocaleString()}
              </dd>
            </dl>
          </section>

          <section className="surface-panel panel-code">
            <h2 className="panel-heading">Twin equipment context (derived mirror)</h2>
            {resolvedTag ? (
              <>
                <dl className="kv-list">
                  <dt>Resolved tag</dt>
                  <dd className="mono tone-ok" style={{ fontWeight: 600 }}>
                    {resolvedTag}
                  </dd>
                  <dt>Description</dt>
                  <dd>{resolvedEq?.description ?? trace.result?.tag}</dd>
                  <dt>Area</dt>
                  <dd className="mono">{trace.result?.area ?? resolvedEq?.area ?? "n/a"}</dd>
                  <dt>P&ID sheet</dt>
                  <dd className="mono">{trace.result?.sheet ?? resolvedEq?.sheet ?? "n/a"}</dd>
                  <dt>Envelopes</dt>
                  <dd className="mono">{(trace.result?.envelopes ?? resolvedEq?.envelopes ?? []).join(", ") || "None"}</dd>
                  <dt>Match method</dt>
                  <dd className="mono">
                    {item.match_method} ({Math.round(item.confidence * 100)}%)
                  </dd>
                </dl>
                <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", marginTop: "0.85rem" }}>
                  <button type="button" className="btn-primary" onClick={() => onHighlightPlot(resolvedTag)}>
                    Highlight on plot plan
                  </button>
                  {(trace.result?.sheet || resolvedEq?.sheet) && (
                    <button
                      type="button"
                      onClick={() => onOpenPid(trace.result?.sheet || resolvedEq?.sheet || "200-PID-002", resolvedTag)}
                    >
                      Open on P&ID
                    </button>
                  )}
                  <button type="button" onClick={() => onOpenGraph(item.request_id)}>
                    Trace in Relate graph
                  </button>
                </div>
              </>
            ) : (
              <p className="tone-ai" style={{ margin: 0, fontSize: "var(--text-sm)" }}>
                Not yet accepted. Current status: {item.match_status}. Open the Match review tab to accept, reject, or assign a tag.
              </p>
            )}
          </section>
        </div>
      )}

      <div className="surface-panel">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem", marginBottom: "0.9rem", flexWrap: "wrap" }}>
          <div>
            <h2 className="panel-heading" style={{ marginBottom: "0.15rem" }}>
              {item.request_id}: {item.title}
            </h2>
            <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-secondary)" }}>
              Status: <strong className={item.match_status === "accepted" ? "tone-ok" : "tone-ai"}>{item.match_status}</strong>
              {resolvedTag ? (
                <>
                  {" "}
                  to <span className="mono tone-code">{resolvedTag}</span>
                </>
              ) : null}
            </div>
          </div>
          {resolvedTag && (
            <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
              <button type="button" className="btn-primary" onClick={() => onHighlightPlot(resolvedTag)}>
                Highlight on plot plan
              </button>
              {trace.result?.sheet && (
                <button type="button" onClick={() => onOpenPid(trace.result!.sheet, resolvedTag)}>
                  Open {trace.result.sheet}
                </button>
              )}
              <button type="button" onClick={() => onOpenGraph(item.request_id)}>
                Trace in Relate graph
              </button>
            </div>
          )}
        </div>

        <ol className="trace-list">
          <li className="trace-step trace-step-code">
            <div className="trace-step-title">1. Raw IMPACT Web input</div>
            <div className="trace-step-body">
              Equipment text: <span className="mono">{trace.raw_equipment_text || "(empty)"}</span> · Area: <span className="mono">{item.area}</span> · Work type: <span className="mono">{item.work_type_label}</span>
              <div style={{ marginTop: "0.2rem" }}>{trace.raw_description}</div>
            </div>
          </li>

          <li className="trace-step trace-step-code">
            <div className="trace-step-title">2. Normalized text and unit check</div>
            <div className="trace-step-body">
              Normalized: <span className="mono">{trace.normalized_text || "(none)"}</span>
              {trace.explicit_unit ? ` · Explicit unit prefix detected: Unit ${trace.explicit_unit}` : ""}
              {trace.instruction_warning && (
                <div className="tone-ai" style={{ marginTop: "0.25rem" }}>
                  Instruction phrase warning: {trace.instruction_hits.join(", ")}
                </div>
              )}
            </div>
          </li>

          <li className="trace-step trace-step-code">
            <div className="trace-step-title">3. Methods run and code findings</div>
            <div className="trace-step-body">
              {trace.methods_run.map((m, idx) => (
                <div key={idx}>
                  <span className="mono tone-code">{m.method}</span>: {m.status}
                  {m.score !== undefined ? ` (score ${m.score})` : ""}
                  {m.detail ? ` - ${m.detail}` : ""}
                </div>
              ))}
              {trace.findings.length > 0 && (
                <div className="tone-danger" style={{ marginTop: "0.3rem" }}>
                  Findings: {trace.findings.map((f) => `${f.kind}${f.tag ? ` (${f.tag})` : ""}: ${f.reason}`).join("; ")}
                </div>
              )}
            </div>
          </li>

          <li className="trace-step trace-step-code">
            <div className="trace-step-title">4. Eligible candidates and DEXPI topology facts ({trace.candidates.length})</div>
            <div className="trace-step-body">
              {trace.candidates.length === 0 ? (
                "No eligible Unit 200 candidates remained after compatibility and unit filters."
              ) : (
                <div className="table-wrap" style={{ marginTop: "0.35rem" }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Tag</th>
                        <th>Class</th>
                        <th>Area</th>
                        <th>Sheet</th>
                        <th className="num">Score</th>
                        <th>DEXPI fact sample</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trace.candidates.slice(0, 6).map((c) => (
                        <tr key={c.tag}>
                          <td className="mono tone-code">{c.tag}</td>
                          <td>{c.equipment_class}</td>
                          <td className="mono">{c.area}</td>
                          <td className="mono">{c.sheet}</td>
                          <td className="num mono">{c.score}</td>
                          <td>{c.facts[0]?.text ?? c.description}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </li>

          <li className="trace-step trace-step-ai">
            <div className="trace-step-title">5. AI proposal (Perplexity Decider + Inkling summary)</div>
            <div className="trace-step-body">
              {ai ? (
                <>
                  <div>
                    Model: <span className="mono tone-ai">{ai.model_version ?? "perplexity/pplx-decider-v1.3"}</span> · Question:{" "}
                    <span className="mono">{ai.question_version ?? "v1"}</span> · Verdict:{" "}
                    <strong>{ai.verdict?.outcome ?? "evaluated"}</strong>
                    {ai.picked_tag ? (
                      <>
                        {" "}
                        · Picked <span className="mono tone-ai">{ai.picked_tag}</span> ({Math.round((ai.confidence ?? 0) * 100)}%)
                      </>
                    ) : null}
                  </div>
                  {ai.evidence_text && (
                    <div style={{ marginTop: "0.25rem" }}>
                      Evidence fact (<span className="mono">{ai.evidence_id}</span>): {ai.evidence_text}
                    </div>
                  )}
                  {ai.inkling_reason && (
                    <div style={{ marginTop: "0.25rem", color: "#fde68a" }}>
                      {ai.inkling_label ?? "AI summary of selected facts"}: {ai.inkling_reason}
                    </div>
                  )}
                </>
              ) : (
                "Deterministic code resolved this item or AI was not invoked."
              )}
            </div>
          </li>

          <li className="trace-step">
            <div className="trace-step-title">6. Reviewer decision</div>
            <div className="trace-step-body">
              Outcome: <strong>{trace.decision.outcome}</strong>
              {trace.decision.decided_by ? ` by ${trace.decision.decided_by}` : ""} · {trace.decision.reason}
            </div>
          </li>

          <li className="trace-step trace-step-code">
            <div className="trace-step-title">7. Resolved plant location</div>
            <div className="trace-step-body">
              {trace.result ? (
                <>
                  Tag <span className="mono tone-ok">{trace.result.tag}</span> · Area{" "}
                  <span className="mono">{trace.result.area}</span> · Sheet{" "}
                  <span className="mono">{trace.result.sheet}</span> · Envelopes{" "}
                  <span className="mono">{trace.result.envelopes.join(", ") || "None"}</span>
                </>
              ) : (
                "Unresolved until planner review completes."
              )}
            </div>
          </li>
        </ol>
      </div>
    </div>
  );
};
