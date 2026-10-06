/**
 * Typed client for the RAGForge API.
 *
 * Requests go to `/backend/...` on the same origin; the route handler in
 * `app/backend/[...path]/route.ts` forwards them to the FastAPI server.
 * The access token is attached from `tokenStore`.
 */

export const API_PREFIX = "/backend";

// ---------------------------------------------------------------- types

export interface User {
  id: number;
  username: string;
  created_at: string;
}

export interface Provider {
  name: string;
  label: string;
  default_model: string;
  requires_base_url: boolean;
  configured: boolean;
}

export interface ProviderKey {
  id: number;
  provider: string;
  masked_key: string;
  base_url: string | null;
}

export interface KeyValidation {
  valid: boolean;
  detail: string;
}

export type DocumentStatus = "pending" | "indexing" | "ready" | "failed" | string;

export interface DocumentSummary {
  id: number;
  user_id: number;
  title: string;
  status: DocumentStatus;
  negative_impact: number;
}

export interface DocumentChunk {
  id: number;
  sequence_order: number;
  page_number: number | null;
  content: string;
}

export interface DocumentDetail {
  id: number;
  status: DocumentStatus;
  error: string | null;
  title: string;
  filename: string | null;
  group_id: number | null;
  created_at: string | null;
  /** The model the document's vectors were made with; null before it is first indexed. */
  embedding: EmbeddingRef | null;
  chunks: DocumentChunk[];
}

export interface EmbeddingRef {
  /** "local" (the server's own model) or a provider name. */
  provider: string;
  model: string;
}

export interface EmbeddingOption {
  provider: string;
  label: string;
  /** "" when the user has to name the model (self-hosted servers). */
  default_model: string;
  has_key: boolean;
}

export interface EmbeddingSettings extends EmbeddingRef {
  /** The chosen provider's key has been deleted since. */
  key_missing: boolean;
  options: EmbeddingOption[];
  /** Ready documents per embedding model. */
  documents: (EmbeddingRef & { documents: number })[];
  /** Documents not yet embedded with the current choice. */
  outdated: number;
  /** Documents queued or being indexed right now. */
  indexing: number;
}

export interface DocumentAccepted {
  id: number;
  title: string;
  filename: string | null;
  status: DocumentStatus;
}

export interface Citation {
  number: number;
  document_id: number;
  document_title: string;
  page_number: number | null;
  chunk_id: number;
  snippet: string;
}

export interface Source {
  number: number;
  document_id: number;
  document_title: string;
  page_number: number | null;
}

export interface PromptVersion {
  id: number;
  version: number;
  template: string;
  note: string | null;
  created_at: string;
}

export interface PromptSummary {
  id: number;
  name: string;
  description: string | null;
  created_at: string | null;
  version_count: number;
  latest_version: PromptVersion | null;
}

export interface PromptDetail extends PromptSummary {
  /** Newest first. */
  versions: PromptVersion[];
}

export type RetrievalStrategy = "hybrid" | "dense" | "keyword";

export interface ExperimentCase {
  question: string;
  reference_answer?: string | null;
}

export interface ExperimentVariantInput {
  label?: string;
  prompt_version_id?: number | null;
  provider: string;
  model?: string;
  retrieval?: RetrievalStrategy;
  top_k?: number;
}

export interface ExperimentVariant {
  id: number;
  label: string;
  prompt_version_id: number | null;
  prompt_label: string;
  provider: string;
  model: string;
  retrieval: RetrievalStrategy;
  top_k: number;
}

export type ExperimentStatus = "draft" | "queued" | "running" | "completed" | "failed";

export interface Experiment {
  id: number;
  name: string;
  status: ExperimentStatus;
  error: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  case_count: number;
  variants: ExperimentVariant[];
  document_ids: number[] | null;
  evaluate: boolean;
  evaluator: string;
  judge_provider: string | null;
  judge_model: string | null;
  /** Answers worked on at once. */
  concurrency: number;
  progress: { done: number; total: number };
  cases?: ExperimentCase[];
}

export type ExperimentMetric =
  | "quality"
  | "faithfulness"
  | "answer_relevancy"
  | "context_precision"
  | "context_recall"
  | "hallucination"
  | "rouge_l"
  | "latency_ms"
  | "cost_usd";

export interface VariantSummary extends ExperimentVariant {
  results: number;
  errors: number;
  averages: Record<ExperimentMetric, number | null>;
  total_cost_usd: number | null;
  prompt_tokens: number;
  completion_tokens: number;
}

export interface CaseResult {
  answer: string | null;
  citations: Citation[];
  error: string | null;
  latency_ms: number | null;
  cost_usd: number | null;
  quality: number | null;
  faithfulness: number | null;
  answer_relevancy: number | null;
  context_precision: number | null;
  context_recall: number | null;
  hallucination: number | null;
  rouge_l: number | null;
  judge_rationale: string | null;
}

export interface ExperimentComparison {
  experiment: Experiment;
  variants: VariantSummary[];
  /** Metric -> id of the best variant (only when at least two have a value). */
  best: Partial<Record<ExperimentMetric, number>>;
  cases: (ExperimentCase & { index: number; results: Record<string, CaseResult> })[];
}

