import type { Evaluation } from "@/lib/api";
import { evaluatorLabel } from "@/lib/evaluators";
import { cn, formatPercent } from "@/lib/utils";

export const METRIC_LABELS: Record<string, string> = {
  faithfulness: "Faithfulness",
  answer_relevancy: "Answer relevancy",
  context_precision: "Context precision",
  context_recall: "Context recall",
  hallucination: "Hallucination",
};

export const METRICS = ["faithfulness", "answer_relevancy", "context_precision", "context_recall", "hallucination"] as const;

/** Higher is better for every metric except hallucination. */
export function scoreTone(metric: string, value: number): "good" | "ok" | "bad" {
  const v = metric === "hallucination" ? 1 - value : value;
  return v >= 0.8 ? "good" : v >= 0.5 ? "ok" : "bad";
}

export const TONE_CLASS = { good: "text-success", ok: "text-foreground", bad: "text-destructive" };

export function EvaluationScores({ evaluation, compact = false }: { evaluation: Evaluation; compact?: boolean }) {
  return (
    <div className={cn("flex flex-col gap-2", compact && "gap-1")}>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-5">
        {METRICS.map((m) => {
          const value = evaluation[m];
          return (
            <div key={m} className="flex flex-col">
              <dt className="text-xs text-muted-foreground">{METRIC_LABELS[m]}</dt>
              <dd className={cn("text-sm font-semibold tabular-nums", value !== null && TONE_CLASS[scoreTone(m, value)])}>
                {value === null ? "n/a" : formatPercent(value)}
              </dd>
            </div>
          );
        })}
      </dl>
      {!compact && evaluation.rationale && <p className="text-xs text-muted-foreground">{evaluation.rationale}</p>}
      {!compact && (
        <p className="text-xs text-muted-foreground">
          {evaluatorLabel(evaluation.evaluator ?? "builtin")} · judged by {evaluation.judge_provider} / {evaluation.judge_model}
        </p>
      )}
    </div>
  );
}
