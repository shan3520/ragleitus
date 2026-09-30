import { gettingStartedSteps } from "../getting-started";

const key = { id: 1, provider: "openai", masked_key: "sk-***", base_url: null };
const doc = (status: string) => ({ id: 1, user_id: 1, title: "a", status, negative_impact: 0 });
const conversation = { id: 1, title: "t", provider: null, model: null, created_at: "", updated_at: "" };

it("marks nothing done for a new account", () => {
  expect(gettingStartedSteps({ keys: [], documents: [], conversations: [] }).map((s) => s.done)).toEqual([false, false, false]);
});

it("only counts a document once it is ready to search", () => {
  expect(gettingStartedSteps({ keys: [key], documents: [doc("indexing")], conversations: [] })[1].done).toBe(false);
  expect(gettingStartedSteps({ keys: [key], documents: [doc("failed"), doc("ready")], conversations: [] })[1].done).toBe(true);
});

it("is complete after the first conversation", () => {
  expect(gettingStartedSteps({ keys: [key], documents: [doc("ready")], conversations: [conversation] }).every((s) => s.done)).toBe(true);
});
