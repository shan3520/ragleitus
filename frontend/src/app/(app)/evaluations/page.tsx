"use client";

import Link from "next/link";

import { Page, PageHeader } from "@/components/app-shell";
import { METRIC_LABELS, scoreTone } from "@/components/chat/evaluation-scores";
import { StatTile } from "@/components/stat-tile";
import { Alert } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, type Evaluation } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { cn, formatDate, formatPercent } from "@/lib/utils";

const METRICS = ["faithfulness", "answer_relevancy", "context_precision", "context_recall", "hallucination"] as const;
const TONE_CLASS = { good: "text-success", ok: "", bad: "text-destructive" };

function Score({ metric, value }: { metric: string; value: number | null }) {
  if (value === null) return <span className="text-muted-foreground">n/a</span>;
  return <span className={cn("tabular-nums", TONE_CLASS[scoreTone(metric, value)])}>{formatPercent(value)}</span>;
}

function Row({ evaluation }: { evaluation: Evaluation }) {
  return (
    <TR>
      <TD className="whitespace-nowrap text-xs">{formatDate(evaluation.created_at)}</TD>
      {METRICS.map((m) => (
        <TD key={m} className="text-right">
          <Score metric={m} value={evaluation[m]} />
        </TD>
      ))}
      <TD className="max-w-72 text-xs text-muted-foreground" title={evaluation.rationale ?? undefined}>
        <p className="line-clamp-2">{evaluation.rationale ?? "—"}</p>
      </TD>
      <TD className="whitespace-nowrap text-xs">
        {evaluation.conversation_id ? (
          <Link href={`/chat?c=${evaluation.conversation_id}`} className="text-primary hover:underline">
            Open chat
          </Link>
        ) : (
          "—"
        )}
      </TD>
    </TR>
  );
}

export default function EvaluationsPage() {
  const history = useApi(() => api.evaluations({ limit: 100 }));
  const data = history.data;

  return (
    <Page>
      <PageHeader
        title="Evaluations"
        description="LLM-judge scores for chat answers. Run one from any answer with “Evaluate answer”."
      />
      {history.error && <Alert variant="destructive">{history.error}</Alert>}
      {!data && !history.error && <Skeleton className="h-40" />}
      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            {METRICS.map((m) => (
              <StatTile
                key={m}
                label={`Avg. ${METRIC_LABELS[m].toLowerCase()}`}
                value={data.averages[m] == null ? "n/a" : formatPercent(data.averages[m])}
                detail={m === "hallucination" ? "Lower is better" : m === "context_recall" ? "Needs a reference answer" : "Higher is better"}
              />
            ))}
          </div>
          <Card>
            <CardHeader>
              <CardTitle>
                {data.total} evaluation{data.total === 1 ? "" : "s"}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {data.items.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No evaluations yet. Open a conversation in{" "}
                  <Link href="/chat" className="text-primary hover:underline">
                    Chat
                  </Link>{" "}
                  and press “Evaluate answer” under a reply.
                </p>
              ) : (
                <Table>
                  <THead>
                    <TR>
                      <TH>When</TH>
                      {METRICS.map((m) => (
                        <TH key={m} className="text-right">
                          {METRIC_LABELS[m]}
                        </TH>
                      ))}
                      <TH>Judge’s note</TH>
                      <TH />
                    </TR>
                  </THead>
                  <TBody>
                    {data.items.map((e) => (
                      <Row key={e.id} evaluation={e} />
                    ))}
                  </TBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </Page>
  );
}
