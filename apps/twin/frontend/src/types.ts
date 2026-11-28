export type TwinView =
  | "plot"
  | "pid"
  | "graph"
  | "trace"
  | "review"
  | "lab"
  | "clusters";

export type PlotLayer = "match_status" | "clusters" | "cut_line" | "changes";

export interface PlotArea {
  code: string;
  name: string;
  x_min_m: number;
  x_max_m: number;
  y_min_m: number;
  y_max_m: number;
}

export interface PlotEquipmentItem {
  tag: string;
  area: string;
  x_m: number;
  y_m: number;
  elevation_m: number;
  width_m: number;
  depth_m: number;
}

export interface PlotPlanData {
  unit: string;
  width_m: number;
  height_m: number;
  pipe_rack_y_range_m: [number, number];
  areas: PlotArea[];
  equipment: PlotEquipmentItem[];
}

export interface EquipmentDetail {
  tag: string;
  dexpi_id?: string;
  equipment_class: string;
  description: string;
  area: string;
  sheet: string;
  labels: string[];
  envelopes: string[];
  nozzles: { id: string; sub_tag: string; chamber?: string }[];
  plot_position: {
    x?: number;
    y?: number;
    elevation?: number;
    x_m?: number;
    y_m?: number;
    elevation_m?: number;
    width_m?: number;
    depth_m?: number;
  } | null;
}

export interface ActiveTagOption {
  tag: string;
  description: string;
  equipment_class: string;
  area: string;
  sheet: string;
}

export interface PidSheet {
  number: string;
  title: string;
  svg_path: string;
}

export interface IsolationEnvelope {
  id: string;
  name: string;
  equipment_tags: string[];
  boundary_valves: string[];
  boundary_valve_count: number;
  blind_estimate: number;
}

export interface MatchCandidate {
  tag: string;
  score: number;
  equipment_class: string;
  shacl_class: string;
  area: string;
  sheet: string;
  description: string;
  envelopes: string[];
  facts: { id: string; text: string }[];
}

export interface MatchFinding {
  kind: string;
  tag?: string;
  reason: string;
}

export interface AiProposalBlock {
  source?: string;
  model_version?: string;
  question_version?: string;
  latency_ms?: number;
  probabilities?: Record<string, number>;
  picked_tag?: string | null;
  confidence?: number;
  evidence_id?: string | null;
  evidence_text?: string | null;
  inkling_reason?: string | null;
  inkling_label?: string | null;
  verdict?: {
    outcome: string;
    reason?: string;
  };
}

export interface MappingTrace {
  request_id: string;
  raw_equipment_text: string;
  raw_description: string;
  updated_at: string;
  normalized_text: string;
  explicit_unit: string | null;
  methods_run: { method: string; status: string; score?: number; detail?: string }[];
  findings: MatchFinding[];
  instruction_warning: boolean;
  instruction_hits: string[];
  candidates: MatchCandidate[];
  ai_proposal: AiProposalBlock | null;
  decision: {
    outcome: string;
    decided_by: string | null;
    decided_at?: string;
    reason: string;
  };
  result: {
    tag: string;
    sheet: string;
    area: string;
    envelopes: string[];
    plot_position?: unknown;
  } | null;
}

export interface ScopeItem {
  request_id: string;
  exercise_id: string;
  event_id: string;
  version: number;
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
  match_status: "accepted" | "needs_review" | "rejected";
  resolved_tag: string | null;
  match_method: string;
  confidence: number;
  proposal: {
    tag: string;
    method: string;
    confidence: number;
    probabilities?: Record<string, number>;
    evidence_id?: string | null;
    evidence_text?: string | null;
    reason?: string | null;
    reason_label?: string | null;
    model_version?: string;
  } | null;
  mapping_trace: MappingTrace;
}

export interface MatchingSummaryBucket {
  key: string;
  total: number;
  accepted: number;
  needs_review: number;
  match_rate: number;
}

export interface MatchingSummary {
  exercise_id: string;
  total_active: number;
  accepted_count: number;
  proposal_coverage_count: number;
  needs_review_count: number;
  rejected_count: number;
  match_rate: number | null;
  proposal_coverage_rate: number | null;
  gate_threshold: number;
  gate_passed: boolean;
  by_area: MatchingSummaryBucket[];
  by_source_group: MatchingSummaryBucket[];
}

export interface ClusterRecord {
  id: string;
  type: "isolation" | "scaffold" | "access";
  name: string;
  area?: string;
  envelope_id?: string;
  equipment_tags: string[];
  request_ids: string[];
  shared_hours: number;
  shared_cost_usd: number;
}

export interface DuplicatePair {
  id: string;
  equipment_tag: string;
  request_ids: string[];
  source_groups: string[];
  overlap_hours: number;
  overlap_cost_usd: number;
  reason: string;
}

export interface ClustersPayload {
  isolation_clusters: ClusterRecord[];
  scaffold_clusters: ClusterRecord[];
  access_clusters: ClusterRecord[];
  duplicate_pairs: DuplicatePair[];
}

export interface CutLineResult {
  budget_usd: number;
  feasible: boolean;
  shortfall_usd: number;
  mandatory_cost_usd: number;
  above_count: number;
  below_count: number;
  above_cost_usd: number;
  above_unclustered_cost_usd: number;
  shared_cost_saved_usd: number;
  below_cost_usd: number;
  above_hours: number;
  below_hours: number;
  active_clusters: string[];
  above_ids: string[];
  below_ids: string[];
}

export interface LabModeTotals {
  total: number;
  auto_accepted: number;
  correct: number;
  wrong: number;
  sent_to_review: number;
  abstained: number;
  rejected_by_checker: number;
  candidate_recall_hits: number;
  resolvable_total: number;
  candidate_recall: number;
  ai_calls: number;
  latency_ms: number;
}

export interface LabClassRow {
  difficulty_class: string;
  count: number;
  auto_accepted: number;
  correct: number;
  wrong: number;
  sent_to_review: number;
  abstained: number;
  rejected_by_checker: number;
  candidate_recall: number;
  ai_calls: number;
}

export interface LabCompareResponse {
  read_only: boolean;
  modes: Record<string, { totals: LabModeTotals; by_class: LabClassRow[] }>;
}

export interface LabStepResponse {
  item: ScopeItem;
  answer_key: {
    request_id: string;
    difficulty_class: string;
    true_tag: string;
    notes?: string;
  } | null;
}

export interface ExploreSuggestion {
  label: string;
  query: string;
}

export interface ExploreFollowUp {
  label: string;
  view?: TwinView;
  query?: string;
  sheet_no?: string;
  envelope_id?: string;
  equipment_tags?: string[];
  layer?: PlotLayer;
}

export interface ExploreResponse {
  query: string;
  intent: string;
  routed_by: "code" | "decider";
  headline: string;
  cypher_name: string;
  cypher_params: Record<string, string | number>;
  cypher_query: string;
  highlight: {
    view?: TwinView;
    envelope_id?: string | null;
    area_code?: string | null;
    sheet_no?: string | null;
    equipment_tags?: string[];
    boundary_valves?: string[];
    request_ids?: string[];
    budget_usd?: number;
    layer?: PlotLayer;
  };
  rows: Record<string, unknown>[];
  follow_ups: ExploreFollowUp[];
}

export interface AuthMember {
  user_id: string;
  email: string;
  full_name: string;
  role: string;
  exercise_id: string;
}
