"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, FileText, FlaskConical } from "lucide-react";

import { api, type Citation, type Evaluation, type Source } from "@/lib/api";
import { citationLabel, citationTarget } from "@/lib/citations";
import { cn, formatCost, formatMs, formatNumber } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { EvaluationScores } from "./evaluation-scores";
import { MarkdownAnswer } from "./markdown-answer";

export interface ChatItem {
  key: string;
  role: "user" | "assistant";
  content: string;
  messageId?: number;
  citations?: Citation[] | null;
  sources?: Source[];
  streaming?: boolean;
  error?: string;
  meta?: {
    model?: string | null;
    promptTokens?: number | null;
    completionTokens?: number | null;
    costUsd?: number | null;
    latencyMs?: number | null;
    finishReason?: string | null;
  };
}

function MetaLine({ meta }: { meta: NonNullable<ChatItem["meta"]> }) {
  const parts = [
    meta.model,
    meta.promptTokens != null && meta.completionTokens != null
      ? `${formatNumber(meta.promptTokens)} → ${formatNumber(meta.completionTokens)} tokens`
      : null,
    meta.costUsd != null ? formatCost(meta.costUsd) : null,
    meta.latencyMs != null ? formatMs(meta.latencyMs) : null,
  ].filter(Boolean);
  return <p className="text-xs text-muted-foreground">{parts.join(" · ")}</p>;
}

function Sources({ citations }: { citations: Citation[] }) {
  return (
    <div className="flex flex-wrap gap-1.5" aria-label="Sources">
      {citations.map((c) => (
        <Link
          key={c.number}
          href={citationTarget(c)}
          className="flex max-w-full items-center gap-1.5 rounded-md border bg-background px-2 py-1 text-xs hover:bg-accent"
          title={c.snippet}
        >
          <span className="font-semibold text-primary">{c.number}</span>
          <FileText className="size-3 shrink-0 text-muted-foreground" aria-hidden />
          <span className="truncate">{citationLabel(c)}</span>
        </Link>
      ))}
    </div>
  );
}

function EvaluateButton({ messageId }: { messageId: number }) {
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setEvaluation(await api.evaluate({ message_id: messageId }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (evaluation) {
    return (
      <div className="rounded-lg border bg-background p-3">
        <EvaluationScores evaluation={evaluation} />
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="ghost" size="sm" onClick={run} disabled={busy} className="-ml-2 text-muted-foreground">
        <FlaskConical />
        {busy ? "Evaluating…" : "Evaluate answer"}
      </Button>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </div>
  );
}

export function MessageView({ item }: { item: ChatItem }) {
  if (item.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-primary px-4 py-2 text-sm text-primary-foreground">
          {item.content}
        </div>
      </div>
    );
  }

  const citations = item.citations ?? [];
  const waiting = item.streaming && !item.content;
  return (
    <div className="flex flex-col gap-2" aria-busy={item.streaming || undefined}>
      {waiting ? (
        <p className="text-sm text-muted-foreground">
          {item.sources?.length ? `Reading ${item.sources.length} passage${item.sources.length === 1 ? "" : "s"}…` : "Thinking…"}
        </p>
      ) : (
        <MarkdownAnswer content={item.content} citations={citations} />
      )}
      {item.streaming && item.content && <span className="inline-block h-4 w-1.5 animate-pulse bg-foreground/60" aria-hidden />}
      {item.error && (
        <p className={cn("flex items-center gap-1.5 text-sm text-destructive")} role="alert">
          <AlertTriangle className="size-4" /> {item.error}
        </p>
      )}
      {item.meta?.finishReason === "refusal" && (
        <p className="text-xs text-muted-foreground">The provider declined to answer this question.</p>
      )}
      {citations.length > 0 && <Sources citations={citations} />}
      {!item.streaming && item.meta && <MetaLine meta={item.meta} />}
      {!item.streaming && item.messageId && <EvaluateButton messageId={item.messageId} />}
    </div>
  );
}
