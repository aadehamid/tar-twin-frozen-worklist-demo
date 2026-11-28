import React, { useMemo, useState } from "react";
import type { ClustersPayload, CutLineResult, CutLineRunRecord, ScopeItem } from "../types";

interface ClustersCutLineViewProps {
  clusters: ClustersPayload | null;
  cutLine: CutLineResult | null;
  savedRuns: CutLineRunRecord[];
  scopeItems: ScopeItem[];
  budgetUsd: number;
  onBudgetChange: (budgetUsd: number) => void;
  onSaveCutLineOption: (name: string) => Promise<void>;
  onColorCutLineOnPlot: () => void;
  onHighlightTagsOnPlot: (tags: string[]) => void;
  onOpenTrace: (requestId: string) => void;
}

type ClusterTab = "isolation" | "scaffold" | "access" | "duplicates";

const PRESETS = [
  { label: "$10M", value: 10_000_000 },
  { label: "$16M", value: 16_000_000 },
  { label: "$20M", value: 20_000_000 },
  { label: "$22M", value: 22_000_000 },
  { label: "$25M", value: 25_000_000 },
];

export const ClustersCutLineView: React.FC<ClustersCutLineViewProps> = ({
  clusters,
  cutLine,
  savedRuns,
  scopeItems,
  budgetUsd,
  onBudgetChange,
  onSaveCutLineOption,
  onColorCutLineOnPlot,
  onHighlightTagsOnPlot,
  onOpenTrace,
}) => {
  const [tab, setTab] = useState<ClusterTab>("isolation");
  const [optionName, setOptionName] = useState<string>("DRB Option A");
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState<boolean>(false);

  const itemById = useMemo(() => {
    const m = new Map<string, ScopeItem>();
    for (const it of scopeItems) m.set(it.request_id, it);
    return m;
  }, [scopeItems]);

  const activeClusters = useMemo(() => {
    if (!clusters) return [];
    if (tab === "isolation") return clusters.isolation_clusters;
    if (tab === "scaffold") return clusters.scaffold_clusters;
    if (tab === "access") return clusters.access_clusters;
    return [];
  }, [clusters, tab]);

  const belowItems = useMemo(() => {
    if (!cutLine) return [];
    return cutLine.below_ids
      .map((id) => itemById.get(id))
      .filter((x): x is ScopeItem => Boolean(x));
  }, [cutLine, itemById]);

  return (
    <div>
      <div className="view-header">
        <div>
          <h1 className="view-title">Clusters and cut line</h1>
          <p className="view-subtitle">
            Shared scaffold, isolation, and crane access costs are counted once per cluster. Slide the budget target to see mandatory floor feasibility and deferred scope.
          </p>
        </div>
        <button type="button" className="btn-primary" onClick={onColorCutLineOnPlot}>
          Color cut line on plot plan
        </button>
      </div>

      {/* Budget Cut Line Control */}
      <section className="surface-panel" style={{ marginBottom: "1rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem", flexWrap: "wrap", marginBottom: "0.7rem" }}>
          <div>
            <h2 className="panel-heading" style={{ marginBottom: "0.15rem" }}>
              Budget target: <span className="mono tone-code">${(budgetUsd / 1_000_000).toFixed(2)}M</span>
            </h2>
            <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-secondary)" }}>
              Mandatory drivers stay above the line first, followed by discretionary scope ranked by RIPT score and clustered cost per risk point.
            </div>
          </div>
          <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
            {PRESETS.map((p) => (
              <button
                key={p.label}
                type="button"
                className={budgetUsd === p.value ? "btn-primary" : "btn-subtle"}
                onClick={() => onBudgetChange(p.value)}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <input
          type="range"
          className="budget-slider"
          aria-label="Turnaround budget target in USD"
          min={8_000_000}
          max={28_000_000}
          step={250_000}
          value={budgetUsd}
          onChange={(e) => onBudgetChange(Number(e.target.value))}
        />

        {cutLine && (
          <div className="metrics-strip" style={{ marginTop: "0.85rem", marginBottom: 0 }}>
            <div>
              <div className="metric-label">Cut line status</div>
              <div className={`metric-value ${cutLine.feasible ? "tone-ok" : "tone-danger"}`}>
                {cutLine.feasible ? "Feasible" : "Infeasible"}
              </div>
              <div className="metric-note">
                {cutLine.feasible
                  ? `Mandatory floor $${cutLine.mandatory_cost_usd.toLocaleString()}`
                  : `Shortfall $${cutLine.shortfall_usd.toLocaleString()} vs mandatory floor`}
              </div>
            </div>
            <div>
              <div className="metric-label">Above the line</div>
              <div className="metric-value">
                {cutLine.above_count} jobs
              </div>
              <div className="metric-note">
                ${cutLine.above_cost_usd.toLocaleString()} · {cutLine.above_hours.toLocaleString()} hrs
              </div>
            </div>
            <div>
              <div className="metric-label">Below the line</div>
              <div className="metric-value tone-ai">
                {cutLine.below_count} jobs
              </div>
              <div className="metric-note">
                ${cutLine.below_cost_usd.toLocaleString()} · {cutLine.below_hours.toLocaleString()} hrs
              </div>
            </div>
            <div>
              <div className="metric-label">Shared cost saved</div>
              <div className="metric-value tone-ok">
                ${cutLine.shared_cost_saved_usd.toLocaleString()}
              </div>
              <div className="metric-note">
                Unclustered ${cutLine.above_unclustered_cost_usd.toLocaleString()}
              </div>
            </div>
          </div>
        )}

        <div
          style={{
            marginTop: "0.95rem",
            paddingTop: "0.85rem",
            borderTop: "1px solid var(--border-subtle)",
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "0.75rem",
          }}
        >
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (!optionName.trim()) return;
              setSaving(true);
              setSaveMessage(null);
              try {
                await onSaveCutLineOption(optionName.trim());
                setSaveMessage(`Saved option "${optionName.trim()}" locally in the twin (IMPACT Web unchanged).`);
              } catch (err) {
                setSaveMessage(err instanceof Error ? err.message : String(err));
              } finally {
                setSaving(false);
              }
            }}
            style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}
          >
            <input
              type="text"
              aria-label="Cut-line option name"
              value={optionName}
              onChange={(e) => setOptionName(e.target.value)}
              placeholder="Option name (e.g. DRB Option A)"
              style={{
                background: "var(--bg-inset)",
                border: "1px solid var(--border-strong)",
                borderRadius: "var(--radius-sm)",
                padding: "0.42rem 0.65rem",
                minWidth: "210px",
              }}
            />
            <button type="submit" className="btn-subtle" disabled={saving}>
              {saving ? "Saving..." : "Save cut-line option"}
            </button>
          </form>
          {saveMessage && (
            <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-secondary)" }}>{saveMessage}</span>
          )}
        </div>

        {savedRuns.length > 0 && (
          <div style={{ marginTop: "0.75rem", overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Saved option (twin-local)</th>
                  <th>Budget</th>
                  <th>Status</th>
                  <th>Above / below</th>
                  <th>Saved by</th>
                </tr>
              </thead>
              <tbody>
                {savedRuns.map((run) => (
                  <tr key={run.id}>
                    <td>{run.name}</td>
                    <td className="mono">${run.budget_usd.toLocaleString()}</td>
                    <td className={run.feasible ? "tone-ok" : "tone-danger"}>
                      {run.feasible ? "Feasible" : `Shortfall $${run.shortfall_usd.toLocaleString()}`}
                    </td>
                    <td className="mono">
                      {run.above_count} / {run.below_count}
                    </td>
                    <td>{run.saved_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Clusters & Duplicates Tabs */}
      <section className="surface-panel" style={{ marginBottom: "1rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem", flexWrap: "wrap", marginBottom: "0.85rem" }}>
          <h2 className="panel-heading" style={{ margin: 0 }}>
            Shared-cost clusters and duplicate scope
          </h2>
          <div className="segmented" role="tablist" aria-label="Cluster categories">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "isolation"}
              onClick={() => setTab("isolation")}
            >
              Isolation ({clusters?.isolation_clusters.length ?? 0})
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "scaffold"}
              onClick={() => setTab("scaffold")}
            >
              Scaffold ({clusters?.scaffold_clusters.length ?? 0})
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "access"}
              onClick={() => setTab("access")}
            >
              Access ({clusters?.access_clusters.length ?? 0})
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "duplicates"}
              onClick={() => setTab("duplicates")}
            >
              Duplicate pairs ({clusters?.duplicate_pairs.length ?? 0})
            </button>
          </div>
        </div>

        {tab === "duplicates" ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Pair</th>
                  <th>Equipment</th>
                  <th>Work requests</th>
                  <th>Source groups</th>
                  <th className="num">Overlap hours</th>
                  <th className="num">Overlap cost</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {(clusters?.duplicate_pairs ?? []).map((p) => (
                  <tr key={p.id}>
                    <td className="mono tone-ai">{p.id}</td>
                    <td className="mono tone-code">{p.equipment_tag}</td>
                    <td className="mono">{p.request_ids.join(", ")}</td>
                    <td>{p.source_groups.join(" vs ")}</td>
                    <td className="num mono">{p.overlap_hours.toLocaleString()}</td>
                    <td className="num mono">${p.overlap_cost_usd.toLocaleString()}</td>
                    <td>
                      <button
                        type="button"
                        className="btn-subtle"
                        style={{ padding: "0.2rem 0.55rem" }}
                        onClick={() => onHighlightTagsOnPlot([p.equipment_tag])}
                      >
                        Plot plan
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Cluster</th>
                  <th>Description</th>
                  <th>Equipment tags</th>
                  <th className="num">Jobs</th>
                  <th className="num">Shared hours</th>
                  <th className="num">Shared cost (once)</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {activeClusters.map((c) => (
                  <tr key={c.id}>
                    <td className="mono tone-code">{c.id}</td>
                    <td>{c.name}</td>
                    <td className="mono">{c.equipment_tags.join(", ")}</td>
                    <td className="num mono">{c.request_ids.length}</td>
                    <td className="num mono">{c.shared_hours.toLocaleString()}</td>
                    <td className="num mono">${c.shared_cost_usd.toLocaleString()}</td>
                    <td>
                      <button
                        type="button"
                        className="btn-subtle"
                        style={{ padding: "0.2rem 0.55rem" }}
                        onClick={() => onHighlightTagsOnPlot(c.equipment_tags)}
                      >
                        Highlight
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Below-the-line candidate deferrals */}
      {cutLine && belowItems.length > 0 && (
        <section className="surface-panel">
          <h2 className="panel-heading">Scope below the ${ (budgetUsd / 1_000_000).toFixed(2) }M cut line ({belowItems.length})</h2>
          <div className="table-wrap" style={{ maxHeight: "340px", overflowY: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Request</th>
                  <th>Title</th>
                  <th>Equipment</th>
                  <th>Area</th>
                  <th className="num">RIPT</th>
                  <th className="num">Hours</th>
                  <th className="num">Cost</th>
                </tr>
              </thead>
              <tbody>
                {belowItems.slice(0, 40).map((it) => (
                  <tr key={it.request_id} style={{ cursor: "pointer" }} onClick={() => onOpenTrace(it.request_id)}>
                    <td className="mono tone-code">{it.request_id}</td>
                    <td>{it.title}</td>
                    <td className="mono">{it.resolved_tag ?? it.equipment_text}</td>
                    <td className="mono">{it.area}</td>
                    <td className="num mono">{it.ript_score}</td>
                    <td className="num mono">{it.estimate_hours.toLocaleString()}</td>
                    <td className="num mono">${it.estimate_cost_usd.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
};
