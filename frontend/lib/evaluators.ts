"use client";

import { useEffect, useState } from "react";

import { api, type EvaluatorInfo } from "./api";

export const DEFAULT_EVALUATOR = "builtin";

let cached: Promise<EvaluatorInfo[]> | null = null;

/** The evaluators installed on this server, loaded once per page load. */
export function useEvaluators(): EvaluatorInfo[] {
  const [list, setList] = useState<EvaluatorInfo[]>([]);
  useEffect(() => {
    let alive = true;
    cached ??= api.evaluators().catch(() => {
      cached = null; // try again next time
      return [];
    });
    cached.then((all) => alive && setList(all.filter((e) => e.available)));
    return () => {
      alive = false;
    };
  }, []);
  return list;
}

export function evaluatorLabel(name: string, list: EvaluatorInfo[] = []): string {
  return list.find((e) => e.name === name)?.label ?? { builtin: "Built-in judge", ragas: "Ragas", deepeval: "DeepEval" }[name] ?? name;
}

/** Reset the cache (tests). */
export function resetEvaluatorCache() {
  cached = null;
}
