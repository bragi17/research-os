const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const isFormData = typeof FormData !== "undefined" && options?.body instanceof FormData;
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API error: ${res.status}${body ? ` - ${body}` : ""}`);
  }
  return res.json();
}

// Run management
export const createRun = (data: Record<string, unknown>) =>
  apiFetch("/api/v1/runs", { method: "POST", body: JSON.stringify(data) });

export const listRuns = async (params?: string): Promise<{ items: Run[]; total: number }> => {
  const sep = params ? "&" : "";
  const raw = await apiFetch<Run[] | { items: Run[]; total: number }>(`/api/v1/runs?limit=100${sep}${params || ""}`);
  if (Array.isArray(raw)) return { items: raw, total: raw.length };
  return raw;
};

export const getRun = (id: string) => apiFetch<Run>(`/api/v1/runs/${id}`);

export const startRun = (id: string) =>
  apiFetch(`/api/v1/runs/${id}/start`, { method: "POST" });

export const pauseRun = (id: string, mode = "soft") =>
  apiFetch(`/api/v1/runs/${id}/pause`, { method: "POST", body: JSON.stringify({ mode }) });

export const resumeRun = (id: string) =>
  apiFetch(`/api/v1/runs/${id}/resume`, { method: "POST", body: JSON.stringify({}) });

export const cancelRun = (id: string) =>
  apiFetch(`/api/v1/runs/${id}/cancel`, { method: "POST" });

export const updateRun = (id: string, data: Record<string, unknown>) =>
  apiFetch<Run>(`/api/v1/runs/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const deleteRun = (id: string) =>
  apiFetch(`/api/v1/runs/${id}`, { method: "DELETE" });

// Events & data
export const getRunEvents = (id: string) =>
  apiFetch<{ run_id: string; total: number; events: RunEvent[] }>(`/api/v1/runs/${id}/events`);

export const getRunHypotheses = (id: string) =>
  apiFetch<Hypothesis[]>(`/api/v1/runs/${id}/hypotheses`);

export const getRunPapers = (id: string) =>
  apiFetch<Paper[]>(`/api/v1/runs/${id}/papers`);

export interface SettingsItem {
  key: string;
  value: string;
  display_value?: string;
  is_set: boolean;
  is_sensitive: boolean;
}

export interface SettingsCategory {
  id: string;
  label: string;
  items: SettingsItem[];
}

export interface SettingsModelsResponse {
  categories: SettingsCategory[];
}

export const getModelSettings = () =>
  apiFetch<SettingsModelsResponse>("/api/v1/settings/models");

// Auth
export const login = (email: string, password: string) =>
  apiFetch<{ access_token: string }>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

export const register = (data: Record<string, unknown>) =>
  apiFetch("/api/v1/auth/register", { method: "POST", body: JSON.stringify(data) });

export const getMe = () => apiFetch<User>("/api/v1/auth/me");

// SSE helper
export function subscribeToEvents(
  runId: string,
  onEvent: (data: RunEvent) => void
): EventSource {
  const url = `${API_BASE}/api/v1/runs/${runId}/events/stream`;
  const es = new EventSource(url);
  es.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data));
    } catch {
      // Ignore malformed events
    }
  };
  return es;
}

// Types
export type RunMode = "atlas" | "frontier" | "divergent" | "review";

