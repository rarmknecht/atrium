// Mirrors the Atrium FastAPI response shapes.

export type RunStatus =
  | "running" | "ok" | "warning" | "error" | "skipped" | "interrupted";
export type TriggerType = "continuous" | "schedule" | "webhook" | "manual";

export interface ModuleSummary {
  id: string;
  status: "ready" | "error";
  error: string | null;
  warnings: string[];
  enabled: boolean;
  name: string;
  version: string | null;
  description: string | null;
  kind: "agent" | "automation" | null;
  triggers_supported: TriggerType[];
}

export interface ModuleDetail extends ModuleSummary {
  config_schema?: JsonSchema;
  config?: Record<string, unknown>;
  config_valid?: boolean;
  config_error?: string;
}

export interface JsonSchema {
  properties?: Record<string, JsonSchemaProp>;
  required?: string[];
  [k: string]: unknown;
}
export interface JsonSchemaProp {
  type?: string | string[];
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  items?: JsonSchemaProp;
  anyOf?: JsonSchemaProp[];
  minimum?: number;
  maximum?: number;
}

export interface Run {
  id: string;
  module_id: string;
  trigger_id: string | null;
  trigger_type: TriggerType;
  status: RunStatus;
  summary: string;
  data_json: string | null;
  logs: string;
  tokens_in: number;
  tokens_out: number;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface TriggerLive {
  registered: boolean;
  next_fire_time?: string | null;
}
export interface Trigger {
  id: string;
  module_id: string;
  type: TriggerType;
  config: Record<string, unknown>;
  token: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  live: TriggerLive;
}

export interface Report {
  id: string;
  module_id: string;
  run_id: string | null;
  kind: string;
  title: string;
  body_md: string;
  data_json: string | null;
  created_at: string;
}

export interface DocLink { target: string; relation: string | null; resolved: boolean; }
export interface ContextDocSummary {
  path: string;
  title: string;
  tags: string[];
  type: string | null;
  summary: string | null;
  updated: string | null;
  links: DocLink[];
  backlinks: string[];
}
export interface ContextDoc extends ContextDocSummary {
  body: string | null;
  frontmatter: Record<string, unknown> | null;
}
export interface SearchHit { doc: ContextDocSummary; score: number; snippets: string[]; }
export interface GraphData {
  nodes: { id: string }[];
  edges: { source: string; target: string; relation: string | null }[];
}

export interface Settings {
  version: string;
  schema_version: number;
  vault_path: string;
  modules_path: string;
  embeddings_provider: string;
  embedding_model: string;
  embeddings_active: boolean;
  llm_model: string;
  router_model: string;
  anthropic_configured: boolean;
  watch_vault: boolean;
  doc_count: number;
}

export interface RunEvent {
  type: "run.started" | "run.finished" | "hello";
  run_id?: string;
  module_id?: string;
  trigger_type?: TriggerType;
  status?: RunStatus;
  summary?: string;
  duration_ms?: number;
  tokens_in?: number;
  tokens_out?: number;
}
