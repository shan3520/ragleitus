import type { TelemetrySummary } from "./api";

export interface DayPoint {
  date: string; // YYYY-MM-DD (UTC)
  label: string; // short axis label
  ok: number;
  errors: number;
  requests: number;
  cost: number;
  tokens: number;
}

const DAY_MS = 86_400_000;

const startOfUtcDay = (t: number) => t - (((t % DAY_MS) + DAY_MS) % DAY_MS);

/**
 * One point per UTC calendar day in the window, oldest first. The API counts
 * calls from exactly `days` x 24h ago, so the window touches `days + 1`
 * calendar dates (the oldest one partly); every one of them is drawn, so the
 * bars add up to the totals above them. Days without calls are zero.
 */
export function fillDays(daily: TelemetrySummary["daily"], days: number, now: Date = new Date()): DayPoint[] {
  const byDate = new Map(daily.map((d) => [d.date, d]));
  const first = startOfUtcDay(now.getTime() - days * DAY_MS);
  const today = startOfUtcDay(now.getTime());
  const points: DayPoint[] = [];
  for (let t = first; t <= today; t += DAY_MS) {
    const date = new Date(t).toISOString().slice(0, 10);
    const d = byDate.get(date);
    const requests = d?.requests ?? 0;
    const errors = d?.errors ?? 0;
    points.push({
      date,
      label: new Date(`${date}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" }),
      ok: requests - errors,
      errors,
      requests,
      cost: d?.cost_usd ?? 0,
      tokens: (d?.prompt_tokens ?? 0) + (d?.completion_tokens ?? 0),
    });
  }
  return points;
}

/** 1284 -> "1,284", 12900 -> "12.9K" */
export function compact(value: number): string {
  return new Intl.NumberFormat(undefined, { notation: value >= 10_000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(value);
}