export interface Conversation {
  id: number;
  prompt_version_id?: number | null;
  title: string;
  provider: string | null;
  model: string | null;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  citations: Citation[] | null;
  provider: string | null;
  model: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  latency_ms: number | null;
  finish_reason: string | null;
  created_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface TurnDone {
  message_id: number;
  provider: string;
  model: string;
  finish_reason: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  cost_usd: number | null;
  latency_ms: number;
  ttft_ms: number | null;
}

export interface UsageBucket {
  requests: number;
  errors: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  avg_latency_ms: number | null;
}

export interface TelemetrySummary extends UsageBucket {
  days: number;
  error_rate: number;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  p50_ttft_ms: number | null;
  unpriced_requests: number;
  by_model: (UsageBucket & { provider: string; model: string })[];
  daily: (UsageBucket & { date: string })[];
}

export interface TelemetryEvent {
  id: number;
  conversation_id: number | null;
  message_id: number | null;
  operation: string;
  provider: string;
  model: string;
  status: "ok" | "error" | string;
  error_type: string | null;
  latency_ms: number | null;
  ttft_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  tokens_estimated: boolean;
  cost_usd: number | null;
  created_at: string;
}

export interface Evaluation {
  id: number;
  message_id: number;
  conversation_id: number | null;
  /** builtin | ragas | deepeval */
  evaluator: string;
  judge_provider: string;
  judge_model: string;
  /** null when the evaluator could not score this metric. */
  faithfulness: number | null;
  answer_relevancy: number | null;
  context_precision: number | null;
  context_recall: number | null;
  hallucination: number | null;
  rationale: string | null;
  reference_answer: string | null;
  rouge_l: number | null;
  context_overlap: number | null;
  created_at: string;
}

export interface EvaluatorInfo {
  name: string;
  label: string;
  description: string;
  /** Installed on this server. */
  available: boolean;
}

export interface EvaluationHistory {
  items: Evaluation[];
  total: number;
  averages: Record<string, number | null>;
}

export interface SubsystemHealth {
  db: string;
  vector_store: string;
}

// ---------------------------------------------------------------- token

const TOKEN_KEY = "ragforge.token";

/** Where the access token lives. localStorage can throw (private mode, blocked storage). */
export const tokenStore = {
  get(): string | null {
    try {
      return window.localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string) {
    try {
      window.localStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* the session still works until reload */
    }
  },
  clear() {
    try {
      window.localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* nothing stored */
    }
  },
};

// ---------------------------------------------------------------- errors

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
    /** The parsed response body, when there was one. */
    public body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Turn a FastAPI error body into one readable sentence. */
export function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // Validation errors: [{loc: [...], msg: "..."}]
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => {
        const field = d.loc?.filter((p) => p !== "body").join(".");
        return field ? `${field}: ${d.msg}` : d.msg;
      })
      .join("; ");
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  if (status === 0) return "Could not reach the server.";
  return `Request failed (${status})`;
}

/** Called on any 401 so the app can send the user back to the login page. */
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

/** For requests made outside `request()` (streaming): report a 401 the same way. */
export function reportStatus(status: number, sentToken: boolean) {
  if (status === 401 && sentToken) onUnauthorized?.();
}

// ---------------------------------------------------------------- request

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = tokenStore.get();
  if (token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, errorMessage(0, null));
  }

  reportStatus(response.status, Boolean(token));
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, errorMessage(response.status, body), (body as { detail?: unknown })?.detail, body);
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

const json = (body: unknown) => JSON.stringify(body);

