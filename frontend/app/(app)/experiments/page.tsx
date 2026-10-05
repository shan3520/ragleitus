"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Plus, X } from "lucide-react";

import { Page, PageHeader } from "@/components/app-shell";
import { ExperimentStatusBadge } from "@/components/experiment-status";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { api, type Provider, type PromptSummary, type RetrievalStrategy } from "@/lib/api";
import { DEFAULT_EVALUATOR, useEvaluators } from "@/lib/evaluators";
import { MAX_VARIANTS, parseCases, progressPercent } from "@/lib/experiments";
import { useApi } from "@/lib/use-api";
import { formatDate } from "@/lib/utils";

interface VariantRow {
  key: number;
  label: string;
  promptVersionId: string; // "" = built-in
  provider: string;
  model: string;
  retrieval: RetrievalStrategy;
  topK: string;
}

let nextKey = 1;

function newRow(provider: string, label: string): VariantRow {
  return { key: nextKey++, label, promptVersionId: "", provider, model: "", retrieval: "hybrid", topK: "" };
}

function VariantFields({
  row,
  index,
  providers,
  prompts,
  onChange,
  onRemove,
}: {
  row: VariantRow;
  index: number;
  providers: Provider[];
  prompts: PromptSummary[];
  onChange: (row: VariantRow) => void;
  onRemove?: () => void;
}) {
  const spec = providers.find((p) => p.name === row.provider);
  const id = (field: string) => `variant-${index}-${field}`;
  return (
    <fieldset className="grid gap-3 rounded-lg border p-3 sm:grid-cols-2 lg:grid-cols-6">
      <legend className="flex items-center gap-2 px-1 text-sm font-medium">
        Variant {index + 1}
        {onRemove && (
          <Button type="button" variant="ghost" size="icon" className="size-6" onClick={onRemove} aria-label={`Remove variant ${index + 1}`}>
            <X className="size-3.5" />
          </Button>
        )}
      </legend>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={id("label")}>Label</Label>
        <Input id={id("label")} maxLength={100} value={row.label} onChange={(e) => onChange({ ...row, label: e.target.value })} />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={id("prompt")}>Prompt</Label>
        <Select id={id("prompt")} value={row.promptVersionId} onChange={(e) => onChange({ ...row, promptVersionId: e.target.value })}>
          <option value="">Built-in prompt</option>
          {prompts.map((p) =>
            p.latest_version ? (
              <option key={p.id} value={p.latest_version.id}>
                {p.name} v{p.latest_version.version}
              </option>
            ) : null,
          )}
        </Select>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={id("provider")}>Provider</Label>
        <Select id={id("provider")} value={row.provider} onChange={(e) => onChange({ ...row, provider: e.target.value, model: "" })}>
          {providers.map((p) => (
            <option key={p.name} value={p.name}>
              {p.label}
            </option>
          ))}
        </Select>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={id("model")}>Model</Label>
        <Input
          id={id("model")}
          value={row.model}
          placeholder={spec?.default_model || "model name"}
          onChange={(e) => onChange({ ...row, model: e.target.value })}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={id("retrieval")}>Retrieval</Label>
        <Select
          id={id("retrieval")}
          value={row.retrieval}
          onChange={(e) => onChange({ ...row, retrieval: e.target.value as RetrievalStrategy })}
        >
          <option value="hybrid">Hybrid</option>
          <option value="dense">Dense only</option>
          <option value="keyword">Keyword only</option>
        </Select>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={id("top-k")}>Passages</Label>
        <Input
          id={id("top-k")}
          type="number"
          min={1}
          max={20}
          placeholder="default"
          value={row.topK}
          onChange={(e) => onChange({ ...row, topK: e.target.value })}
        />
      </div>
    </fieldset>
  );
}

