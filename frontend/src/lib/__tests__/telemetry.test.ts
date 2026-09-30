import { compact, fillDays } from "../telemetry";

const bucket = (date: string, requests: number, errors: number, cost: number) => ({
  date,
  requests,
  errors,
  cost_usd: cost,
  prompt_tokens: 100,
  completion_tokens: 20,
  avg_latency_ms: 500,
});

describe("fillDays", () => {
  const now = new Date("2026-09-30T15:00:00Z");

  it("returns one point per day, oldest first, ending today", () => {
    const points = fillDays([], 7, now);
    expect(points).toHaveLength(7);
    expect(points[0].date).toBe("2026-09-24");
    expect(points[6].date).toBe("2026-09-30");
    expect(points.every((p) => p.requests === 0 && p.cost === 0)).toBe(true);
  });

  it("places reported days and splits ok from errors", () => {
    const points = fillDays([bucket("2026-09-29", 5, 2, 0.01)], 7, now);
    const day = points.find((p) => p.date === "2026-09-29")!;
    expect(day).toMatchObject({ requests: 5, errors: 2, ok: 3, cost: 0.01, tokens: 120 });
  });

  it("ignores days outside the window", () => {
    const points = fillDays([bucket("2026-08-01", 9, 0, 1)], 7, now);
    expect(points.reduce((sum, p) => sum + p.requests, 0)).toBe(0);
  });
});

it("compacts only large numbers", () => {
  expect(compact(1284)).toBe("1,284");
  expect(compact(12900)).toBe("12.9K");
});
