import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  CRAFT_RATES,
  ChangeRequestItem,
  DEMO_PERSONAS,
  ExerciseDetail,
  UserProfile,
  WorkRequestItem,
  apiFetch,
  loginDemoPersona,
} from "./api";

type TabId = "dashboard" | "work-requests" | "review-queue" | "change-requests";
type ReviewStage = "fit_to_frame" | "challenge" | "drb";

const AREAS = ["200-A", "200-B", "200-C", "200-D", "200-E", "200-F"];
const DRIVERS = ["inspection", "reliability", "regulatory", "capital", "operations"];
const SOURCE_GROUPS = [
  "fixed_equipment",
  "rotating",
  "inspection",
  "operations",
  "projects",
  "instrumentation",
];
const CATEGORIES = [
  "Exchanger bundle work",
  "Reactor internals and catalyst",
  "Rotating equipment",
  "Fired heater work",
  "Column and vessel internals",
  "PSV and relief devices",
  "General piping and valves",
  "Instrumentation and controls",
  "Corrosion and thickness inspection",
  "Electrical and heat tracing",
  "Capital tie-in",
  "Deferrable cleanup and painting",
];

function fmtUsd(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(amount);
}

function fmtUsdM(amount: number): string {
  return `$${(amount / 1_000_000).toFixed(2)}M`;
}

function fmtNum(val: number): string {
  return new Intl.NumberFormat("en-US").format(val);
}

function labelize(raw: string): string {
  return raw
    .replace(/_/g, " ")
    .replace(/\bnde\b/gi, "NDE")
    .replace(/^\w/, (c) => c.toUpperCase());
}

