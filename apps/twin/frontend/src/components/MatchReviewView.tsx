import React, { useMemo, useState } from "react";
import type { ActiveTagOption, AuthMember, MatchingSummary, ScopeItem } from "../types";

interface MatchReviewViewProps {
  summary: MatchingSummary | null;
  queue: ScopeItem[];
  activeTags: ActiveTagOption[];
  authMember: AuthMember | null;
  authMode: string;
  onQuickPlannerLogin: () => Promise<void>;
  onOpenLoginModal: () => void;
  onDecide: (
    requestId: string,
    payload: { action: "accept" | "reject" | "pick_another"; tag?: string; reason?: string }
  ) => Promise<void>;
  onOpenTrace: (requestId: string) => void;
}

export const MatchReviewView: React.FC<MatchReviewViewProps> = ({
  summary,
  queue,
  activeTags,
  authMember,
  authMode,
  onQuickPlannerLogin,
  onOpenLoginModal,
  onDecide,
  onOpenTrace,
}) => {
  const [selectedId, setSelectedId] = useState<string>(queue[0]?.request_id ?? "");
  const [pickTag, setPickTag] = useState<string>("");
  const [reason, setReason] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);
  const [feedback, setFeedback] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const selected = useMemo(() => {
    if (queue.length === 0) return null;
    return queue.find((q) => q.request_id === selectedId) ?? queue[0];
  }, [queue, selectedId]);

  const canReview = authMember && (authMember.role === "planner" || authMember.role === "ta_manager");

  const runDecision = async (action: "accept" | "reject" | "pick_another", tag?: string) => {
    if (!selected) return;
    setBusy(true);
    setFeedback(null);
    try {
      const updated = await onDecide(selected.request_id, {
        action,
        tag,
        reason: reason.trim(),
      });
      void updated;
      setFeedback({
        kind: "ok",
        text:
          action === "accept"
            ? `Accepted match for ${selected.request_id} (${tag ?? selected.proposal?.tag ?? ""}).`
            : action === "pick_another"
              ? `Assigned ${tag} to ${selected.request_id}.`
              : `Rejected match for ${selected.request_id}.`,
      });
      setReason("");
      setPickTag("");
    } catch (err) {
      setFeedback({ kind: "err", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  };

  const matchPct = summary?.match_rate != null ? `${(summary.match_rate * 100).toFixed(1)}%` : "n/a";
  const coveragePct =
    summary?.proposal_coverage_rate != null ? `${(summary.proposal_coverage_rate * 100).toFixed(1)}%` : "n/a";

  return (
    <div>
      <div className="view-header">
        <div>
          <h1 className="view-title">Match review queue</h1>
          <p className="view-subtitle">
            Every AI proposal and ambiguous work request waits here for planner verification. Accepting or assigning tags updates the live match rate against the 95% readiness gate.
          </p>
        </div>
        {!canReview && authMode === "local" && (
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <button type="button" className="btn-primary" onClick={onQuickPlannerLogin}>
              Sign in as J. Planner
            </button>
            <button type="button" className="btn-subtle" onClick={onOpenLoginModal}>
              Choose account
            </button>
          </div>
        )}
        {authMember && (
          <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-secondary)" }}>
            Signed in as <strong>{authMember.full_name}</strong> ({authMember.role})
          </div>
        )}
      </div>

      {summary && (
        <div className="metrics-strip">
          <div>
            <div className="metric-label">Accepted match rate</div>
            <div className="metric-value" data-testid="match-rate-value">
              {matchPct}
            </div>
            <div className="bar-track" style={{ marginTop: "0.35rem" }}>
              <div
                className={`bar-fill ${summary.gate_passed ? "ok" : "ai"}`}
                style={{ width: `${Math.min(100, Math.round((summary.match_rate ?? 0) * 100))}%` }}
              />
            </div>
            <div className="metric-note" style={{ marginTop: "0.25rem" }}>
              {summary.accepted_count} of {summary.total_active} active items (gate {Math.round(summary.gate_threshold * 100)}%)
            </div>
          </div>
          <div>
            <div className="metric-label">Proposal coverage</div>
            <div className="metric-value">{coveragePct}</div>
            <div className="metric-note">{summary.proposal_coverage_count} items have an accepted or proposed tag</div>
          </div>
          <div>
            <div className="metric-label">Awaiting review</div>
            <div className="metric-value tone-ai">{summary.needs_review_count}</div>
            <div className="metric-note">Includes AI proposals and no-match findings</div>
          </div>
          <div>
            <div className="metric-label">Rejected</div>
            <div className="metric-value">{summary.rejected_count}</div>
            <div className="metric-note">Confirmed outside Unit 200 or invalid</div>
          </div>
        </div>
      )}

      {feedback && (
        <div className={`notice ${feedback.kind}`} role="status">
          {feedback.text}
        </div>
      )}

      <div className="split-workspace">
        {/* Queue table */}
        <div className="surface-panel">
          <h2 className="panel-heading">Items needing review ({queue.length})</h2>
          {queue.length === 0 ? (
            <p className="tone-ok" style={{ margin: 0, fontSize: "var(--text-sm)" }}>
              All active scope items have been reviewed.
            </p>
          ) : (
            <div className="table-wrap" style={{ maxHeight: "480px", overflowY: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Request</th>
                    <th>Raw equipment text</th>
                    <th>Proposed tag</th>
                    <th>Method</th>
                    <th className="num">Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {queue.map((it) => {
                    const isSel = selected?.request_id === it.request_id;
                    return (
                      <tr
                        key={it.request_id}
                        style={{
                          cursor: "pointer",
                          background: isSel ? "var(--accent-code-dim)" : undefined,
                        }}
                        onClick={() => setSelectedId(it.request_id)}
                      >
                        <td className="mono tone-code">{it.request_id}</td>
                        <td>{it.equipment_text || "(blank)"}</td>
                        <td className="mono tone-ai">{it.proposal?.tag ?? "none"}</td>
                        <td className="mono">{it.proposal?.method ?? it.match_method}</td>
                        <td className="num mono">
                          {it.proposal ? `${Math.round(it.proposal.confidence * 100)}%` : "0%"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Focused Review Inspector */}
        <aside className="surface-panel" aria-label="Review decision panel">
          {selected ? (
            <>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "0.5rem" }}>
                <h2 className="panel-heading mono" style={{ marginBottom: "0.2rem" }}>
                  {selected.request_id}
                </h2>
                <button
                  type="button"
                  className="btn-subtle"
                  style={{ padding: "0.18rem 0.5rem" }}
                  onClick={() => onOpenTrace(selected.request_id)}
                >
                  Full trace
                </button>
              </div>
              <p style={{ margin: "0 0 0.65rem", fontSize: "var(--text-sm)", color: "var(--ink-primary)" }}>
                {selected.title}
              </p>

              <dl className="kv-list">
                <dt>Equipment text</dt>
                <dd className="mono">{selected.equipment_text || "(blank)"}</dd>
                <dt>Area / work type</dt>
                <dd className="mono">
                  {selected.area} · {selected.work_type_label}
                </dd>
                <dt>Proposed tag</dt>
                <dd className="mono tone-ai" style={{ fontWeight: 600 }}>
                  {selected.proposal?.tag ?? "No proposal (abstained)"}
                </dd>
              </dl>

              {selected.mapping_trace.findings.length > 0 && (
                <div className="notice err" style={{ marginTop: "0.7rem", marginBottom: "0.5rem" }}>
                  {selected.mapping_trace.findings.map((f, i) => (
                    <div key={i}>
                      <strong>{f.kind}</strong>: {f.reason}
                    </div>
                  ))}
                </div>
              )}

              {selected.mapping_trace.instruction_warning && (
                <div className="notice warn" style={{ marginTop: "0.5rem", marginBottom: "0.5rem" }}>
                  Instruction phrase detected: {selected.mapping_trace.instruction_hits.join(", ")}. Confirm the physical target asset.
                </div>
              )}

              {selected.proposal?.evidence_text && (
                <div style={{ marginTop: "0.7rem", fontSize: "var(--text-sm)" }}>
                  <div style={{ color: "var(--ink-muted)" }}>Evidence fact ({selected.proposal.evidence_id})</div>
                  <div>{selected.proposal.evidence_text}</div>
                </div>
              )}

              {selected.proposal?.reason && (
                <div
                  style={{
                    marginTop: "0.65rem",
                    padding: "0.55rem 0.65rem",
                    background: "var(--accent-ai-dim)",
                    borderLeft: "2px solid var(--accent-ai)",
                    fontSize: "var(--text-sm)",
                  }}
                >
                  <div style={{ color: "var(--accent-ai)", fontWeight: 600 }}>
                    {selected.proposal.reason_label ?? "AI summary of selected facts"}
                  </div>
                  <div style={{ marginTop: "0.15rem" }}>{selected.proposal.reason}</div>
                </div>
              )}

              {selected.proposal?.probabilities && Object.keys(selected.proposal.probabilities).length > 0 && (
                <div style={{ marginTop: "0.75rem" }}>
                  <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-muted)", marginBottom: "0.35rem" }}>
                    Candidate probabilities
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                    {Object.entries(selected.proposal.probabilities)
                      .sort((a, b) => b[1] - a[1])
                      .slice(0, 5)
                      .map(([tag, prob]) => (
                        <div key={tag} style={{ fontSize: "var(--text-sm)" }}>
                          <div style={{ display: "flex", justifyContent: "space-between" }}>
                            <span className="mono">{tag}</span>
                            <span className="mono">{(prob * 100).toFixed(1)}%</span>
                          </div>
                          <div className="bar-track" style={{ height: "5px", marginTop: "2px" }}>
                            <div className="bar-fill ai" style={{ width: `${Math.round(prob * 100)}%` }} />
                          </div>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              <hr className="section-divider" />

              <div style={{ display: "flex", flexDirection: "column", gap: "0.55rem" }}>
                <input
                  type="text"
                  aria-label="Review reason note"
                  placeholder="Optional review note..."
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />

                <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="btn-ok"
                    disabled={busy || !canReview || !selected.proposal?.tag}
                    onClick={() => runDecision("accept", selected.proposal?.tag)}
                  >
                    Accept proposed tag
                  </button>
                  <button
                    type="button"
                    className="btn-danger"
                    disabled={busy || !canReview}
                    onClick={() => runDecision("reject")}
                  >
                    Reject
                  </button>
                </div>

                <div style={{ display: "flex", gap: "0.45rem", alignItems: "center" }}>
                  <select
                    aria-label="Pick another Unit 200 tag"
                    value={pickTag}
                    onChange={(e) => setPickTag(e.target.value)}
                    style={{ flex: 1, minWidth: 0 }}
                  >
                    <option value="">Pick another active Unit 200 tag...</option>
                    {activeTags.map((t) => (
                      <option key={t.tag} value={t.tag}>
                        {t.tag} ({t.area} · {t.equipment_class})
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    disabled={busy || !canReview || !pickTag}
                    onClick={() => runDecision("pick_another", pickTag)}
                  >
                    Assign
                  </button>
                </div>

                {!canReview && (
                  <p className="tone-ai" style={{ margin: "0.2rem 0 0", fontSize: "var(--text-sm)" }}>
                    Sign in as a planner or TA manager to record review decisions.
                  </p>
                )}
              </div>
            </>
          ) : (
            <p className="tone-muted" style={{ margin: 0 }}>
              No items currently waiting in the queue.
            </p>
          )}
        </aside>
      </div>

      {summary && (
        <div className="split-even" style={{ marginTop: "1rem" }}>
          <section className="surface-panel">
            <h2 className="panel-heading">Match rate by area</h2>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Area</th>
                    <th className="num">Accepted</th>
                    <th className="num">Active</th>
                    <th className="num">Rate</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.by_area.map((b) => (
                    <tr key={b.key}>
                      <td className="mono">{b.key}</td>
                      <td className="num mono">{b.accepted}</td>
                      <td className="num mono">{b.total}</td>
                      <td className={`num mono ${b.match_rate >= 0.95 ? "tone-ok" : "tone-ai"}`}>
                        {(b.match_rate * 100).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="surface-panel">
            <h2 className="panel-heading">Match rate by source group</h2>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Source group</th>
                    <th className="num">Accepted</th>
                    <th className="num">Active</th>
                    <th className="num">Rate</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.by_source_group.map((b) => (
                    <tr key={b.key}>
                      <td>{b.key.replace(/_/g, " ")}</td>
                      <td className="num mono">{b.accepted}</td>
                      <td className="num mono">{b.total}</td>
                      <td className={`num mono ${b.match_rate >= 0.95 ? "tone-ok" : "tone-ai"}`}>
                        {(b.match_rate * 100).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </div>
  );
};
