"use client";

import { useEffect, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type EmbeddingSettings } from "@/lib/api";
import { embeddingLabel, LOCAL, modelToSave, selectableOptions } from "@/lib/embeddings";
import { formatNumber } from "@/lib/utils";
import { useApi } from "@/lib/use-api";

type Result = { ok: boolean; text: string } | null;

function EmbeddingForm({ settings, onSaved }: { settings: EmbeddingSettings; onSaved: (s: EmbeddingSettings) => void }) {
  const [provider, setProvider] = useState(settings.provider);
  const [model, setModel] = useState(settings.provider === LOCAL ? "" : settings.model);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result>(null);

  const options = selectableOptions(settings.options, settings.provider);
  const option = settings.options.find((o) => o.provider === provider);
  const isLocal = provider === LOCAL;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setResult(null);
    try {
      const saved = await api.saveEmbeddingSettings({ provider, model: modelToSave(provider, model) });
      setModel(saved.provider === LOCAL ? "" : saved.model);
      setResult({ ok: true, text: `Saved. New documents are embedded with ${embeddingLabel(saved, saved.options)}.` });
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
        <Label htmlFor="embedding-provider">Embedding provider</Label>
        <Select
          id="embedding-provider"
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
            Add a key on the Providers page to embed with OpenAI, Gemini, Mistral, Together AI or a
            self-hosted server.
          </p>
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="embedding-model">Embedding model</Label>
        <Input
          id="embedding-model"
          value={isLocal ? (option?.default_model ?? "") : model}
          placeholder={option?.default_model || "e.g. nomic-embed-text"}
          disabled={isLocal}
          onChange={(e) => setModel(e.target.value)}
        />
        {!isLocal && option?.default_model && (
          <p className="text-xs text-muted-foreground">Leave blank for {option.default_model}.</p>
        )}
      </div>
      {result && <Alert variant={result.ok ? "success" : "destructive"}>{result.text}</Alert>}
      <div>
        <Button type="submit" disabled={busy}>
          {busy ? "Checking…" : "Save embedding model"}
        </Button>
      </div>
    </form>
  );
}

function Reindex({ settings, onDone }: { settings: EmbeddingSettings; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result>(null);

  async function reindex() {
    setBusy(true);
    setResult(null);
    try {
      const { queued } = await api.reindexForEmbeddings();
      setResult({ ok: true, text: `Re-indexing ${formatNumber(queued)} document${queued === 1 ? "" : "s"}.` });
      onDone();
    } catch (err) {
      setResult({ ok: false, text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {settings.outdated > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm">
            {formatNumber(settings.outdated)} document{settings.outdated === 1 ? " was" : "s were"} embedded with
            another model. Questions still search them, with the model they were made with.
          </p>
          <Button variant="outline" onClick={reindex} disabled={busy}>
            {busy ? "Queueing…" : `Re-index ${settings.outdated === 1 ? "it" : "them"}`}
          </Button>
        </div>
      )}
      {result && <Alert variant={result.ok ? "success" : "destructive"}>{result.text}</Alert>}
    </div>
  );
}

export function EmbeddingSettingsCard() {
  const state = useApi(api.embeddingSettings);
  const [saved, setSaved] = useState<EmbeddingSettings>();
  const settings = saved ?? state.data;

  // Follow re-indexing until it is done.
  const indexing = settings?.indexing ?? 0;
  const { reload, error } = state;
  useEffect(() => {
    if (!indexing || error) return;
    const timer = window.setInterval(() => {
      setSaved(undefined);
      void reload();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [indexing, reload, error]);

  if (state.error) return <Alert variant="destructive">{state.error}</Alert>;
  if (!settings) return <Skeleton className="h-40" />;

  return (
    <div className="flex flex-col gap-5">
      {settings.key_missing && (
        <Alert variant="destructive">
          The key for {embeddingLabel(settings, settings.options)} has been deleted. New documents will fail to index, and
          questions search their documents by keyword only, until you add the key again or choose another model.
        </Alert>
      )}
      <EmbeddingForm settings={settings} onSaved={setSaved} />
      {settings.documents.length > 0 && (
        <div className="flex flex-col gap-1 text-sm">
          <p className="text-muted-foreground">Your indexed documents</p>
          <ul className="flex flex-col gap-0.5">
            {settings.documents.map((d) => (
              <li key={`${d.provider}/${d.model}`}>
                {embeddingLabel(d, settings.options)}: {formatNumber(d.documents)}
              </li>
            ))}
          </ul>
        </div>
      )}
      {settings.indexing > 0 && (
        <p className="text-sm text-muted-foreground" role="status">
          Indexing {formatNumber(settings.indexing)} document{settings.indexing === 1 ? "" : "s"}…
        </p>
      )}
      <Reindex
        settings={settings}
        onDone={() => {
          setSaved(undefined);
          void state.reload();
        }}
      />
    </div>
  );
}
