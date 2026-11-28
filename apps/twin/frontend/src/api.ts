import type {
  ActiveTagOption,
  AuthMember,
  ClustersPayload,
  CutLineResult,
  EquipmentDetail,
  ExploreResponse,
  ExploreSuggestion,
  IsolationEnvelope,
  LabCompareResponse,
  LabStepResponse,
  MatchingSummary,
  PidSheet,
  PlotPlanData,
  ScopeItem,
} from "./types";

export function apiPrefix(): string {
  const p = window.location.pathname;
  return p === "/twin" || p.startsWith("/twin/") ? "/twin" : "";
}

function apiUrl(path: string): string {
  return `${apiPrefix()}${path}`;
}

export async function apiFetch<T>(
  path: string,
  options: { method?: string; body?: unknown; token?: string | null } = {}
): Promise<T> {
  const headers: Record<string, string> = {};
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (options.token) {
    headers["Authorization"] = `Bearer ${options.token}`;
  }
  const resp = await fetch(apiUrl(path), {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  if (!resp.ok) {
    let msg = `Request failed (${resp.status})`;
    try {
      const err = await resp.json();
      if (err && typeof err.detail === "string") msg = err.detail;
    } catch {
      // ignore non-json error
    }
    throw new Error(msg);
  }
  return (await resp.json()) as T;
}

export async function fetchSvgText(sheetNo: string): Promise<string> {
  const resp = await fetch(apiUrl(`/api/v1/plant/sheets/${encodeURIComponent(sheetNo)}.svg`));
  if (!resp.ok) throw new Error(`Unable to load P&ID sheet ${sheetNo}`);
  return await resp.text();
}

export const twinApi = {
  authMode: () => apiFetch<{ auth_mode: string; impactweb_connected: boolean }>("/api/v1/auth/mode"),
  authMe: (token: string | null, exerciseId = "EX-DEMO") =>
    apiFetch<AuthMember>(`/api/v1/auth/me?exercise_id=${encodeURIComponent(exerciseId)}`, { token }),
  authLogin: (email: string, password: string) =>
    apiFetch<{ access_token: string; user: { id: string; email: string; full_name: string } }>("/api/v1/auth/login", {
      method: "POST",
      body: { email, password },
    }),

  plotPlan: () => apiFetch<PlotPlanData>("/api/v1/plant/plot-plan"),
  equipment: () => apiFetch<EquipmentDetail[]>("/api/v1/plant/equipment"),
  activeTags: () => apiFetch<ActiveTagOption[]>("/api/v1/plant/active-tags"),
  sheets: () => apiFetch<PidSheet[]>("/api/v1/plant/sheets"),
  envelopes: () => apiFetch<IsolationEnvelope[]>("/api/v1/plant/envelopes"),

  sync: (exerciseId = "EX-DEMO", useAi = true) =>
    apiFetch<Record<string, unknown>>(
      `/api/v1/sync?exercise_id=${encodeURIComponent(exerciseId)}&use_ai=${useAi ? "true" : "false"}`,
      { method: "POST" }
    ),
  scopeItems: (exerciseId = "EX-DEMO") =>
    apiFetch<ScopeItem[]>(`/api/v1/scope-items?exercise_id=${encodeURIComponent(exerciseId)}`),
  matchingSummary: (exerciseId = "EX-DEMO") =>
    apiFetch<MatchingSummary>(`/api/v1/matching/summary?exercise_id=${encodeURIComponent(exerciseId)}`),
  reviewQueue: (exerciseId = "EX-DEMO") =>
    apiFetch<ScopeItem[]>(`/api/v1/matching/review-queue?exercise_id=${encodeURIComponent(exerciseId)}`),
  decideReview: (
    requestId: string,
    payload: { action: "accept" | "reject" | "pick_another"; tag?: string; reason?: string },
    token: string | null,
    exerciseId = "EX-DEMO"
  ) =>
    apiFetch<ScopeItem>(
      `/api/v1/matching/review/${encodeURIComponent(requestId)}?exercise_id=${encodeURIComponent(exerciseId)}`,
      { method: "POST", body: payload, token }
    ),

  labStep: (requestId: string, exerciseId = "EX-DEMO") =>
    apiFetch<LabStepResponse>(
      `/api/v1/matching/lab/step/${encodeURIComponent(requestId)}?exercise_id=${encodeURIComponent(exerciseId)}`
    ),
  labCompare: (exerciseId = "EX-DEMO") =>
    apiFetch<LabCompareResponse>(`/api/v1/matching/lab/compare?exercise_id=${encodeURIComponent(exerciseId)}`),

  clusters: (exerciseId = "EX-DEMO") =>
    apiFetch<ClustersPayload>(`/api/v1/clusters?exercise_id=${encodeURIComponent(exerciseId)}`),
  evaluateCutLine: (budgetUsd: number, exerciseId = "EX-DEMO") =>
    apiFetch<CutLineResult>("/api/v1/cut-line/evaluate", {
      method: "POST",
      body: { exercise_id: exerciseId, budget_usd: budgetUsd },
    }),

  exploreSuggestions: () => apiFetch<ExploreSuggestion[]>("/api/v1/explore/suggestions"),
  exploreQuery: (query: string, exerciseId = "EX-DEMO") =>
    apiFetch<ExploreResponse>("/api/v1/explore/query", {
      method: "POST",
      body: { exercise_id: exerciseId, query, allow_external_ai: false },
    }),
};
