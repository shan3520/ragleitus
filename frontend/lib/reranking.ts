import type { RerankOption } from "./api";

export const OFF = "none";
export const LOCAL = "local";

/** "Off", "Local model (Xenova/ms-marco-MiniLM-L-6-v2)" or "Together AI · Salesforce/Llama-Rank-V1". */
export function rerankLabel(ref: { provider: string; model: string }, options: RerankOption[] = []): string {
  if (ref.provider === OFF) return "Off";
  if (ref.provider === LOCAL) return `Local model (${ref.model})`;
  const label = options.find((o) => o.provider === ref.provider)?.label ?? ref.provider;
  return `${label} · ${ref.model}`;
}

/** The choices worth offering: off, the local model, and providers the user has a key for (plus the current one). */
export function selectableRerankOptions(options: RerankOption[], current?: string): RerankOption[] {
  return options.filter((o) => o.provider === OFF || o.provider === LOCAL || o.has_key || o.provider === current);
}

/** The model to send: blank means the provider's default; off and the local model have none to choose. */
export function rerankModelToSave(provider: string, model: string): string | undefined {
  if (provider === OFF || provider === LOCAL) return undefined;
  return model.trim() || undefined;
}
