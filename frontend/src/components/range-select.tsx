"use client";

import { cn } from "@/lib/utils";

export const RANGES = [7, 30, 90] as const;
export type Range = (typeof RANGES)[number];

/** Date-range presets as one segmented control; scopes everything below it. */
export function RangeSelect({ value, onChange }: { value: Range; onChange: (days: Range) => void }) {
  return (
    <div role="radiogroup" aria-label="Date range" className="inline-flex rounded-md border bg-background p-0.5">
      {RANGES.map((days) => (
        <button
          key={days}
          role="radio"
          aria-checked={value === days}
          onClick={() => onChange(days)}
          className={cn(
            "rounded px-3 py-1 text-sm transition-colors",
            value === days ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          Last {days} days
        </button>
      ))}
    </div>
  );
}
