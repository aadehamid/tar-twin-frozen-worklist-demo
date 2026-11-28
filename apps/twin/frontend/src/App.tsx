import React, { useCallback, useEffect, useState } from "react";
import { twinApi } from "./api";
import { BaselineKpisView } from "./components/BaselineKpisView";
import { ClustersCutLineView } from "./components/ClustersCutLineView";
import { DebriefView } from "./components/DebriefView";
import { ExploreBar } from "./components/ExploreBar";
import { GraphPanel } from "./components/GraphPanel";
import { MappingTraceView } from "./components/MappingTraceView";
import { MatchingLabView } from "./components/MatchingLabView";
import { MatchReviewView } from "./components/MatchReviewView";
import { PidViewer } from "./components/PidViewer";
import { PlotPlanView } from "./components/PlotPlanView";
import { RaiseChangeRequestModal } from "./components/RaiseChangeRequestModal";
import type { NamedQueryId } from "./relateQueries";
import type {
  ActiveTagOption,
  AuthMember,
  BaselineSummary,
  ClustersPayload,
  CutLineResult,
  CutLineRunRecord,
  DebriefReport,
  EquipmentDetail,
  ExerciseSummary,
  ExploreFollowUp,
  ExploreResponse,
  ExploreSuggestion,
  IsolationEnvelope,
  KpisSummary,
  MatchingSummary,
  PidSheet,
  PlotLayer,
  PlotPlanData,
  ScopeItem,
  TwinView,
  ValuePanelData,
} from "./types";

const DEFAULT_EXERCISE_ID = "EX-DEMO";
const TOKEN_KEY = "tar_twin_local_token";

const DEMO_ACCOUNTS = [
  { email: "j.planner@demo.local", label: "J. Planner (planner)" },
  { email: "ta.manager@demo.local", label: "M. Turnaround (ta_manager)" },
  { email: "facilitator@demo.local", label: "A. Facilitator (facilitator)" },
];