export default function App() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem("impactweb_token"));
  const [exeMode, setExeMode] = useState(false);
  const [user, setUser] = useState<UserProfile | null>(null);
  const [exercise, setExercise] = useState<ExerciseDetail | null>(null);
  const [workRequests, setWorkRequests] = useState<WorkRequestItem[]>([]);
  const [changeRequests, setChangeRequests] = useState<ChangeRequestItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [feedback, setFeedback] = useState<{ kind: "error" | "success"; text: string } | null>(null);

  const [activeTab, setActiveTab] = useState<TabId>("dashboard");
  const [searchText, setSearchText] = useState("");
  const [filterArea, setFilterArea] = useState("");
  const [filterDriver, setFilterDriver] = useState("");
  const [filterSource, setFilterSource] = useState("");
  const [filterStatus, setFilterStatus] = useState("");

  const [selectedWr, setSelectedWr] = useState<WorkRequestItem | null>(null);
  const [showNewWrModal, setShowNewWrModal] = useState(false);

  const [reviewStage, setReviewStage] = useState<ReviewStage>("drb");
  const [reviewSearch, setReviewSearch] = useState("");
  const [onlyStale, setOnlyStale] = useState(false);
  const [selectedReviewIds, setSelectedReviewIds] = useState<string[]>([]);
  const [decisionReason, setDecisionReason] = useState("Reviewed against Unit 200 turnaround scope criteria");

  const [crFormOpen, setCrFormOpen] = useState(false);
  const [crTargetId, setCrTargetId] = useState<string>("");
  const [crType, setCrType] = useState<"change" | "add" | "delete">("change");
  const [crMandatory, setCrMandatory] = useState(false);
  const [crHoursDelta, setCrHoursDelta] = useState("140");
  const [crCostDelta, setCrCostDelta] = useState("32900");
  const [crTitle, setCrTitle] = useState("");
  const [crEquipText, setCrEquipText] = useState("");
  const [crArea, setCrArea] = useState("200-E");
  const [crReason, setCrReason] = useState("");

  const exerciseId = "EX-DEMO";

  const loadWorkspace = useCallback(
    async (activeToken: string | null) => {
      const [me, ex, wrs, crs] = await Promise.all([
        apiFetch<UserProfile>("/api/v1/auth/me", activeToken),
        apiFetch<ExerciseDetail>(`/api/v1/exercises/${exerciseId}`, activeToken),
        apiFetch<WorkRequestItem[]>(`/api/v1/work-requests?exercise_id=${exerciseId}`, activeToken),
        apiFetch<ChangeRequestItem[]>(`/api/v1/change-requests?exercise_id=${exerciseId}`, activeToken),
      ]);
      setUser(me);
      setExercise(ex);
      setWorkRequests(wrs);
      setChangeRequests(crs);
      setSelectedWr((prev) => (prev ? wrs.find((w) => w.id === prev.id) ?? null : null));
    },
    [exerciseId],
  );

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      setLoading(true);
      try {
        const modeInfo = await apiFetch<{ auth_mode: string }>("/api/v1/auth/mode", null);
        if (cancelled) return;
        if (modeInfo.auth_mode === "exe") {
          setExeMode(true);
          await loadWorkspace(null);
          return;
        }
        if (token) {
          try {
            await loadWorkspace(token);
            return;
          } catch {
            localStorage.removeItem("impactweb_token");
          }
        }
        const res = await loginDemoPersona("ta.manager@demo.local");
        if (cancelled) return;
        localStorage.setItem("impactweb_token", res.access_token);
        setToken(res.access_token);
        await loadWorkspace(res.access_token);
      } catch (err) {
        if (!cancelled) {
          setFeedback({
            kind: "error",
            text: err instanceof Error ? err.message : "Failed to load IMPACT Web workspace",
          });
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    bootstrap();
    return () => {
      cancelled = true;
    };
  }, [loadWorkspace, token]);

  const membership = useMemo(() => {
    if (!user) return null;
    return user.memberships.find((m) => m.exercise_id === exerciseId) ?? null;
  }, [user, exerciseId]);

  const role = membership?.role ?? "viewer";
  const userSourceGroup = membership?.source_group ?? null;

  const canCreateWr =
    !exercise?.frozen && (role === "ta_manager" || role === "planner" || role === "source_group");
  const canEditWr = (wr: WorkRequestItem) => {
    if (exercise?.frozen) return false;
    if (role === "ta_manager" || role === "planner") return true;
    return role === "source_group" && userSourceGroup === wr.source_group;
  };
  const canRaiseCr =
    Boolean(exercise?.frozen) && (role === "ta_manager" || role === "planner" || role === "source_group");
  const canToggleWriteThrough = role === "facilitator" || role === "ta_manager";

  async function handleSwitchPersona(email: string) {
    setFeedback(null);
    try {
      const res = await loginDemoPersona(email);
      localStorage.setItem("impactweb_token", res.access_token);
      setToken(res.access_token);
      await loadWorkspace(res.access_token);
      setFeedback({ kind: "success", text: `Signed in as ${email}.` });
    } catch (err) {
      setFeedback({
        kind: "error",
        text: err instanceof Error ? err.message : "Sign-in failed",
      });
    }
  }

  async function handleToggleWriteThrough() {
    if (!exercise) return;
    setFeedback(null);
    try {
      const nextVal = !exercise.twin_write_through;
      await apiFetch(`/api/v1/exercises/${exercise.id}/write-through`, token, {
        method: "PATCH",
        body: JSON.stringify({ twin_write_through: nextVal }),
      });
      await loadWorkspace(token);
      setFeedback({
        kind: "success",
        text: `Twin write-through switch is now ${nextVal ? "on" : "off"}.`,
      });
    } catch (err) {
      setFeedback({
        kind: "error",
        text: err instanceof Error ? err.message : "Could not update write-through switch",
      });
    }
  }

  async function handleFreeze() {
    if (!exercise) return;
    setFeedback(null);
    try {
      const res = await apiFetch<{ id: string; item_count: number }>("/api/v1/freezes", token, {
        method: "POST",
        body: JSON.stringify({ exercise_id: exercise.id, event_id: exercise.event?.id ?? "TAR-200-2028" }),
      });
      await loadWorkspace(token);
      setFeedback({
        kind: "success",
        text: `Work list frozen as ${res.id} with ${res.item_count} DRB-accepted items. Direct edits are now closed.`,
      });
    } catch (err) {
      setFeedback({
        kind: "error",
        text: err instanceof Error ? err.message : "Freeze failed",
      });
    }
  }

  async function handleBulkAcceptCandidates() {
    const candidateIds = workRequests
      .filter((w) => w.status === "candidate" || w.needs_re_review)
      .map((w) => w.id);
    if (candidateIds.length === 0) return;
    setFeedback(null);
    try {
      const res = await apiFetch<{ applied_count: number }>("/api/v1/work-requests/bulk-decisions", token, {
        method: "POST",
        body: JSON.stringify({
          exercise_id: exerciseId,
          request_ids: candidateIds,
          stage: "drb",
          decision: "accept",
          reason: "Accepted by TA Manager at DRB review",
        }),
      });
      await loadWorkspace(token);
      setFeedback({
        kind: "success",
        text: `Recorded final DRB accept on ${res.applied_count} work requests.`,
      });
    } catch (err) {
      setFeedback({
        kind: "error",
        text: err instanceof Error ? err.message : "Bulk decision failed",
      });
    }
  }

  async function handleSingleDecision(
    wr: WorkRequestItem,
    stage: ReviewStage,
    kind: "recommendation" | "final",
    decision: string,
  ) {
    setFeedback(null);
    try {
      await apiFetch(`/api/v1/work-requests/${wr.id}/decisions?exercise_id=${exerciseId}`, token, {
        method: "POST",
        body: JSON.stringify({
          stage,
          kind,
          decision,
          reason: decisionReason.trim() || "Recorded in review queue",
        }),
      });
      await loadWorkspace(token);
      setFeedback({
        kind: "success",
        text: `Recorded ${stage} ${kind} (${decision}) on ${wr.id} at v${wr.version}.`,
      });
    } catch (err) {
      setFeedback({
        kind: "error",
        text: err instanceof Error ? err.message : "Could not record decision",
      });
    }
  }

  async function handleBulkSelectedAccept() {
    if (selectedReviewIds.length === 0) return;
    setFeedback(null);
    try {
      const res = await apiFetch<{ applied_count: number }>("/api/v1/work-requests/bulk-decisions", token, {
        method: "POST",
        body: JSON.stringify({
          exercise_id: exerciseId,
          request_ids: selectedReviewIds,
          stage: reviewStage,
          decision: "accept",
          reason: decisionReason.trim() || "Batch accepted in review queue",
        }),
      });
      setSelectedReviewIds([]);
      await loadWorkspace(token);
      setFeedback({
        kind: "success",
        text: `Accepted ${res.applied_count} selected work requests at ${labelize(reviewStage)}.`,
      });
    } catch (err) {
      setFeedback({
        kind: "error",
        text: err instanceof Error ? err.message : "Batch accept failed",
      });
    }
  }

  async function handleRaiseChangeRequest(e: React.FormEvent) {
    e.preventDefault();
    setFeedback(null);
    try {
      const created = await apiFetch<ChangeRequestItem>("/api/v1/change-requests", token, {
        method: "POST",
        body: JSON.stringify({
          exercise_id: exerciseId,
          request_id: crType === "add" ? null : crTargetId || null,
          change_type: crType,
          mandatory: crMandatory,
          hours_delta: Number(crHoursDelta) || 0,
          cost_delta_usd: Number(crCostDelta) || 0,
          title: crTitle.trim(),
          equipment_text: crEquipText.trim() || null,
          area: crType === "add" ? crArea : null,
          reason: crReason.trim(),
        }),
      });
      setCrFormOpen(false);
      setCrTitle("");
      setCrEquipText("");
      setCrReason("");
      await loadWorkspace(token);
      setFeedback({
        kind: "success",
        text: `Raised pending change request ${created.id} via IMPACT Web.`,
      });
    } catch (err) {
      setFeedback({
        kind: "error",
        text: err instanceof Error ? err.message : "Could not raise change request",
      });
    }
  }

  async function handleDecideChangeRequest(cr: ChangeRequestItem, decision: "approved" | "rejected") {
    setFeedback(null);
    try {
      await apiFetch(`/api/v1/change-requests/${cr.id}/decide?exercise_id=${exerciseId}`, token, {
        method: "POST",
        body: JSON.stringify({
          decision,
          reason: decision === "approved" ? "Approved by TA Manager" : "Rejected by TA Manager",
        }),
      });
      await loadWorkspace(token);
      setFeedback({
        kind: "success",
        text: `Change request ${cr.id} marked ${decision}.`,
      });
    } catch (err) {
      setFeedback({
        kind: "error",
        text: err instanceof Error ? err.message : "Could not decide change request",
      });
    }
  }

  const filteredWrs = useMemo(() => {
    const q = searchText.trim().toLowerCase();
    return workRequests.filter((w) => {
      if (filterArea && w.area !== filterArea) return false;
      if (filterDriver && w.driver !== filterDriver) return false;
      if (filterSource && w.source_group !== filterSource) return false;
      if (filterStatus && w.status !== filterStatus) return false;
      if (q && !`${w.id} ${w.title} ${w.equipment_text} ${w.description}`.toLowerCase().includes(q)) {
        return false;
      }
      return true;
    });
  }, [workRequests, filterArea, filterDriver, filterSource, filterStatus, searchText]);

  const reviewRows = useMemo(() => {
    const q = reviewSearch.trim().toLowerCase();
    return workRequests.filter((w) => {
      if (onlyStale && !w.needs_re_review) return false;
      if (q && !`${w.id} ${w.title} ${w.equipment_text}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [workRequests, reviewSearch, onlyStale]);

  const stats = useMemo(() => {
    const totalHours = workRequests.reduce((acc, w) => acc + w.estimate_hours, 0);
    const totalCost = workRequests.reduce((acc, w) => acc + w.estimate_cost_usd, 0);
    const acceptedCount = workRequests.filter((w) => w.drb_final_decision === "accept").length;
    const staleCount = workRequests.filter((w) => w.needs_re_review).length;
    const pendingCr = changeRequests.filter((c) => c.status === "pending").length;
    const byArea = AREAS.map((area) => {
      const items = workRequests.filter((w) => w.area === area);
      return {
        area,
        count: items.length,
        hours: items.reduce((a, b) => a + b.estimate_hours, 0),
        cost: items.reduce((a, b) => a + b.estimate_cost_usd, 0),
      };
    });
    const bySource = SOURCE_GROUPS.map((sg) => {
      const items = workRequests.filter((w) => w.source_group === sg);
      return {
        sg,
        count: items.length,
        hours: items.reduce((a, b) => a + b.estimate_hours, 0),
        cost: items.reduce((a, b) => a + b.estimate_cost_usd, 0),
      };
    });
    return { totalHours, totalCost, acceptedCount, staleCount, pendingCr, byArea, bySource };
  }, [workRequests, changeRequests]);

  const budgetTarget = exercise?.event?.budget_target_usd ?? 22_000_000;

  if (loading && !user) {
    return (
      <div className="workspace">
        <div className="panel">
          <div className="panel-body">Loading IMPACT Web work list...</div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand-group">
            <div className="brand">
              <span className="brand-mark">IMPACT Web</span>
              <span className="brand-unit">TAR-200-2028 · Unit 200 DHT</span>
            </div>
            <nav className="nav-tabs" aria-label="Primary navigation">
              <button
                type="button"
                className={`nav-tab ${activeTab === "dashboard" ? "active" : ""}`}
                onClick={() => setActiveTab("dashboard")}
              >
                Dashboard
              </button>
              <button
                type="button"
                className={`nav-tab ${activeTab === "work-requests" ? "active" : ""}`}
                onClick={() => setActiveTab("work-requests")}
              >
                Work requests ({workRequests.length})
              </button>
              <button
                type="button"
                className={`nav-tab ${activeTab === "review-queue" ? "active" : ""}`}
                onClick={() => setActiveTab("review-queue")}
              >
                Review queue
              </button>
              <button
                type="button"
                className={`nav-tab ${activeTab === "change-requests" ? "active" : ""}`}
                onClick={() => setActiveTab("change-requests")}
              >
                Change requests ({changeRequests.length})
              </button>
            </nav>
          </div>
          <div className="user-controls">
            {!exeMode && user && (
              <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <span className="field-hint">Signed in:</span>
                <select
                  aria-label="Active persona"
                  className="persona-select"
                  value={user.email}
                  onChange={(e) => handleSwitchPersona(e.target.value)}
                >
                  {DEMO_PERSONAS.map((p) => (
                    <option key={p.email} value={p.email}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {exeMode && user && (
              <span className="field-hint">
                {user.full_name} ({labelize(role)})
              </span>
            )}
            <a className="twin-link" href="/twin/">
              Open digital twin
            </a>
          </div>
        </div>
      </header>

      <div className="gov-strip">
        <div className="gov-inner">
          <span>
            System of record for TAR-200-2028. The digital twin reads this register and raises pending
            change requests only when write-through is on.
          </span>
          <div className="gov-meta">
            <span>
              List state:{" "}
              <span className="gov-state">
                {exercise?.frozen ? `Frozen (${exercise.freeze_id})` : "Open for review"}
              </span>
            </span>
            <span>
              Twin write-through:{" "}
              <span className="gov-state">{exercise?.twin_write_through ? "On" : "Off"}</span>
            </span>
            {canToggleWriteThrough && (
              <button type="button" className="btn btn-sm" onClick={handleToggleWriteThrough}>
                Turn {exercise?.twin_write_through ? "off" : "on"}
              </button>
            )}
          </div>
        </div>
      </div>

      <main className="workspace">
        {feedback && (
          <div className={`feedback-bar ${feedback.kind}`} role="status">
            <span>{feedback.text}</span>
            <button type="button" className="btn btn-sm" onClick={() => setFeedback(null)}>
              Dismiss
            </button>
          </div>
        )}

        {activeTab === "dashboard" && (
          <>
            <section className="metrics-strip" aria-label="Work list totals">
              <div className="metric-cell">
                <div className="metric-label">Work requests</div>
                <div className="metric-value">{fmtNum(workRequests.length)}</div>
                <div className="metric-sub">
                  {stats.acceptedCount} DRB accepted · {stats.staleCount} need re-review
                </div>
              </div>
              <div className="metric-cell">
                <div className="metric-label">Total estimated hours</div>
                <div className="metric-value">{fmtNum(stats.totalHours)}</div>
                <div className="metric-sub">28-day planned window (Oct 2028)</div>
              </div>
              <div className="metric-cell">
                <div className="metric-label">Candidate estimate vs budget</div>
                <div className="metric-value">{fmtUsdM(stats.totalCost)}</div>
                <div className="metric-sub">
                  Target {fmtUsdM(budgetTarget)} ({stats.totalCost > budgetTarget ? "+" : ""}
                  {Math.round(((stats.totalCost - budgetTarget) / budgetTarget) * 100)}%)
                </div>
              </div>
              <div className="metric-cell">
                <div className="metric-label">Post-freeze change requests</div>
                <div className="metric-value">{fmtNum(changeRequests.length)}</div>
                <div className="metric-sub">{stats.pendingCr} pending TA Manager approval</div>
              </div>
            </section>

            <section className="panel">
              <div className="panel-header">
                <div>
                  <h2 className="panel-title">Scope freeze control</h2>
                  <p className="panel-subtitle">
                    Freezing snapshots every request whose current version carries a final DRB accept
                    decision. Direct edits close after freeze.
                  </p>
                </div>
                <div className="action-row">
                  {role === "ta_manager" && !exercise?.frozen && (
                    <>
                      <button
                        type="button"
                        className="btn"
                        onClick={handleBulkAcceptCandidates}
                        disabled={workRequests.every((w) => w.drb_final_decision === "accept")}
                      >
                        Accept all unreviewed at DRB
                      </button>
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={handleFreeze}
                        disabled={stats.acceptedCount === 0}
                      >
                        Freeze work list ({stats.acceptedCount} items)
                      </button>
                    </>
                  )}
                  {exercise?.frozen && (
                    <span className="status-text status-accepted">
                      Frozen as {exercise.freeze_id}
                    </span>
                  )}
                </div>
              </div>
            </section>

            <div className="two-col">
              <section className="panel">
                <div className="panel-header">
                  <h2 className="panel-title">Scope by plant area</h2>
                </div>
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Area</th>
                        <th className="num">Requests</th>
                        <th className="num">Hours</th>
                        <th className="num">Estimate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.byArea.map((row) => (
                        <tr
                          key={row.area}
                          className="clickable"
                          onClick={() => {
                            setFilterArea(row.area);
                            setFilterSource("");
                            setActiveTab("work-requests");
                          }}
                        >
                          <td className="mono">{row.area}</td>
                          <td className="num">{fmtNum(row.count)}</td>
                          <td className="num">{fmtNum(row.hours)}</td>
                          <td className="num">{fmtUsd(row.cost)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="panel">
                <div className="panel-header">
                  <h2 className="panel-title">Scope by source group</h2>
                </div>
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Source group</th>
                        <th className="num">Requests</th>
                        <th className="num">Hours</th>
                        <th className="num">Estimate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.bySource.map((row) => (
                        <tr
                          key={row.sg}
                          className="clickable"
                          onClick={() => {
                            setFilterSource(row.sg);
                            setFilterArea("");
                            setActiveTab("work-requests");
                          }}
                        >
                          <td>{labelize(row.sg)}</td>
                          <td className="num">{fmtNum(row.count)}</td>
                          <td className="num">{fmtNum(row.hours)}</td>
                          <td className="num">{fmtUsd(row.cost)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>
          </>
        )}

        {activeTab === "work-requests" && (
          <section className="panel">
            <div className="panel-header">
              <div>
                <h2 className="panel-title">Work requests</h2>
                <p className="panel-subtitle">
                  Equipment references are free text entered by source groups. Select a row to inspect or
                  edit.
                </p>
              </div>
              <div className="action-row">
                {canCreateWr && (
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => setShowNewWrModal(true)}
                  >
                    New work request
                  </button>
                )}
              </div>
            </div>

            <div className="toolbar">
              <input
                type="search"
                className="input search-input"
                aria-label="Search work requests"
                placeholder="Search ID, title, or equipment text..."
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
              />
              <select
                aria-label="Filter by area"
                className="select"
                value={filterArea}
                onChange={(e) => setFilterArea(e.target.value)}
              >
                <option value="">All areas</option>
                {AREAS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
              <select
                aria-label="Filter by driver"
                className="select"
                value={filterDriver}
                onChange={(e) => setFilterDriver(e.target.value)}
              >
                <option value="">All drivers</option>
                {DRIVERS.map((d) => (
                  <option key={d} value={d}>
                    {labelize(d)}
                  </option>
                ))}
              </select>
              <select
                aria-label="Filter by source group"
                className="select"
                value={filterSource}
                onChange={(e) => setFilterSource(e.target.value)}
              >
                <option value="">All source groups</option>
                {SOURCE_GROUPS.map((sg) => (
                  <option key={sg} value={sg}>
                    {labelize(sg)}
                  </option>
                ))}
              </select>
              <select
                aria-label="Filter by status"
                className="select"
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value)}
              >
                <option value="">All statuses</option>
                <option value="candidate">Candidate</option>
                <option value="accepted">Accepted</option>
                <option value="deferred">Deferred</option>
                <option value="rejected">Rejected</option>
                <option value="screened_out">Screened out</option>
                <option value="deleted">Deleted</option>
              </select>
              {(filterArea || filterDriver || filterSource || filterStatus || searchText) && (
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => {
                    setSearchText("");
                    setFilterArea("");
                    setFilterDriver("");
                    setFilterSource("");
                    setFilterStatus("");
                  }}
                >
                  Clear filters
                </button>
              )}
              <span className="field-hint" style={{ marginLeft: "auto" }}>
                Showing {filteredWrs.length} of {workRequests.length}
              </span>
            </div>

            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Request ID</th>
                    <th>Title</th>
                    <th>Equipment text</th>
                    <th>Area</th>
                    <th>Source group</th>
                    <th className="num">RIPT</th>
                    <th className="num">Hours</th>
                    <th className="num">Cost</th>
                    <th>Status</th>
                    <th className="num">Ver</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredWrs.map((wr) => (
                    <tr
                      key={wr.id}
                      className={`clickable ${selectedWr?.id === wr.id ? "selected-row" : ""}`}
                      onClick={() => setSelectedWr(wr)}
                    >
                      <td className="mono mono-id">{wr.id}</td>
                      <td>
                        <div>{wr.title}</div>
                        {wr.needs_re_review && (
                          <span className="status-text status-stale">Needs re-review</span>
                        )}
                      </td>
                      <td className="mono">{wr.equipment_text}</td>
                      <td className="mono">{wr.area}</td>
                      <td>{labelize(wr.source_group)}</td>
                      <td className="num">{wr.ript_score}</td>
                      <td className="num">{fmtNum(wr.estimate_hours)}</td>
                      <td className="num">{fmtUsd(wr.estimate_cost_usd)}</td>
                      <td>
                        <span className={`status-text status-${wr.status}`}>
                          {labelize(wr.status)}
                        </span>
                      </td>
                      <td className="num mono">v{wr.version}</td>
                    </tr>
                  ))}
                  {filteredWrs.length === 0 && (
                    <tr>
                      <td colSpan={10} style={{ textAlign: "center", padding: 24 }}>
                        No work requests match the current filters.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {activeTab === "review-queue" && (
          <section className="panel">
            <div className="panel-header">
              <div>
                <h2 className="panel-title">Review queue</h2>
                <p className="panel-subtitle">
                  Decisions attach to the request version shown. Editing a request marks earlier
                  decisions stale and requires re-review before freeze.
                </p>
              </div>
              <div className="segmented" role="tablist" aria-label="Review stage">
                {(
                  [
                    ["fit_to_frame", "Fit to frame"],
                    ["challenge", "Challenge"],
                    ["drb", "DRB"],
                  ] as const
                ).map(([stage, label]) => (
                  <button
                    key={stage}
                    type="button"
                    role="tab"
                    aria-selected={reviewStage === stage}
                    className={reviewStage === stage ? "active" : ""}
                    onClick={() => setReviewStage(stage)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="toolbar">
              <input
                type="search"
                className="input search-input"
                aria-label="Search review queue"
                placeholder="Search ID, title, or equipment..."
                value={reviewSearch}
                onChange={(e) => setReviewSearch(e.target.value)}
              />
              <input
                type="text"
                className="input"
                style={{ minWidth: 260, flex: "1 1 260px" }}
                aria-label="Decision reason"
                placeholder="Decision rationale..."
                value={decisionReason}
                onChange={(e) => setDecisionReason(e.target.value)}
              />
              <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13 }}>
                <input
                  type="checkbox"
                  checked={onlyStale}
                  onChange={(e) => setOnlyStale(e.target.checked)}
                />
                Needs re-review only ({stats.staleCount})
              </label>
              {role === "ta_manager" && !exercise?.frozen && selectedReviewIds.length > 0 && (
                <button type="button" className="btn btn-primary" onClick={handleBulkSelectedAccept}>
                  Accept selected ({selectedReviewIds.length})
                </button>
              )}
            </div>

            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    {role === "ta_manager" && !exercise?.frozen && <th style={{ width: 32 }}></th>}
                    <th>Request</th>
                    <th>Equipment text</th>
                    <th className="num">Ver</th>
                    <th className="num">Hours</th>
                    <th>Current decisions</th>
                    <th>Actions ({labelize(reviewStage)})</th>
                  </tr>
                </thead>
                <tbody>
                  {reviewRows.slice(0, 60).map((wr) => {
                    const stageDecisions = wr.decisions.filter((d) => d.stage === reviewStage);
                    const checked = selectedReviewIds.includes(wr.id);
                    return (
                      <tr key={wr.id}>
                        {role === "ta_manager" && !exercise?.frozen && (
                          <td>
                            <input
                              type="checkbox"
                              aria-label={`Select ${wr.id}`}
                              checked={checked}
                              onChange={(e) =>
                                setSelectedReviewIds((prev) =>
                                  e.target.checked ? [...prev, wr.id] : prev.filter((id) => id !== wr.id),
                                )
                              }
                            />
                          </td>
                        )}
                        <td>
                          <div className="mono">{wr.id}</div>
                          <div>{wr.title}</div>
                          {wr.needs_re_review && (
                            <span className="status-text status-stale">Needs re-review</span>
                          )}
                        </td>
                        <td className="mono">{wr.equipment_text}</td>
                        <td className="num mono">v{wr.version}</td>
                        <td className="num">{fmtNum(wr.estimate_hours)}</td>
                        <td>
                          {stageDecisions.length === 0 && (
                            <span className="field-hint">No decision yet</span>
                          )}
                          {stageDecisions.map((d) => (
                            <div key={d.id} style={{ fontSize: 13 }}>
                              <span
                                className={`status-text ${d.stale ? "status-stale" : `status-${d.decision === "accept" ? "accepted" : d.decision}`}`}
                              >
                                {labelize(d.kind)}: {labelize(d.decision)} (v{d.request_version}
                                {d.stale ? ", stale" : ""})
                              </span>
                            </div>
                          ))}
                        </td>
                        <td>
                          {exercise?.frozen ? (
                            <span className="field-hint">Frozen</span>
                          ) : reviewStage === "drb" && role === "drb_member" ? (
                            <div className="action-row">
                              <button
                                type="button"
                                className="btn btn-sm"
                                onClick={() => handleSingleDecision(wr, "drb", "recommendation", "accept")}
                              >
                                Recommend accept
                              </button>
                              <button
                                type="button"
                                className="btn btn-sm"
                                onClick={() => handleSingleDecision(wr, "drb", "recommendation", "defer")}
                              >
                                Recommend defer
                              </button>
                            </div>
                          ) : reviewStage === "drb" && role === "ta_manager" ? (
                            <div className="action-row">
                              <button
                                type="button"
                                className="btn btn-sm btn-primary"
                                onClick={() => handleSingleDecision(wr, "drb", "final", "accept")}
                              >
                                Final accept
                              </button>
                              <button
                                type="button"
                                className="btn btn-sm"
                                onClick={() => handleSingleDecision(wr, "drb", "final", "defer")}
                              >
                                Defer
                              </button>
                              <button
                                type="button"
                                className="btn btn-sm btn-danger"
                                onClick={() => handleSingleDecision(wr, "drb", "final", "reject")}
                              >
                                Reject
                              </button>
                            </div>
                          ) : reviewStage === "fit_to_frame" && (role === "ta_manager" || role === "planner") ? (
                            <div className="action-row">
                              <button
                                type="button"
                                className="btn btn-sm"
                                onClick={() => handleSingleDecision(wr, "fit_to_frame", "final", "keep")}
                              >
                                Keep
                              </button>
                              <button
                                type="button"
                                className="btn btn-sm"
                                onClick={() => handleSingleDecision(wr, "fit_to_frame", "final", "screen_out")}
                              >
                                Screen out
                              </button>
                            </div>
                          ) : reviewStage === "challenge" && role === "ta_manager" ? (
                            <div className="action-row">
                              <button
                                type="button"
                                className="btn btn-sm"
                                onClick={() => handleSingleDecision(wr, "challenge", "final", "keep")}
                              >
                                Keep
                              </button>
                              <button
                                type="button"
                                className="btn btn-sm"
                                onClick={() => handleSingleDecision(wr, "challenge", "final", "defer")}
                              >
                                Defer
                              </button>
                            </div>
                          ) : (
                            <span className="field-hint">View only for {labelize(role)}</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {activeTab === "change-requests" && (
          <section className="panel">
            <div className="panel-header">
              <div>
                <h2 className="panel-title">Post-freeze change requests</h2>
                <p className="panel-subtitle">
                  All scope changes after freeze land here as pending requests for TA Manager
                  approval, showing whether raised directly in IMPACT Web or via the digital twin.
                </p>
              </div>
              <div className="action-row">
                {canRaiseCr && (
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => setCrFormOpen((v) => !v)}
                  >
                    {crFormOpen ? "Close form" : "Raise change request"}
                  </button>
                )}
              </div>
            </div>

            {!exercise?.frozen && (
              <div className="panel-body">
                Change requests unlock after the TA Manager freezes the work list.
              </div>
            )}

            {crFormOpen && canRaiseCr && (
              <form className="panel-body" style={{ borderBottom: "1px solid var(--border-hairline)" }} onSubmit={handleRaiseChangeRequest}>
                <div className="form-grid">
                  <div className="field">
                    <label htmlFor="cr-type">Change type</label>
                    <select
                      id="cr-type"
                      className="select"
                      value={crType}
                      onChange={(e) => setCrType(e.target.value as "change" | "add" | "delete")}
                    >
                      <option value="change">Modify existing request</option>
                      <option value="add">Add new post-freeze work</option>
                      <option value="delete">Delete frozen request</option>
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="cr-target">Target work request</label>
                    <select
                      id="cr-target"
                      className="select"
                      disabled={crType === "add"}
                      value={crTargetId}
                      onChange={(e) => setCrTargetId(e.target.value)}
                    >
                      <option value="">Select work request...</option>
                      {workRequests.map((w) => (
                        <option key={w.id} value={w.id}>
                          {w.id} (v{w.version}) - {w.title}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="cr-title">Title</label>
                    <input
                      id="cr-title"
                      required
                      className="input"
                      value={crTitle}
                      onChange={(e) => setCrTitle(e.target.value)}
                      placeholder="Short change title"
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="cr-equip">Equipment text (free text)</label>
                    <input
                      id="cr-equip"
                      className="input"
                      value={crEquipText}
                      onChange={(e) => setCrEquipText(e.target.value)}
                      placeholder="e.g. C-201 nozzle N3"
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="cr-hours">Hours delta</label>
                    <input
                      id="cr-hours"
                      type="number"
                      className="input"
                      value={crHoursDelta}
                      onChange={(e) => setCrHoursDelta(e.target.value)}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="cr-cost">Cost delta (USD)</label>
                    <input
                      id="cr-cost"
                      type="number"
                      className="input"
                      value={crCostDelta}
                      onChange={(e) => setCrCostDelta(e.target.value)}
                    />
                  </div>
                </div>
                <div className="form-grid">
                  <div className="field">
                    <label htmlFor="cr-area">Area</label>
                    <select
                      id="cr-area"
                      className="select"
                      value={crArea}
                      onChange={(e) => setCrArea(e.target.value)}
                    >
                      {AREAS.map((a) => (
                        <option key={a} value={a}>
                          {a}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="field" style={{ justifyContent: "flex-end" }}>
                    <label style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                      <input
                        type="checkbox"
                        checked={crMandatory}
                        onChange={(e) => setCrMandatory(e.target.checked)}
                      />
                      Mandatory safety or regulatory change
                    </label>
                  </div>
                </div>
                <div className="field">
                  <label htmlFor="cr-reason">Justification</label>
                  <textarea
                    id="cr-reason"
                    required
                    rows={2}
                    className="textarea"
                    value={crReason}
                    onChange={(e) => setCrReason(e.target.value)}
                    placeholder="Evidence and scope justification"
                  />
                </div>
                <div className="action-row">
                  <button type="submit" className="btn btn-primary">
                    Submit change request
                  </button>
                  <button type="button" className="btn" onClick={() => setCrFormOpen(false)}>
                    Cancel
                  </button>
                </div>
              </form>
            )}

            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Change ID</th>
                    <th>Target</th>
                    <th>Type</th>
                    <th>Title and reason</th>
                    <th className="num">Hours delta</th>
                    <th className="num">Base ver</th>
                    <th>Raised by</th>
                    <th>Raised via</th>
                    <th>Status</th>
                    <th>Decision</th>
                  </tr>
                </thead>
                <tbody>
                  {changeRequests.map((cr) => (
                    <tr key={cr.id}>
                      <td className="mono mono-id">{cr.id}</td>
                      <td className="mono mono-id">{cr.request_id ?? "New scope"}</td>
                      <td>{labelize(cr.change_type)}</td>
                      <td>
                        <div style={{ fontWeight: 500 }}>{cr.title}</div>
                        <div className="field-hint">{cr.reason}</div>
                      </td>
                      <td className="num">
                        {cr.hours_delta >= 0 ? `+${fmtNum(cr.hours_delta)}` : fmtNum(cr.hours_delta)}
                      </td>
                      <td className="num mono">v{cr.base_version}</td>
                      <td>{cr.raised_by_name}</td>
                      <td>
                        <span className={cr.raised_via === "twin" ? "provenance-twin" : ""}>
                          {cr.raised_via === "twin" ? "Digital twin" : "IMPACT Web"}
                        </span>
                      </td>
                      <td>
                        <span className={`status-text status-${cr.status}`}>{labelize(cr.status)}</span>
                      </td>
                      <td>
                        {cr.status === "pending" && role === "ta_manager" ? (
                          <div className="action-row">
                            <button
                              type="button"
                              className="btn btn-sm btn-primary"
                              onClick={() => handleDecideChangeRequest(cr, "approved")}
                            >
                              Approve
                            </button>
                            <button
                              type="button"
                              className="btn btn-sm btn-danger"
                              onClick={() => handleDecideChangeRequest(cr, "rejected")}
                            >
                              Reject
                            </button>
                          </div>
                        ) : (
                          <span className="field-hint">{cr.decision_reason || "Awaiting TA Manager"}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {changeRequests.length === 0 && (
                    <tr>
                      <td colSpan={10} style={{ textAlign: "center", padding: 24 }}>
                        No change requests recorded yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </main>

      {selectedWr && (
        <WorkRequestDrawer
          wr={selectedWr}
          editable={canEditWr(selectedWr)}
          frozen={Boolean(exercise?.frozen)}
          token={token}
          onClose={() => setSelectedWr(null)}
          onSaved={async (msg) => {
            await loadWorkspace(token);
            setFeedback({ kind: "success", text: msg });
          }}
          onError={(msg) => setFeedback({ kind: "error", text: msg })}
        />
      )}

      {showNewWrModal && (
        <NewWorkRequestDrawer
          token={token}
          defaultSourceGroup={userSourceGroup ?? "fixed_equipment"}
          lockSourceGroup={role === "source_group" && Boolean(userSourceGroup)}
          onClose={() => setShowNewWrModal(false)}
          onCreated={async (created) => {
            setShowNewWrModal(false);
            await loadWorkspace(token);
            setSelectedWr(created);
            setFeedback({ kind: "success", text: `Created work request ${created.id}.` });
          }}
          onError={(msg) => setFeedback({ kind: "error", text: msg })}
        />
      )}
    </div>
  );
}

function WorkRequestDrawer({
  wr,
  editable,
  frozen,
  token,
  onClose,
  onSaved,
  onError,
}: {
  wr: WorkRequestItem;
  editable: boolean;
  frozen: boolean;
  token: string | null;
  onClose: () => void;
  onSaved: (msg: string) => Promise<void>;
  onError: (msg: string) => void;
}) {
  const [title, setTitle] = useState(wr.title);
  const [equipmentText, setEquipmentText] = useState(wr.equipment_text);
  const [description, setDescription] = useState(wr.description);
  const [area, setArea] = useState(wr.area);
  const [driver, setDriver] = useState(wr.driver);
  const [riptScore, setRiptScore] = useState(String(wr.ript_score));
  const [crafts, setCrafts] = useState<Record<string, number>>(() => ({
    ...Object.fromEntries(Object.keys(CRAFT_RATES).map((k) => [k, 0])),
    ...wr.estimate_hours_by_craft,
  }));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setTitle(wr.title);
    setEquipmentText(wr.equipment_text);
    setDescription(wr.description);
    setArea(wr.area);
    setDriver(wr.driver);
    setRiptScore(String(wr.ript_score));
    setCrafts({
      ...Object.fromEntries(Object.keys(CRAFT_RATES).map((k) => [k, 0])),
      ...wr.estimate_hours_by_craft,
    });
  }, [wr]);

  const previewTotals = useMemo(() => {
    let hrs = 0;
    let cost = 0;
    for (const [k, v] of Object.entries(crafts)) {
      const n = Math.max(0, Number(v) || 0);
      hrs += n;
      cost += n * (CRAFT_RATES[k] ?? 235);
    }
    return { hrs, cost };
  }, [crafts]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const nonZeroCrafts = Object.fromEntries(
        Object.entries(crafts).filter(([, v]) => (Number(v) || 0) > 0),
      );
      const updated = await apiFetch<WorkRequestItem>(
        `/api/v1/work-requests/${wr.id}?exercise_id=${wr.exercise_id}`,
        token,
        {
          method: "PATCH",
          body: JSON.stringify({
            version: wr.version,
            title: title.trim(),
            equipment_text: equipmentText.trim(),
            description: description.trim(),
            area,
            driver,
            ript_score: Number(riptScore),
            estimate_hours_by_craft: nonZeroCrafts,
          }),
        },
      );
      await onSaved(`Saved ${updated.id} (now v${updated.version}).`);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : "Could not save work request");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" role="dialog" aria-label={`Work request ${wr.id}`} onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <div>
            <div className="mono" style={{ fontWeight: 600 }}>
              {wr.id} · v{wr.version} · {labelize(wr.status)}
            </div>
            <div className="field-hint">
              Source group: {labelize(wr.source_group)} · Category: {wr.category}
            </div>
            {wr.needs_re_review && (
              <div className="status-text status-stale">
                Prior review decision is stale. Re-review required before freeze.
              </div>
            )}
          </div>
          <div className="action-row">
            <a className="twin-link" href={`/twin/?request=${encodeURIComponent(wr.id)}`}>
              View in twin
            </a>
            <button type="button" className="btn btn-sm" onClick={onClose}>
              Close
            </button>
          </div>
        </div>

        <form className="drawer-body" onSubmit={handleSave}>
          <div className="field">
            <label htmlFor="edit-title">Title</label>
            <input
              id="edit-title"
              className="input"
              disabled={!editable}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>

          <div className="field">
            <label htmlFor="edit-equipment">Equipment text (free text, no catalog lookup)</label>
            <input
              id="edit-equipment"
              className="input mono"
              disabled={!editable}
              value={equipmentText}
              onChange={(e) => setEquipmentText(e.target.value)}
            />
          </div>

          <div className="field">
            <label htmlFor="edit-desc">Scope description</label>
            <textarea
              id="edit-desc"
              rows={3}
              className="textarea"
              disabled={!editable}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          <div className="form-grid">
            <div className="field">
              <label htmlFor="edit-area">Area</label>
              <select
                id="edit-area"
                className="select"
                disabled={!editable}
                value={area}
                onChange={(e) => setArea(e.target.value)}
              >
                {AREAS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="edit-driver">Driver</label>
              <select
                id="edit-driver"
                className="select"
                disabled={!editable}
                value={driver}
                onChange={(e) => setDriver(e.target.value)}
              >
                {DRIVERS.map((d) => (
                  <option key={d} value={d}>
                    {labelize(d)}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="edit-ript">RIPT score (1 to 25)</label>
              <input
                id="edit-ript"
                type="number"
                min={1}
                max={25}
                className="input"
                disabled={!editable}
                value={riptScore}
                onChange={(e) => setRiptScore(e.target.value)}
              />
            </div>
            <div className="field">
              <label>Calculated total</label>
              <div style={{ paddingTop: 6, fontWeight: 600 }} className="mono">
                {fmtNum(previewTotals.hrs)} hrs · {fmtUsd(previewTotals.cost)}
              </div>
            </div>
          </div>

          <div className="field">
            <label>Craft hours breakdown</label>
            <div className="craft-grid">
              {Object.keys(CRAFT_RATES).map((craft) => (
                <div className="craft-row" key={craft}>
                  <label htmlFor={`craft-${craft}`}>{labelize(craft)}</label>
                  <input
                    id={`craft-${craft}`}
                    type="number"
                    min={0}
                    className="input"
                    disabled={!editable}
                    value={crafts[craft] ?? 0}
                    onChange={(e) =>
                      setCrafts((prev) => ({ ...prev, [craft]: Math.max(0, Number(e.target.value) || 0) }))
                    }
                  />
                </div>
              ))}
            </div>
          </div>

          <div className="field">
            <label>Downstream 4.1 / 4.2 schema slots (release-one reserved)</label>
            <div className="field-hint mono">
              work_package_id: {wr.work_package_id ?? "null"} · schedule_activity_id:{" "}
              {wr.schedule_activity_id ?? "null"}
            </div>
          </div>

          <div className="drawer-footer" style={{ margin: "16px -20px -32px" }}>
            <span className="field-hint">
              {frozen
                ? "Work list is frozen. Use Change requests to modify scope."
                : editable
                  ? `Optimistic lock: saving against v${wr.version}`
                  : "Read-only for current role or source group."}
            </span>
            {editable && (
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {saving ? "Saving..." : "Save changes"}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}

function NewWorkRequestDrawer({
  token,
  defaultSourceGroup,
  lockSourceGroup,
  onClose,
  onCreated,
  onError,
}: {
  token: string | null;
  defaultSourceGroup: string;
  lockSourceGroup: boolean;
  onClose: () => void;
  onCreated: (wr: WorkRequestItem) => Promise<void>;
  onError: (msg: string) => void;
}) {
  const [title, setTitle] = useState("");
  const [equipmentText, setEquipmentText] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState(CATEGORIES[0]);
  const [driver, setDriver] = useState("inspection");
  const [sourceGroup, setSourceGroup] = useState(defaultSourceGroup);
  const [area, setArea] = useState("200-C");
  const [riptScore, setRiptScore] = useState("15");
  const [boilermakerHrs, setBoilermakerHrs] = useState("120");
  const [pipefitterHrs, setPipefitterHrs] = useState("40");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const crafts: Record<string, number> = {};
      if (Number(boilermakerHrs) > 0) crafts.boilermaker = Number(boilermakerHrs);
      if (Number(pipefitterHrs) > 0) crafts.pipefitter = Number(pipefitterHrs);
      const created = await apiFetch<WorkRequestItem>("/api/v1/work-requests", token, {
        method: "POST",
        body: JSON.stringify({
          exercise_id: "EX-DEMO",
          event_id: "TAR-200-2028",
          title: title.trim(),
          description: description.trim(),
          equipment_text: equipmentText.trim(),
          category,
          driver,
          source_group: sourceGroup,
          area,
          ript_score: Number(riptScore),
          estimate_hours_by_craft: crafts,
        }),
      });
      await onCreated(created);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Could not create work request");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" role="dialog" aria-label="New work request" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <div>
            <h2 className="panel-title">New work request</h2>
            <div className="field-hint">Equipment field accepts free text; synthetic Unit 200 names only.</div>
          </div>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Close
          </button>
        </div>

        <form className="drawer-body" onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="new-title">Title</label>
            <input
              id="new-title"
              required
              className="input"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Inspect E-201B channel head gasket face"
            />
          </div>
          <div className="field">
            <label htmlFor="new-equipment">Equipment text (free text)</label>
            <input
              id="new-equipment"
              required
              className="input mono"
              value={equipmentText}
              onChange={(e) => setEquipmentText(e.target.value)}
              placeholder="e.g. feed effluent exchanger middle shell"
            />
          </div>
          <div className="field">
            <label htmlFor="new-desc">Scope description</label>
            <textarea
              id="new-desc"
              required
              rows={3}
              className="textarea"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe turnaround scope, craft needs, and inspection basis"
            />
          </div>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="new-category">Category</label>
              <select
                id="new-category"
                className="select"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="new-driver">Driver</label>
              <select
                id="new-driver"
                className="select"
                value={driver}
                onChange={(e) => setDriver(e.target.value)}
              >
                {DRIVERS.map((d) => (
                  <option key={d} value={d}>
                    {labelize(d)}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="new-source">Source group</label>
              <select
                id="new-source"
                className="select"
                disabled={lockSourceGroup}
                value={sourceGroup}
                onChange={(e) => setSourceGroup(e.target.value)}
              >
                {SOURCE_GROUPS.map((sg) => (
                  <option key={sg} value={sg}>
                    {labelize(sg)}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="new-area">Area</label>
              <select
                id="new-area"
                className="select"
                value={area}
                onChange={(e) => setArea(e.target.value)}
              >
                {AREAS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="new-ript">RIPT score</label>
              <input
                id="new-ript"
                type="number"
                min={1}
                max={25}
                className="input"
                value={riptScore}
                onChange={(e) => setRiptScore(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="new-bm">Boilermaker hours</label>
              <input
                id="new-bm"
                type="number"
                min={0}
                className="input"
                value={boilermakerHrs}
                onChange={(e) => setBoilermakerHrs(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="new-pf">Pipefitter hours</label>
              <input
                id="new-pf"
                type="number"
                min={0}
                className="input"
                value={pipefitterHrs}
                onChange={(e) => setPipefitterHrs(e.target.value)}
              />
            </div>
          </div>
          <div className="drawer-footer" style={{ margin: "16px -20px -32px" }}>
            <button type="button" className="btn" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? "Creating..." : "Create work request"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
