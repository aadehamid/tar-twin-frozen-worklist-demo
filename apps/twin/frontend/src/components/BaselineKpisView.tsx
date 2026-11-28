import React from "react";
import type { BaselineSummary, KpisSummary, ValuePanelData } from "../types";

interface BaselineKpisViewProps {
  baseline: BaselineSummary | null;
  kpis: KpisSummary | null;
  valuePanel: ValuePanelData | null;
  onOpenRaiseModal: (tag: string) => void;
}

export const BaselineKpisView: React.FC<BaselineKpisViewProps> = ({
  baseline,
  kpis,
  valuePanel,
  onOpenRaiseModal,
}) => {
  const frozenRatePct =
    baseline?.frozen_match_rate != null ? `${(baseline.frozen_match_rate * 100).toFixed(1)}%` : "n/a";
  const siteRatePct =
    kpis?.tag_match_rate != null ? `${(kpis.tag_match_rate * 100).toFixed(1)}%` : "n/a";

  return (
    <div>
      <div className="view-header">
        <div>
          <h1 className="view-title">Baseline, KPIs, and value</h1>
          <p className="view-subtitle">
            Immutable frozen baseline captured from IMPACT Web, post-freeze scope growth in man-hours, and focus-area brief assumptions separated from measured demo counts.
          </p>
        </div>
        <button type="button" className="btn-primary" onClick={() => onOpenRaiseModal("C-201")}>
          Raise change request (C-201 N3)
        </button>
      </div>

      {/* Baseline & Growth Metrics Strip */}
      <div className="metrics-strip">
        <div>
          <div className="metric-label">Frozen baseline</div>
          <div className={`metric-value ${baseline?.frozen ? "tone-ok" : "tone-ai"}`}>
            {baseline?.frozen ? `${baseline.baseline_item_count} frozen items` : "Not frozen yet"}
          </div>
          <div className="metric-note">
            {baseline?.frozen
              ? `${baseline.baseline_hours.toLocaleString()} hrs · ${baseline.freeze_id}`
              : "Freeze TAR-200-2028 in IMPACT Web to snapshot baseline"}
          </div>
        </div>

        <div>
          <div className="metric-label">3.1 readiness gate (separate from freeze)</div>
          <div className={`metric-value ${baseline?.ready_for_use ? "tone-ok" : "tone-ai"}`}>
            {baseline?.ready_for_use ? "Ready for 3.1 use" : "Not ready"}
          </div>
          <div className="metric-note">
            Frozen match rate {frozenRatePct} vs {Math.round((baseline?.gate_threshold ?? 0.95) * 100)}% gate
          </div>
        </div>

        <div>
          <div className="metric-label">Post-freeze net growth</div>
          <div className="metric-value" data-testid="growth-hours-value">
            {kpis ? `${kpis.growth_hours >= 0 ? "+" : ""}${kpis.growth_hours.toLocaleString()} hrs` : "0 hrs"}
          </div>
          <div className="metric-note">
            {kpis
              ? `${kpis.growth_pct_of_baseline.toFixed(1)}% of baseline · Mandatory ${kpis.mandatory_growth_hours >= 0 ? "+" : ""}${kpis.mandatory_growth_hours.toLocaleString()} / Disc. ${kpis.discretionary_growth_hours >= 0 ? "+" : ""}${kpis.discretionary_growth_hours.toLocaleString()}`
              : "Approved changes only"}
          </div>
        </div>

        <div>
          <div className="metric-label">Write-through switch</div>
          <div className={`metric-value ${kpis?.twin_write_through ? "tone-code" : "tone-ai"}`}>
            {kpis?.twin_write_through ? "On (demo delegated raise)" : "Off (read-only fallback)"}
          </div>
          <div className="metric-note">
            {kpis
              ? `${kpis.adds_approved} adds, ${kpis.deletes_approved} deletes approved, ${kpis.rejected_count} rejected, ${kpis.pending_count} pending`
              : "IMPACT Web remains system of record"}
          </div>
        </div>
      </div>

      {/* Post-freeze Change Log */}
      <section className="surface-panel" style={{ marginBottom: "1rem" }}>
        <h2 className="panel-heading">
          Post-freeze change log ({kpis?.all_change_requests.length ?? 0} requests mirrored from IMPACT Web)
        </h2>
        {!kpis || kpis.all_change_requests.length === 0 ? (
          <p className="tone-muted" style={{ margin: 0, fontSize: "var(--text-sm)" }}>
            No post-freeze change requests recorded yet. Freeze in IMPACT Web, run the late-scope simulation, or raise a change request from the Twin.
          </p>
        ) : (
          <div className="table-wrap" style={{ maxHeight: "340px", overflowY: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Change ID</th>
                  <th>Type</th>
                  <th>Title</th>
                  <th>Source group</th>
                  <th>Provenance</th>
                  <th>Status</th>
                  <th className="num">Hours delta</th>
                </tr>
              </thead>
              <tbody>
                {kpis.all_change_requests.map((cr) => (
                  <tr key={cr.id}>
                    <td className="mono tone-code">{cr.id}</td>
                    <td className="mono">
                      {cr.change_type} {cr.mandatory ? "(mandatory)" : "(discretionary)"}
                    </td>
                    <td>
                      <div>{cr.title}</div>
                      <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-muted)" }}>{cr.reason}</div>
                    </td>
                    <td>{(cr.source_group ?? "operations").replace(/_/g, " ")}</td>
                    <td className={cr.raised_via === "twin" ? "tone-code" : "tone-muted"}>
                      {cr.raised_via === "twin"
                        ? `Raised from twin (${cr.raised_by_name ?? "planner"})`
                        : `IMPACT Web (${cr.raised_by_name ?? "user"})`}
                    </td>
                    <td
                      className={
                        cr.status === "approved"
                          ? "tone-ok"
                          : cr.status === "rejected"
                            ? "tone-danger"
                            : "tone-ai"
                      }
                    >
                      {cr.status}
                    </td>
                    <td className="num mono">
                      {cr.hours_delta >= 0 ? "+" : ""}
                      {cr.hours_delta.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Value Panel (Unvalidated Assumptions) + Measured Counts */}
      {valuePanel && (
        <div className="split-even" style={{ marginBottom: "1rem" }}>
          <section className="surface-panel panel-ai">
            <h2 className="panel-heading">Value panel (unvalidated brief assumptions)</h2>
            <div className="notice warn">{valuePanel.assumption_notice}</div>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Lever</th>
                    <th className="num">Default per TAR</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {valuePanel.levers.map((lv) => (
                    <tr key={lv.lever}>
                      <td>{lv.lever}</td>
                      <td className="num mono">{lv.display_amount}</td>
                      <td className="tone-ai">Unvalidated assumption</td>
                    </tr>
                  ))}
                  <tr>
                    <td>
                      <strong>Total</strong>
                    </td>
                    <td className="num mono">
                      <strong>{valuePanel.total_display}</strong>
                    </td>
                    <td className="tone-ai">
                      <strong>Unvalidated assumption</strong>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section className="surface-panel panel-code">
            <h2 className="panel-heading">Measured in Unit 200 demo dataset</h2>
            <p style={{ margin: "0 0 0.75rem", fontSize: "var(--text-sm)", color: "var(--ink-secondary)" }}>
              Counts computed directly from the synthetic Unit 200 plant graph, clusters, and synced IMPACT Web scope.
            </p>
            <dl className="kv-list">
              <dt>Tag match rate</dt>
              <dd className="mono">{siteRatePct}</dd>
              <dt>Hours bundled</dt>
              <dd className="mono">{valuePanel.measured_in_demo.hours_bundled.toLocaleString()} shared hrs</dd>
              <dt>Duplicate pairs</dt>
              <dd className="mono">
                {valuePanel.measured_in_demo.duplicate_pair_count} pairs (
                {valuePanel.measured_in_demo.duplicate_hours_flagged.toLocaleString()} overlap hrs)
              </dd>
              <dt>Baseline hours</dt>
              <dd className="mono">{valuePanel.measured_in_demo.baseline_hours.toLocaleString()} hrs</dd>
              <dt>Growth after freeze</dt>
              <dd className="mono">
                {valuePanel.measured_in_demo.post_freeze_growth_hours >= 0 ? "+" : ""}
                {valuePanel.measured_in_demo.post_freeze_growth_hours.toLocaleString()} hrs
              </dd>
            </dl>
          </section>
        </div>
      )}

      {/* Reserved 4.1 and 4.2 Schema Slots Only */}
      <section className="surface-panel">
        <h2 className="panel-heading">Reserved wave-2 schema slots (release one scope boundary)</h2>
        <div className="split-even">
          <div>
            <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>4.1 Work packages</div>
            <p style={{ margin: 0, fontSize: "var(--text-sm)", color: "var(--ink-secondary)" }}>
              Schema slots reserved on the same graph (<span className="mono">WorkPackage</span>,{" "}
              <span className="mono">Standard</span>, <span className="mono">Material</span>,{" "}
              <span className="mono">Redline</span>). Status: <span className="mono">schema_slot_only (null)</span>.
            </p>
          </div>
          <div>
            <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>4.2 Execution plan and logistics</div>
            <p style={{ margin: 0, fontSize: "var(--text-sm)", color: "var(--ink-secondary)" }}>
              Schema slots reserved on the same graph (<span className="mono">Activity</span>,{" "}
              <span className="mono">LogisticsObject</span>, <span className="mono">Permit</span>). Status:{" "}
              <span className="mono">schema_slot_only (null)</span>.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
};
