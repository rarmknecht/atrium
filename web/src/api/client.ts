import type {
  ContextDoc,
  ContextDocSummary,
  GraphData,
  ModuleDetail,
  ModuleSummary,
  Report,
  Run,
  SearchHit,
  Settings,
  Trigger,
  TriggerType,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) {
    super(message);
  }
}

const TOKEN_KEY = "atrium-token";
export const auth = {
  get: () => localStorage.getItem(TOKEN_KEY) ?? "",
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = auth.get();
  const res = await fetch(`/api${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...init,
  });
  if (!res.ok) {
    let detail: unknown;
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = body.detail ?? body;
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  // modules
  listModules: () => req<ModuleSummary[]>("/modules"),
  getModule: (id: string) => req<ModuleDetail>(`/modules/${id}`),
  saveConfig: (id: string, config: Record<string, unknown>) =>
    req<{ config: Record<string, unknown> }>(`/modules/${id}/config`, {
      method: "PUT",
      body: JSON.stringify(config),
    }),
  setEnabled: (id: string, enabled: boolean) =>
    req(`/modules/${id}/enabled`, { method: "PUT", body: JSON.stringify({ enabled }) }),
  runModule: (id: string) => req<Run>(`/modules/${id}/run`, { method: "POST" }),
  listRuns: (id: string, limit = 50) => req<Run[]>(`/modules/${id}/runs?limit=${limit}`),

  // global
  recentRuns: (limit = 30) => req<Run[]>(`/runs?limit=${limit}`),
  settings: () => req<Settings>("/settings"),

  // triggers
  listTriggers: (moduleId?: string) =>
    req<Trigger[]>(`/triggers${moduleId ? `?module_id=${moduleId}` : ""}`),
  createTrigger: (body: {
    module_id: string;
    type: TriggerType;
    config?: Record<string, unknown>;
    enabled?: boolean;
  }) => req<Trigger>("/triggers", { method: "POST", body: JSON.stringify(body) }),
  updateTrigger: (id: string, body: { config?: Record<string, unknown>; enabled?: boolean }) =>
    req<Trigger>(`/triggers/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteTrigger: (id: string) => req(`/triggers/${id}`, { method: "DELETE" }),

  // reports
  listReports: (params: { module_id?: string; kind?: string; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.module_id) q.set("module_id", params.module_id);
    if (params.kind) q.set("kind", params.kind);
    q.set("limit", String(params.limit ?? 50));
    return req<Report[]>(`/reports?${q}`);
  },

  // context
  contextTree: () => req<ContextDocSummary[]>("/context/tree"),
  getDoc: (path: string) => req<ContextDoc>(`/context/doc?path=${encodeURIComponent(path)}`),
  putDoc: (body: { path: string; frontmatter: Record<string, unknown>; body: string }) =>
    req<ContextDoc>("/context/doc", { method: "PUT", body: JSON.stringify(body) }),
  deleteDoc: (path: string) =>
    req(`/context/doc?path=${encodeURIComponent(path)}`, { method: "DELETE" }),
  ask: (query: string, k = 8) =>
    req<SearchHit[]>("/context/ask", { method: "POST", body: JSON.stringify({ query, k }) }),
  graph: () => req<GraphData>("/context/graph"),
  reindex: () => req<Record<string, number>>("/context/reindex", { method: "POST" }),
};
