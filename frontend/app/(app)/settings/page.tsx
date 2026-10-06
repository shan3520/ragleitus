"use client";

import { useState } from "react";

import { Page, PageHeader } from "@/components/app-shell";
import { EmbeddingSettingsCard } from "@/components/embedding-settings";
import { RerankSettingsCard } from "@/components/rerank-settings";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/utils";

function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (next !== confirm) {
      setResult({ ok: false, text: "The new passwords do not match." });
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      await api.changePassword(current, next);
      setResult({ ok: true, text: "Password changed." });
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      setResult({ ok: false, text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex max-w-sm flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="current-password">Current password</Label>
        <Input id="current-password" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="new-password">New password</Label>
        <Input id="new-password" type="password" autoComplete="new-password" required minLength={8} value={next} onChange={(e) => setNext(e.target.value)} />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="confirm-password">Confirm new password</Label>
        <Input id="confirm-password" type="password" autoComplete="new-password" required minLength={8} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      </div>
      {result && <Alert variant={result.ok ? "success" : "destructive"}>{result.text}</Alert>}
      <div>
        <Button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Change password"}
        </Button>
      </div>
    </form>
  );
}

export default function SettingsPage() {
  const { state, logout } = useAuth();
  if (state.status !== "signed-in") return null;

  return (
    <Page>
      <PageHeader title="Settings" />
      <Card>
        <CardHeader>
          <CardTitle>Account</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <dl className="grid w-fit grid-cols-[auto_1fr] gap-x-6 gap-y-1">
            <dt className="text-muted-foreground">Username</dt>
            <dd className="font-medium">{state.user.username}</dd>
            <dt className="text-muted-foreground">Member since</dt>
            <dd>{formatDate(state.user.created_at)}</dd>
          </dl>
          <div>
            <Button variant="outline" onClick={logout}>
              Sign out
            </Button>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Embeddings</CardTitle>
          <CardDescription>
            The model that turns your documents and questions into vectors. The local model runs on this server and needs
            no key; a provider embeds with your own key. Documents indexed from now on use your choice.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <EmbeddingSettingsCard />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Reranking</CardTitle>
          <CardDescription>
            A second, closer look at the passages a search finds: a reranker reads the question with each passage and
            puts the best first. Slower than search alone, and off by default.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <RerankSettingsCard />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Change password</CardTitle>
          <CardDescription>At least 8 characters.</CardDescription>
        </CardHeader>
        <CardContent>
          <PasswordForm />
        </CardContent>
      </Card>
    </Page>
  );
}
