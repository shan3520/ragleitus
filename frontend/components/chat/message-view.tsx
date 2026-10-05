"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, FileText, FlaskConical } from "lucide-react";

import { api, type Citation, type Evaluation, type Source } from "@/lib/api";
import { citationLabel, citationTarget } from "@/lib/citations";
import { DEFAULT_EVALUATOR, useEvaluators } from "@/lib/evaluators";
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
  /** Retrieval problems, e.g. documents that could only be searched by keyword. */
  warnings?: string[];
  /** The answer's latest saved evaluation, if it has one. */
  evaluation?: Evaluation;
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

function EvaluateButton({ messageId, saved }: { messageId: number; saved?: Evaluation }) {
  const [evaluation, setEvaluation] = useState<Evaluation | null>(saved ?? null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const evaluators = useEvaluators();
  const [evaluator, setEvaluator] = useState(DEFAULT_EVALUATOR);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setEvaluation(await api.evaluate({ message_id: messageId, evaluator }));
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
      {evaluators.length > 1 && (
        <select
          aria-label="Evaluator"
          className="h-7 rounded-md border bg-background px-2 text-xs text-muted-foreground"
          value={evaluator}
          onChange={(e) => setEvaluator(e.target.value)}
          disabled={busy}
        >
          {evaluators.map((e) => (
            <option key={e.name} value={e.name} title={e.description}>
              {e.label}
            </option>
          ))}
        </select>
      )}
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
      {item.warnings?.map((warning) => (
        <p key={warning} className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>{warning}</span>
        </p>
      ))}
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
      {!item.streaming && item.messageId && <EvaluateButton messageId={item.messageId} saved={item.evaluation} />}
    </div>
  );
}
