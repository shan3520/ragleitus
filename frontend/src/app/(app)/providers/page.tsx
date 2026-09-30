"use client";

import { useState } from "react";
import { CheckCircle2, KeyRound, Trash2, XCircle } from "lucide-react";

import { Page, PageHeader } from "@/components/app-shell";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, type Provider, type ProviderKey } from "@/lib/api";
import { useApi } from "@/lib/use-api";

function AddKeyForm({ providers, onSaved }: { providers: Provider[]; onSaved: () => void }) {
  const [provider, setProvider] = useState(providers[0]?.name ?? "");
  const [key, setKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [validate, setValidate] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const spec = providers.find((p) => p.name === provider);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setResult(null);
    try {
      const saved = await api.saveProviderKey({
        provider,
        key,
        base_url: spec?.requires_base_url ? baseUrl : undefined,
        validate,
      });
      setResult({ ok: true, text: `Saved ${spec?.label ?? provider} key ${saved.masked_key}.` });
      setKey("");
      onSaved();
    } catch (err) {
      setResult({ ok: false, text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-4 md:grid-cols-2">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="provider">Provider</Label>
        <Select id="provider" value={provider} onChange={(e) => setProvider(e.target.value)}>
          {providers.map((p) => (
            <option key={p.name} value={p.name}>
              {p.label}
              {p.configured ? " (key stored)" : ""}
            </option>
          ))}
        </Select>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="api-key">API key</Label>
        <Input
          id="api-key"
          type="password"
          autoComplete="off"
          required
          placeholder={spec?.requires_base_url ? "Any value if your server needs none" : "Paste your key"}
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
      </div>
      {spec?.requires_base_url && (
        <div className="flex flex-col gap-1.5 md:col-span-2">
          <Label htmlFor="base-url">Base URL</Label>
          <Input
            id="base-url"
            type="url"
            required
            placeholder="http://localhost:11434/v1"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">The OpenAI-compatible endpoint of your server (Ollama, LM Studio, vLLM…).</p>
        </div>
      )}
      <label className="flex items-center gap-2 text-sm md:col-span-2">
        <input type="checkbox" checked={validate} onChange={(e) => setValidate(e.target.checked)} className="size-4 accent-[var(--primary)]" />
        Check the key with the provider before saving
      </label>
      {result && (
        <Alert variant={result.ok ? "success" : "destructive"} className="md:col-span-2">
          {result.text}
        </Alert>
      )}
      <div className="md:col-span-2">
        <Button type="submit" disabled={busy || !provider}>
          <KeyRound />
          {busy ? (validate ? "Checking…" : "Saving…") : "Save key"}
        </Button>
      </div>
    </form>
  );
}

function KeyRow({ keyInfo, label, onChanged }: { keyInfo: ProviderKey; label: string; onChanged: () => void }) {
  const [status, setStatus] = useState<{ valid: boolean; detail: string } | null>(null);
  const [busy, setBusy] = useState<"test" | "delete" | null>(null);

  async function test() {
    setBusy("test");
    try {
      setStatus(await api.validateProviderKey(keyInfo.provider));
    } catch (err) {
      setStatus({ valid: false, detail: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete the ${label} key? Chats using ${label} will stop working.`)) return;
    setBusy("delete");
    try {
      await api.deleteProviderKey(keyInfo.id);
      onChanged();
    } finally {
      setBusy(null);
    }
  }

  return (
    <TR>
      <TD className="font-medium">{label}</TD>
      <TD className="font-mono text-xs">{keyInfo.masked_key}</TD>
      <TD className="max-w-60 truncate text-xs text-muted-foreground">{keyInfo.base_url ?? "—"}</TD>
      <TD>
        {status &&
          (status.valid ? (
            <Badge variant="success" title={status.detail}>
              <CheckCircle2 /> Works
            </Badge>
          ) : (
            <Badge variant="destructive" title={status.detail}>
              <XCircle /> {status.detail}
            </Badge>
          ))}
      </TD>
      <TD className="text-right">
        <div className="flex justify-end gap-1">
          <Button variant="outline" size="sm" onClick={test} disabled={busy !== null}>
            {busy === "test" ? "Testing…" : "Test"}
          </Button>
          <Button variant="ghost" size="icon" onClick={remove} disabled={busy !== null} aria-label={`Delete ${label} key`}>
            <Trash2 />
          </Button>
        </div>
      </TD>
    </TR>
  );
}

export default function ProvidersPage() {
  const providers = useApi(api.providers);
  const keys = useApi(api.providerKeys);
  const labels = Object.fromEntries((providers.data ?? []).map((p) => [p.name, p.label]));
  const refresh = () => {
    void keys.reload();
    void providers.reload();
  };

  return (
    <Page>
      <PageHeader
        title="Providers"
        description="Bring your own keys. They are encrypted at rest, only ever shown masked, and used only for your requests."
      />

      <Card>
        <CardHeader>
          <CardTitle>Add or replace a key</CardTitle>
          <CardDescription>Saving a key for a provider that already has one replaces it.</CardDescription>
        </CardHeader>
        <CardContent>
          {providers.error && <Alert variant="destructive">{providers.error}</Alert>}
          {providers.data ? <AddKeyForm providers={providers.data} onSaved={refresh} /> : !providers.error && <Skeleton className="h-24" />}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Your keys</CardTitle>
        </CardHeader>
        <CardContent>
          {keys.error && <Alert variant="destructive">{keys.error}</Alert>}
          {keys.loading && !keys.data ? (
            <Skeleton className="h-16" />
          ) : keys.data && keys.data.length > 0 ? (
            <Table>
              <THead>
                <TR>
                  <TH>Provider</TH>
                  <TH>Key</TH>
                  <TH>Base URL</TH>
                  <TH>Status</TH>
                  <TH className="text-right">Actions</TH>
                </TR>
              </THead>
              <TBody>
                {keys.data.map((k) => (
                  <KeyRow key={k.id} keyInfo={k} label={labels[k.provider] ?? k.provider} onChanged={refresh} />
                ))}
              </TBody>
            </Table>
          ) : (
            <p className="text-sm text-muted-foreground">No keys yet. Add one above to start chatting.</p>
          )}
        </CardContent>
      </Card>
    </Page>
  );
}
