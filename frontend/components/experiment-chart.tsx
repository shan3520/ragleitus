"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipContentProps } from "recharts";

import type { VariantSummary } from "@/lib/api";
import { judgeChartRows } from "@/lib/experiments";
import { useCssVars } from "@/lib/use-css-vars";

const SLOTS = ["series-1", "series-2", "series-3", "series-4", "series-5", "series-6"] as const;
const BAR_MAX = 28;

/** Variant colors in fixed categorical order: the nth variant always gets slot n. */
export function useVariantColors(count: number): string[] {
  const colors = useCssVars(SLOTS);
  return SLOTS.slice(0, count).map((slot) => colors[slot]);
}

function ChartTooltip({
  active,
  payload,
  label,
  variants,
  colors,
}: TooltipContentProps<number, string> & { variants: VariantSummary[]; colors: string[] }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload as Record<string, number | null>;
  return (
    <div className="rounded-md border bg-card px-3 py-2 text-xs shadow-md">
      <p className="mb-1 text-muted-foreground">{label}</p>
      {variants.map((v, i) => (
        <p key={v.id} className="flex items-center gap-2">
          <span className="inline-block h-0.5 w-3 rounded" style={{ background: colors[i] }} aria-hidden />
          <span className="font-semibold tabular-nums text-foreground">
            {row[String(v.id)] == null ? "–" : Number(row[String(v.id)]).toFixed(2)}
          </span>
          <span className="text-muted-foreground">{v.label}</span>
        </p>
      ))}
    </div>
  );
}

export function VariantLegend({ variants, colors }: { variants: VariantSummary[]; colors: string[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Legend">
      {variants.map((v, i) => (
        <li key={v.id} className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-sm" style={{ background: colors[i] }} aria-hidden />
          {v.label}
        </li>
      ))}
    </ul>
  );
}

/** Judge scores (0-1) per metric, one bar per variant. */
export function JudgeScoresChart({ variants }: { variants: VariantSummary[] }) {
  const colors = useVariantColors(variants.length);
  const ui = useCssVars(["chart-grid", "muted-foreground", "card"] as const);
  const rows = judgeChartRows(variants);
  if (!rows.length) return null;
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={rows} margin={{ top: 8, right: 4, bottom: 0, left: 4 }} barCategoryGap="22%" barGap={2}>
        <CartesianGrid vertical={false} stroke={ui["chart-grid"]} strokeWidth={1} />
        <XAxis dataKey="metric" tickLine={false} axisLine={{ stroke: ui["chart-grid"] }} tick={{ fill: ui["muted-foreground"], fontSize: 11 }} />
        <YAxis
          domain={[0, 1]}
          ticks={[0, 0.25, 0.5, 0.75, 1]}
          tickLine={false}
          axisLine={false}
          tick={{ fill: ui["muted-foreground"], fontSize: 11 }}
          width={36}
        />
        <Tooltip
          cursor={{ fill: ui["chart-grid"], opacity: 0.6 }}
          content={(props) => (
            <ChartTooltip {...(props as TooltipContentProps<number, string>)} variants={variants} colors={colors} />
          )}
        />
        {variants.map((v, i) => (
          <Bar
            key={v.id}
            dataKey={String(v.id)}
            name={v.label}
            fill={colors[i]}
            maxBarSize={BAR_MAX}
            radius={[4, 4, 0, 0]}
            // A surface-colored edge keeps a gap between neighbouring bars.
            stroke={ui.card}
            strokeWidth={1}
            isAnimationActive={false}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