/** Fetch a file the API serves as an attachment and hand it to the browser to save. */
export async function download(path: string): Promise<void> {
  const headers: Record<string, string> = {};
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}${path}`, { headers });
  } catch {
    throw new ApiError(0, errorMessage(0, null));
  }
  reportStatus(response.status, Boolean(token));
  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, errorMessage(response.status, payload));
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "download";
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------- endpoints

export const api = {
  register: (username: string, password: string) =>
    request<{ id: number; username: string }>("/auth/register", { method: "POST", body: json({ username, password }) }),
  login: (username: string, password: string) =>
    request<{ access_token: string }>("/auth/login", { method: "POST", body: json({ username, password }) }),
  me: () => request<User>("/auth/me"),
  /** The server signs out every other session; keep this one going with the token it returns. */
  changePassword: async (current_password: string, new_password: string) => {
    const { access_token } = await request<{ access_token: string }>("/auth/me/password", {
      method: "PATCH",
      body: json({ current_password, new_password }),
    });
    tokenStore.set(access_token);
  },

  providers: () => request<Provider[]>("/api/providers"),
  providerKeys: () => request<ProviderKey[]>("/api/provider-keys"),
  saveProviderKey: (body: { provider: string; key: string; base_url?: string; validate?: boolean }) =>
    request<ProviderKey>("/api/provider-keys", { method: "POST", body: json(body) }),
  deleteProviderKey: (id: number) => request<void>(`/api/provider-keys/${id}`, { method: "DELETE" }),
  validateProviderKey: (provider: string) =>
    request<KeyValidation>(`/api/provider-keys/${encodeURIComponent(provider)}/validate`, { method: "POST" }),

  documents: () => request<DocumentSummary[]>("/api/documents"),
  document: (id: number) => request<DocumentDetail>(`/api/documents/${id}`),
  uploadDocument: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DocumentAccepted>("/api/documents", { method: "POST", body: form });
  },
  reindexDocument: (id: number) => request<DocumentAccepted>(`/api/documents/${id}/reindex`, { method: "POST" }),
  deleteDocument: (id: number) => request<void>(`/api/documents/${id}`, { method: "DELETE" }),

  embeddingSettings: () => request<EmbeddingSettings>("/api/settings/embeddings"),
  saveEmbeddingSettings: (body: { provider: string; model?: string }) =>
    request<EmbeddingSettings>("/api/settings/embeddings", { method: "PUT", body: json(body) }),
  reindexForEmbeddings: (scope: "outdated" | "all" = "outdated") =>
    request<{ queued: number; document_ids: number[] }>("/api/settings/embeddings/reindex", {
      method: "POST",
      body: json({ scope }),
    }),

  prompts: () => request<PromptSummary[]>("/api/prompts"),
  prompt: (id: number) => request<PromptDetail>(`/api/prompts/${id}`),
  defaultPrompt: () => request<{ template: string }>("/api/prompts/default"),
  createPrompt: (body: { name: string; description?: string; template: string; note?: string }) =>
    request<PromptDetail>("/api/prompts", { method: "POST", body: json(body) }),
  updatePrompt: (id: number, body: { name?: string; description?: string }) =>
    request<PromptDetail>(`/api/prompts/${id}`, { method: "PATCH", body: json(body) }),
  addPromptVersion: (id: number, body: { template: string; note?: string }) =>
    request<PromptVersion>(`/api/prompts/${id}/versions`, { method: "POST", body: json(body) }),
  clonePrompt: (id: number, name?: string) =>
    request<PromptDetail>(`/api/prompts/${id}/clone`, { method: "POST", body: json({ name }) }),
  deletePrompt: (id: number) => request<void>(`/api/prompts/${id}`, { method: "DELETE" }),

  experiments: () => request<Experiment[]>("/api/experiments"),
  experiment: (id: number) => request<Experiment>(`/api/experiments/${id}`),
  createExperiment: (body: {
    name: string;
    cases: ExperimentCase[];
    variants: ExperimentVariantInput[];
    evaluate?: boolean;
    evaluator?: string;
    /** Answers worked on at once (1 to 16); the server's default if left out. */
    concurrency?: number;
    run?: boolean;
  }) => request<Experiment>("/api/experiments", { method: "POST", body: json(body) }),
  runExperiment: (id: number) => request<Experiment>(`/api/experiments/${id}/run`, { method: "POST" }),
  deleteExperiment: (id: number) => request<void>(`/api/experiments/${id}`, { method: "DELETE" }),
  compareExperiment: (id: number) => request<ExperimentComparison>(`/api/experiments/${id}/compare`),
  /** The export as a file (CSV or JSON), named by the server. */
  exportExperiment: (id: number, format: "csv" | "json") => download(`/api/experiments/${id}/export?format=${format}`),

  conversations: () => request<Conversation[]>("/api/conversations"),
  conversation: (id: number) => request<ConversationDetail>(`/api/conversations/${id}`),
  createConversation: (body: { title?: string; provider?: string; model?: string } = {}) =>
    request<Conversation>("/api/conversations", { method: "POST", body: json(body) }),
  deleteConversation: (id: number) => request<void>(`/api/conversations/${id}`, { method: "DELETE" }),

  telemetrySummary: (days: number) => request<TelemetrySummary>(`/api/telemetry/summary?days=${days}`),
  /** Usage, evaluation and activity numbers as a file (CSV or JSON). */
  exportMetrics: (days: number, format: "csv" | "json") => download(`/api/export/metrics?days=${days}&format=${format}`),
  telemetryEvents: (limit = 50, offset = 0) =>
    request<{ items: TelemetryEvent[]; total: number }>(`/api/telemetry/events?limit=${limit}&offset=${offset}`),

  evaluators: () => request<EvaluatorInfo[]>("/api/evaluators"),
  evaluate: (body: { message_id: number; reference_answer?: string; provider?: string; model?: string; evaluator?: string }) =>
    request<Evaluation>("/api/evaluations", { method: "POST", body: json(body) }),
  evaluations: (params: { conversation_id?: number; limit?: number; offset?: number } = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && query.set(k, String(v)));
    const qs = query.toString();
    return request<EvaluationHistory>(`/api/evaluations${qs ? `?${qs}` : ""}`);
  },

  /** Resolves on 503 too: that status still carries which subsystem is down. */
  health: () =>
    request<SubsystemHealth>("/api/health/subsystems").catch((e: unknown) => {
      if (e instanceof ApiError && e.status === 503 && e.body) return e.body as SubsystemHealth;
      throw e;
    }),
};
