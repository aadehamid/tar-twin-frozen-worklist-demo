import React, { useEffect, useMemo, useRef, useState } from "react";
import { fetchSvgText } from "../api";
import type { EquipmentDetail, IsolationEnvelope, PidSheet } from "../types";

interface PidViewerProps {
  sheets: PidSheet[];
  equipment: EquipmentDetail[];
  envelopes: IsolationEnvelope[];
  activeSheet: string;
  onSelectSheet: (sheetNo: string) => void;
  highlightedTags: string[];
  activeEnvelopeId: string | null;
  onSelectEquipment: (tag: string, sheetNo: string) => void;
  onSelectEnvelope: (envId: string | null) => void;
  onOpenGraphForEnvelope: (envId: string) => void;
}

function tagToSvgId(tag: string): string {
  return tag.replace(/-/g, "_");
}

export const PidViewer: React.FC<PidViewerProps> = ({
  sheets,
  equipment,
  envelopes,
  activeSheet,
  onSelectSheet,
  highlightedTags,
  activeEnvelopeId,
  onSelectEquipment,
  onSelectEnvelope,
  onOpenGraphForEnvelope,
}) => {
  const [svgMarkup, setSvgMarkup] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [zoomPct, setZoomPct] = useState<number>(100);
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchSvgText(activeSheet)
      .then((txt) => {
        if (!cancelled) {
          setSvgMarkup(txt);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeSheet]);

  const activeEnvelope = useMemo(
    () => envelopes.find((e) => e.id === activeEnvelopeId) ?? null,
    [envelopes, activeEnvelopeId]
  );

  // Programmatically highlight selected equipment and boundary valves in the loaded DEXPI SVG
  useEffect(() => {
    const root = hostRef.current;
    if (!root || !svgMarkup) return;

    root.querySelectorAll(".pid-hl-equipment").forEach((el) => el.classList.remove("pid-hl-equipment"));
    root.querySelectorAll(".pid-hl-valve").forEach((el) => el.classList.remove("pid-hl-valve"));

    const eqIds = new Set<string>(highlightedTags.map(tagToSvgId));
    if (activeEnvelope) {
      activeEnvelope.equipment_tags.forEach((t) => eqIds.add(tagToSvgId(t)));
    }
    eqIds.forEach((id) => {
      const el = root.querySelector(`g#${CSS.escape(id)}`);
      if (el) el.classList.add("pid-hl-equipment");
    });

    if (activeEnvelope) {
      activeEnvelope.boundary_valves.forEach((v) => {
        const el = root.querySelector(`g#${CSS.escape(tagToSvgId(v))}`);
        if (el) el.classList.add("pid-hl-valve");
      });
    }
  }, [svgMarkup, highlightedTags, activeEnvelope]);

  const sheetEquipment = useMemo(
    () => equipment.filter((e) => e.sheet === activeSheet),
    [equipment, activeSheet]
  );

  const sheetEnvelopes = useMemo(() => {
    const tagsOnSheet = new Set(sheetEquipment.map((e) => e.tag));
    return envelopes.filter((env) => env.equipment_tags.some((t) => tagsOnSheet.has(t)));
  }, [sheetEquipment, envelopes]);

  return (
    <div>
      <div className="view-header">
        <div>
          <h1 className="view-title">P&ID sheet viewer</h1>
          <p className="view-subtitle">
            DEXPI 2.0.1 process diagrams rendered with pyDEXPI. Selected equipment highlights in cyan; active envelope boundary valves highlight in amber.
          </p>
        </div>
        <div className="segmented" role="tablist" aria-label="P&ID sheets">
          {sheets.map((s) => (
            <button
              key={s.number}
              type="button"
              role="tab"
              aria-selected={activeSheet === s.number}
              onClick={() => onSelectSheet(s.number)}
            >
              {s.number}
            </button>
          ))}
        </div>
      </div>

      <div className="split-workspace">
        <div>
          <div className="plot-toolbar" style={{ borderRadius: "6px 6px 0 0", border: "1px solid var(--border-subtle)", borderBottom: "none" }}>
            <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-secondary)" }}>
              Sheet <span className="mono tone-code">{activeSheet}</span>
              {activeEnvelope ? (
                <>
                  {" "}
                  · Highlighting envelope <span className="mono tone-ai">{activeEnvelope.id}</span> (
                  {activeEnvelope.boundary_valve_count} boundary valves)
                </>
              ) : null}
            </div>
            <div style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
              <button type="button" className="btn-subtle" onClick={() => setZoomPct((z) => Math.max(70, z - 15))}>
                -
              </button>
              <span className="mono" style={{ fontSize: "var(--text-sm)", minWidth: "48px", textAlign: "center" }}>
                {zoomPct}%
              </span>
              <button type="button" className="btn-subtle" onClick={() => setZoomPct((z) => Math.min(200, z + 15))}>
                +
              </button>
              <button type="button" className="btn-subtle" onClick={() => setZoomPct(100)}>
                Fit
              </button>
            </div>
          </div>

          <div className="pid-viewport">
            {loading && <p style={{ padding: "1.5rem", color: "#334155" }}>Loading {activeSheet}...</p>}
            {error && (
              <div className="notice err" style={{ margin: "1rem" }}>
                {error}
              </div>
            )}
            <div
              ref={hostRef}
              className="pid-svg-host"
              style={{ width: `${zoomPct}%` }}
              dangerouslySetInnerHTML={{ __html: svgMarkup }}
            />
          </div>
        </div>

        <aside className="surface-panel" aria-label="Sheet equipment and isolation envelopes">
          <h2 className="panel-heading">Equipment on {activeSheet}</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem", marginBottom: "1rem" }}>
            {sheetEquipment.map((eq) => {
              const isActive = highlightedTags.includes(eq.tag);
              return (
                <button
                  key={eq.tag}
                  type="button"
                  className="explore-row-btn"
                  style={isActive ? { borderColor: "var(--accent-code)", background: "var(--accent-code-dim)" } : undefined}
                  onClick={() => onSelectEquipment(eq.tag, eq.sheet)}
                >
                  <span className="explore-row-id">{eq.tag}</span>
                  <span className="explore-row-desc">{eq.description}</span>
                </button>
              );
            })}
          </div>

          <hr className="section-divider" />

          <h2 className="panel-heading">Isolation envelopes on sheet</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.45rem" }}>
            {sheetEnvelopes.map((env) => {
              const selected = activeEnvelopeId === env.id;
              return (
                <div
                  key={env.id}
                  style={{
                    padding: "0.6rem 0.7rem",
                    background: selected ? "var(--accent-ai-dim)" : "var(--bg-inset)",
                    border: `1px solid ${selected ? "var(--accent-ai)" : "var(--border-subtle)"}`,
                    borderRadius: "var(--radius-sm)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
                    <span className="mono tone-ai" style={{ fontWeight: 600 }}>
                      {env.id}
                    </span>
                    <button
                      type="button"
                      className="btn-subtle"
                      style={{ padding: "0.2rem 0.5rem" }}
                      onClick={() => onSelectEnvelope(selected ? null : env.id)}
                    >
                      {selected ? "Clear" : "Highlight"}
                    </button>
                  </div>
                  <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-secondary)", marginTop: "0.2rem" }}>
                    {env.name} · {env.boundary_valve_count} boundary valves · {env.blind_estimate} blinds
                  </div>
                  <div style={{ marginTop: "0.45rem" }}>
                    <button
                      type="button"
                      className="btn-subtle"
                      style={{ padding: "0.2rem 0.55rem" }}
                      onClick={() => onOpenGraphForEnvelope(env.id)}
                    >
                      Inspect in Relate graph
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </aside>
      </div>
    </div>
  );
};
