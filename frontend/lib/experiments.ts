import type { ExperimentCase, ExperimentComparison, ExperimentMetric, ExperimentStatus, VariantSummary } from "./api";
import { formatCost, formatMs } from "./utils";

export interface MetricSpec {
  key: ExperimentMetric;
  label: string;
  /** Whether a higher value is better. */
  higher: boolean;
  format: (v: number) => string;
  /** A 0-1 score from the judge (charted together). */
  judge: boolean;
}

const score = (v: number) => v.toFixed(2);

export const METRICS: MetricSpec[] = [
  { key: "quality", label: "Quality", higher: true, format: score, judge: false },
  { key: "faithfulness", label: "Faithfulness", higher: true, format: score, judge: true },
  { key: "answer_relevancy", label: "Answer relevancy", higher: true, format: score, judge: true },
  { key: "context_precision", label: "Context precision", higher: true, format: score, judge: true },
  { key: "context_recall", label: "Context recall", higher: true, format: score, judge: true },
  { key: "hallucination", label: "Hallucination", higher: false, format: score, judge: false },
  { key: "rouge_l", label: "ROUGE-L", higher: true, format: score, judge: false },
  { key: "latency_ms", label: "Latency", higher: false, format: formatMs, judge: false },
  { key: "cost_usd", label: "Cost per answer", higher: false, format: formatCost, judge: false },
];

export const MAX_VARIANTS = 6;

/** Choices for how many answers an experiment works on at once (the API allows 1 to 16). */
export const CONCURRENCY_OPTIONS = [1, 2, 4, 8, 16] as const;

/**
 * Questions from pasted text: one per line, optionally followed by " | " and a
 * reference answer. A JSON array of {question, reference_answer} (or of
 * strings) is accepted too, so an exported list can be pasted back.
 */
export function parseCases(text: string): ExperimentCase[] {
  const trimmed = text.trim();
  if (!trimmed) return [];
  if (trimmed.startsWith("[")) {
    let data: unknown;
    try {
      data = JSON.parse(trimmed);
    } catch {
      throw new Error("The questions look like JSON but could not be read.");
    }
    if (!Array.isArray(data)) throw new Error("Expected a JSON list of questions.");
    return data
      .map((item) =>
        typeof item === "string"
          ? { question: item.trim() }
          : { question: String(item?.question ?? "").trim(), reference_answer: item?.reference_answer?.trim() || null },
      )
      .filter((c) => c.question);
  }
  return trimmed
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [question, ...rest] = line.split(" | ");
      const reference = rest.join(" | ").trim();
      return { question: question.trim(), reference_answer: reference || null };
    });
}

export function isRunning(status: ExperimentStatus): boolean {
  return status === "queued" || status === "running";
}

export const STATUS_LABELS: Record<ExperimentStatus, string> = {
  draft: "Not run",
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
};

export function progressPercent(progress: { done: number; total: number }): number {
  return progress.total ? Math.round((progress.done / progress.total) * 100) : 0;
}

/** The judge metrics as chart rows: one row per metric, one value per variant (keyed by variant id). */
export function judgeChartRows(variants: VariantSummary[]): Array<Record<string, string | number | null>> {
  return METRICS.filter((m) => m.judge)
    .map((m) => {
      const row: Record<string, string | number | null> = { metric: m.label };
      for (const v of variants) row[String(v.id)] = v.averages[m.key];
      return row;
    })
    .filter((row) => variants.some((v) => row[String(v.id)] != null));
}

export function isBest(comparison: ExperimentComparison, metric: ExperimentMetric, variantId: number): boolean {
  return comparison.best[metric] === variantId;
}
