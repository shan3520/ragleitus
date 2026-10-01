import type { Conversation, DocumentSummary, ProviderKey } from "./api";

export interface Step {
  id: "key" | "document" | "chat";
  title: string;
  description: string;
  href: string;
  done: boolean;
}

/** The three things a new user does before RAGForge is useful, in order. */
export function gettingStartedSteps(input: {
  keys: ProviderKey[];
  documents: DocumentSummary[];
  conversations: Conversation[];
}): Step[] {
  return [
    {
      id: "key",
      title: "Add an LLM provider key",
      description: "Answers are generated with your own key. It is encrypted and never shown again.",
      href: "/providers",
      done: input.keys.length > 0,
    },
    {
      id: "document",
      title: "Upload a document",
      description: "PDF, Markdown or text. It is split into passages and indexed for search.",
      href: "/documents",
      done: input.documents.some((d) => d.status === "ready"),
    },
    {
      id: "chat",
      title: "Ask a question",
      description: "Answers cite the passages they come from.",
      href: "/chat",
      done: input.conversations.length > 0,
    },
  ];
}
