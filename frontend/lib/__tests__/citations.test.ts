import { citationLabel, citationNumber, citationTarget, linkCitations } from "../citations";

describe("linkCitations", () => {
  it("links single and grouped markers", () => {
    expect(linkCitations("Leave is 25 days [1]. See [2, 3].")).toBe(
      "Leave is 25 days [1](#cite-1). See [2](#cite-2)[3](#cite-3).",
    );
  });

  it("leaves code spans, fenced code and existing links alone", () => {
    const text = "Use `arr[1]` here [1].\n```\nx = y[2]\n```\nand [docs](https://x.test) [3]";
    expect(linkCitations(text)).toBe(
      "Use `arr[1]` here [1](#cite-1).\n```\nx = y[2]\n```\nand [docs](https://x.test) [3](#cite-3)",
    );
  });

  it("does not touch an unterminated code fence while streaming", () => {
    expect(linkCitations("Answer [1]\n```py\nprint(a[0]")).toBe("Answer [1](#cite-1)\n```py\nprint(a[0]");
  });
});

it("reads citation numbers back from hrefs", () => {
  expect(citationNumber("#cite-4")).toBe(4);
  expect(citationNumber("https://example.test")).toBeNull();
  expect(citationNumber(undefined)).toBeNull();
});

it("builds targets and labels", () => {
  expect(citationTarget({ document_id: 7, chunk_id: 42 })).toBe("/documents/7#chunk-42");
  expect(citationLabel({ document_title: "FAQ", page_number: 3 })).toBe("FAQ, p. 3");
  expect(citationLabel({ document_title: "Notes", page_number: null })).toBe("Notes");
});
