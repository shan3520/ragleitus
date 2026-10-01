import { API_PREFIX, ApiError, Citation, errorMessage, Message, reportStatus, Source, tokenStore, TurnDone } from "./api";
import type { ChatItem } from "@/components/chat/message-view";
import { readSse } from "./sse";

export interface SendMessageBody {
  content: string;
  provider?: string;
  model?: string;
  document_ids?: number[];
}

export interface TurnHandlers {
  onSources?: (sources: Source[]) => void;
  onToken?: (text: string) => void;
  onCitations?: (citations: Citation[]) => void;
  onDone?: (done: TurnDone) => void;
}

/**
 * Send a message and stream the answer. Resolves when the stream ends.
 * Throws ApiError if the request is refused (e.g. no key for the provider)
 * or the provider fails mid-stream.
 */
export async function streamMessage(
  conversationId: number,
  body: SendMessageBody,
  handlers: TurnHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json", Accept: "text/event-stream" };
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}/api/conversations/${conversationId}/messages`, {
      method: "POST",
      headers,
      body: JSON.stringify({ ...body, stream: true }),
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, errorMessage(0, null));
  }

  reportStatus(response.status, Boolean(token));
  if (!response.ok || !response.body) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, errorMessage(response.status, payload));
  }

  for await (const event of readSse(response.body)) {
    const data = JSON.parse(event.data);
    switch (event.event) {
      case "sources":
        handlers.onSources?.(data.sources);
        break;
      case "token":
        handlers.onToken?.(data.text);
        break;
      case "citations":
        handlers.onCitations?.(data.citations);
        break;
      case "done":
        handlers.onDone?.(data);
        break;
      case "error":
        throw new ApiError(data.status_code ?? 502, data.message);
    }
  }
}

/** Stored messages as the chat view shows them. */
export function toChatItems(messages: Message[]): ChatItem[] {
  return messages.map((m) => ({
    key: `m${m.id}`,
    role: m.role,
    content: m.content,
    messageId: m.role === "assistant" ? m.id : undefined,
    citations: m.citations,
    meta:
      m.role === "assistant"
        ? {
            model: m.model,
            promptTokens: m.prompt_tokens,
            completionTokens: m.completion_tokens,
            latencyMs: m.latency_ms,
            finishReason: m.finish_reason,
          }
        : undefined,
  }));
}
