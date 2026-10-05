"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { MessageSquarePlus, Send, Square, Trash2 } from "lucide-react";

import { MessageView, type ChatItem } from "@/components/chat/message-view";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, type ConversationDetail, type EvaluationHistory } from "@/lib/api";
import { streamMessage, toChatItems } from "@/lib/chat";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

function setUrl(conversationId: number | null) {
  window.history.replaceState(null, "", conversationId ? `/chat?c=${conversationId}` : "/chat");
}

function ChatWorkspace() {
  const searchParams = useSearchParams();
  const conversationId = Number(searchParams.get("c")) || null;

  const conversations = useApi(api.conversations);
  const providers = useApi(api.providers);
  const prompts = useApi(api.prompts);
  const configured = (providers.data ?? []).filter((p) => p.configured);

  const [items, setItems] = useState<ChatItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  // A prompt-library version id, or "" for the built-in prompt. "Use in chat" links pass ?prompt=.
  const [promptVersion, setPromptVersion] = useState(() => searchParams.get("prompt") ?? "");
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const createdHere = useRef<number | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  // Load the selected conversation, unless it was just created by this page
  // (its first answer is still streaming into `items`).
  useEffect(() => {
    if (!conversationId) {
      setItems([]);
      return;
    }
    if (createdHere.current === conversationId) return;
    let cancelled = false;
    setLoadError(null);
    Promise.all([
      api.conversation(conversationId),
      // Saved scores are shown under their answers; without them the chat still loads.
      api.evaluations({ conversation_id: conversationId, limit: 500 }).catch(() => null),
    ])
      .then(([c, evaluations]: [ConversationDetail, EvaluationHistory | null]) => {
        if (cancelled) return;
        setItems(toChatItems(c.messages, evaluations?.items));
        setProvider(c.provider ?? "");
        setModel(c.model ?? "");
        setPromptVersion(c.prompt_version_id ? String(c.prompt_version_id) : "");
      })
      .catch((err) => !cancelled && setLoadError(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [items]);

  const updateLast = useCallback((patch: (item: ChatItem) => ChatItem) => {
    setItems((prev) => (prev.length ? [...prev.slice(0, -1), patch(prev[prev.length - 1])] : prev));
  }, []);

  async function send() {
    const content = input.trim();
    if (!content || streaming) return;
    setInput("");
    setStreaming(true);

    const turnKey = `t${Date.now()}`;
    setItems((prev) => [
      ...prev,
      { key: `${turnKey}u`, role: "user", content },
      { key: `${turnKey}a`, role: "assistant", content: "", streaming: true },
    ]);

    const controller = new AbortController();
    abort.current = controller;
    // False once the user opens another conversation: this turn must then leave the screen alone.
    const stillShown = () => abort.current === controller;
    try {
      let id = conversationId;
      if (!id) {
        const created = await api.createConversation({ provider: provider || undefined, model: model || undefined });
        if (!stillShown()) return;
        id = created.id;
        createdHere.current = id;
        setUrl(id);
      }
      await streamMessage(
        id,
        {
          content,
          provider: provider || undefined,
          model: model || undefined,
          prompt_version_id: promptVersion ? Number(promptVersion) : null,
        },
        {
          onSources: (sources, warnings) => updateLast((it) => ({ ...it, sources, warnings })),
          onToken: (text) => updateLast((it) => ({ ...it, content: it.content + text })),
          onCitations: (citations) => updateLast((it) => ({ ...it, citations })),
          onDone: (done) =>
            updateLast((it) => ({
              ...it,
              messageId: done.message_id,
              meta: {
                model: done.model,
                promptTokens: done.prompt_tokens,
                completionTokens: done.completion_tokens,
                costUsd: done.cost_usd,
                latencyMs: done.latency_ms,
                finishReason: done.finish_reason,
              },
            })),
        },
        controller.signal,
      );
    } catch (err) {
      if (stillShown()) {
        const stopped = (err as Error).name === "AbortError";
        updateLast((it) => ({ ...it, error: stopped ? "Stopped." : err instanceof Error ? err.message : String(err) }));
      }
    } finally {
      if (stillShown()) {
        updateLast((it) => ({ ...it, streaming: false }));
        abort.current = null;
      }
      setStreaming(false);
      void conversations.reload();
    }
  }

  function openConversation(id: number | null) {
    // Stop the answer in progress and detach it from the screen (see stillShown in send).
    abort.current?.abort();
    abort.current = null;
    createdHere.current = null;
    setLoadError(null);
    // The load effect only runs when the URL changes; "New chat" from an unsaved chat doesn't change it.
    if (id === null) setItems([]);
    setUrl(id);
  }

  async function removeConversation(id: number) {
    if (!window.confirm("Delete this conversation?")) return;
    try {
      await api.deleteConversation(id);
    } catch (err) {
      setLoadError(`Could not delete the conversation: ${err instanceof Error ? err.message : String(err)}`);
      return;
    }
    if (id === conversationId) openConversation(null);
    void conversations.reload();
  }

  // With a single key there is nothing to choose: show it selected (the API uses it by default).
  const shownProvider = provider || (configured.length === 1 ? configured[0].name : "");
  const selectedSpec = (providers.data ?? []).find((p) => p.name === shownProvider);
  const noKeys = providers.data && configured.length === 0;

  return (
    <div className="flex h-full min-h-0">
      <aside className="hidden w-64 shrink-0 flex-col border-r lg:flex">
        <div className="p-3">
          <Button variant="outline" className="w-full justify-start" onClick={() => openConversation(null)}>
            <MessageSquarePlus /> New chat
          </Button>
        </div>
        <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-3" aria-label="Conversations">
          {(conversations.data ?? []).map((c) => (
            <div
              key={c.id}
              className={cn(
                "group flex items-center rounded-md text-sm",
                c.id === conversationId ? "bg-accent text-accent-foreground" : "hover:bg-accent/60",
              )}
            >
              <button className="min-w-0 flex-1 truncate px-2.5 py-1.5 text-left" onClick={() => openConversation(c.id)} title={c.title}>
                {c.title}
              </button>
              <button
                className="mr-1 rounded p-1 text-muted-foreground opacity-0 hover:text-destructive focus:opacity-100 group-hover:opacity-100"
                onClick={() => removeConversation(c.id)}
                aria-label={`Delete conversation ${c.title}`}
              >
                <Trash2 className="size-3.5" />
              </button>
            </div>
          ))}
          {conversations.data?.length === 0 && <p className="px-2.5 text-xs text-muted-foreground">No conversations yet.</p>}
        </nav>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2">
          <Button variant="outline" size="sm" className="lg:hidden" onClick={() => openConversation(null)}>
            <MessageSquarePlus /> New
          </Button>
          <label className="sr-only" htmlFor="chat-provider">
            Provider
          </label>
          <Select id="chat-provider" className="h-8 w-auto min-w-40" value={shownProvider} onChange={(e) => setProvider(e.target.value)} disabled={streaming}>
            {configured.length !== 1 && <option value="">Choose provider</option>}
            {configured.map((p) => (
              <option key={p.name} value={p.name}>
                {p.label}
              </option>
            ))}
          </Select>
          <label className="sr-only" htmlFor="chat-model">
            Model
          </label>
          <Input
            id="chat-model"
            className="h-8 w-56"
            placeholder={selectedSpec?.default_model || "Model (provider default)"}
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={streaming}
          />
          <label className="sr-only" htmlFor="chat-prompt">
            Prompt
          </label>
          <Select
            id="chat-prompt"
            className="h-8 w-auto min-w-40"
            value={promptVersion}
            onChange={(e) => setPromptVersion(e.target.value)}
            disabled={streaming}
          >
            <option value="">Built-in prompt</option>
            {(prompts.data ?? []).map((p) =>
              p.latest_version ? (
                <option key={p.id} value={String(p.latest_version.id)}>
                  {p.name} v{p.latest_version.version}
                </option>
              ) : null,
            )}
            {promptVersion && prompts.data && !prompts.data.some((p) => String(p.latest_version?.id) === promptVersion) && (
              <option value={promptVersion}>An earlier prompt version</option>
            )}
          </Select>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6">
            {noKeys && (
              <Alert>
                Add an API key on the{" "}
                <Link href="/providers" className="font-medium text-primary hover:underline">
                  Providers
                </Link>{" "}
                page to start chatting.
              </Alert>
            )}
            {loadError && <Alert variant="destructive">{loadError}</Alert>}
            {items.length === 0 && !loadError && (
              <div className="py-16 text-center">
                <h1 className="text-lg font-semibold">Ask your documents</h1>
                <p className="mt-1 text-sm text-muted-foreground">
                  Answers cite the passages they come from. Upload files on the{" "}
                  <Link href="/documents" className="text-primary hover:underline">
                    Documents
                  </Link>{" "}
                  page.
                </p>
              </div>
            )}
            {items.map((item) => (
              <MessageView key={item.key} item={item} />
            ))}
            <div ref={bottom} />
          </div>
        </div>

        <form
          className="border-t p-3"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <label className="sr-only" htmlFor="chat-input">
              Message
            </label>
            <Textarea
              id="chat-input"
              rows={1}
              className="max-h-48 min-h-10 resize-none"
              placeholder="Ask a question about your documents…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            {streaming ? (
              <Button type="button" variant="outline" size="icon" onClick={() => abort.current?.abort()} aria-label="Stop generating">
                <Square />
              </Button>
            ) : (
              <Button type="submit" size="icon" disabled={!input.trim()} aria-label="Send">
                <Send />
              </Button>
            )}
          </div>
        </form>
      </section>
    </div>
  );
}

export default function ChatPage() {
  // useSearchParams needs a Suspense boundary so the page can be prerendered.
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading…</div>}>
      <ChatWorkspace />
    </Suspense>
  );
}
