"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { RefreshCw, Trash2 } from "lucide-react";

import { Page, PageHeader } from "@/components/app-shell";
import { DocumentStatusBadge, isInProgress } from "@/components/document-status";
import { UploadDropzone } from "@/components/upload-dropzone";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api, type DocumentSummary } from "@/lib/api";
import { useApi } from "@/lib/use-api";

const POLL_MS = 2000;

interface UploadResult {
  name: string;
  ok: boolean;
  message: string;
}

function DocumentRow({ doc, onChanged }: { doc: DocumentSummary; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);

  async function act(action: "reindex" | "delete") {
    if (action === "delete" && !window.confirm(`Delete "${doc.title}"? Its chunks and vectors are removed too.`)) return;
    setBusy(true);
    try {
      await (action === "reindex" ? api.reindexDocument(doc.id) : api.deleteDocument(doc.id));
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <TR>
      <TD>
        <Link href={`/documents/${doc.id}`} className="font-medium hover:underline">
          {doc.title}
        </Link>
      </TD>
      <TD>
        <DocumentStatusBadge status={doc.status} />
      </TD>
      <TD className="text-right">
        <div className="flex justify-end gap-1">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => act("reindex")}
            disabled={busy || isInProgress(doc.status)}
            aria-label={`Re-index ${doc.title}`}
            title="Re-index"
          >
            <RefreshCw />
          </Button>
          <Button variant="ghost" size="icon" onClick={() => act("delete")} disabled={busy} aria-label={`Delete ${doc.title}`} title="Delete">
            <Trash2 />
          </Button>
        </div>
      </TD>
    </TR>
  );
}

export default function DocumentsPage() {
  const documents = useApi(api.documents);
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<UploadResult[]>([]);
  const inProgress = documents.data?.some((d) => isInProgress(d.status)) ?? false;

  // While anything is indexing, refresh the list until it settles.
  const { reload } = documents;
  useEffect(() => {
    if (!inProgress) return;
    const timer = window.setInterval(() => void reload(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [inProgress, reload]);

  async function upload(files: File[]) {
    setUploading(true);
    const outcome: UploadResult[] = [];
    for (const file of files) {
      try {
        await api.uploadDocument(file);
        outcome.push({ name: file.name, ok: true, message: "Uploaded, indexing…" });
      } catch (err) {
        outcome.push({ name: file.name, ok: false, message: err instanceof Error ? err.message : String(err) });
      }
    }
    setResults(outcome);
    setUploading(false);
    void documents.reload();
  }

  const sorted = [...(documents.data ?? [])].sort((a, b) => b.id - a.id);

  return (
    <Page>
      <PageHeader title="Documents" description="Uploaded files are split into passages and indexed for search. Chat answers cite them by page." />

      <Card>
        <CardContent className="pt-5">
          <UploadDropzone onFiles={upload} disabled={uploading} />
          {uploading && <p className="mt-3 text-sm text-muted-foreground">Uploading…</p>}
          {results.length > 0 && (
            <ul className="mt-3 flex flex-col gap-2" aria-label="Upload results">
              {results.map((r) => (
                <li key={r.name}>
                  <Alert variant={r.ok ? "success" : "destructive"}>
                    <span className="font-medium">{r.name}</span>: {r.message}
                  </Alert>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Your documents</CardTitle>
        </CardHeader>
        <CardContent>
          {documents.error && <Alert variant="destructive">{documents.error}</Alert>}
          {documents.loading && !documents.data ? (
            <Skeleton className="h-24" />
          ) : sorted.length ? (
            <Table>
              <THead>
                <TR>
                  <TH>Title</TH>
                  <TH>Status</TH>
                  <TH className="text-right">Actions</TH>
                </TR>
              </THead>
              <TBody>
                {sorted.map((doc) => (
                  <DocumentRow key={doc.id} doc={doc} onChanged={() => void documents.reload()} />
                ))}
              </TBody>
            </Table>
          ) : (
            <p className="text-sm text-muted-foreground">No documents yet. Upload one above.</p>
          )}
        </CardContent>
      </Card>
    </Page>
  );
}
