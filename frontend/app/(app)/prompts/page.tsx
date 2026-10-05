"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Page, PageHeader } from "@/components/app-shell";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { formatDate } from "@/lib/utils";

function NewPrompt() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [template, setTemplate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Start from the built-in prompt.
  useEffect(() => {
    api.defaultPrompt().then((d) => setTemplate((t) => t || d.template), () => undefined);
  }, []);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const prompt = await api.createPrompt({ name, description: description || undefined, template });
      router.push(`/prompts/${prompt.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="prompt-name">Name</Label>
          <Input id="prompt-name" required maxLength={255} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="prompt-description">Description (optional)</Label>
          <Input id="prompt-description" maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="prompt-template">System prompt</Label>
        <Textarea
          id="prompt-template"
          required
          rows={12}
          className="font-mono text-xs"
          value={template}
          onChange={(e) => setTemplate(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          <code>{"{context}"}</code> is replaced by the numbered passages (required); <code>{"{question}"}</code> by the
          question (optional).
        </p>
      </div>
      {error && <Alert variant="destructive">{error}</Alert>}
      <div>
        <Button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save prompt"}
        </Button>
      </div>
    </form>
  );
}

export default function PromptsPage() {
  const prompts = useApi(api.prompts);

  return (
    <Page>
      <PageHeader
        title="Prompt library"
        description="Your own system prompts, versioned. Use one in chat, or compare them in an experiment."
      />
      <Card>
        <CardHeader>
          <CardTitle>Prompts</CardTitle>
        </CardHeader>
        <CardContent>
          {prompts.error && <Alert variant="destructive">{prompts.error}</Alert>}
          {!prompts.data && !prompts.error && <Skeleton className="h-24" />}
          {prompts.data?.length === 0 && (
            <p className="text-sm text-muted-foreground">No prompts yet. Chat uses the built-in prompt until you choose one.</p>
          )}
          {!!prompts.data?.length && (
            <Table>
              <THead>
                <TR>
                  <TH>Name</TH>
                  <TH>Description</TH>
                  <TH className="text-right">Versions</TH>
                  <TH>Created</TH>
                </TR>
              </THead>
              <TBody>
                {prompts.data.map((p) => (
                  <TR key={p.id}>
                    <TD>
                      <Link href={`/prompts/${p.id}`} className="font-medium hover:underline">
                        {p.name}
                      </Link>
                    </TD>
                    <TD className="max-w-md truncate text-muted-foreground">{p.description}</TD>
                    <TD className="text-right tabular-nums">{p.version_count}</TD>
                    <TD>{formatDate(p.created_at)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>New prompt</CardTitle>
          <CardDescription>Starts from the built-in prompt.</CardDescription>
        </CardHeader>
        <CardContent>
          <NewPrompt />
        </CardContent>
      </Card>
    </Page>
  );
}
