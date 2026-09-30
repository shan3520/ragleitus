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

/**
 * One point per calendar day in the window, oldest first. The API only
 * returns days that had calls; missing days are zero so the axis is honest.
 */
export function fillDays(daily: TelemetrySummary["daily"], days: number, now: Date = new Date()): DayPoint[] {
  const byDate = new Map(daily.map((d) => [d.date, d]));
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  const points: DayPoint[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const date = new Date(today - i * DAY_MS).toISOString().slice(0, 10);
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
