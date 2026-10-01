"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";

import { Page, PageHeader } from "@/components/app-shell";
import { RangeSelect, type Range } from "@/components/range-select";
import { StatTile } from "@/components/stat-tile";
import { TelemetryCharts } from "@/components/telemetry-charts";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { compact, fillDays } from "@/lib/telemetry";
import { useApi } from "@/lib/use-api";
import { cn, formatCost, formatDate, formatMs, formatNumber, formatPercent } from "@/lib/utils";

export default function TelemetryPage() {
  const [days, setDays] = useState<Range>(30);
  const summary = useApi(() => api.telemetrySummary(days), [days]);
  const events = useApi(() => api.telemetryEvents(25));
  const s = summary.data;

  return (
    <Page>
      <PageHeader title="Telemetry" description="Latency, token usage and cost of every LLM call made with your keys." />
      <div>
        <RangeSelect value={days} onChange={setDays} />
      </div>

      {summary.error && <Alert variant="destructive">{summary.error}</Alert>}
      {!s && !summary.error && <Skeleton className="h-64" />}

      {s && (
        // While a new range loads, keep the previous numbers on screen, dimmed.
        <div className={cn("flex flex-col gap-6 transition-opacity", summary.loading && "opacity-60")} aria-busy={summary.loading}>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <StatTile label="Requests" value={compact(s.requests)} detail={`${formatNumber(s.errors)} failed`} />
            <StatTile label="Error rate" value={formatPercent(s.error_rate, 1)} detail={s.errors ? "See recent calls below" : "No failures"} />
            <StatTile label="Median latency" value={formatMs(s.p50_latency_ms)} detail={`p95 ${formatMs(s.p95_latency_ms)}`} />
            <StatTile label="Time to first token" value={formatMs(s.p50_ttft_ms)} detail="Median, streamed calls" />
            <StatTile
              label="Estimated cost"
              value={formatCost(s.cost_usd)}
              detail={
                s.unpriced_requests ? (
                  <span className="flex items-center gap-1">
                    <AlertTriangle className="size-3" aria-hidden /> {s.unpriced_requests} call{s.unpriced_requests === 1 ? "" : "s"} without a price
                  </span>
                ) : (
                  `${compact(s.prompt_tokens + s.completion_tokens)} tokens`
                )
              }
            />
          </div>

          {s.requests === 0 ? (
            <Card>
              <CardContent className="py-10 text-center text-sm text-muted-foreground">
                No LLM calls in the last {s.days} days. Ask a question in Chat to see numbers here.
              </CardContent>
            </Card>
          ) : (
            <TelemetryCharts points={fillDays(s.daily, s.days)} unpriced={s.unpriced_requests} />
          )}

          {s.by_model.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>By model</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <THead>
                    <TR>
                      <TH>Provider</TH>
                      <TH>Model</TH>
                      <TH className="text-right">Requests</TH>
                      <TH className="text-right">Failed</TH>
                      <TH className="text-right">Prompt tokens</TH>
                      <TH className="text-right">Completion tokens</TH>
                      <TH className="text-right">Avg latency</TH>
                      <TH className="text-right">Cost</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {s.by_model.map((m) => (
                      <TR key={`${m.provider}/${m.model}`}>
                        <TD>{m.provider}</TD>
                        <TD className="font-mono text-xs">{m.model}</TD>
                        <TD className="text-right tabular-nums">{formatNumber(m.requests)}</TD>
                        <TD className="text-right tabular-nums">{formatNumber(m.errors)}</TD>
                        <TD className="text-right tabular-nums">{formatNumber(m.prompt_tokens)}</TD>
                        <TD className="text-right tabular-nums">{formatNumber(m.completion_tokens)}</TD>
                        <TD className="text-right tabular-nums">{formatMs(m.avg_latency_ms)}</TD>
                        <TD className="text-right tabular-nums">{formatCost(m.cost_usd)}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Recent calls</CardTitle>
        </CardHeader>
        <CardContent>
          {events.error && <Alert variant="destructive">{events.error}</Alert>}
          {events.data && events.data.items.length === 0 && <p className="text-sm text-muted-foreground">No calls yet.</p>}
          {events.data && events.data.items.length > 0 && (
            <Table>
              <THead>
                <TR>
                  <TH>When</TH>
                  <TH>Operation</TH>
                  <TH>Model</TH>
                  <TH>Status</TH>
                  <TH className="text-right">Tokens</TH>
                  <TH className="text-right">Latency</TH>
                  <TH className="text-right">Cost</TH>
                </TR>
              </THead>
              <TBody>
                {events.data.items.map((e) => (
                  <TR key={e.id}>
                    <TD className="whitespace-nowrap text-xs">{formatDate(e.created_at)}</TD>
                    <TD className="capitalize">{e.operation}</TD>
                    <TD className="font-mono text-xs">
                      {e.provider}/{e.model}
                    </TD>
                    <TD>
                      {e.status === "ok" ? (
                        <Badge variant="success">OK</Badge>
                      ) : (
                        <Badge variant="destructive" title={e.error_type ?? undefined}>
                          <AlertTriangle /> {e.error_type ?? "Error"}
                        </Badge>
                      )}
                    </TD>
                    <TD className="text-right tabular-nums" title={e.tokens_estimated ? "Estimated: the provider did not report usage" : undefined}>
                      {e.prompt_tokens != null ? `${formatNumber(e.prompt_tokens)} → ${formatNumber(e.completion_tokens)}` : "—"}
                      {e.tokens_estimated && " *"}
                    </TD>
                    <TD className="text-right tabular-nums">{formatMs(e.latency_ms)}</TD>
                    <TD className="text-right tabular-nums">{formatCost(e.cost_usd)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
          {events.data?.items.some((e) => e.tokens_estimated) && (
            <p className="mt-2 text-xs text-muted-foreground">* Estimated: the provider did not report token usage.</p>
          )}
        </CardContent>
      </Card>
    </Page>
  );
}
