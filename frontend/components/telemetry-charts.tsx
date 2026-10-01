"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipContentProps } from "recharts";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useCssVars } from "@/lib/use-css-vars";
import type { DayPoint } from "@/lib/telemetry";
import { formatCost, formatNumber } from "@/lib/utils";

const CHART_HEIGHT = 200;
const BAR_MAX = 24; // thin marks: cap bar thickness, let the rest be air

interface SeriesSpec {
  key: "ok" | "errors" | "cost";
  name: string;
  color: string;
  format: (v: number) => string;
}

/** Values lead, names follow; each row keyed by a short stroke in the series color. */
function ChartTooltip({ active, payload, label, series }: TooltipContentProps<number, string> & { series: SeriesSpec[] }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload as DayPoint;
  return (
    <div className="rounded-md border bg-card px-3 py-2 text-xs shadow-md">
      <p className="mb-1 text-muted-foreground">{label}</p>
      {series.map((s) => (
        <p key={s.key} className="flex items-center gap-2">
          <span className="inline-block h-0.5 w-3 rounded" style={{ background: s.color }} aria-hidden />
          <span className="font-semibold tabular-nums text-foreground">{s.format(point[s.key])}</span>
          <span className="text-muted-foreground">{s.name}</span>
        </p>
      ))}
    </div>
  );
}

function Legend({ series }: { series: SeriesSpec[] }) {
  return (
    <ul className="flex gap-4 text-xs text-muted-foreground" aria-label="Legend">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-sm" style={{ background: s.color }} aria-hidden />
          {s.name}
        </li>
      ))}
    </ul>
  );
}

function DailyBars({
  data,
  series,
  yFormat,
  axisColor,
  gridColor,
  surface,
}: {
  data: DayPoint[];
  series: SeriesSpec[];
  yFormat: (v: number) => string;
  axisColor: string;
  gridColor: string;
  surface: string;
}) {
  const stacked = series.length > 1;
  return (
    <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
      <BarChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: 4 }} barCategoryGap="25%">
        <CartesianGrid vertical={false} stroke={gridColor} strokeWidth={1} />
        <XAxis
          dataKey="label"
          tickLine={false}
          axisLine={{ stroke: gridColor }}
          tick={{ fill: axisColor, fontSize: 11 }}
          interval="preserveStartEnd"
          minTickGap={24}
        />
        <YAxis tickLine={false} axisLine={false} tick={{ fill: axisColor, fontSize: 11 }} tickFormatter={yFormat} width={48} allowDecimals={!stacked} />
        <Tooltip
          cursor={{ fill: gridColor, opacity: 0.6 }}
          content={(props) => <ChartTooltip {...(props as TooltipContentProps<number, string>)} series={series} />}
        />
        {series.map((s, i) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.name}
            stackId={stacked ? "day" : undefined}
            fill={s.color}
            maxBarSize={BAR_MAX}
            // Rounded data-end on the top segment only; square at the baseline.
            radius={i === series.length - 1 ? [4, 4, 0, 0] : 0}
            // A surface-colored edge acts as the 2px gap between stacked segments.
            stroke={stacked ? surface : undefined}
            strokeWidth={stacked ? 1 : 0}
            isAnimationActive={false}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function TelemetryCharts({ points, unpriced = 0 }: { points: DayPoint[]; unpriced?: number }) {
  const colors = useCssVars(["series-1", "status-critical", "chart-grid", "muted-foreground", "card"] as const);
  const requestSeries: SeriesSpec[] = [
    { key: "ok", name: "Succeeded", color: colors["series-1"], format: (v) => formatNumber(v) },
    { key: "errors", name: "Failed", color: colors["status-critical"], format: (v) => formatNumber(v) },
  ];
  const costSeries: SeriesSpec[] = [{ key: "cost", name: "Cost", color: colors["series-1"], format: formatCost }];
  const anyCost = points.some((p) => p.cost > 0);
  const common = { data: points, axisColor: colors["muted-foreground"], gridColor: colors["chart-grid"], surface: colors.card };

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-2">
          <div>
            <CardTitle>Requests per day</CardTitle>
            <CardDescription>LLM calls from chat and evaluation</CardDescription>
          </div>
          <Legend series={requestSeries} />
        </CardHeader>
        <CardContent>
          <DailyBars {...common} series={requestSeries} yFormat={(v) => formatNumber(v)} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Cost per day</CardTitle>
          <CardDescription>Estimated from token usage; unpriced models count as $0</CardDescription>
        </CardHeader>
        <CardContent>
          {anyCost ? (
            <DailyBars {...common} series={costSeries} yFormat={formatCost} />
          ) : (
            // An all-zero chart would read as "free"; say why there is nothing to plot.
            <p className="flex items-center justify-center text-center text-sm text-muted-foreground" style={{ height: CHART_HEIGHT }}>
              {unpriced
                ? `No cost to show: ${formatNumber(unpriced)} call${unpriced === 1 ? "" : "s"} used a model without a known price.`
                : "No cost recorded in this range."}
            </p>
          )}
        </CardContent>
      </Card>
      <details className="rounded-xl border bg-card px-5 py-3 text-sm lg:col-span-2">
        <summary className="cursor-pointer text-muted-foreground">View daily numbers as a table</summary>
        <Table className="mt-3">
          <THead>
            <TR>
              <TH>Day</TH>
              <TH className="text-right">Requests</TH>
              <TH className="text-right">Failed</TH>
              <TH className="text-right">Tokens</TH>
              <TH className="text-right">Cost</TH>
            </TR>
          </THead>
          <TBody>
            {points
              .filter((p) => p.requests > 0)
              .reverse()
              .map((p) => (
                <TR key={p.date}>
                  <TD>{p.date}</TD>
                  <TD className="text-right tabular-nums">{formatNumber(p.requests)}</TD>
                  <TD className="text-right tabular-nums">{formatNumber(p.errors)}</TD>
                  <TD className="text-right tabular-nums">{formatNumber(p.tokens)}</TD>
                  <TD className="text-right tabular-nums">{formatCost(p.cost)}</TD>
                </TR>
              ))}
          </TBody>
        </Table>
      </details>
    </div>
  );
}
