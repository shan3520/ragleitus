"use client";

import Link from "next/link";
import { ArrowRight, CheckCircle2, Circle } from "lucide-react";

import { Page, PageHeader } from "@/components/app-shell";
import { isInProgress } from "@/components/document-status";
import { StatTile } from "@/components/stat-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { gettingStartedSteps } from "@/lib/getting-started";
import { compact } from "@/lib/telemetry";
import { useApi } from "@/lib/use-api";
import { cn, formatCost, formatDate, formatMs } from "@/lib/utils";

async function loadOverview() {
  const [keys, documents, conversations, telemetry, health] = await Promise.all([
    api.providerKeys(),
    api.documents(),
    api.conversations(),
    api.telemetrySummary(7),
    api.health().catch(() => null),
  ]);
  return { keys, documents, conversations, telemetry, health };
}

export default function DashboardPage() {
  const { state } = useAuth();
  const overview = useApi(loadOverview);
  const data = overview.data;
  const username = state.status === "signed-in" ? state.user.username : "";

  if (overview.error) {
    return (
      <Page>
        <PageHeader title="Dashboard" />
        <p className="text-sm text-destructive">{overview.error}</p>
      </Page>
    );
  }
  if (!data) {
    return (
      <Page>
        <PageHeader title="Dashboard" />
        <Skeleton className="h-28" />
        <Skeleton className="h-48" />
      </Page>
    );
  }

  const steps = gettingStartedSteps(data);
  const allDone = steps.every((s) => s.done);
  const ready = data.documents.filter((d) => d.status === "ready").length;
  const indexing = data.documents.filter((d) => isInProgress(d.status)).length;
  const failed = data.documents.filter((d) => d.status === "failed").length;
  const t = data.telemetry;

  return (
    <Page>
      <PageHeader
        title={username ? `Welcome, ${username}` : "Dashboard"}
        actions={
          <Button asChild>
            <Link href="/chat">
              Ask a question <ArrowRight />
            </Link>
          </Button>
        }
      />

      {!allDone && (
        <Card>
          <CardHeader>
            <CardTitle>Get started</CardTitle>
            <CardDescription>Three steps to your first cited answer.</CardDescription>
          </CardHeader>
          <CardContent>
            <ol className="flex flex-col gap-2">
              {steps.map((step) => (
                <li key={step.id}>
                  <Link
                    href={step.href}
                    className={cn("flex items-start gap-3 rounded-lg border p-3 transition-colors hover:bg-accent", step.done && "opacity-70")}
                  >
                    {step.done ? (
                      <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" aria-label="Done" />
                    ) : (
                      <Circle className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-label="To do" />
                    )}
                    <span>
                      <span className={cn("block text-sm font-medium", step.done && "line-through")}>{step.title}</span>
                      <span className="block text-xs text-muted-foreground">{step.description}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label="Documents ready"
          value={`${ready} / ${data.documents.length}`}
          detail={[indexing && `${indexing} indexing`, failed && `${failed} failed`].filter(Boolean).join(" · ") || "All indexed"}
        />
        <StatTile label="Provider keys" value={data.keys.length} detail={data.keys.map((k) => k.provider).join(", ") || "None yet"} />
        <StatTile label="LLM calls, last 7 days" value={compact(t.requests)} detail={`Median ${formatMs(t.p50_latency_ms)}`} />
        <StatTile label="Estimated cost, last 7 days" value={formatCost(t.cost_usd)} 
          detail={
            t.unpriced_requests
              ? `${t.unpriced_requests} call${t.unpriced_requests === 1 ? "" : "s"} without a price`
              : `${compact(t.prompt_tokens + t.completion_tokens)} tokens`
          }
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Recent conversations</CardTitle>
            <Link href="/chat" className="text-sm text-primary hover:underline">
              All
            </Link>
          </CardHeader>
          <CardContent>
            {data.conversations.length === 0 ? (
              <p className="text-sm text-muted-foreground">No conversations yet.</p>
            ) : (
              <ul className="divide-y">
                {data.conversations.slice(0, 6).map((c) => (
                  <li key={c.id}>
                    <Link href={`/chat?c=${c.id}`} className="flex items-center justify-between gap-3 py-2 text-sm hover:text-primary">
                      <span className="min-w-0 truncate">{c.title}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">{formatDate(c.updated_at)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>System</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            {data.health ? (
              (["db", "vector_store"] as const).map((k) => (
                <div key={k} className="flex items-center justify-between">
                  <span>{k === "db" ? "Database" : "Vector store"}</span>
                  <Badge variant={data.health![k] === "healthy" ? "success" : "destructive"}>{data.health![k]}</Badge>
                </div>
              ))
            ) : (
              <p className="text-muted-foreground">Health check unavailable.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </Page>
  );
}