function NewExperiment({ providers, prompts }: { providers: Provider[]; prompts: PromptSummary[] }) {
  const router = useRouter();
  const first = providers[0]?.name ?? "";
  const [name, setName] = useState("");
  const [questions, setQuestions] = useState("");
  const [rows, setRows] = useState<VariantRow[]>(() => [newRow(first, "A"), newRow(first, "B")]);
  const [evaluate, setEvaluate] = useState(true);
  const evaluators = useEvaluators();
  const [evaluator, setEvaluator] = useState(DEFAULT_EVALUATOR);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    let cases;
    try {
      cases = parseCases(questions);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return;
    }
    if (!cases.length) {
      setError("Add at least one question.");
      return;
    }
    setBusy(true);
    try {
      const experiment = await api.createExperiment({
        name,
        cases,
        evaluate,
        evaluator,
        run: true,
        variants: rows.map((r) => ({
          label: r.label || undefined,
          prompt_version_id: r.promptVersionId ? Number(r.promptVersionId) : null,
          provider: r.provider,
          model: r.model || undefined,
          retrieval: r.retrieval,
          top_k: r.topK ? Number(r.topK) : undefined,
        })),
      });
      router.push(`/experiments/${experiment.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  if (!providers.length) {
    return (
      <p className="text-sm text-muted-foreground">
        Add a provider key on the <Link href="/providers" className="underline">Providers</Link> page first.
      </p>
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5 sm:max-w-md">
        <Label htmlFor="experiment-name">Name</Label>
        <Input id="experiment-name" required maxLength={255} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="experiment-questions">Questions</Label>
        <Textarea
          id="experiment-questions"
          rows={5}
          value={questions}
          placeholder={"What does error E-4711 mean? | The upstream certificate expired.\nHow many days of annual leave do employees get?"}
          onChange={(e) => setQuestions(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          One per line. Add <code>{" | "}</code> and a reference answer to also score context recall and ROUGE-L. A JSON
          list works too.
        </p>
      </div>
      <div className="flex flex-col gap-3">
        {rows.map((row, i) => (
          <VariantFields
            key={row.key}
            row={row}
            index={i}
            providers={providers}
            prompts={prompts}
            onChange={(next) => setRows(rows.map((r) => (r.key === row.key ? next : r)))}
            onRemove={rows.length > 1 ? () => setRows(rows.filter((r) => r.key !== row.key)) : undefined}
          />
        ))}
        {rows.length < MAX_VARIANTS && (
          <div>
            <Button
              type="button"
              variant="outline"
              onClick={() => setRows([...rows, newRow(first, String.fromCharCode(65 + rows.length))])}
            >
              <Plus /> Add variant
            </Button>
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={evaluate} onChange={(e) => setEvaluate(e.target.checked)} />
          Score every answer (judged by each variant&apos;s own provider and model) with
        </label>
        <Select
          aria-label="Evaluator"
          className="h-8 w-auto"
          value={evaluator}
          disabled={!evaluate}
          onChange={(e) => setEvaluator(e.target.value)}
        >
          {(evaluators.length ? evaluators : [{ name: DEFAULT_EVALUATOR, label: "Built-in judge", description: "" }]).map((e) => (
            <option key={e.name} value={e.name} title={e.description}>
              {e.label}
            </option>
          ))}
        </Select>
      </div>
      {error && <Alert variant="destructive">{error}</Alert>}
      <div>
        <Button type="submit" disabled={busy}>
          {busy ? "Starting…" : "Create and run"}
        </Button>
      </div>
    </form>
  );
}

export default function ExperimentsPage() {
  const experiments = useApi(api.experiments);
  const providers = useApi(api.providers);
  const prompts = useApi(api.prompts);
  const configured = providers.data?.filter((p) => p.configured) ?? [];

  return (
    <Page>
      <PageHeader
        title="Experiments"
        description="Answer the same questions with different prompts, models and retrieval, and compare quality, latency and cost."
      />
      <Card>
        <CardHeader>
          <CardTitle>Your experiments</CardTitle>
        </CardHeader>
        <CardContent>
          {experiments.error && <Alert variant="destructive">{experiments.error}</Alert>}
          {!experiments.data && !experiments.error && <Skeleton className="h-24" />}
          {experiments.data?.length === 0 && <p className="text-sm text-muted-foreground">No experiments yet.</p>}
          {!!experiments.data?.length && (
            <Table>
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Status</TH>
                  <TH className="text-right">Questions</TH>
                  <TH className="text-right">Variants</TH>
                  <TH>Created</TH>
                </TR>
              </THead>
              <TBody>
                {experiments.data.map((e) => (
                  <TR key={e.id}>
                    <TD>
                      <Link href={`/experiments/${e.id}`} className="font-medium hover:underline">
                        {e.name}
                      </Link>
                    </TD>
                    <TD>
                      <ExperimentStatusBadge status={e.status} />
                      {e.status === "running" && (
                        <span className="ml-2 text-xs text-muted-foreground tabular-nums">{progressPercent(e.progress)}%</span>
                      )}
                    </TD>
                    <TD className="text-right tabular-nums">{e.case_count}</TD>
                    <TD className="text-right tabular-nums">{e.variants.length}</TD>
                    <TD>{formatDate(e.created_at)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>New experiment</CardTitle>
          <CardDescription>Every question is answered by every variant, using your documents and your keys.</CardDescription>
        </CardHeader>
        <CardContent>
          {providers.data && prompts.data ? (
            <NewExperiment providers={configured} prompts={prompts.data} />
          ) : (
            <Skeleton className="h-40" />
          )}
        </CardContent>
      </Card>
    </Page>
  );
}
