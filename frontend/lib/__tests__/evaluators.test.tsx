import { renderHook, waitFor } from "@testing-library/react";

import { api } from "../api";
import { evaluatorLabel, resetEvaluatorCache, useEvaluators } from "../evaluators";

afterEach(() => {
  jest.restoreAllMocks();
  resetEvaluatorCache();
});

const ALL = [
  { name: "builtin", label: "Built-in judge", description: "", available: true },
  { name: "ragas", label: "Ragas", description: "", available: false },
  { name: "deepeval", label: "DeepEval", description: "", available: true },
];

it("offers only the evaluators installed on the server, fetched once", async () => {
  const spy = jest.spyOn(api, "evaluators").mockResolvedValue(ALL);
  const first = renderHook(() => useEvaluators());
  const second = renderHook(() => useEvaluators());
  await waitFor(() => expect(first.result.current.map((e) => e.name)).toEqual(["builtin", "deepeval"]));
  await waitFor(() => expect(second.result.current).toHaveLength(2));
  expect(spy).toHaveBeenCalledTimes(1);
});

it("labels evaluators, also without the list", () => {
  expect(evaluatorLabel("deepeval", ALL)).toBe("DeepEval");
  expect(evaluatorLabel("ragas")).toBe("Ragas");
  expect(evaluatorLabel("other")).toBe("other");
});
