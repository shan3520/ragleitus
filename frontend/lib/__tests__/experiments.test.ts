import type { ExperimentComparison, VariantSummary } from "../api";
import { isBest, judgeChartRows, parseCases, progressPercent } from "../experiments";

it("reads one question per line with an optional reference answer", () => {
  expect(parseCases("  What is E-4711? | The certificate expired.\n\nHow much leave?\n")).toEqual([
    { question: "What is E-4711?", reference_answer: "The certificate expired." },
    { question: "How much leave?", reference_answer: null },
  ]);
  expect(parseCases("   ")).toEqual([]);
});

it("reads a pasted JSON list", () => {
  expect(parseCases('["Q1", {"question": " Q2 ", "reference_answer": "R2"}, {"question": ""}]')).toEqual([
    { question: "Q1" },
    { question: "Q2", reference_answer: "R2" },
  ]);
  expect(() => parseCases("[not json")).toThrow("could not be read");
  expect(() => parseCases('[1, {"question": "x"}]')).not.toThrow();
});

it("reports progress", () => {
  expect(progressPercent({ done: 1, total: 3 })).toBe(33);
  expect(progressPercent({ done: 0, total: 0 })).toBe(0);
});

const variant = (id: number, faithfulness: number | null, recall: number | null): VariantSummary =>
  ({
    id,
    label: `V${id}`,
    averages: { faithfulness, answer_relevancy: 0.5, context_precision: null, context_recall: recall },
  }) as unknown as VariantSummary;

it("charts each judge metric that some variant has, one value per variant", () => {
  const rows = judgeChartRows([variant(1, 0.9, null), variant(2, 0.7, null)]);
  expect(rows.map((r) => r.metric)).toEqual(["Faithfulness", "Answer relevancy"]);
  expect(rows[0]).toEqual({ metric: "Faithfulness", "1": 0.9, "2": 0.7 });
});

it("knows the best variant per metric", () => {
  const comparison = { best: { faithfulness: 2 } } as unknown as ExperimentComparison;
  expect(isBest(comparison, "faithfulness", 2)).toBe(true);
  expect(isBest(comparison, "faithfulness", 1)).toBe(false);
  expect(isBest(comparison, "cost_usd", 1)).toBe(false);
});
