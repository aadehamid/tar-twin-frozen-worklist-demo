import React from "react";
import type { DebriefReport } from "../types";

interface DebriefViewProps {
  debrief: DebriefReport | null;
  onRefresh: () => Promise<void>;
}

function fmtUsd(n: number): string {
  return `$${Math.round(n).toLocaleString("en-US")}`;
}

function fmtStep(step: string): string {
  if (step === "drb") return "DRB";
  if (step.startsWith("t_minus_")) return `T-${step.slice("t_minus_".length)}`;
  return step.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export const DebriefView: React.FC<DebriefViewProps> = ({ debrief, onRefresh }) => {
  if (!debrief) {
    return (
      <div>
        <div className="view-header">
          <div>
            <h1 className="view-title">Exercise debrief</h1>
            <p className="view-subtitle">
              Loading debrief metrics from the synchronized work list and IMPACT Web decision history.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const latestRate =
    debrief.current_match_rate !== null ? `${(debrief.current_match_rate * 100).toFixed(1)}%` : "n/a";
  const gr = debrief.growth_after_freeze;
  const sc = debrief.shared_costs;

  return (
    <div>
      <div className="view-header">
        <div>
          <h1 className="view-title">Exercise debrief</h1>
          <p className="view-subtitle">
            Exercise {debrief.exercise_id} ({debrief.mode} mode, {debrief.starting_fixture} fixture, epoch{" "}
            {debrief.epoch}, clock at {fmtStep(debrief.clock_step)}).
          </p>
        </div>
        <button type="button" className="btn-subtle" onClick={() => void onRefresh()}>
          Refresh debrief
        </button>
      </div>

      <div className="metrics-strip">
        <div>
          <div className="metric-label">Current match rate</div>
          <div className="metric-value tone-code">{latestRate}</div>
          <div className="metric-note">
            {debrief.frozen
              ? debrief.ready_for_use
                ? "Frozen baseline ready for 3.1 use"
                : "Frozen below 95% match gate"
              : "Work list not frozen yet"}
          </div>
        </div>
        <div>
          <div className="metric-label">Shared hours bundled</div>
          <div className="metric-value tone-ok">{sc.bundled_hours.toLocaleString("en-US")} hrs</div>
          <div className="metric-note">
            {sc.bundled_clusters.length} bundled, {sc.missed_clusters.length} missed
          </div>
        </div>
        <div>
          <div className="metric-label">Approved growth after freeze</div>
          <div className={`metric-value ${gr.approved_growth_hours > 0 ? "tone-ai" : "tone-ok"}`}>
            {gr.approved_growth_hours >= 0 ? "+" : ""}
            {gr.approved_growth_hours.toLocaleString("en-US")} hrs
          </div>
          <div className="metric-note">
            Mandatory {gr.mandatory_growth_hours >= 0 ? "+" : ""}
            {gr.mandatory_growth_hours} hrs, discretionary {gr.discretionary_growth_hours >= 0 ? "+" : ""}
            {gr.discretionary_growth_hours} hrs
          </div>
        </div>
        <div>
          <div className="metric-label">Pending and rejected changes</div>
          <div className="metric-value">
            {gr.pending_count} / {gr.rejected_count}
          </div>
          <div className="metric-note">Excluded from live hours and growth totals</div>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
          gap: "1rem",
          marginBottom: "1rem",
        }}
      >
        <section className="surface-panel">
          <h2 className="panel-heading">Match rate over time</h2>
          <p style={{ margin: "0 0 0.7rem", color: "var(--ink-secondary)", fontSize: "var(--text-sm)" }}>
            Active items exclude screened-out, rejected, deferred, and deleted scope. Steps with zero active items show
            n/a.
          </p>
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Clock step</th>
                  <th>Active items</th>
                  <th>Matched</th>
                  <th>Match rate</th>
                </tr>
              </thead>
              <tbody>
                {debrief.match_rate_over_time.map((pt, idx) => (
                  <tr key={`${pt.clock_step}-${idx}`}>
                    <td>{fmtStep(pt.clock_step)}</td>
                    <td className="mono">{pt.total_active}</td>
                    <td className="mono">{pt.accepted_count}</td>
                    <td className="mono">{pt.display}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="surface-panel">
          <h2 className="panel-heading">Shared costs bundled vs missed</h2>
          <p style={{ margin: "0 0 0.7rem", color: "var(--ink-secondary)", fontSize: "var(--text-sm)" }}>
            Reference:{" "}
            {sc.answer_key_source === "planted_answer_key"
              ? "planted Unit 200 cluster answer key"
              : "computed reference clusters from the final list"}
            . Bundled savings: {fmtUsd(sc.shared_cost_saved_usd)}.
          </p>
          {sc.missed_clusters.length === 0 ? (
            <p style={{ margin: 0, fontSize: "var(--text-sm)", color: "var(--accent-ok)" }}>
              All reference shared-setup clusters retained two or more bundled active jobs.
            </p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Missed cluster</th>
                    <th>Shared hours</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {sc.missed_clusters.slice(0, 8).map((mc) => (
                    <tr key={mc.id}>
                      <td>{mc.name}</td>
                      <td className="mono">{mc.shared_hours} hrs</td>
                      <td>{mc.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      <section className="surface-panel" style={{ marginBottom: "1rem" }}>
        <h2 className="panel-heading">Saved cut-line options vs DRB decisions</h2>
        {debrief.cut_line_vs_drb.length === 0 ? (
          <p style={{ margin: 0, color: "var(--ink-secondary)", fontSize: "var(--text-sm)" }}>
            No cut-line options were saved in this exercise. Save an option in Clusters and cut line to compare it
            against DRB outcomes.
          </p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Option name</th>
                  <th>Budget</th>
                  <th>Feasible</th>
                  <th>Above line</th>
                  <th>DRB accepted</th>
                  <th>Accepted from below</th>
                </tr>
              </thead>
              <tbody>
                {debrief.cut_line_vs_drb.map((run) => (
                  <tr key={run.id}>
                    <td>{run.name}</td>
                    <td className="mono">{fmtUsd(run.budget_usd)}</td>
                    <td className={run.feasible ? "tone-ok" : "tone-danger"}>
                      {run.feasible ? "Feasible" : `Shortfall ${fmtUsd(run.shortfall_usd)}`}
                    </td>
                    <td className="mono">{run.above_count}</td>
                    <td className="mono">{run.drb_accepted_total}</td>
                    <td className="mono">{run.accepted_from_below_line.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {gr.material_changes.length > 0 && (
        <section className="surface-panel" style={{ marginBottom: "1rem" }}>
          <h2 className="panel-heading">Material post-freeze changes (10% or more of frozen item hours)</h2>
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Work request</th>
                  <th>Frozen hours</th>
                  <th>Cumulative delta</th>
                  <th>Share of frozen item</th>
                </tr>
              </thead>
              <tbody>
                {gr.material_changes.map((mc) => (
                  <tr key={mc.request_id}>
                    <td className="mono">{mc.request_id}</td>
                    <td className="mono">{mc.frozen_hours} hrs</td>
                    <td className="mono">
                      {mc.cumulative_hours_delta >= 0 ? "+" : ""}
                      {mc.cumulative_hours_delta} hrs
                    </td>
                    <td className="mono">{mc.pct_of_frozen_hours}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
          gap: "1rem",
        }}
      >
        <section className="surface-panel">
          <h2 className="panel-heading">Decision timeline</h2>
          {debrief.decision_timeline.length === 0 ? (
            <p style={{ margin: 0, color: "var(--ink-secondary)", fontSize: "var(--text-sm)" }}>
              No clock moves, injects, reviews, or change decisions recorded yet.
            </p>
          ) : (
            <div style={{ overflowX: "auto", maxHeight: "340px", overflowY: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Actor</th>
                    <th>Event</th>
                    <th>Summary</th>
                  </tr>
                </thead>
                <tbody>
                  {debrief.decision_timeline.slice(0, 40).map((ev, idx) => (
                    <tr key={`${ev.at}-${idx}`}>
                      <td>{ev.actor}</td>
                      <td>{fmtStep(ev.kind)}</td>
                      <td>{ev.summary}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="surface-panel">
          <h2 className="panel-heading">Facilitator talking points</h2>
          <ul
            style={{
              margin: "0 0 1rem",
              paddingLeft: "1.15rem",
              display: "flex",
              flexDirection: "column",
              gap: "0.45rem",
            }}
          >
            {debrief.talking_points.map((pt, idx) => (
              <li key={idx} style={{ fontSize: "var(--text-body)", color: "var(--ink-primary)", lineHeight: 1.45 }}>
                {pt}
              </li>
            ))}
          </ul>

          <div style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: "0.85rem" }}>
            <h3 style={{ margin: "0 0 0.3rem", fontSize: "var(--text-body)", fontWeight: 600 }}>
              Focus-area brief value assumptions (unvalidated)
            </h3>
            <p style={{ margin: "0 0 0.6rem", fontSize: "var(--text-sm)", color: "var(--ink-secondary)" }}>
              {debrief.value_assumptions.assumption_notice}
            </p>
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Value lever</th>
                    <th>Unvalidated assumption</th>
                  </tr>
                </thead>
                <tbody>
                  {debrief.value_assumptions.levers.map((lv) => (
                    <tr key={lv.lever}>
                      <td>{lv.lever}</td>
                      <td className="mono">{lv.display_amount}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};
