import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** Label, one headline value, and an optional secondary line (never color alone). */
export function StatTile({
  label,
  value,
  detail,
  className,
}: {
  label: string;
  value: React.ReactNode;
  detail?: React.ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("flex flex-col gap-1 p-4", className)}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-2xl font-semibold tracking-tight">{value}</p>
      {detail && <p className="text-xs text-muted-foreground">{detail}</p>}
    </Card>
  );
}
