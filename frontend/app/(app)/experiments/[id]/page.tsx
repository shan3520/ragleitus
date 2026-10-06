"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, Download, Play, Trash2 } from "lucide-react";

import { Page, PageHeader } from "@/components/app-shell";
import { JudgeScoresChart, useVariantColors, VariantLegend } from "@/components/experiment-chart";
import { ExperimentStatusBadge } from "@/components/experiment-status";
import { StatTile } from "@/components/stat-tile";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, type ExperimentComparison } from "@/lib/api";
import { evaluatorLabel } from "@/lib/evaluators";
import { isBest, isRunning, METRICS, progressPercent } from "@/lib/experiments";
import { useApi } from "@/lib/use-api";
import { formatCost, formatDate, formatMs } from "@/lib/utils";

const RETRIEVAL = { hybrid: "Hybrid", dense: "Dense", keyword: "Keyword" } as const;

function VariantTable({ comparison }: { comparison: ExperimentComparison }) {
  const colors = useVariantColors(comparison.variants.length);
  const metrics = METRICS.filter((m) => comparison.variants.some((v) => v.averages[m.key] != null));
  return (
    <div className="overflow-x-auto">
      <Table>
        <THead>
          <TR>
            <TH>Variant</TH>
            {metrics.map((m) => (
              <TH key={m.key} className="text-right">
                {m.label}
                <span className="sr-only">{m.higher ? " (higher is better)" : " (lower is better)"}</span>
              </TH>
            ))}
            <TH className="text-right">Errors</TH>
          </TR>
        </THead>
        <TBody>
          {comparison.variants.map((v, i) => (
            <TR key={v.id}>
              <TD>
                <div className="flex items-center gap-2 font-medium">
                  <span className="inline-block size-2.5 shrink-0 rounded-sm" style={{ background: colors[i] }} aria-hidden />
                  {v.label}
                </div>
                <p className="text-xs text-muted-foreground">
                  {v.prompt_label} · {v.model} · {RETRIEVAL[v.retrieval]}
                  {v.rerank ? ", reranked" : ""}, {v.top_k} passages
                </p>
              </TD>
              {metrics.map((m) => {
                const value = v.averages[m.key];
                const best = isBest(comparison, m.key, v.id);
                return (
                  <TD key={m.key} className="whitespace-nowrap text-right tabular-nums">
                    <span className={best ? "font-semibold" : undefined}>{value == null ? "–" : m.format(value)}</span>
                    {best && <span className="ml-1 text-xs text-muted-foreground">best</span>}
                  </TD>
                );
              })}
              <TD className="text-right tabular-nums">{v.errors}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

function Answers({ comparison }: { comparison: ExperimentComparison }) {
  return (
    <div className="flex flex-col gap-3">
      {comparison.cases.map((c) => (
        <details key={c.index} className="rounded-lg border px-3 py-2" open={comparison.cases.length <= 3}>
          <summary className="cursor-pointer text-sm font-medium">
            {c.index + 1}. {c.question}
          </summary>
          {c.reference_answer && (
            <p className="mt-2 text-xs text-muted-foreground">Reference: {c.reference_answer}</p>
          )}
          <div className="mt-2 grid gap-2 md:grid-cols-2">
            {comparison.variants.map((v) => {
              const r = c.results[String(v.id)];
              return (
                <div key={v.id} className="rounded-md bg-muted/50 p-2 text-sm" data-testid="variant-answer">
                  <p className="mb-1 text-xs font-medium">{v.label}</p>
                  {!r && <p className="text-xs text-muted-foreground">Not answered yet.</p>}
                  {r?.answer && <p className="whitespace-pre-wrap">{r.answer}</p>}
                  {r?.error && <p className="mt-1 text-xs text-destructive">{r.error}</p>}
                  {r && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {[
                        r.quality != null && `quality ${r.quality.toFixed(2)}`,
                        r.faithfulness != null && `faithfulness ${r.faithfulness.toFixed(2)}`,
                        r.rouge_l != null && `ROUGE-L ${r.rouge_l.toFixed(2)}`,
                        r.latency_ms != null && formatMs(r.latency_ms),
                        r.cost_usd != null && formatCost(r.cost_usd),
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </details>
      ))}
    </div>
  );
}

export default function ExperimentPage() {
  const { id } = useParams<{ id: string }>();
  const experimentId = Number(id);
  const router = useRouter();
  const comparison = useApi(() => api.compareExperiment(experimentId), [experimentId]);
  const [error, setError] = useState<string | null>(null);
  const data = comparison.data;
  const experiment = data?.experiment;
  const running = experiment ? isRunning(experiment.status) : false;
  const colors = useVariantColors(data?.variants.length ?? 0);

  // Follow the run until it finishes.
  const { reload, error: loadError } = comparison;
  useEffect(() => {
    if (!running || loadError) return;
    const timer = window.setInterval(() => void reload(), 2000);
    return () => window.clearInterval(timer);
  }, [running, reload, loadError]);

  async function act(action: () => Promise<void>) {
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const priced = data?.variants.filter((v) => v.total_cost_usd != null) ?? [];
  const totalCost = priced.reduce((sum, v) => sum + (v.total_cost_usd ?? 0), 0);
  const bestQuality = data?.best.quality ? data.variants.find((v) => v.id === data.best.quality) : undefined;

  return (
    <Page>
      <Link href="/experiments" className="flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Experiments
      </Link>
      {comparison.error && <Alert variant="destructive">{comparison.error}</Alert>}
      {!data && !comparison.error && <Skeleton className="h-40" />}
      {data && experiment && (
        <>
          <PageHeader
            title={experiment.name}
            description={[
              `Created ${formatDate(experiment.created_at)}`,
              experiment.evaluate ? `scored with ${evaluatorLabel(experiment.evaluator)}` : "not scored",
              `${experiment.concurrency} at once`,
            ].join(" · ")}
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <ExperimentStatusBadge status={experiment.status} />
                <Button
                  variant="outline"
                  disabled={running}
                  onClick={() =>
                    act(async () => {
                      await api.runExperiment(experimentId);
                      await reload();
                    })
                  }
                >
                  <Play /> {experiment.status === "draft" ? "Run" : "Run again"}
                </Button>
                <Button variant="outline" onClick={() => act(() => api.exportExperiment(experimentId, "csv"))}>
                  <Download /> CSV
                </Button>
                <Button variant="outline" onClick={() => act(() => api.exportExperiment(experimentId, "json"))}>
                  <Download /> JSON
                </Button>
                <Button
                  variant="outline"
                  aria-label="Delete experiment"
                  onClick={() =>
                    act(async () => {
                      if (!window.confirm(`Delete "${experiment.name}" and its results?`)) return;
                      await api.deleteExperiment(experimentId);
                      router.push("/experiments");
                    })
                  }
                >
                  <Trash2 />
                </Button>
              </div>
            }
          />
          {error && <Alert variant="destructive">{error}</Alert>}
          {experiment.error && <Alert variant="destructive">The run failed: {experiment.error}</Alert>}
          {running && (
            <div className="flex flex-col gap-1" role="status">
              <p className="text-sm text-muted-foreground">
                Answered {experiment.progress.done} of {experiment.progress.total}…
              </p>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div className="h-full bg-primary transition-all" style={{ width: `${progressPercent(experiment.progress)}%` }} />
              </div>
            </div>
          )}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatTile label="Questions" value={experiment.case_count} />
            <StatTile label="Variants" value={experiment.variants.length} />
            <StatTile
              label="Best quality"
              value={bestQuality ? bestQuality.label : "–"}
              detail={
                bestQuality?.averages.quality != null
                  ? `mean judge score ${bestQuality.averages.quality.toFixed(2)}`
                  : data.variants.some((v) => v.averages.quality != null)
                    ? "no single variant is ahead"
                    : undefined
              }
            />
            <StatTile
              label="Total cost"
              value={priced.length ? formatCost(totalCost) : "–"}
              detail={priced.length ? "estimated from token usage" : "no known price for these models"}
            />
          </div>
          <Card>
            <CardHeader className="flex-row items-start justify-between gap-2">
              <div>
                <CardTitle>Judge scores</CardTitle>
                <CardDescription>Mean per variant, 0 to 1, higher is better</CardDescription>
              </div>
              <VariantLegend variants={data.variants} colors={colors} />
            </CardHeader>
            <CardContent>
              {data.variants.some((v) => v.averages.faithfulness != null) ? (
                <JudgeScoresChart variants={data.variants} />
              ) : (
                <p className="text-sm text-muted-foreground">
                  {running ? "Scores appear as answers are judged." : "No judge scores: this experiment was run without the LLM judge."}
                </p>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Comparison</CardTitle>
              <CardDescription>Averages per variant; the best value of each column is marked</CardDescription>
            </CardHeader>
            <CardContent>
              <VariantTable comparison={data} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Answers</CardTitle>
            </CardHeader>
            <CardContent>
              <Answers comparison={data} />
            </CardContent>
          </Card>
        </>
      )}
    </Page>
  );
}
