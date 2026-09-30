import { CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";

export function DocumentStatusBadge({ status }: { status: string }) {
  switch (status) {
    case "ready":
      return (
        <Badge variant="success">
          <CheckCircle2 /> Ready
        </Badge>
      );
    case "failed":
      return (
        <Badge variant="destructive">
          <XCircle /> Failed
        </Badge>
      );
    case "indexing":
      return (
        <Badge variant="warning">
          <Loader2 className="animate-spin" /> Indexing
        </Badge>
      );
    case "pending":
      return (
        <Badge variant="secondary">
          <Clock /> Queued
        </Badge>
      );
    default:
      return <Badge variant="outline">{status}</Badge>;
  }
}

export const isInProgress = (status: string) => status === "pending" || status === "indexing";
