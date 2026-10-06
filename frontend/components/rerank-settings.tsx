"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type RerankSettings } from "@/lib/api";
import { LOCAL, OFF, rerankLabel, rerankModelToSave, selectableRerankOptions } from "@/lib/reranking";
import { useApi } from "@/lib/use-api";

type Result = { ok: boolean; text: string } | null;

function RerankForm({ settings, onSaved }: { settings: RerankSettings; onSaved: (s: RerankSettings) => void }) {
  const [provider, setProvider] = useState(settings.provider);
  const [model, setModel] = useState(settings.provider === OFF || settings.provider === LOCAL ? "" : settings.model);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result>(null);

  const options = selectableRerankOptions(settings.options, settings.provider);
  const option = settings.options.find((o) => o.provider === provider);
  const fixedModel = provider === OFF || provider === LOCAL;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setResult(null);
    try {
      const saved = await api.saveRerankSettings({ provider, model: rerankModelToSave(provider, model) });
      setModel(saved.provider === OFF || saved.provider === LOCAL ? "" : saved.model);
      setResult({
        ok: true,
        text:
          saved.provider === OFF
            ? "Saved. Passages are no longer reranked."
            : `Saved. Passages are reranked with ${rerankLabel(saved, saved.options)}.`,
      });
      onSaved(saved);
    } catch (err) {
      setResult({ ok: false, text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex max-w-md flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="rerank-provider">Reranker</Label>
        <Select
          id="rerank-provider"
          value={provider}
          onChange={(e) => {
            setProvider(e.target.value);
            setModel("");
            setResult(null);
          }}
        >
          {options.map((o) => (
            <option key={o.provider} value={o.provider}>
              {o.label}
            </option>
          ))}
        </Select>
        {options.length < settings.options.length && (
          <p className="text-xs text-muted-foreground">
            Add a key on the Providers page to rerank with Together AI, NVIDIA NIM or a self-hosted server.
          </p>
        )}
      </div>
      {provider !== OFF && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="rerank-model">Reranking model</Label>
          <Input
            id="rerank-model"
            value={fixedModel ? (option?.default_model ?? "") : model}
            placeholder={option?.default_model || "e.g. BAAI/bge-reranker-base"}
            disabled={fixedModel}
            onChange={(e) => setModel(e.target.value)}
          />
          {!fixedModel && option?.default_model && (
            <p className="text-xs text-muted-foreground">Leave blank for {option.default_model}.</p>
          )}
        </div>
      )}
      {result && <Alert variant={result.ok ? "success" : "destructive"}>{result.text}</Alert>}
      <div>
        <Button type="submit" disabled={busy}>
          {busy ? "Checking…" : "Save reranker"}
        </Button>
      </div>
    </form>
  );
}

export function RerankSettingsCard() {
  const state = useApi(api.rerankSettings);
  const [saved, setSaved] = useState<RerankSettings>();
  const settings = saved ?? state.data;

  if (state.error) return <Alert variant="destructive">{state.error}</Alert>;
  if (!settings) return <Skeleton className="h-32" />;

  return (
    <div className="flex flex-col gap-4">
      {settings.key_missing && (
        <Alert variant="destructive">
          The key for {rerankLabel(settings, settings.options)} has been deleted. Passages are kept in their usual order
          until you add the key again or choose another reranker.
        </Alert>
      )}
      <p className="text-sm text-muted-foreground">
        When it is on, the best {settings.candidates} passages found for a question are scored by the reranker, and
        the highest-scoring ones are used for the answer.
      </p>
      <RerankForm settings={settings} onSaved={setSaved} />
    </div>
  );
}
