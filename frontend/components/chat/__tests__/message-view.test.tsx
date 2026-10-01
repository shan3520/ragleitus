import { render, screen } from "@testing-library/react";

import { MessageView, type ChatItem } from "../message-view";

const answer: ChatItem = { key: "m2", role: "assistant", content: "Leave is 25 days.", messageId: 2 };

it("offers to evaluate an answer that has no saved evaluation", () => {
  render(<MessageView item={answer} />);
  expect(screen.getByRole("button", { name: "Evaluate answer" })).toBeInTheDocument();
});

it("shows a saved evaluation instead of the button", () => {
  render(
    <MessageView
      item={{
        ...answer,
        evaluation: {
          id: 7, message_id: 2, conversation_id: 1, judge_provider: "openai", judge_model: "gpt-4o-mini",
          faithfulness: 0.95, answer_relevancy: 0.9, context_precision: 0.7, context_recall: null,
          hallucination: 0.05, rationale: "Supported by the handbook.", reference_answer: null,
          rouge_l: null, context_overlap: null, created_at: "",
        },
      }}
    />,
  );
  expect(screen.queryByRole("button", { name: "Evaluate answer" })).not.toBeInTheDocument();
  expect(screen.getByText("Faithfulness")).toBeInTheDocument();
  expect(screen.getByText("95%")).toBeInTheDocument();
});
