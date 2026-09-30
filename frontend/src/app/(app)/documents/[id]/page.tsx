"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useSyncExternalStore } from "react";
import { ArrowLeft } from "lucide-react";

import { Page, PageHeader } from "@/components/app-shell";
import { DocumentStatusBadge, isInProgress } from "@/components/document-status";
import { Alert } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { formatDate } from "@/lib/utils";

// The URL hash, kept current. CSS :target is not enough here: it does not update
// when the app navigates client-side (pushState), which is how citations arrive.
function subscribeToHash(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  window.addEventListener("popstate", onChange);
  return () => {
    window.removeEventListener("hashchange", onChange);
    window.removeEventListener("popstate", onChange);
  };
}
const useHash = () =>
  useSyncExternalStore(
    subscribeToHash,
    () => window.location.hash,
    () => "",
  );

export default function DocumentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const documentId = Number(id);
  const doc = useApi(() => api.document(documentId), [documentId]);
  const status = doc.data?.status;

  const { reload } = doc;
  useEffect(() => {
    if (!status || !isInProgress(status)) return;
    const timer = window.setInterval(() => void reload(), 2000);
    return () => window.clearInterval(timer);
  }, [status, reload]);

  // Citations link here as #chunk-<id>; highlight that passage and scroll to it once it exists.
  const cited = useHash().slice(1);
  const chunkCount = doc.data?.chunks.length ?? 0;
  useEffect(() => {
    if (chunkCount && cited) document.getElementById(cited)?.scrollIntoView({ block: "center" });
  }, [chunkCount, cited]);

  return (
    <Page>
      <Link href="/documents" className="flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Documents
      </Link>
      {doc.error && <Alert variant="destructive">{doc.error}</Alert>}
      {!doc.data && !doc.error && <Skeleton className="h-40" />}
      {doc.data && (
        <>
          <PageHeader
            title={doc.data.title}
            description={[doc.data.filename, formatDate(doc.data.created_at)].filter(Boolean).join(" · ")}
            actions={<DocumentStatusBadge status={doc.data.status} />}
          />
          {doc.data.error && <Alert variant="destructive">Indexing failed: {doc.data.error}</Alert>}
          <Card>
            <CardHeader>
              <CardTitle>
                {doc.data.chunks.length} passage{doc.data.chunks.length === 1 ? "" : "s"}
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {doc.data.chunks.map((chunk) => (
                <section
                  key={chunk.id}
                  id={`chunk-${chunk.id}`}
                  aria-current={cited === `chunk-${chunk.id}` ? "location" : undefined}
                  className="scroll-mt-24 rounded-lg border p-3 aria-[current=location]:border-primary aria-[current=location]:bg-primary/5 aria-[current=location]:ring-2 aria-[current=location]:ring-primary/30"
                >
                  <p className="mb-1 text-xs text-muted-foreground">
                    Passage {chunk.sequence_order}
                    {chunk.page_number ? ` · page ${chunk.page_number}` : ""}
                  </p>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">{chunk.content}</p>
                </section>
              ))}
              {doc.data.chunks.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  {isInProgress(doc.data.status) ? "Indexing in progress…" : "No passages."}
                </p>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </Page>
  );
}
