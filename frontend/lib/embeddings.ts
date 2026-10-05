import type { EmbeddingOption, EmbeddingRef } from "./api";

export const LOCAL = "local";

/** "OpenAI · text-embedding-3-small", or "Local model (BAAI/bge-small-en-v1.5)". */
export function embeddingLabel(ref: EmbeddingRef, options: EmbeddingOption[] = []): string {
  if (ref.provider === LOCAL) return `Local model (${ref.model})`;
  const label = options.find((o) => o.provider === ref.provider)?.label ?? ref.provider;
  return `${label} · ${ref.model}`;
}

/** The choices worth offering: the local model, and providers the user has a key for (plus the current one). */
export function selectableOptions(options: EmbeddingOption[], current?: string): EmbeddingOption[] {
  return options.filter((o) => o.provider === LOCAL || o.has_key || o.provider === current);
}

/** The model to send: blank means the provider's default; the local model has none to choose. */
export function modelToSave(provider: string, model: string): string | undefined {
  if (provider === LOCAL) return undefined;
  return model.trim() || undefined;
}
