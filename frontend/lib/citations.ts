import type { Citation } from "./api";

export const CITATION_HREF_PREFIX = "#cite-";

/**
 * Turn [n] and [n, m] markers into markdown links (`[n](#cite-n)`) so the
 * markdown renderer can show them as citation chips. Code spans and fenced
 * code blocks are left alone.
 */
export function linkCitations(markdown: string): string {
  const parts = markdown.split(/(```[\s\S]*?(?:```|$)|`[^`\n]*`)/g);
  return parts
    .map((part, i) => {
      if (i % 2 === 1) return part; // code
      return part.replace(/\[(\d+(?:\s*,\s*\d+)*)\](?!\()/g, (_match, group: string) =>
        group
          .split(",")
          .map((n) => n.trim())
          .map((n) => `[${n}](${CITATION_HREF_PREFIX}${n})`)
          .join(""),
      );
    })
    .join("");
}

export function citationNumber(href: string | undefined): number | null {
  if (!href?.startsWith(CITATION_HREF_PREFIX)) return null;
  const n = Number(href.slice(CITATION_HREF_PREFIX.length));
  return Number.isInteger(n) ? n : null;
}

/** Where a citation points: the cited passage on its document's page. */
export function citationTarget(citation: Pick<Citation, "document_id" | "chunk_id">): string {
  return `/documents/${citation.document_id}#chunk-${citation.chunk_id}`;
}

export function citationLabel(citation: Pick<Citation, "document_title" | "page_number">): string {
  return citation.page_number ? `${citation.document_title}, p. ${citation.page_number}` : citation.document_title;
}
