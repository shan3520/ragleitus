import { CheckCircle2, CircleDashed, Clock, Loader2, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { ExperimentStatus } from "@/lib/api";
import { STATUS_LABELS } from "@/lib/experiments";

const ICONS = { draft: CircleDashed, queued: Clock, running: Loader2, completed: CheckCircle2, failed: XCircle };
const VARIANTS = { draft: "outline", queued: "secondary", running: "warning", completed: "success", failed: "destructive" } as const;

export function ExperimentStatusBadge({ status }: { status: ExperimentStatus }) {
  const Icon = ICONS[status] ?? CircleDashed;
  return (
    <Badge variant={VARIANTS[status] ?? "outline"}>
      <Icon className={status === "running" ? "animate-spin" : undefined} /> {STATUS_LABELS[status] ?? status}
    </Badge>
  );
}
