import React, { useEffect, useRef } from "react";
import type { ExploreFollowUp, ExploreResponse, ExploreSuggestion } from "../types";

interface ExploreBarProps {
  query: string;
  onQueryChange: (q: string) => void;
  onSubmit: (q: string) => void;
  loading: boolean;
  suggestions: ExploreSuggestion[];
  result: ExploreResponse | null;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  error: string | null;
  onClear: () => void;
  onFollowUp: (fu: ExploreFollowUp) => void;
  onSelectRow: (row: Record<string, unknown>) => void;
}

export const ExploreBar: React.FC<ExploreBarProps> = ({
  query,
  onQueryChange,
  onSubmit,
  loading,
  suggestions,
  result,
  collapsed,
  onToggleCollapsed,
  error,
  onClear,
  onFollowUp,
  onSelectRow,
}) => {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      } else if (
        e.key === "/" &&
        document.activeElement?.tagName !== "INPUT" &&
        document.activeElement?.tagName !== "TEXTAREA" &&
        document.activeElement?.tagName !== "SELECT"
      ) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (trimmed.length >= 2) {
      onSubmit(trimmed);
    }
  };

  return (
    <section className="explore-bar" aria-label="Unit 200 natural language explorer">
      <div className="explore-bar-inner">
        <form className="explore-form" onSubmit={handleSubmit}>
          <div className="explore-input-wrap">
            <input
              ref={inputRef}
              type="text"
              className="explore-input"
              aria-label="Explore Unit 200 in plain English"
              placeholder="Explore Unit 200: shared isolation on E-201B, duplicates, $20M cut line, C-201 bundles, area 200-C..."
              value={query}
              onChange={(e) => onQueryChange(e.target.value)}
            />
            <span className="explore-shortcut" aria-hidden="true">
              Cmd+K
            </span>
          </div>
          <button type="submit" className="btn-primary" disabled={loading || query.trim().length < 2}>
            {loading ? "Exploring..." : "Explore"}
          </button>
          {result && (
            <button type="button" className="btn-subtle" onClick={onClear}>
              Clear
            </button>
          )}
        </form>

        <div className="explore-starters" role="group" aria-label="Quick planning explorations">
          <span className="explore-starter-label">Quick queries:</span>
          {suggestions.map((s) => (
            <button
              key={s.label}
              type="button"
              className="explore-starter-btn"
              onClick={() => {
                onQueryChange(s.query);
                onSubmit(s.query);
              }}
            >
              {s.label}
            </button>
          ))}
        </div>

        {error && (
          <div className="notice err" role="alert" style={{ marginBottom: 0 }}>
            {error}
          </div>
        )}

        {result && (
          <div className="explore-panel" role="region" aria-label="Explore query results">
            <div className="explore-panel-head">
              <div>
                <p className="explore-headline">{result.headline}</p>
                {!collapsed && (
                  <div className="explore-meta">
                    Named query <span className="mono tone-code">{result.cypher_name}</span> via{" "}
                    {result.routed_by === "decider" ? "Perplexity Decider + read-only template" : "deterministic planner rule"}
                  </div>
                )}
              </div>
              <div style={{ display: "flex", gap: "0.4rem", flexShrink: 0 }}>
                <button type="button" className="btn-subtle" onClick={onToggleCollapsed}>
                  {collapsed ? "Show details" : "Minimize"}
                </button>
                <button type="button" className="btn-subtle" onClick={onClear} aria-label="Dismiss explore result">
                  Dismiss
                </button>
              </div>
            </div>

            {!collapsed && (
              <>
                <pre className="explore-cypher">{result.cypher_query}</pre>

                {result.rows.length > 0 && (
                  <div className="explore-rows">
                    {result.rows.slice(0, 12).map((row, idx) => {
                      const rowId = String(row.id ?? row.equipment_tag ?? idx);
                      const primaryTitle = String(
                        row.title ?? row.name ?? row.reason ?? (Array.isArray(row.request_ids) ? row.request_ids.join(", ") : "")
                      );
                      const meta =
                        row.kind === "equipment"
                          ? `${String(row.area ?? "")} · ${String(row.jobs ?? 0)} jobs`
                          : row.kind === "duplicate"
                            ? `${String(row.equipment_tag ?? "")} · ${String(row.overlap_hours ?? 0)} overlap hrs`
                            : row.kind === "cluster"
                              ? `${String(row.type ?? "")} · ${String(row.job_count ?? 0)} jobs · $${Number(row.shared_cost_usd ?? 0).toLocaleString()}`
                              : row.kind === "work_request"
                                ? `${String(row.equipment_tag ?? "")} · RIPT ${String(row.ript_score ?? "")} · ${String(row.estimate_hours ?? 0)} hrs`
                                : `${String(row.proposed_tag ?? "")} · ${String(row.equipment_text ?? "")}`;
                      return (
                        <button
                          key={`${rowId}-${idx}`}
                          type="button"
                          className="explore-row-btn"
                          onClick={() => onSelectRow(row)}
                        >
                          <span className="explore-row-id">{rowId}</span>
                          <span className="explore-row-desc">{primaryTitle || meta}</span>
                          <span className="explore-row-desc" style={{ color: "var(--ink-muted)" }}>
                            {meta}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}

                {result.follow_ups.length > 0 && (
                  <div className="explore-followups">
                    {result.follow_ups.map((fu) => (
                      <button
                        key={fu.label}
                        type="button"
                        className="btn-subtle"
                        onClick={() => onFollowUp(fu)}
                      >
                        {fu.label}
                      </button>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </section>
  );
};