export default function App() {
  const [exercises, setExercises] = useState<ExerciseSummary[]>([]);
  const [exerciseId, setExerciseId] = useState<string>(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("exercise") || DEFAULT_EXERCISE_ID;
  });
  const [view, setView] = useState<TwinView>("plot");
  const [plotPlan, setPlotPlan] = useState<PlotPlanData | null>(null);
  const [equipment, setEquipment] = useState<EquipmentDetail[]>([]);
  const [activeTags, setActiveTags] = useState<ActiveTagOption[]>([]);
  const [sheets, setSheets] = useState<PidSheet[]>([]);
  const [envelopes, setEnvelopes] = useState<IsolationEnvelope[]>([]);
  const [scopeItems, setScopeItems] = useState<ScopeItem[]>([]);
  const [matchingSummary, setMatchingSummary] = useState<MatchingSummary | null>(null);
  const [reviewQueue, setReviewQueue] = useState<ScopeItem[]>([]);
  const [clusters, setClusters] = useState<ClustersPayload | null>(null);
  const [cutLine, setCutLine] = useState<CutLineResult | null>(null);
  const [savedCutLineRuns, setSavedCutLineRuns] = useState<CutLineRunRecord[]>([]);
  const [baseline, setBaseline] = useState<BaselineSummary | null>(null);
  const [kpis, setKpis] = useState<KpisSummary | null>(null);
  const [valuePanel, setValuePanel] = useState<ValuePanelData | null>(null);
  const [debrief, setDebrief] = useState<DebriefReport | null>(null);
  const [raiseModalTag, setRaiseModalTag] = useState<string | null>(null);
  const [budgetUsd, setBudgetUsd] = useState<number>(22_000_000);

  // Shared cross-view selection and highlights
  const [plotLayer, setPlotLayer] = useState<PlotLayer>("match_status");
  const [selectedTag, setSelectedTag] = useState<string>("E-201B");
  const [highlightedTags, setHighlightedTags] = useState<string[]>([]);
  const [activeSheet, setActiveSheet] = useState<string>("200-PID-002");
  const [activeEnvelopeId, setActiveEnvelopeId] = useState<string | null>("ENV-200-02");
  const [selectedRequestId, setSelectedRequestId] = useState<string>("WR-200-0147");
  const [graphMode, setGraphMode] = useState<NamedQueryId>("equipment_neighborhood");

  // Native natural-language Explore bar state
  const [exploreQuery, setExploreQuery] = useState<string>("");
  const [exploreSuggestions, setExploreSuggestions] = useState<ExploreSuggestion[]>([]);
  const [exploreResult, setExploreResult] = useState<ExploreResponse | null>(null);
  const [exploreCollapsed, setExploreCollapsed] = useState<boolean>(false);
  const [exploreLoading, setExploreLoading] = useState<boolean>(false);
  const [exploreError, setExploreError] = useState<string | null>(null);

  // Auth & sync state
  const [authMode, setAuthMode] = useState<string>("local");
  const [token, setToken] = useState<string | null>(() => window.sessionStorage.getItem(TOKEN_KEY));
  const [authMember, setAuthMember] = useState<AuthMember | null>(null);
  const [loginModalOpen, setLoginModalOpen] = useState<boolean>(false);
  const [loginEmail, setLoginEmail] = useState<string>("j.planner@demo.local");
  const [loginPassword, setLoginPassword] = useState<string>("demo-pass-2028");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState<boolean>(false);
  const [bootError, setBootError] = useState<string | null>(null);

  const refreshScopeData = useCallback(
    async (targetBudget: number, targetExerciseId: string) => {
      const [items, summary, queue, cl, clEval, runs, bl, kp, vp, deb] = await Promise.all([
        twinApi.scopeItems(targetExerciseId),
        twinApi.matchingSummary(targetExerciseId),
        twinApi.reviewQueue(targetExerciseId),
        twinApi.clusters(targetExerciseId),
        twinApi.evaluateCutLine(targetBudget, targetExerciseId),
        twinApi.cutLineRuns(targetExerciseId),
        twinApi.baseline(targetExerciseId),
        twinApi.kpis(targetExerciseId),
        twinApi.valuePanel(targetExerciseId),
        twinApi.debrief(targetExerciseId),
      ]);
      setScopeItems(items);
      setMatchingSummary(summary);
      setReviewQueue(queue);
      setClusters(cl);
      setCutLine(clEval);
      setSavedCutLineRuns(runs);
      setBaseline(bl);
      setKpis(kp);
      setValuePanel(vp);
      setDebrief(deb);
    },
    []
  );

  // Initial load of shared read-only plant graph + exercise list + handle deep-link ?request=WR-200-0147
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const reqParam = params.get("request");
    if (reqParam) {
      setSelectedRequestId(reqParam);
      setView("trace");
    }

    let cancelled = false;
    (async () => {
      try {
        const [modeInfo, exList, pp, eq, tags, sh, envs, sug] = await Promise.all([
          twinApi.authMode(),
          twinApi.exercises().catch(() => [] as ExerciseSummary[]),
          twinApi.plotPlan(),
          twinApi.equipment(),
          twinApi.activeTags(),
          twinApi.sheets(),
          twinApi.envelopes(),
          twinApi.exploreSuggestions(),
        ]);
        if (cancelled) return;
        setAuthMode(modeInfo.auth_mode);
        setExercises(exList);
        setPlotPlan(pp);
        setEquipment(eq);
        setActiveTags(tags);
        setSheets(sh);
        setEnvelopes(envs);
        setExploreSuggestions(sug);
      } catch (err) {
        if (!cancelled) setBootError(err instanceof Error ? err.message : String(err));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  // Reload exercise-scoped data and membership cleanly whenever exerciseId changes
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const savedToken = window.sessionStorage.getItem(TOKEN_KEY);
        if (authMode === "exe") {
          twinApi
            .authMe(null, exerciseId)
            .then((m) => {
              if (!cancelled) setAuthMember(m);
            })
            .catch(() => {
              if (!cancelled) setAuthMember(null);
            });
        } else if (savedToken) {
          twinApi
            .authMe(savedToken, exerciseId)
            .then((m) => {
              if (!cancelled) setAuthMember(m);
            })
            .catch(() => {
              if (!cancelled) setAuthMember(null);
            });
        }

        let items = await twinApi.scopeItems(exerciseId);
        if (items.length === 0) {
          await twinApi.sync(exerciseId, true);
          items = await twinApi.scopeItems(exerciseId);
        }
        if (cancelled) return;
        setScopeItems(items);
        await refreshScopeData(budgetUsd, exerciseId);
      } catch (err) {
        if (!cancelled) setBootError(err instanceof Error ? err.message : String(err));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [exerciseId, authMode, refreshScopeData]);

  const handleBudgetChange = async (newBudget: number) => {
    setBudgetUsd(newBudget);
    try {
      const res = await twinApi.evaluateCutLine(newBudget, exerciseId);
      setCutLine(res);
    } catch {
      // ignore transient eval error
    }
  };

  const handleSaveCutLineOption = async (saveName: string) => {
    const res = await twinApi.evaluateCutLine(budgetUsd, exerciseId, saveName, token);
    setCutLine(res);
    const [runs, deb] = await Promise.all([twinApi.cutLineRuns(exerciseId), twinApi.debrief(exerciseId)]);
    setSavedCutLineRuns(runs);
    setDebrief(deb);
  };

  const handleSyncNow = async () => {
    setSyncing(true);
    try {
      await twinApi.sync(exerciseId, true);
      const exList = await twinApi.exercises().catch(() => exercises);
      setExercises(exList);
      await refreshScopeData(budgetUsd, exerciseId);
    } finally {
      setSyncing(false);
    }
  };

  const performLogin = async (email: string, password: string) => {
    setLoginError(null);
    const res = await twinApi.authLogin(email, password);
    window.sessionStorage.setItem(TOKEN_KEY, res.access_token);
    setToken(res.access_token);
    const member = await twinApi.authMe(res.access_token, exerciseId);
    setAuthMember(member);
    setLoginModalOpen(false);
  };

  const handleQuickPlannerLogin = async () => {
    try {
      await performLogin("j.planner@demo.local", "demo-pass-2028");
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : String(err));
      setLoginModalOpen(true);
    }
  };

  const handleSignOut = () => {
    window.sessionStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setAuthMember(null);
  };

  const handleExploreSubmit = async (q: string) => {
    setExploreLoading(true);
    setExploreError(null);
    try {
      const res = await twinApi.exploreQuery(q, exerciseId);
      setExploreResult(res);
      setExploreCollapsed(false);

      // Drive the live workspace directly from structured highlight directives
      const hl = res.highlight;
      if (hl.equipment_tags && hl.equipment_tags.length > 0) {
        setHighlightedTags(hl.equipment_tags);
        setSelectedTag(hl.equipment_tags[0]);
      } else {
        setHighlightedTags([]);
      }
      if (hl.envelope_id) setActiveEnvelopeId(hl.envelope_id);
      if (hl.sheet_no) setActiveSheet(hl.sheet_no);
      if (hl.layer) setPlotLayer(hl.layer);
      if (typeof hl.budget_usd === "number") {
        await handleBudgetChange(hl.budget_usd);
      }
      if (hl.view && (["plot", "pid", "graph", "trace", "review", "lab", "clusters", "kpis"] as string[]).includes(hl.view)) {
        setView(hl.view as TwinView);
      }
    } catch (err) {
      setExploreError(err instanceof Error ? err.message : String(err));
    } finally {
      setExploreLoading(false);
    }
  };

  const handleExploreFollowUp = (fu: ExploreFollowUp) => {
    if (fu.query) {
      setExploreQuery(fu.query);
      void handleExploreSubmit(fu.query);
      return;
    }
    if (fu.sheet_no) setActiveSheet(fu.sheet_no);
    if (fu.envelope_id) {
      setActiveEnvelopeId(fu.envelope_id);
      setGraphMode("envelope_subgraph");
    }
    if (fu.equipment_tags && fu.equipment_tags.length > 0) {
      setHighlightedTags(fu.equipment_tags);
      setSelectedTag(fu.equipment_tags[0]);
      if (fu.view === "graph") setGraphMode("equipment_neighborhood");
    }
    if (fu.layer) setPlotLayer(fu.layer);
    if (fu.view) setView(fu.view);
    setExploreCollapsed(true);
  };

  const handleExploreRowSelect = (row: Record<string, unknown>) => {
    const kind = String(row.kind ?? "");
    if (kind === "equipment") {
      const tag = String(row.id ?? "");
      if (tag) {
        setSelectedTag(tag);
        setHighlightedTags([tag]);
        setView("plot");
      }
    } else if (kind === "work_request" || kind === "review_item") {
      const rid = String(row.id ?? "");
      if (rid) {
        setSelectedRequestId(rid);
        setView(kind === "review_item" ? "review" : "trace");
      }
    } else if (kind === "duplicate") {
      const tag = String(row.equipment_tag ?? "");
      if (tag) {
        setSelectedTag(tag);
        setHighlightedTags([tag]);
        setPlotLayer("clusters");
        setView("plot");
      }
    } else if (kind === "cluster" && Array.isArray(row.equipment_tags)) {
      const tags = row.equipment_tags.map(String);
      setHighlightedTags(tags);
      if (tags[0]) setSelectedTag(tags[0]);
      setPlotLayer("clusters");
      setView("plot");
    }
  };

  const handleDecideReview = async (
    requestId: string,
    payload: { action: "accept" | "reject" | "pick_another"; tag?: string; reason?: string }
  ) => {
    await twinApi.decideReview(requestId, payload, token, exerciseId);
    await refreshScopeData(budgetUsd, exerciseId);
  };

  const navItems: { id: TwinView; label: string }[] = [
    { id: "plot", label: "Plot plan" },
    { id: "pid", label: "P&ID" },
    { id: "graph", label: "Graph" },
    { id: "trace", label: "Trace" },
    { id: "review", label: "Review" },
    { id: "lab", label: "Matching lab" },
    { id: "clusters", label: "Clusters & cut line" },
    { id: "kpis", label: "Baseline & KPIs" },
    { id: "debrief", label: "Debrief" },
  ];

  const activeExMeta = exercises.find((e) => e.id === exerciseId);
  const lastSyncShort = kpis?.last_synced_at
    ? new Date(kpis.last_synced_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : null;

  return (
    <>
      <header className="twin-header">
        <div className="twin-header-inner">
          <div className="brand-block">
            <span className="brand-wordmark">Unit 200 Twin</span>
            {exercises.length > 0 ? (
              <select
                aria-label="Active exercise"
                className="exercise-select"
                value={exerciseId}
                onChange={(e) => {
                  const next = e.target.value;
                  setExerciseId(next);
                  setExploreResult(null);
                  setHighlightedTags([]);
                  setBootError(null);
                }}
              >
                {exercises.map((ex) => (
                  <option key={ex.id} value={ex.id}>
                    {ex.id}
                  </option>
                ))}
              </select>
            ) : (
              <span className="brand-sub">{activeExMeta?.id ?? exerciseId}</span>
            )}
          </div>

          <nav className="primary-nav" role="tablist" aria-label="Digital twin views">
            {navItems.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={view === item.id}
                onClick={() => {
                  setView(item.id);
                  if (exploreResult) setExploreCollapsed(true);
                }}
              >
                {item.label}
              </button>
            ))}
          </nav>

          <div className="header-actions">
            {lastSyncShort && (
              <span className="sync-stamp" title={`Last synced at ${kpis?.last_synced_at}`}>
                Synced {lastSyncShort}
              </span>
            )}
            <button type="button" className="btn-subtle" onClick={handleSyncNow} disabled={syncing}>
              {syncing ? "Syncing..." : "Sync now"}
            </button>
            <a className="header-link" href="/impactweb/">
              IMPACT Web
            </a>
            {authMember ? (
              <button type="button" className="btn-subtle" onClick={authMode === "local" ? handleSignOut : undefined}>
                {authMember.full_name}
              </button>
            ) : authMode === "local" ? (
              <button type="button" className="btn-subtle" onClick={() => setLoginModalOpen(true)}>
                Sign in
              </button>
            ) : null}
          </div>
        </div>
      </header>

      <ExploreBar
        query={exploreQuery}
        onQueryChange={setExploreQuery}
        onSubmit={handleExploreSubmit}
        loading={exploreLoading}
        suggestions={exploreSuggestions}
        result={exploreResult}
        collapsed={exploreCollapsed}
        onToggleCollapsed={() => setExploreCollapsed((c) => !c)}
        error={exploreError}
        onClear={() => {
          setExploreResult(null);
          setExploreCollapsed(false);
          setExploreError(null);
          setHighlightedTags([]);
        }}
        onFollowUp={handleExploreFollowUp}
        onSelectRow={(row) => {
          handleExploreRowSelect(row);
          setExploreCollapsed(true);
        }}
      />

      <main className="twin-main">
        {bootError && (
          <div className="notice err" role="alert">
            {bootError}
          </div>
        )}

        {view === "plot" && (
          <PlotPlanView
            plotPlan={plotPlan}
            equipment={equipment}
            scopeItems={scopeItems}
            clusters={clusters}
            cutLine={cutLine}
            layer={plotLayer}
            onLayerChange={setPlotLayer}
            selectedTag={selectedTag}
            highlightedTags={highlightedTags}
            onSelectTag={(tag) => setSelectedTag(tag)}
            onOpenPid={(sheetNo, tag) => {
              setActiveSheet(sheetNo);
              setSelectedTag(tag);
              setHighlightedTags([tag]);
              setView("pid");
            }}
            onOpenGraph={(tag) => {
              setSelectedTag(tag);
              setGraphMode("equipment_neighborhood");
              setView("graph");
            }}
            onOpenTrace={(reqId) => {
              setSelectedRequestId(reqId);
              setView("trace");
            }}
            onRaiseChangeRequest={(tag) => setRaiseModalTag(tag)}
          />
        )}

        {view === "pid" && (
          <PidViewer
            sheets={sheets}
            equipment={equipment}
            envelopes={envelopes}
            activeSheet={activeSheet}
            onSelectSheet={setActiveSheet}
            highlightedTags={highlightedTags.length > 0 ? highlightedTags : [selectedTag]}
            activeEnvelopeId={activeEnvelopeId}
            onSelectEquipment={(tag, sheetNo) => {
              setSelectedTag(tag);
              setHighlightedTags([tag]);
              setActiveSheet(sheetNo);
            }}
            onSelectEnvelope={setActiveEnvelopeId}
            onOpenGraphForEnvelope={(envId) => {
              setActiveEnvelopeId(envId);
              setGraphMode("envelope_subgraph");
              setView("graph");
            }}
          />
        )}

        {view === "graph" && (
          <GraphPanel
            exerciseId={exerciseId}
            equipment={equipment}
            envelopes={envelopes}
            scopeItems={scopeItems}
            initialMode={graphMode}
            selectedTag={selectedTag}
            selectedEnvelopeId={activeEnvelopeId ?? "ENV-200-02"}
            selectedRequestId={selectedRequestId}
            onSelectTag={setSelectedTag}
            onSelectEnvelope={(envId) => setActiveEnvelopeId(envId)}
            onSelectRequest={setSelectedRequestId}
            onNavigateToTrace={(reqId) => {
              setSelectedRequestId(reqId);
              setView("trace");
            }}
            onNavigateToPlot={(tag) => {
              setSelectedTag(tag);
              setHighlightedTags([tag]);
              setView("plot");
            }}
          />
        )}

        {view === "trace" && (
          <MappingTraceView
            scopeItems={scopeItems}
            equipment={equipment}
            selectedRequestId={selectedRequestId}
            onSelectRequestId={setSelectedRequestId}
            onHighlightPlot={(tag) => {
              setSelectedTag(tag);
              setHighlightedTags([tag]);
              setView("plot");
            }}
            onOpenPid={(sheetNo, tag) => {
              setActiveSheet(sheetNo);
              setSelectedTag(tag);
              setHighlightedTags([tag]);
              setView("pid");
            }}
            onOpenGraph={(reqId) => {
              setSelectedRequestId(reqId);
              setGraphMode("work_request_chain");
              setView("graph");
            }}
          />
        )}

        {view === "review" && (
          <MatchReviewView
            summary={matchingSummary}
            queue={reviewQueue}
            activeTags={activeTags}
            authMember={authMember}
            authMode={authMode}
            onQuickPlannerLogin={handleQuickPlannerLogin}
            onOpenLoginModal={() => setLoginModalOpen(true)}
            onDecide={handleDecideReview}
            onOpenTrace={(reqId) => {
              setSelectedRequestId(reqId);
              setView("trace");
            }}
          />
        )}

        {view === "lab" && (
          <MatchingLabView
            exerciseId={exerciseId}
            scopeItems={scopeItems}
            initialRequestId={selectedRequestId}
          />
        )}

        {view === "clusters" && (
          <ClustersCutLineView
            clusters={clusters}
            cutLine={cutLine}
            savedRuns={savedCutLineRuns}
            scopeItems={scopeItems}
            budgetUsd={budgetUsd}
            onBudgetChange={handleBudgetChange}
            onSaveCutLineOption={handleSaveCutLineOption}
            onColorCutLineOnPlot={() => {
              setPlotLayer("cut_line");
              setView("plot");
            }}
            onHighlightTagsOnPlot={(tags) => {
              setHighlightedTags(tags);
              if (tags[0]) setSelectedTag(tags[0]);
              setPlotLayer("clusters");
              setView("plot");
            }}
            onOpenTrace={(reqId) => {
              setSelectedRequestId(reqId);
              setView("trace");
            }}
          />
        )}

        {view === "kpis" && (
          <BaselineKpisView
            baseline={baseline}
            kpis={kpis}
            valuePanel={valuePanel}
            onOpenRaiseModal={(tag) => setRaiseModalTag(tag)}
          />
        )}

        {view === "debrief" && (
          <DebriefView
            debrief={debrief}
            onRefresh={async () => {
              await twinApi.sync(exerciseId, true);
              await refreshScopeData(budgetUsd, exerciseId);
            }}
          />
        )}
      </main>

      {raiseModalTag && (
        <RaiseChangeRequestModal
          exerciseId={exerciseId}
          tag={raiseModalTag}
          authMember={authMember}
          authMode={authMode}
          token={token}
          onQuickPlannerLogin={handleQuickPlannerLogin}
          onRaised={async () => {
            await twinApi.sync(exerciseId, true);
            await refreshScopeData(budgetUsd, exerciseId);
          }}
          onClose={() => setRaiseModalTag(null)}
        />
      )}

      {loginModalOpen && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Sign in to Twin">
          <div className="modal-panel">
            <h2 className="panel-heading">Sign in via IMPACT Web identity</h2>
            <p style={{ margin: "0 0 0.85rem", fontSize: "var(--text-sm)", color: "var(--ink-secondary)" }}>
              Match review decisions require a planner or TA manager account verified by IMPACT Web.
            </p>
            {loginError && (
              <div className="notice err" role="alert">
                {loginError}
              </div>
            )}
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                try {
                  await performLogin(loginEmail, loginPassword);
                } catch (err) {
                  setLoginError(err instanceof Error ? err.message : String(err));
                }
              }}
              style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}
            >
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "var(--text-sm)" }}>
                Account
                <select value={loginEmail} onChange={(e) => setLoginEmail(e.target.value)}>
                  {DEMO_ACCOUNTS.map((acc) => (
                    <option key={acc.email} value={acc.email}>
                      {acc.label}
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: "0.25rem", fontSize: "var(--text-sm)" }}>
                Password
                <input
                  type="password"
                  value={loginPassword}
                  onChange={(e) => setLoginPassword(e.target.value)}
                />
              </label>
              <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end", marginTop: "0.35rem" }}>
                <button type="button" className="btn-subtle" onClick={() => setLoginModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn-primary">
                  Sign in
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
