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
  chunks: DocumentChunk[];
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

export interface Conversation {
  id: number;
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
  judge_provider: string;
  judge_model: string;
  faithfulness: number;
  answer_relevancy: number;
  context_precision: number;
  context_recall: number | null;
  hallucination: number;
  rationale: string | null;
  reference_answer: string | null;
  rouge_l: number | null;
  context_overlap: number | null;
  created_at: string;
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

  conversations: () => request<Conversation[]>("/api/conversations"),
  conversation: (id: number) => request<ConversationDetail>(`/api/conversations/${id}`),
  createConversation: (body: { title?: string; provider?: string; model?: string } = {}) =>
    request<Conversation>("/api/conversations", { method: "POST", body: json(body) }),
  deleteConversation: (id: number) => request<void>(`/api/conversations/${id}`, { method: "DELETE" }),

  telemetrySummary: (days: number) => request<TelemetrySummary>(`/api/telemetry/summary?days=${days}`),
  telemetryEvents: (limit = 50, offset = 0) =>
    request<{ items: TelemetryEvent[]; total: number }>(`/api/telemetry/events?limit=${limit}&offset=${offset}`),

  evaluate: (body: { message_id: number; reference_answer?: string; provider?: string; model?: string }) =>
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
