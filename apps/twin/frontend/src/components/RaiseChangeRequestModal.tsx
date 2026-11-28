import React, { useEffect, useState } from "react";
import { twinApi } from "../api";
import type { AuthMember, ChangeRequestPrefill } from "../types";

interface RaiseChangeRequestModalProps {
  exerciseId: string;
  tag: string;
  authMember: AuthMember | null;
  authMode: string;
  token: string | null;
  onQuickPlannerLogin: () => Promise<void>;
  onRaised: () => Promise<void>;
  onClose: () => void;
}

export const RaiseChangeRequestModal: React.FC<RaiseChangeRequestModalProps> = ({
  exerciseId,
  tag,
  authMember,
  authMode,
  token,
  onQuickPlannerLogin,
  onRaised,
  onClose,
}) => {
  const [prefill, setPrefill] = useState<ChangeRequestPrefill | null>(null);
  const [title, setTitle] = useState("");
  const [equipmentText, setEquipmentText] = useState("");
  const [hoursDelta, setHoursDelta] = useState(140);
  const [costDeltaUsd, setCostDeltaUsd] = useState(32900);
  const [mandatory, setMandatory] = useState(false);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    twinApi
      .changeRequestPrefill(tag, exerciseId)
      .then((res) => {
        if (cancelled) return;
        setPrefill(res);
        setTitle(res.prefilled_title);
        setEquipmentText(res.prefilled_equipment_text);
        setHoursDelta(res.default_hours_delta);
        setCostDeltaUsd(res.default_cost_delta_usd);
        setReason(res.prefilled_reason);
        setLoading(false);
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
  }, [tag, exerciseId]);

  const isPlanner = authMember?.role === "planner";
  const writeThroughOn = prefill?.twin_write_through ?? false;

  const copyableBlock = [
    `Title: ${title}`,
    `Equipment (free text): ${equipmentText}`,
    `Hours delta: +${hoursDelta} hrs ($${costDeltaUsd.toLocaleString()})`,
    `Reason and twin evidence: ${reason}`,
  ].join("\n");

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(copyableBlock);
      setCopied(true);
    } catch {
      setCopied(true);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prefill) return;
    setSubmitting(true);
    setError(null);
    try {
      const cr = await twinApi.raiseFromTwin(
        {
          exercise_id: exerciseId,
          request_id: null,
          change_type: "add",
          mandatory,
          schedule_impact_days: 0.0,
          risk_if_not_done: "Misses shared equipment outage window.",
          hours_delta: Number(hoursDelta),
          cost_delta_usd: Number(costDeltaUsd),
          title: title.trim(),
          equipment_text: equipmentText.trim(),
          category: "Late Scope",
          driver: prefill.default_driver,
          source_group: prefill.default_source_group,
          area: prefill.area,
          evidence: `Twin shared context: envelopes ${prefill.shared_envelopes.join(", ") || "none"}, scaffolds ${prefill.shared_scaffolds.join(", ") || "none"}.`,
          reason: reason.trim(),
        },
        token
      );
      setCreatedId(cr.id);
      await onRaised();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={`Raise change request for ${tag}`}>
      <div className="modal-panel" style={{ maxWidth: "600px", maxHeight: "90vh", overflowY: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.75rem", marginBottom: "0.75rem" }}>
          <h2 className="view-title" style={{ margin: 0 }}>
            Raise change request from Twin ({tag})
          </h2>
          <button type="button" className="btn-subtle" onClick={onClose}>
            Close
          </button>
        </div>

        {loading && <p className="tone-muted">Loading plant context for {tag}...</p>}

        {prefill && !loading && (
          <>
            <div className="notice" style={{ marginBottom: "0.85rem" }}>
              <div>
                <strong>{prefill.equipment_tag}</strong> ({prefill.equipment_description}, area {prefill.area}) has{" "}
                <strong>{prefill.already_open_job_count}</strong> existing job(s) sharing isolation{" "}
                <span className="mono tone-code">{prefill.shared_envelopes.join(", ") || "none"}</span>
                {prefill.shared_scaffolds.length > 0 ? (
                  <>
                    {" "}
                    and scaffold <span className="mono tone-code">{prefill.shared_scaffolds.join(", ")}</span>
                  </>
                ) : null}
                .
              </div>
              {prefill.shared_setup_hours_saved > 0 && (
                <div style={{ marginTop: "0.25rem", color: "var(--accent-ok)" }}>
                  Shared entry, scaffold, and isolation avoid ~{prefill.shared_setup_hours_saved} duplicate setup hours; only direct work hours are incremental.
                </div>
              )}
            </div>

            {!writeThroughOn ? (
              <div>
                <div className="notice warn" role="status">
                  Write-through is off for this exercise. IMPACT Web refuses delegated raises in read-only mode. Copy the prefilled text below and enter it directly in IMPACT Web.
                </div>
                <label style={{ display: "flex", flexDirection: "column", gap: "0.35rem", fontSize: "var(--text-sm)" }}>
                  Prefilled change request text for IMPACT Web
                  <textarea
                    readOnly
                    rows={6}
                    value={copyableBlock}
                    style={{
                      width: "100%",
                      background: "var(--bg-inset)",
                      border: "1px solid var(--border-strong)",
                      borderRadius: "var(--radius-sm)",
                      padding: "0.6rem",
                      fontFamily: "var(--font-mono)",
                    }}
                  />
                </label>
                <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end", marginTop: "0.8rem" }}>
                  <button type="button" className="btn-primary" onClick={handleCopy}>
                    {copied ? "Copied text" : "Copy prefilled text"}
                  </button>
                  <a className="header-link" href="/impactweb/">
                    Open IMPACT Web
                  </a>
                </div>
              </div>
            ) : createdId ? (
              <div>
                <div className="notice ok" role="status">
                  Pending change request <strong className="mono">{createdId}</strong> raised in IMPACT Web by{" "}
                  <strong>{authMember?.full_name ?? "J. Planner"}</strong> (<span className="mono">raised_via = twin</span>).
                  Approve it in IMPACT Web DRB and click Sync now to update scope growth.
                </div>
                <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
                  <a className="header-link" href="/impactweb/">
                    Open IMPACT Web
                  </a>
                  <button type="button" className="btn-primary" onClick={onClose}>
                    Done
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
                {!prefill.frozen && (
                  <div className="notice warn">
                    Exercise {exerciseId} is not frozen yet. IMPACT Web only accepts change requests after freeze.
                  </div>
                )}

                {!isPlanner && (
                  <div className="notice warn" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
                    <span>Delegated twin change requests require the planner role (J. Planner).</span>
                    {authMode === "local" && (
                      <button type="button" className="btn-primary" onClick={onQuickPlannerLogin}>
                        Sign in as J. Planner
                      </button>
                    )}
                  </div>
                )}

                {error && (
                  <div className="notice err" role="alert">
                    {error}
                  </div>
                )}

                <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "var(--text-sm)" }}>
                  Change request title
                  <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} required />
                </label>

                <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "var(--text-sm)" }}>
                  Equipment text (plain text only in IMPACT Web; normalized link stays in Twin)
                  <input type="text" value={equipmentText} onChange={(e) => setEquipmentText(e.target.value)} required />
                </label>

                <div className="split-even">
                  <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "var(--text-sm)" }}>
                    Incremental hours
                    <input
                      type="text"
                      inputMode="numeric"
                      value={hoursDelta}
                      onChange={(e) => setHoursDelta(Number(e.target.value) || 0)}
                    />
                  </label>
                  <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "var(--text-sm)" }}>
                    Incremental cost (USD)
                    <input
                      type="text"
                      inputMode="numeric"
                      value={costDeltaUsd}
                      onChange={(e) => setCostDeltaUsd(Number(e.target.value) || 0)}
                    />
                  </label>
                </div>

                <label style={{ display: "inline-flex", alignItems: "center", gap: "0.45rem", fontSize: "var(--text-sm)" }}>
                  <input type="checkbox" checked={mandatory} onChange={(e) => setMandatory(e.target.checked)} />
                  Mandatory driver
                </label>

                <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "var(--text-sm)" }}>
                  Reason and twin evidence (editable)
                  <textarea
                    rows={4}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    required
                    style={{
                      width: "100%",
                      background: "var(--bg-inset)",
                      border: "1px solid var(--border-strong)",
                      borderRadius: "var(--radius-sm)",
                      padding: "0.55rem",
                    }}
                  />
                </label>

                <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end", marginTop: "0.35rem" }}>
                  <button type="button" className="btn-subtle" onClick={onClose}>
                    Cancel
                  </button>
                  <button type="submit" className="btn-primary" disabled={submitting || !isPlanner}>
                    {submitting ? "Submitting..." : "Submit to IMPACT Web"}
                  </button>
                </div>
              </form>
            )}
          </>
        )}
      </div>
    </div>
  );
};
