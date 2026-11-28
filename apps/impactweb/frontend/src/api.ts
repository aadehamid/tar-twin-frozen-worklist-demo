export interface Membership {
  exercise_id: string;
  role: string;
  source_group: string | null;
}

export interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  memberships: Membership[];
}

export interface ExerciseDetail {
  id: string;
  name: string;
  mode: string;
  starting_fixture: string;
  clock_step: string;
  twin_write_through: boolean;
  epoch: number;
  frozen: boolean;
  freeze_id: string | null;
  event: {
    id: string;
    site: string;
    unit: string;
    name: string;
    planned_start: string;
    duration_days: number;
    freeze_date: string;
    budget_target_usd: number;
  } | null;
}

export interface ReviewDecisionItem {
  id: number;
  stage: string;
  kind: string;
  decision: string;
  reason: string;
  request_version: number;
  stale: boolean;
  decided_by: string;
  decided_at: string;
}

export interface WorkRequestItem {
  id: string;
  exercise_id: string;
  event_id: string;
  title: string;
  description: string;
  equipment_text: string;
  category: string;
  work_type_label: string;
  driver: string;
  source_group: string;
  area: string;
  ript_score: number;
  mandatory: boolean;
  estimate_hours: number;
  estimate_hours_by_craft: Record<string, number>;
  estimate_cost_usd: number;
  status: string;
  version: number;
  decision_reason: string;
  work_package_id: string | null;
  schedule_activity_id: string | null;
  needs_re_review: boolean;
  drb_final_decision: string | null;
  decisions: ReviewDecisionItem[];
  submitted_at: string;
  updated_at: string;
}

export interface ChangeRequestItem {
  id: string;
  exercise_id: string;
  request_id: string | null;
  base_version: number;
  change_type: string;
  mandatory: boolean;
  schedule_impact_days: number;
  risk_if_not_done: string;
  hours_delta: number;
  cost_delta_usd: number;
  title: string;
  equipment_text: string;
  category: string;
  driver: string;
  source_group: string;
  area: string;
  evidence: string;
  reason: string;
  raised_by: string;
  raised_by_name: string;
  raised_via: "iw" | "twin";
  delegate_token_id: string | null;
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
  decision_reason: string;
  created_at: string;
  decided_at: string | null;
}

export const DEMO_PERSONAS = [
  { email: "ta.manager@demo.local", label: "M. Turnaround (TA Manager)" },
  { email: "j.planner@demo.local", label: "J. Planner (Planner)" },
  { email: "fixed.lead@demo.local", label: "R. Fixed-Equip (Fixed Equipment)" },
  { email: "rotating.lead@demo.local", label: "S. Rotating (Rotating)" },
  { email: "inspection.lead@demo.local", label: "K. Inspection (Inspection)" },
  { email: "drb.member@demo.local", label: "P. Review-Board (DRB Member)" },
  { email: "facilitator@demo.local", label: "A. Facilitator (Facilitator)" },
  { email: "viewer@demo.local", label: "V. Observer (Viewer)" },
];

export const CRAFT_RATES: Record<string, number> = {
  boilermaker: 235,
  pipefitter: 225,
  millwright: 245,
  instrument_tech: 240,
  inspector_nde: 260,
  scaffolder: 195,
  crane_rigging: 275,
  catalyst_specialist: 295,
};

function apiPrefix(): string {
  const path = window.location.pathname;
  if (path.startsWith("/impactweb")) {
    return "/impactweb";
  }
  return "";
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function apiFetch<T>(
  path: string,
  token: string | null,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const resp = await fetch(`${apiPrefix()}${path}`, { ...init, headers });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const parsed = await resp.json();
      if (parsed && typeof parsed.detail === "string") {
        detail = parsed.detail;
      } else if (parsed && Array.isArray(parsed.detail) && parsed.detail[0]?.msg) {
        detail = parsed.detail.map((d: { msg: string }) => d.msg).join("; ");
      }
    } catch {
      // keep default status text
    }
    throw new ApiError(resp.status, detail);
  }
  return (await resp.json()) as T;
}

export async function loginDemoPersona(
  email: string,
  password = "demo-pass-2028",
): Promise<{ access_token: string }> {
  return apiFetch<{ access_token: string }>("/api/v1/auth/login", null, {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}
