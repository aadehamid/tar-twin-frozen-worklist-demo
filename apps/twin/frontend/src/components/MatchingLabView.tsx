import React, { useEffect, useState } from "react";
import { twinApi } from "../api";
import type { LabCompareResponse, LabStepResponse, ScopeItem } from "../types";

interface MatchingLabViewProps {
  exerciseId: string;
  scopeItems: ScopeItem[];
  initialRequestId: string;
}

export const MatchingLabView: React.FC<MatchingLabViewProps> = ({
  exerciseId,
  scopeItems,
  initialRequestId,
}) => {
  const [selectedId, setSelectedId] = useState<string>(initialRequestId || "WR-200-0147");
  const [stepData, setStepData] = useState<LabStepResponse | null>(null);
  const [compareData, setCompareData] = useState<LabCompareResponse | null>(null);
  const [loadingCompare, setLoadingCompare] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadingCompare(true);
    twinApi
      .labCompare(exerciseId)
      .then((res) => {
        if (!cancelled) {
          setCompareData(res);
          setLoadingCompare(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoadingCompare(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [exerciseId]);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    twinApi
      .labStep(selectedId, exerciseId)
      .then((res) => {
        if (!cancelled) setStepData(res);
      })
      .catch(() => {
        // ignore transient lookup
      });
    return () => {
      cancelled = true;
    };
  }, [exerciseId, selectedId]);

  const modes = compareData?.modes;
  const codeOnly = modes?.code_only;
  const codeThenAi = modes?.code_then_ai;
  const aiAll = modes?.ai_on_everything;

  const classes = codeThenAi?.by_class.map((r) => r.difficulty_class) ?? [];

  return (
    <div>
      <div className="view-header">
        <div>
          <h1 className="view-title">Matching lab</h1>
          <p className="view-subtitle">
            Read-only comparison of deterministic code (cyan) against Perplexity Decider AI proposals (amber) over all 200 Unit 200 work requests.
          </p>
        </div>
        <select
          aria-label="Step through work request in matching lab"
          value={selectedId}
          onChange={(e) => setSelectedId(e.target.value)}
          style={{ maxWidth: "340px" }}
        >
          {scopeItems.map((it) => (
            <option key={it.request_id} value={it.request_id}>
              {it.request_id}: {it.equipment_text.slice(0, 36) || "(blank)"}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <div className="notice err" role="alert">
          {error}
        </div>
      )}

      {/* Single-request Code vs AI step-through */}
      {stepData && (
        <div className="split-even" style={{ marginBottom: "1rem" }}>
          <section className="surface-panel panel-code">
            <h2 className="panel-heading tone-code">What deterministic code did</h2>
            <dl className="kv-list">
              <dt>Request</dt>
              <dd className="mono">{stepData.item.request_id}</dd>
              <dt>Raw text</dt>
              <dd className="mono">{stepData.item.equipment_text || "(blank)"}</dd>
              <dt>Normalized</dt>
              <dd className="mono">{stepData.item.mapping_trace.normalized_text || "(none)"}</dd>
              <dt>Candidates built</dt>
              <dd className="mono">{stepData.item.mapping_trace.candidates.length} eligible Unit 200 tags</dd>
              <dt>Code findings</dt>
              <dd>
                {stepData.item.mapping_trace.findings.length > 0
                  ? stepData.item.mapping_trace.findings.map((f) => `${f.kind}: ${f.reason}`).join("; ")
                  : "None"}
              </dd>
              <dt>Answer key</dt>
              <dd className="mono tone-ok">
                {stepData.answer_key
                  ? `${stepData.answer_key.true_tag} (${stepData.answer_key.difficulty_class})`
                  : "n/a"}
              </dd>
            </dl>
          </section>

          <section className="surface-panel panel-ai">
            <h2 className="panel-heading tone-ai">What Perplexity Decider + checker did</h2>
            {stepData.item.mapping_trace.ai_proposal ? (
              <dl className="kv-list">
                <dt>Model</dt>
                <dd className="mono">{stepData.item.mapping_trace.ai_proposal.model_version}</dd>
                <dt>Verdict</dt>
                <dd className="mono">{stepData.item.mapping_trace.ai_proposal.verdict?.outcome}</dd>
                <dt>Picked tag</dt>
                <dd className="mono tone-ai">
                  {stepData.item.mapping_trace.ai_proposal.picked_tag ?? "none (abstained)"}
                </dd>
                <dt>Evidence fact</dt>
                <dd>{stepData.item.mapping_trace.ai_proposal.evidence_text ?? "None"}</dd>
                <dt>AI summary</dt>
                <dd>{stepData.item.mapping_trace.ai_proposal.inkling_reason ?? "Not generated"}</dd>
              </dl>
            ) : (
              <p style={{ margin: 0, fontSize: "var(--text-sm)", color: "var(--ink-secondary)" }}>
                Deterministic rules resolved {stepData.item.request_id} to{" "}
                <span className="mono tone-code">{stepData.item.resolved_tag ?? "review"}</span> without calling an LLM.
              </p>
            )}
          </section>
        </div>
      )}

      {/* 3-mode comparison summary */}
      <section className="surface-panel" style={{ marginBottom: "1rem" }}>
        <h2 className="panel-heading">Three-mode pipeline comparison (read-only)</h2>
        {loadingCompare || !codeOnly || !codeThenAi || !aiAll ? (
          <p className="tone-muted" style={{ margin: 0 }}>
            Evaluating 200 work requests across all three modes...
          </p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Mode</th>
                  <th className="num">Auto-accepted</th>
                  <th className="num">Correct</th>
                  <th className="num">Wrong</th>
                  <th className="num">Review queue</th>
                  <th className="num">Abstained</th>
                  <th className="num">Candidate recall</th>
                  <th className="num">AI calls</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { label: "Code only", data: codeOnly.totals, tone: "tone-code" },
                  { label: "Code then AI", data: codeThenAi.totals, tone: "tone-ok" },
                  { label: "AI on everything", data: aiAll.totals, tone: "tone-ai" },
                ].map((row) => (
                  <tr key={row.label}>
                    <td className={row.tone} style={{ fontWeight: 600 }}>
                      {row.label}
                    </td>
                    <td className="num mono">{row.data.auto_accepted}</td>
                    <td className="num mono tone-ok">{row.data.correct}</td>
                    <td className={`num mono ${row.data.wrong > 0 ? "tone-danger" : ""}`}>{row.data.wrong}</td>
                    <td className="num mono">{row.data.sent_to_review}</td>
                    <td className="num mono">{row.data.abstained}</td>
                    <td className="num mono tone-ok">{(row.data.candidate_recall * 100).toFixed(1)}%</td>
                    <td className="num mono">{row.data.ai_calls}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Difficulty class breakdown */}
      {codeOnly && codeThenAi && aiAll && (
        <section className="surface-panel">
          <h2 className="panel-heading">Breakdown across difficulty classes</h2>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Difficulty class</th>
                  <th className="num">Requests</th>
                  <th className="num">Code only correct</th>
                  <th className="num">Code then AI correct</th>
                  <th className="num">AI on everything correct</th>
                  <th className="num">Candidate recall</th>
                </tr>
              </thead>
              <tbody>
                {classes.map((cls) => {
                  const c1 = codeOnly.by_class.find((r) => r.difficulty_class === cls);
                  const c2 = codeThenAi.by_class.find((r) => r.difficulty_class === cls);
                  const c3 = aiAll.by_class.find((r) => r.difficulty_class === cls);
                  return (
                    <tr key={cls}>
                      <td>{cls}</td>
                      <td className="num mono">{c2?.count ?? 0}</td>
                      <td className="num mono">{c1?.correct ?? 0}</td>
                      <td className="num mono tone-ok">{c2?.correct ?? 0}</td>
                      <td className="num mono">{c3?.correct ?? 0}</td>
                      <td className="num mono">{((c2?.candidate_recall ?? 1) * 100).toFixed(1)}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
};
