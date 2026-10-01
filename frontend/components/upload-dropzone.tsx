"use client";

import { useRef, useState } from "react";
import { Upload } from "lucide-react";

import { cn } from "@/lib/utils";

export const ACCEPTED_TYPES = ".pdf,.md,.markdown,.txt";

/** Click or drop files. Calls onFiles with the accepted ones. */
export function UploadDropzone({ onFiles, disabled }: { onFiles: (files: File[]) => void; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function take(list: FileList | null) {
    if (list && list.length) onFiles(Array.from(list));
  }

  return (
    <div
      role="button"
      tabIndex={0}
      aria-disabled={disabled}
      onClick={() => !disabled && input.current?.click()}
      onKeyDown={(e) => {
        if ((e.key === "Enter" || e.key === " ") && !disabled) {
          e.preventDefault();
          input.current?.click();
        }
      }}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        if (!disabled) take(e.dataTransfer.files);
      }}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        dragging ? "border-primary bg-primary/5" : "border-border hover:bg-muted/50",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      <Upload className="size-6 text-muted-foreground" aria-hidden />
      <p className="text-sm font-medium">Drop files here or click to choose</p>
      <p className="text-xs text-muted-foreground">PDF, Markdown or plain text</p>
      <input
        ref={input}
        type="file"
        multiple
        accept={ACCEPTED_TYPES}
        className="sr-only"
        data-testid="file-input"
        onChange={(e) => {
          take(e.target.files);
          e.target.value = "";
        }}
      />
    </div>
  );
}
