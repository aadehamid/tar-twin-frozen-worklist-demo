import React, { useEffect, useMemo, useRef } from "react";
import { select } from "d3-selection";
import { zoom, zoomIdentity, type ZoomBehavior } from "d3-zoom";
import type {
  ClustersPayload,
  CutLineResult,
  EquipmentDetail,
  PlotLayer,
  PlotPlanData,
  ScopeItem,
} from "../types";

interface PlotPlanViewProps {
  plotPlan: PlotPlanData | null;
  equipment: EquipmentDetail[];
  scopeItems: ScopeItem[];
  clusters: ClustersPayload | null;
  cutLine: CutLineResult | null;
  layer: PlotLayer;
  onLayerChange: (layer: PlotLayer) => void;
  selectedTag: string | null;
  highlightedTags: string[];
  onSelectTag: (tag: string) => void;
  onOpenPid: (sheetNo: string, tag: string) => void;
  onOpenGraph: (tag: string) => void;
  onOpenTrace: (requestId: string) => void;
  onRaiseChangeRequest: (tag: string) => void;
}

const SCALE = 8; // 120m x 80m -> 960 x 640 SVG units

export const PlotPlanView: React.FC<PlotPlanViewProps> = ({
  plotPlan,
  equipment,
  scopeItems,
  clusters,
  cutLine,
  layer,
  onLayerChange,
  selectedTag,
  highlightedTags,
  onSelectTag,
  onOpenPid,
  onOpenGraph,
  onOpenTrace,
  onRaiseChangeRequest,
}) => {
  const svgRef = useRef<SVGSVGElement>(null);
  const gRef = useRef<SVGGElement>(null);
  const zoomBehaviorRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);

  useEffect(() => {
    if (!svgRef.current || !gRef.current) return;
    const svgSel = select(svgRef.current);
    const gSel = select(gRef.current);
    const zb = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.65, 4])
      .on("zoom", (event) => {
        gSel.attr("transform", event.transform.toString());
      });
    zoomBehaviorRef.current = zb;
    svgSel.call(zb);
    return () => {
      svgSel.on(".zoom", null);
    };
  }, [plotPlan]);

  const handleZoom = (factor: number) => {
    if (!svgRef.current || !zoomBehaviorRef.current) return;
    select(svgRef.current).call(zoomBehaviorRef.current.scaleBy, factor);
  };

  const handleReset = () => {
    if (!svgRef.current || !zoomBehaviorRef.current) return;
    select(svgRef.current).call(zoomBehaviorRef.current.transform, zoomIdentity);
  };

  const eqByTag = useMemo(() => {
    const m = new Map<string, EquipmentDetail>();
    for (const e of equipment) m.set(e.tag, e);
    return m;
  }, [equipment]);

  const jobsByTag = useMemo(() => {
    const m = new Map<string, ScopeItem[]>();
    for (const it of scopeItems) {
      const targetTag = it.resolved_tag ?? (it.match_status === "needs_review" ? it.proposal?.tag ?? null : null);
      if (targetTag) {
        const list = m.get(targetTag) ?? [];
        list.push(it);
        m.set(targetTag, list);
      }
    }
    return m;
  }, [scopeItems]);

  const clusterTags = useMemo(() => {
    const iso = new Set<string>();
    const scaf = new Set<string>();
    const acc = new Set<string>();
    if (clusters) {
      for (const c of clusters.isolation_clusters) c.equipment_tags.forEach((t) => iso.add(t));
      for (const c of clusters.scaffold_clusters) c.equipment_tags.forEach((t) => scaf.add(t));
      for (const c of clusters.access_clusters) c.equipment_tags.forEach((t) => acc.add(t));
    }
    return { iso, scaf, acc };
  }, [clusters]);

  const cutLineSets = useMemo(() => {
    const above = new Set(cutLine?.above_ids ?? []);
    const below = new Set(cutLine?.below_ids ?? []);
    return { above, below };
  }, [cutLine]);

  const highlightSet = useMemo(() => new Set(highlightedTags), [highlightedTags]);

  const colorForTag = (tag: string): { fill: string; stroke: string } => {
    const jobs = jobsByTag.get(tag) ?? [];
    if (highlightSet.has(tag)) {
      return { fill: "rgba(56, 189, 248, 0.35)", stroke: "#38bdf8" };
    }
    if (layer === "match_status") {
      if (jobs.length === 0) return { fill: "#162338", stroke: "#3d5578" };
      const hasReview = jobs.some((j) => j.match_status === "needs_review");
      if (hasReview) return { fill: "rgba(245, 158, 11, 0.25)", stroke: "#f59e0b" };
      return { fill: "rgba(52, 211, 153, 0.24)", stroke: "#34d399" };
    }
    if (layer === "clusters") {
      if (clusterTags.scaf.has(tag)) return { fill: "rgba(245, 158, 11, 0.28)", stroke: "#f59e0b" };
      if (clusterTags.acc.has(tag)) return { fill: "rgba(56, 189, 248, 0.26)", stroke: "#38bdf8" };
      if (clusterTags.iso.has(tag)) return { fill: "rgba(52, 211, 153, 0.22)", stroke: "#34d399" };
      return { fill: "#162338", stroke: "#3d5578" };
    }
    if (layer === "cut_line") {
      const hasBelow = jobs.some((j) => cutLineSets.below.has(j.request_id));
      const hasAbove = jobs.some((j) => cutLineSets.above.has(j.request_id));
      if (hasBelow && !hasAbove) return { fill: "rgba(248, 113, 113, 0.28)", stroke: "#f87171" };
      if (hasBelow && hasAbove) return { fill: "rgba(245, 158, 11, 0.28)", stroke: "#f59e0b" };
      if (hasAbove) return { fill: "rgba(52, 211, 153, 0.26)", stroke: "#34d399" };
      return { fill: "#162338", stroke: "#3d5578" };
    }
    // post-freeze changes
    const hasLate = jobs.some((j) => j.work_type_label === "LateScopeAdd" || j.version > 1);
    if (hasLate) return { fill: "rgba(245, 158, 11, 0.30)", stroke: "#f59e0b" };
    return { fill: "#162338", stroke: "#3d5578" };
  };

  const activeEq = selectedTag ? eqByTag.get(selectedTag) ?? null : equipment[0] ?? null;
  const activeJobs = activeEq ? jobsByTag.get(activeEq.tag) ?? [] : [];

  if (!plotPlan) {
    return <div className="surface-panel">Loading Unit 200 plot plan...</div>;
  }

  const widthPx = plotPlan.width_m * SCALE;
  const heightPx = plotPlan.height_m * SCALE;
  const [rackY0, rackY1] = plotPlan.pipe_rack_y_range_m;

  return (
    <div>
      <div className="view-header">
        <div>
          <h1 className="view-title">Unit 200 plot plan</h1>
          <p className="view-subtitle">
            Diesel hydrotreater 2D layout (120 m by 80 m) showing all 32 major equipment tags, seven process areas, and synced turnaround scope.
          </p>
        </div>
        <div className="segmented" role="radiogroup" aria-label="Plot plan overlay layer">
          {(
            [
              ["match_status", "Match status"],
              ["clusters", "Clusters"],
              ["cut_line", "Cut line"],
              ["changes", "Post-freeze changes"],
            ] as [PlotLayer, string][]
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="radio"
              aria-checked={layer === id}
              onClick={() => onLayerChange(id)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="split-workspace">
        <div className="plot-canvas-wrap">
          <div className="plot-toolbar">
            <div className="plot-legend">
              {layer === "match_status" && (
                <>
                  <span className="legend-item">
                    <span className="legend-swatch" style={{ background: "#34d399" }} /> Accepted scope
                  </span>
                  <span className="legend-item">
                    <span className="legend-swatch" style={{ background: "#f59e0b" }} /> Needs review
                  </span>
                  <span className="legend-item">
                    <span className="legend-swatch" style={{ background: "#38bdf8" }} /> Explore highlight
                  </span>
                </>
              )}
              {layer === "clusters" && (
                <>
                  <span className="legend-item">
                    <span className="legend-swatch" style={{ background: "#f59e0b" }} /> Scaffold cluster
                  </span>
                  <span className="legend-item">
                    <span className="legend-swatch" style={{ background: "#38bdf8" }} /> Access cluster
                  </span>
                  <span className="legend-item">
                    <span className="legend-swatch" style={{ background: "#34d399" }} /> Isolation envelope
                  </span>
                </>
              )}
              {layer === "cut_line" && (
                <>
                  <span className="legend-item">
                    <span className="legend-swatch" style={{ background: "#34d399" }} /> Above cut line
                  </span>
                  <span className="legend-item">
                    <span className="legend-swatch" style={{ background: "#f59e0b" }} /> Mixed above/below
                  </span>
                  <span className="legend-item">
                    <span className="legend-swatch" style={{ background: "#f87171" }} /> Below cut line
                  </span>
                </>
              )}
              {layer === "changes" && (
                <>
                  <span className="legend-item">
                    <span className="legend-swatch" style={{ background: "#f59e0b" }} /> Post-freeze / revised scope
                  </span>
                  <span className="legend-item">
                    <span className="legend-swatch" style={{ background: "#3d5578" }} /> Unchanged baseline
                  </span>
                </>
              )}
            </div>
            <div style={{ display: "flex", gap: "0.35rem" }}>
              <button type="button" className="btn-subtle" onClick={() => handleZoom(1.25)}>
                Zoom in
              </button>
              <button type="button" className="btn-subtle" onClick={() => handleZoom(0.8)}>
                Zoom out
              </button>
              <button type="button" className="btn-subtle" onClick={handleReset}>
                Reset view
              </button>
            </div>
          </div>

          <svg
            ref={svgRef}
            className="plot-svg"
            viewBox={`0 0 ${widthPx} ${heightPx}`}
            aria-label="Unit 200 2D plot plan"
          >
            <g ref={gRef}>
              {/* Engineering grid */}
              <rect x={0} y={0} width={widthPx} height={heightPx} fill="#08101c" />
              {Array.from({ length: 13 }).map((_, i) => (
                <line
                  key={`vx-${i}`}
                  x1={i * 10 * SCALE}
                  y1={0}
                  x2={i * 10 * SCALE}
                  y2={heightPx}
                  stroke="#132138"
                  strokeWidth={1}
                />
              ))}
              {Array.from({ length: 9 }).map((_, i) => (
                <line
                  key={`hy-${i}`}
                  x1={0}
                  y1={i * 10 * SCALE}
                  x2={widthPx}
                  y2={i * 10 * SCALE}
                  stroke="#132138"
                  strokeWidth={1}
                />
              ))}

              {/* Central pipe rack */}
              <rect
                x={8}
                y={rackY0 * SCALE}
                width={widthPx - 16}
                height={(rackY1 - rackY0) * SCALE}
                fill="#111d30"
                stroke="#294063"
                strokeDasharray="6 4"
              />
              <text
                x={widthPx / 2}
                y={((rackY0 + rackY1) / 2) * SCALE + 4}
                textAnchor="middle"
                fill="#7f95b2"
                fontSize={12}
                fontFamily="JetBrains Mono, monospace"
              >
                MAIN PIPE RACK (Y = 36m TO 44m)
              </text>

              {/* 7 Process Areas */}
              {plotPlan.areas.map((a) => (
                <g key={a.code}>
                  <rect
                    x={a.x_min_m * SCALE}
                    y={a.y_min_m * SCALE}
                    width={(a.x_max_m - a.x_min_m) * SCALE}
                    height={(a.y_max_m - a.y_min_m) * SCALE}
                    fill="rgba(18, 32, 54, 0.55)"
                    stroke="#263c5e"
                    strokeWidth={1.2}
                    rx={4}
                  />
                  <text
                    x={a.x_min_m * SCALE + 8}
                    y={a.y_min_m * SCALE + 16}
                    fill="#9fb3cc"
                    fontSize={12}
                    fontWeight={600}
                  >
                    {a.code} {a.name}
                  </text>
                </g>
              ))}

              {/* 32 Major Equipment Footprints */}
              {plotPlan.equipment.map((eq) => {
                const w = Math.max(50, eq.width_m * SCALE);
                const h = Math.max(24, eq.depth_m * SCALE);
                const x = eq.x_m * SCALE - w / 2;
                const y = eq.y_m * SCALE - h / 2;
                const isSelected = activeEq?.tag === eq.tag;
                const isHighlighted = highlightSet.has(eq.tag);
                const colors = colorForTag(eq.tag);
                const jobCount = (jobsByTag.get(eq.tag) ?? []).length;

                return (
                  <g
                    key={eq.tag}
                    data-tag={eq.tag}
                    role="button"
                    tabIndex={0}
                    aria-label={`Equipment ${eq.tag}, ${jobCount} matched jobs`}
                    style={{ cursor: "pointer" }}
                    onClick={() => onSelectTag(eq.tag)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onSelectTag(eq.tag);
                      }
                    }}
                  >
                    {(isSelected || isHighlighted) && (
                      <rect
                        x={x - 4}
                        y={y - 4}
                        width={w + 8}
                        height={h + 8}
                        fill="none"
                        stroke={isSelected ? "#edf3fb" : "#38bdf8"}
                        strokeWidth={2}
                        rx={5}
                      />
                    )}
                    <rect
                      x={x}
                      y={y}
                      width={w}
                      height={h}
                      fill={colors.fill}
                      stroke={colors.stroke}
                      strokeWidth={1.6}
                      rx={3}
                    />
                    <text
                      x={x + w / 2}
                      y={y + h / 2 + 4}
                      textAnchor="middle"
                      fill="#edf3fb"
                      fontSize={10.5}
                      fontFamily="JetBrains Mono, monospace"
                      fontWeight={600}
                    >
                      {eq.tag}
                    </text>
                    {jobCount > 0 && (
                      <g transform={`translate(${x + w - 2}, ${y - 2})`}>
                        <circle r={9} fill="#0c4a6e" stroke="#38bdf8" strokeWidth={1.2} />
                        <text
                          y={3.5}
                          textAnchor="middle"
                          fill="#f0f9ff"
                          fontSize={9.5}
                          fontWeight={700}
                        >
                          {jobCount}
                        </text>
                      </g>
                    )}
                  </g>
                );
              })}
            </g>
          </svg>
        </div>

        {/* Right-hand Equipment Inspector */}
        <aside className="surface-panel" aria-label="Selected equipment details">
          {activeEq ? (
            <>
              <h2 className="view-title" style={{ marginBottom: "0.2rem" }}>
                {activeEq.tag}
              </h2>
              <p style={{ margin: "0 0 0.8rem", color: "var(--ink-secondary)", fontSize: "var(--text-sm)" }}>
                {activeEq.description}
              </p>

              <dl className="kv-list">
                <dt>Class</dt>
                <dd>{activeEq.equipment_class}</dd>
                <dt>Area</dt>
                <dd className="mono">{activeEq.area}</dd>
                <dt>P&ID sheet</dt>
                <dd className="mono">{activeEq.sheet}</dd>
                <dt>Envelopes</dt>
                <dd className="mono">{activeEq.envelopes.join(", ") || "None"}</dd>
                <dt>Position</dt>
                <dd className="mono">
                  {activeEq.plot_position
                    ? `x ${activeEq.plot_position.x ?? activeEq.plot_position.x_m ?? 0} m, y ${activeEq.plot_position.y ?? activeEq.plot_position.y_m ?? 0} m, el ${activeEq.plot_position.elevation ?? activeEq.plot_position.elevation_m ?? 0} m`
                    : "n/a"}
                </dd>
                <dt>Nozzles</dt>
                <dd className="mono">{activeEq.nozzles.map((n) => n.sub_tag).join(", ") || "None"}</dd>
              </dl>

              <div style={{ display: "flex", gap: "0.45rem", flexWrap: "wrap", marginTop: "0.85rem" }}>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={() => onOpenPid(activeEq.sheet, activeEq.tag)}
                >
                  Open on P&ID
                </button>
                <button type="button" onClick={() => onOpenGraph(activeEq.tag)}>
                  Open in Relate graph
                </button>
                <button type="button" onClick={() => onRaiseChangeRequest(activeEq.tag)}>
                  Raise change request
                </button>
              </div>

              <hr className="section-divider" />

              <h3 className="panel-heading">
                Matched work requests ({activeJobs.length})
              </h3>
              {activeJobs.length === 0 ? (
                <p style={{ fontSize: "var(--text-sm)", color: "var(--ink-muted)", margin: 0 }}>
                  No accepted scope items resolved to {activeEq.tag} yet.
                </p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "0.45rem", maxHeight: "260px", overflowY: "auto" }}>
                  {activeJobs.map((job) => (
                    <button
                      key={job.request_id}
                      type="button"
                      className="explore-row-btn"
                      onClick={() => onOpenTrace(job.request_id)}
                    >
                      <span className="explore-row-id">{job.request_id}</span>
                      <span className="explore-row-desc">{job.title}</span>
                      <span className="explore-row-desc" style={{ color: "var(--ink-muted)" }}>
                        RIPT {job.ript_score} · {job.estimate_hours.toLocaleString()} hrs · ${job.estimate_cost_usd.toLocaleString()}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </>
          ) : (
            <p className="tone-muted">Select an equipment footprint on the plot plan to inspect its scope and isolation.</p>
          )}
        </aside>
      </div>
    </div>
  );
};
