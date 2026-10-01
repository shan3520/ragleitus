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

  it("covers every date the API's window touches, oldest first, ending today", () => {
    // 7 x 24h before 2026-09-30T15:00Z is 2026-09-23T15:00Z, so the 23rd is partly in the window.
    const points = fillDays([], 7, now);
    expect(points).toHaveLength(8);
    expect(points[0].date).toBe("2026-09-23");
    expect(points[7].date).toBe("2026-09-30");
    expect(points.every((p) => p.requests === 0 && p.cost === 0)).toBe(true);
  });

  it("draws the calls from the partial oldest day, so bars add up to the totals", () => {
    const daily = [bucket("2026-09-23", 1, 0, 0.5), bucket("2026-09-30", 2, 0, 0.5)];
    const total = fillDays(daily, 7, now).reduce((sum, p) => sum + p.requests, 0);
    expect(total).toBe(3);
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
