const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
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

export const listRuns = (params?: string) =>
  apiFetch<{ items: Run[]; total: number }>(`/api/v1/runs${params ? "?" + params : ""}`);

export const getRun = (id: string) => apiFetch<Run>(`/api/v1/runs/${id}`);

export const startRun = (id: string) =>
  apiFetch(`/api/v1/runs/${id}/start`, { method: "POST" });

export const pauseRun = (id: string, mode = "soft") =>
  apiFetch(`/api/v1/runs/${id}/pause`, { method: "POST", body: JSON.stringify({ mode }) });

export const resumeRun = (id: string) =>
  apiFetch(`/api/v1/runs/${id}/resume`, { method: "POST", body: JSON.stringify({}) });

export const cancelRun = (id: string) =>
  apiFetch(`/api/v1/runs/${id}/cancel`, { method: "POST" });

// Events & data
export const getRunEvents = (id: string) =>
  apiFetch<{ run_id: string; total: number; events: RunEvent[] }>(`/api/v1/runs/${id}/events`);

export const getRunHypotheses = (id: string) =>
  apiFetch<Hypothesis[]>(`/api/v1/runs/${id}/hypotheses`);

export const getRunPapers = (id: string) =>
  apiFetch<Paper[]>(`/api/v1/runs/${id}/papers`);

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
  apiFetch("/api/v2/runs", { method: "POST", body: JSON.stringify(data) });

export const spawnRun = (runId: string, data: Record<string, unknown>) =>
  apiFetch(`/api/v2/runs/${runId}/spawn`, { method: "POST", body: JSON.stringify(data) });

export const getPainPoints = (runId: string) =>
  apiFetch<{ items: PainPoint[]; total: number }>(`/api/v2/runs/${runId}/pain-points`);

export const getIdeaCards = (runId: string) =>
  apiFetch<{ items: IdeaCard[]; total: number }>(`/api/v2/runs/${runId}/idea-cards`);

export const getTimeline = (runId: string) =>
  apiFetch<{ timeline: TimelineEntry[] }>(`/api/v2/runs/${runId}/timeline`);

export const getTaxonomy = (runId: string) =>
  apiFetch<{ taxonomy: TaxonomyNode }>(`/api/v2/runs/${runId}/taxonomy`);

export const getMindmap = (runId: string) =>
  apiFetch<{ mindmap: Record<string, unknown> }>(`/api/v2/runs/${runId}/mindmap`);

export const getComparison = (runId: string) =>
  apiFetch<{ comparison: Record<string, unknown> }>(`/api/v2/runs/${runId}/comparison`);

export const getReadingPath = (runId: string) =>
  apiFetch<Record<string, unknown>>(`/api/v2/runs/${runId}/reading-path`);

export const getFigures = (runId: string) =>
  apiFetch<{ items: Record<string, unknown>[]; total: number }>(`/api/v2/runs/${runId}/figures`);

export const runAction = (runId: string, action: string, payload: Record<string, unknown>) =>
  apiFetch(`/api/v2/runs/${runId}/actions/${action}`, {
    method: "POST",
    body: JSON.stringify({ payload }),
  });
