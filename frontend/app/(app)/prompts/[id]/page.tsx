"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowLeft, Copy, MessageSquare, Trash2 } from "lucide-react";

import { Page, PageHeader } from "@/components/app-shell";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { api, type PromptDetail } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { formatDate } from "@/lib/utils";

type Result = { ok: boolean; text: string } | null;

function Editor({ prompt, onSaved }: { prompt: PromptDetail; onSaved: () => void }) {
  const latest = prompt.versions[0];
  const [template, setTemplate] = useState(latest?.template ?? "");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result>(null);
  const unchanged = template === latest?.template;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setResult(null);
    try {
      const version = await api.addPromptVersion(prompt.id, { template, note: note || undefined });
      setNote("");
      setResult({ ok: true, text: `Saved as version ${version.version}.` });
      onSaved();
    } catch (err) {
      setResult({ ok: false, text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <Textarea
        aria-label="System prompt"
        rows={14}
        className="font-mono text-xs"
        value={template}
        onChange={(e) => setTemplate(e.target.value)}
      />
      <div className="flex flex-col gap-1.5 sm:max-w-md">
        <Label htmlFor="version-note">What changed (optional)</Label>
        <Input id="version-note" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      {result && <Alert variant={result.ok ? "success" : "destructive"}>{result.text}</Alert>}
      <div>
        <Button type="submit" disabled={busy || unchanged}>
          {busy ? "Saving…" : "Save as new version"}
        </Button>
      </div>
    </form>
  );
}

export default function PromptPage() {
  const { id } = useParams<{ id: string }>();
  const promptId = Number(id);
  const router = useRouter();
  const prompt = useApi(() => api.prompt(promptId), [promptId]);
  const [error, setError] = useState<string | null>(null);
  const latest = prompt.data?.versions[0];

  async function act(action: () => Promise<void>) {
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <Page>
      <Link href="/prompts" className="flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Prompt library
      </Link>
      {prompt.error && <Alert variant="destructive">{prompt.error}</Alert>}
      {!prompt.data && !prompt.error && <Skeleton className="h-40" />}
      {prompt.data && latest && (
        <>
          <PageHeader
            title={prompt.data.name}
            description={prompt.data.description ?? undefined}
            actions={
              <div className="flex flex-wrap gap-2">
                <Link href={`/chat?prompt=${latest.id}`} className={buttonVariants({ variant: "outline" })}>
                  <MessageSquare /> Use in chat
                </Link>
                <Button
                  variant="outline"
                  onClick={() =>
                    act(async () => {
                      const copy = await api.clonePrompt(promptId);
                      router.push(`/prompts/${copy.id}`);
                    })
                  }
                >
                  <Copy /> Clone
                </Button>
                <Button
                  variant="outline"
                  onClick={() =>
                    act(async () => {
                      if (!window.confirm(`Delete "${prompt.data?.name}" and all its versions?`)) return;
                      await api.deletePrompt(promptId);
                      router.push("/prompts");
                    })
                  }
                >
                  <Trash2 /> Delete
                </Button>
              </div>
            }
          />
          {error && <Alert variant="destructive">{error}</Alert>}
          <Card>
            <CardHeader>
              <CardTitle>Version {latest.version}</CardTitle>
              <CardDescription>
                Editing saves a new version; earlier ones stay as they were. <code>{"{context}"}</code> is required.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Editor key={latest.id} prompt={prompt.data} onSaved={() => void prompt.reload()} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>History</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {prompt.data.versions.map((v) => (
                <details key={v.id} className="rounded-lg border px-3 py-2">
                  <summary className="flex cursor-pointer flex-wrap items-center gap-2 text-sm">
                    <Badge variant={v.id === latest.id ? "default" : "outline"}>v{v.version}</Badge>
                    <span>{v.note ?? "No note"}</span>
                    <span className="text-muted-foreground">{formatDate(v.created_at)}</span>
                  </summary>
                  <pre className="mt-2 whitespace-pre-wrap font-mono text-xs text-muted-foreground">{v.template}</pre>
                </details>
              ))}
            </CardContent>
          </Card>
        </>
      )}
    </Page>
  );
}