export interface Run {
  id: string;
  title: string;
  topic: string;
  status: "queued" | "running" | "completed" | "failed" | "paused" | "cancelled";
  goal_type: string;
  mode?: RunMode;
  parent_run_id?: string | null;
  progress_pct: string;
  current_step: string | null;
  pause_reason: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface RunEvent {
  event_type: string;
  severity: "info" | "warning" | "error" | "success";
  payload: Record<string, unknown>;
  timestamp: string;
}

export interface Hypothesis {
  id: string;
  run_id: string;
  title: string;
  type: string;
  statement: string;
  status: "candidate" | "verified" | "rejected";
  novelty_score: number;
  feasibility_score: number;
  evidence_score: number;
  risk_score: number;
  created_at: string;
}

export interface Paper {
  id: string;
  title: string;
  authors: string[];
  doi?: string;
  arxiv_id?: string;
  abstract?: string;
  year?: number;
}

export interface User {
  id: string;
  email: string;
  name: string;
}

// V2 types
export interface PainPoint {
  id: string;
  run_id: string;
  statement: string;
  pain_type: string;
  severity_score: number;
  novelty_potential: number;
}

export interface IdeaCard {
  id: string;
  run_id: string;
  title: string;
  problem_statement: string;
  borrowed_methods: string[];
  source_domains: string[];
  mechanism_of_transfer: string;
  expected_benefit: string;
  risks: string[];
  required_experiments: string[];
  prior_art_check_status: string;
  novelty_score: number;
  feasibility_score: number;
  status: string;
  dedup_key?: string | null;
  novelty_verdict?: "novel" | "incremental" | "duplicate" | "unclear";
  quality_verdict?: "pursue" | "hold" | "reject";
  closest_prior_work?: Array<Record<string, unknown>>;
  strongest_objection?: string | null;
  required_validation?: string[];
  jury_model?: string | null;
  jury_trace_id?: string | null;
  jury_status?: "pending" | "reviewed" | "error";
  prior_art_details?: Array<Record<string, unknown>>;
}

export interface TimelineEntry {
  year: number;
  title: string;
  significance: string;
  phase: string;
}

export interface TaxonomyNode {
  label: string;
  children?: TaxonomyNode[];
  representative_papers?: string[];
}

// V2 API functions
export const createRunV2 = (data: Record<string, unknown>) =>
  apiFetch("/api/v1/runs/multimode", { method: "POST", body: JSON.stringify(data) });

export const spawnRun = (runId: string, data: Record<string, unknown>) =>
  apiFetch(`/api/v1/runs/${runId}/spawn`, { method: "POST", body: JSON.stringify(data) });

export const getPainPoints = (runId: string) =>
  apiFetch<{ items: PainPoint[]; total: number }>(`/api/v1/runs/${runId}/pain-points`);

export const getIdeaCards = (runId: string) =>
  apiFetch<{ items: IdeaCard[]; total: number }>(`/api/v1/runs/${runId}/idea-cards`);

export const getTimeline = (runId: string) =>
  apiFetch<{ timeline: TimelineEntry[] }>(`/api/v1/runs/${runId}/timeline`);

export const getTaxonomy = (runId: string) =>
  apiFetch<{ taxonomy: TaxonomyNode }>(`/api/v1/runs/${runId}/taxonomy`);

export const getMindmap = (runId: string) =>
  apiFetch<{ mindmap: Record<string, unknown> }>(`/api/v1/runs/${runId}/mindmap`);

export const getComparison = (runId: string) =>
  apiFetch<{ comparison: Record<string, unknown> }>(`/api/v1/runs/${runId}/comparison`);

export const getReadingPath = (runId: string) =>
  apiFetch<Record<string, unknown>>(`/api/v1/runs/${runId}/reading-path`);

export const getFigures = (runId: string) =>
  apiFetch<{ items: Record<string, unknown>[]; total: number }>(`/api/v1/runs/${runId}/figures`);

export const runAction = (runId: string, action: string, payload: Record<string, unknown>) =>
  apiFetch(`/api/v1/runs/${runId}/actions/${action}`, {
    method: "POST",
    body: JSON.stringify({ payload }),
  });

// Library types
export interface LibraryPaper {
  id: string;
  title: string;
  arxiv_id?: string;
  doi?: string;
  field?: string;
  sub_field?: string;
  keywords: string[];
  methods: string[];
  datasets: string[];
  benchmarks: string[];
  innovation_points: string[];
  summary_json: Record<string, unknown>;
  deep_analysis_json?: Record<string, unknown>;
  year?: number;
  venue?: string;
  authors: string[];
  citation_count: number;
  status: string;
  project_tags: string[];
  pool_ids?: string[];
  pool_names?: string[];
  created_at: string;
}

export interface LibraryPool {
  id: string;
  name: string;
  description?: string | null;
  kind: "default" | "unassigned" | "custom";
  is_system: boolean;
  paper_count: number;
}

export interface LibraryDuplicateCandidate {
  paper_ids: string[];
  reason: string;
  confidence: "high" | "medium" | string;
  score: number;
}

// Library API
export const listLibraryPapers = (params?: string) =>
  apiFetch<{ items: LibraryPaper[]; total: number }>(`/api/v1/library/papers${params ? "?" + params : ""}`);

export const getLibraryPaper = (id: string) =>
  apiFetch<LibraryPaper>(`/api/v1/library/papers/${id}`);

export const addToLibrary = (data: Record<string, unknown>) =>
  apiFetch<LibraryPaper>("/api/v1/library/papers", { method: "POST", body: JSON.stringify(data) });

export const removeFromLibrary = (id: string) =>
  apiFetch(`/api/v1/library/papers/${id}`, { method: "DELETE" });

export const analyzeLibraryPaper = (id: string) =>
  apiFetch<{ status: string; paper_id: string; paper: LibraryPaper }>(
    `/api/v1/library/papers/${id}/analyze`,
    { method: "POST" },
  );

export const searchLibrary = (q: string, limit = 20, poolIds: string[] = []) => {
  const params = new URLSearchParams({ q, limit: String(limit) });
  if (poolIds.length > 0) params.set("pool_ids", poolIds.join(","));
  return apiFetch<{ items: LibraryPaper[]; total: number }>(`/api/v1/library/search?${params.toString()}`);
};

export const searchLibraryTitles = (q: string, limit = 10, poolIds: string[] = []) => {
  const params = new URLSearchParams({ q, limit: String(limit) });
  if (poolIds.length > 0) params.set("pool_ids", poolIds.join(","));
  return apiFetch<{ items: LibraryPaper[]; total: number }>(`/api/v1/library/search/titles?${params.toString()}`);
};

export const getLibraryStats = () =>
  apiFetch<{ papers: number; chunks: number }>("/api/v1/library/stats");

export const uploadToLibrary = (data: Record<string, unknown>) =>
  apiFetch<LibraryPaper>("/api/v1/library/upload", { method: "POST", body: JSON.stringify(data) });

export const uploadLibraryFile = (file: File, poolId?: string | null) => {
  const formData = new FormData();
  formData.append("file", file);
  if (poolId) formData.append("pool_ids", poolId);
  return apiFetch<LibraryPaper>("/api/v1/library/upload-file", {
    method: "POST",
    body: formData,
  });
};

export const listLibraryPools = () =>
  apiFetch<{ items: LibraryPool[]; total: number }>("/api/v1/library/pools");

export const createLibraryPool = (data: { name: string; description?: string }) =>
  apiFetch<LibraryPool>("/api/v1/library/pools", { method: "POST", body: JSON.stringify(data) });

export const updateLibraryPool = (id: string, data: { name?: string; description?: string }) =>
  apiFetch<LibraryPool>(`/api/v1/library/pools/${id}`, { method: "PATCH", body: JSON.stringify(data) });

export const deleteLibraryPool = (id: string, deletePapers = false) =>
  apiFetch<{ status: string; deleted_papers: number; moved_to_unassigned: number }>(
    `/api/v1/library/pools/${id}?delete_papers=${deletePapers ? "true" : "false"}`,
    { method: "DELETE" },
  );

export const copyLibraryPaperToPool = (paperId: string, targetPoolId: string) =>
  apiFetch<{ status: string; paper_id: string }>(
    `/api/v1/library/pools/${targetPoolId}/papers/${paperId}/copy`,
    { method: "POST" },
  );

export const moveLibraryPaperToPool = (paperId: string, sourcePoolId: string, targetPoolId: string) =>
  apiFetch<{ status: string; paper_id: string }>(
    `/api/v1/library/pools/${sourcePoolId}/papers/${paperId}/move`,
    { method: "POST", body: JSON.stringify({ target_pool_id: targetPoolId }) },
  );

export const getLibraryPoolDuplicates = (poolId: string) =>
  apiFetch<{ items: LibraryDuplicateCandidate[]; total: number }>(`/api/v1/library/pools/${poolId}/duplicates`);

// Production experiment workspace types
type ProductionQueryValue = string | number | boolean | null | undefined;

function productionQuery(params?: Record<string, ProductionQueryValue>): string {
  if (!params) return "";
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return query ? `?${query}` : "";
}

export interface ProductionListParams {
  project_id?: string;
  run_id?: string;
  experiment_plan_id?: string;
  manifest_id?: string;
  coding_task_id?: string;
  experiment_job_id?: string;
  artifact_type?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

export interface ProductionProject {
  id: string;
  title: string;
  description?: string | null;
  primary_topic: string;
  status: "active" | "paused" | "archived" | "completed" | string;
  owner_user_id?: string | null;
  default_library_pool_ids: string[];
  default_workspace_path?: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface RemoteHost {
  id: string;
  name: string;
  owner_user_id?: string | null;
  host: string;
  port: number;
  username?: string | null;
  auth_type: "key" | "agent" | "password_ref" | string;
  key_ref?: string | null;
  default_workdir?: string | null;
  default_env_json: Record<string, unknown>;
  capabilities_json: Record<string, unknown>;
  status: "unknown" | "reachable" | "unreachable" | "disabled" | string;
  last_checked_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExperimentPlan {
  id: string;
  project_id: string;
  idea_id?: string | null;
  source_run_id?: string | null;
  title: string;
  hypothesis: string;
  method_plan_markdown: string;
  implementation_plan_markdown: string;
  datasets_json: Record<string, unknown>;
  baselines_json: Record<string, unknown>;
  metrics_json: Record<string, unknown>;
  ablation_plan_json: Record<string, unknown>;
  resource_plan_json: Record<string, unknown>;
  expected_outputs_json: Record<string, unknown>;
  acceptance_criteria_json: Record<string, unknown>;
  risk_register_json: Record<string, unknown>;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface CodingTask {
  id: string;
  project_id: string;
  run_id?: string | null;
  experiment_plan_id?: string | null;
  provider: string;
  provider_session_id?: string | null;
  workspace_path?: string | null;
  thread_name?: string | null;
  system_prompt?: string | null;
  user_prompt: string;
  model?: string | null;
  timeout_sec?: number | null;
  semantic_inactivity_timeout_sec?: number | null;
  env_json: Record<string, string>;
  mcp_config_json: Record<string, unknown>;
  thinking_level?: string | null;
  prompt_hash?: string | null;
  status: string;
  failure_reason?: string | null;
  failure_detail?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
  token_usage_json: Record<string, unknown>;
  extra_args: string[];
  custom_args: string[];
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CodingEvent {
  id: number;
  coding_task_id: string;
  run_id?: string | null;
  event_type: string;
  content?: string | null;
  tool?: string | null;
  call_id?: string | null;
  input_json?: Record<string, unknown> | null;
  output_text?: string | null;
  status_text?: string | null;
  level?: string | null;
  provider_raw_json: Record<string, unknown>;
  created_at: string;
}

export interface CodeArtifact {
  id: string;
  coding_task_id?: string | null;
  project_id: string;
  experiment_plan_id?: string | null;
  artifact_type: string;
  path: string;
  content_hash?: string | null;
  summary?: string | null;
  validation_status: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface ExperimentManifest {
  id: string;
  experiment_plan_id: string;
  project_id: string;
  manifest_json: Record<string, unknown>;
  manifest_version: string;
  generated_by_coding_task_id?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ExperimentJob {
  id: string;
  manifest_id: string;
  experiment_plan_id: string;
  project_id: string;
  phase_name: string;
  job_name: string;
  executor_type: string;
  remote_host_id?: string | null;
  cmd: string;
  cwd: string;
  pid?: number | null;
  status: string;
  attempt: number;
  max_attempts: number;
  expected_outputs_json: unknown[];
  metrics_json: Record<string, unknown>;
  stdout_log_path?: string | null;
  stderr_log_path?: string | null;
  artifact_dir?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  last_heartbeat_at?: string | null;
  failure_reason?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ClaimLedger {
  id: string;
  project_id: string;
  experiment_plan_id?: string | null;
  claim_text: string;
  claim_type: string;
  status: string;
  support_level?: number | null;
  evidence_summary?: string | null;
  reviewer_model?: string | null;
  human_decision?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentRuntime {
  provider: string;
  status: string;
  executable_path?: string | null;
  version?: string | null;
  failure_reason?: string | null;
  details?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface TerminalSession {
  id: string;
  project_id?: string | null;
  run_id?: string | null;
  experiment_job_id?: string | null;
  session_type: string;
  remote_host_id?: string | null;
  cwd?: string | null;
  shell?: string | null;
  status: string;
  created_by?: string | null;
  closed_at?: string | null;
  created_at: string;
}

export interface ManuscriptPackage {
  id: string;
  project_id: string;
  title: string;
  venue_target?: string | null;
  paper_dir?: string | null;
  status: string;
  claim_ledger_snapshot_id?: string | null;
  bib_snapshot_id?: string | null;
  artifact_snapshot_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SubmissionPackage {
  id: string;
  manuscript_package_id: string;
  venue: string;
  deadline?: string | null;
  submission_dir?: string | null;
  checklist_json: Record<string, unknown>;
  anonymity_report_json: Record<string, unknown>;
  compile_report_json: Record<string, unknown>;
  claim_audit_report_json: Record<string, unknown>;
  citation_audit_report_json: Record<string, unknown>;
  artifact_provenance_report_json: Record<string, unknown>;
  paper_claim_audit_report_json: Record<string, unknown>;
  adversarial_audit_report_json: Record<string, unknown>;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceTreeEntry {
  name: string;
  path: string;
  kind: "file" | "directory" | string;
  size?: number | null;
  modified_at?: number;
}

export interface WorkspaceTree {
  root: string;
  path?: string;
  entries: WorkspaceTreeEntry[];
  truncated?: boolean;
}

export interface WorkspaceFile {
  root: string;
  path: string;
  content: string;
  size: number;
  truncated: boolean;
}

export interface JobLogTail {
  root: string;
  path: string;
  content: string;
  size: number;
  truncated: boolean;
}

export interface CodingTaskRunResult {
  task: CodingTask;
  events: CodingEvent[];
  output: string;
  status: string;
  failure_reason?: string | null;
  failure_detail?: string | null;
}

export interface ClaimGenerationResult {
  claims: ClaimLedger[];
  evidence: Record<string, unknown>[];
}

export type ProductionProjectCreate = Omit<ProductionProject, "id" | "created_at" | "updated_at">;
export type RemoteHostCreate = Omit<RemoteHost, "id" | "created_at" | "updated_at">;
export type ExperimentPlanCreate = Omit<ExperimentPlan, "id" | "created_at" | "updated_at">;
export type CodingTaskCreate = Omit<
  CodingTask,
  | "id"
  | "provider_session_id"
  | "env_json"
  | "mcp_config_json"
  | "prompt_hash"
  | "status"
  | "failure_reason"
  | "failure_detail"
  | "started_at"
  | "completed_at"
  | "duration_ms"
  | "token_usage_json"
  | "created_at"
  | "updated_at"
> & {
  env?: Record<string, string>;
  mcp_config?: Record<string, unknown> | null;
};
export type CodeArtifactCreate = Omit<CodeArtifact, "id" | "created_at">;
export type ExperimentManifestCreate = Omit<ExperimentManifest, "id" | "created_at" | "updated_at">;
export type ExperimentJobCreate = Omit<ExperimentJob, "id" | "created_at" | "updated_at">;
export type ClaimLedgerCreate = Omit<ClaimLedger, "id" | "created_at" | "updated_at">;
export type TerminalSessionCreate = Omit<TerminalSession, "id" | "created_at">;
export type ManuscriptPackageCreate = Omit<ManuscriptPackage, "id" | "created_at" | "updated_at">;
export type SubmissionPackageCreate = Pick<SubmissionPackage, "manuscript_package_id" | "venue"> &
  Partial<Omit<SubmissionPackage, "id" | "created_at" | "updated_at" | "manuscript_package_id" | "venue">>;

const productionPath = (path: string, params?: Record<string, ProductionQueryValue>) =>
  `/api/v1/production${path}${productionQuery(params)}`;

export const listAgentRuntimes = (providers?: string[]) =>
  apiFetch<AgentRuntime[]>(productionPath("/agent-runtimes", providers?.length ? { providers: providers.join(",") } : undefined));

export const detectAgentRuntime = (provider: string) =>
  apiFetch<AgentRuntime>(productionPath("/agent-runtimes/detect"), {
    method: "POST",
    body: JSON.stringify({ provider }),
  });

export const listProductionProjects = (params?: Pick<ProductionListParams, "status" | "limit" | "offset">) =>
  apiFetch<ProductionProject[]>(productionPath("/projects", params));

export const createProductionProject = (data: Partial<ProductionProjectCreate>) =>
  apiFetch<ProductionProject>(productionPath("/projects"), { method: "POST", body: JSON.stringify(data) });

export const listRemoteHosts = (params?: Pick<ProductionListParams, "status" | "limit" | "offset">) =>
  apiFetch<RemoteHost[]>(productionPath("/remote-hosts", params));

export const createRemoteHost = (data: Partial<RemoteHostCreate>) =>
  apiFetch<RemoteHost>(productionPath("/remote-hosts"), { method: "POST", body: JSON.stringify(data) });

export const listExperimentPlans = (params?: Pick<ProductionListParams, "project_id" | "status" | "limit" | "offset">) =>
  apiFetch<ExperimentPlan[]>(productionPath("/experiment-plans", params));

export const createExperimentPlan = (data: ExperimentPlanCreate) =>
  apiFetch<ExperimentPlan>(productionPath("/experiment-plans"), { method: "POST", body: JSON.stringify(data) });

export const updateExperimentPlanStatus = (planId: string, status: string) =>
  apiFetch<ExperimentPlan>(productionPath(`/experiment-plans/${planId}/status`), {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });

export const listCodingTasks = (params?: Pick<ProductionListParams, "project_id" | "run_id" | "status" | "limit" | "offset">) =>
  apiFetch<CodingTask[]>(productionPath("/coding-tasks", params));

export const createCodingTask = (data: CodingTaskCreate) =>
  apiFetch<CodingTask>(productionPath("/coding-tasks"), { method: "POST", body: JSON.stringify(data) });

export const updateCodingTask = (taskId: string, data: Partial<CodingTask>) =>
  apiFetch<CodingTask>(productionPath(`/coding-tasks/${taskId}`), { method: "PATCH", body: JSON.stringify(data) });

export const runCodingTask = (taskId: string) =>
  apiFetch<CodingTaskRunResult>(productionPath(`/coding-tasks/${taskId}/run`), { method: "POST" });

export const listCodingEvents = (taskId: string, params?: Pick<ProductionListParams, "limit" | "offset">) =>
  apiFetch<CodingEvent[]>(productionPath(`/coding-tasks/${taskId}/events`, params));

export const createCodingEvent = (taskId: string, data: Omit<CodingEvent, "id" | "created_at">) =>
  apiFetch<CodingEvent>(productionPath(`/coding-tasks/${taskId}/events`), {
    method: "POST",
    body: JSON.stringify(data),
  });

export const listCodeArtifacts = (
  params?: Pick<ProductionListParams, "project_id" | "coding_task_id" | "experiment_plan_id" | "artifact_type" | "limit" | "offset">,
) => apiFetch<CodeArtifact[]>(productionPath("/code-artifacts", params));

export const createCodeArtifact = (data: CodeArtifactCreate) =>
  apiFetch<CodeArtifact>(productionPath("/code-artifacts"), { method: "POST", body: JSON.stringify(data) });

export const listExperimentManifests = (
  params?: Pick<ProductionListParams, "project_id" | "experiment_plan_id" | "limit" | "offset">,
) => apiFetch<ExperimentManifest[]>(productionPath("/experiment-manifests", params));

export const createExperimentManifest = (data: ExperimentManifestCreate) =>
  apiFetch<ExperimentManifest>(productionPath("/experiment-manifests"), { method: "POST", body: JSON.stringify(data) });

export const expandExperimentManifestJobs = (manifestId: string) =>
  apiFetch<ExperimentJob[]>(productionPath(`/experiment-manifests/${manifestId}/jobs/expand`), { method: "POST" });

export const listExperimentJobs = (
  params?: Pick<ProductionListParams, "project_id" | "experiment_plan_id" | "manifest_id" | "status" | "limit" | "offset">,
) => apiFetch<ExperimentJob[]>(productionPath("/experiment-jobs", params));

export const createExperimentJob = (data: ExperimentJobCreate) =>
  apiFetch<ExperimentJob>(productionPath("/experiment-jobs"), { method: "POST", body: JSON.stringify(data) });

export const runLocalExperimentJob = (jobId: string) =>
  apiFetch<{ job: ExperimentJob; result: Record<string, unknown> }>(
    productionPath(`/experiment-jobs/${jobId}/run-local`),
    { method: "POST", body: JSON.stringify({}) },
  );

export const updateExperimentJob = (jobId: string, data: Partial<ExperimentJob>) =>
  apiFetch<ExperimentJob>(productionPath(`/experiment-jobs/${jobId}`), { method: "PATCH", body: JSON.stringify(data) });

export const getExperimentJobLog = (jobId: string, streamName: "stdout" | "stderr", lines = 200) =>
  apiFetch<JobLogTail>(productionPath(`/experiment-jobs/${jobId}/logs/${streamName}`, { lines }));

export const getExperimentJobArtifacts = (jobId: string) =>
  apiFetch<WorkspaceTree>(productionPath(`/experiment-jobs/${jobId}/artifacts`));

export const listClaims = (params?: Pick<ProductionListParams, "project_id" | "experiment_plan_id" | "status" | "limit" | "offset">) =>
  apiFetch<ClaimLedger[]>(productionPath("/claims", params));

export const createClaim = (data: ClaimLedgerCreate) =>
  apiFetch<ClaimLedger>(productionPath("/claims"), { method: "POST", body: JSON.stringify(data) });

export const generateClaimsFromResults = (planId: string, projectId?: string | null) =>
  apiFetch<ClaimGenerationResult>(productionPath(`/experiment-plans/${planId}/claims/generate`), {
    method: "POST",
    body: JSON.stringify(projectId ? { project_id: projectId } : {}),
  });

export const getWorkspaceTree = (projectId: string, params?: { run_id?: string; path?: string }) =>
  apiFetch<WorkspaceTree>(
    productionPath("/workspaces/tree", {
      project_id: projectId,
      run_id: params?.run_id,
      path: params?.path || ".",
    }),
  );

export const getWorkspaceFile = (projectId: string, params: { run_id?: string; path: string }) =>
  apiFetch<WorkspaceFile>(
    productionPath("/workspaces/file", {
      project_id: projectId,
      run_id: params.run_id,
      path: params.path,
    }),
  );

export const listTerminalSessions = (
  params?: Pick<ProductionListParams, "project_id" | "run_id" | "experiment_job_id" | "status" | "limit" | "offset">,
) => apiFetch<TerminalSession[]>(productionPath("/terminal/sessions", params));

export const createTerminalSession = (data: Partial<TerminalSessionCreate>) =>
  apiFetch<TerminalSession>(productionPath("/terminal/sessions"), { method: "POST", body: JSON.stringify(data) });

export const updateTerminalSession = (sessionId: string, data: Partial<TerminalSession>) =>
  apiFetch<TerminalSession>(productionPath(`/terminal/sessions/${sessionId}`), { method: "PATCH", body: JSON.stringify(data) });

export const closeTerminalSession = (sessionId: string) =>
  apiFetch<TerminalSession>(productionPath(`/terminal/sessions/${sessionId}/close`), { method: "POST" });

export const resizeTerminalSession = (sessionId: string, rows: number, cols: number) =>
  apiFetch<{ resized: boolean; rows: number; cols: number }>(productionPath(`/terminal/sessions/${sessionId}/resize`), {
    method: "POST",
    body: JSON.stringify({ rows, cols }),
  });

export function productionTerminalWebSocketUrl(sessionId: string): string {
  const base = API_BASE || (typeof window !== "undefined" ? window.location.origin : "");
  const url = new URL(`${base}/api/v1/production/terminal/sessions/${sessionId}/ws`);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export const listManuscriptPackages = (params?: Pick<ProductionListParams, "project_id" | "status" | "limit" | "offset">) =>
  apiFetch<ManuscriptPackage[]>(productionPath("/manuscripts", params));

export const createManuscriptPackage = (data: ManuscriptPackageCreate) =>
  apiFetch<ManuscriptPackage>(productionPath("/manuscripts"), { method: "POST", body: JSON.stringify(data) });

export const startManuscriptDrafting = (manuscriptId: string) =>
  apiFetch<ManuscriptPackage>(productionPath(`/manuscripts/${manuscriptId}/start-drafting`), { method: "POST" });

export const listSubmissionPackages = (
  params?: { manuscript_package_id?: string; status?: string; limit?: number; offset?: number },
) => apiFetch<SubmissionPackage[]>(productionPath("/submissions", params));

export const createSubmissionPackage = (data: SubmissionPackageCreate) =>
  apiFetch<SubmissionPackage>(productionPath("/submissions"), { method: "POST", body: JSON.stringify(data) });

export const gateSubmissionPackage = (submissionId: string) =>
  apiFetch<SubmissionPackage>(productionPath(`/submissions/${submissionId}/gate`), { method: "POST" });
