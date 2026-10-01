import { ApiError, setUnauthorizedHandler, tokenStore } from "../api";
import { streamMessage } from "../chat";

function sseResponse(body: string, status = 200) {
  return new Response(body, { status, headers: { "Content-Type": "text/event-stream" } });
}

afterEach(() => jest.restoreAllMocks());

it("dispatches sources, tokens, citations and done in order", async () => {
  const body = [
    'event: sources\ndata: {"sources":[{"number":1,"document_id":7,"document_title":"FAQ","page_number":3}]}\n\n',
    'event: token\ndata: {"text":"Recalibrate "}\n\n',
    'event: token\ndata: {"text":"joint 3 [1]."}\n\n',
    'event: citations\ndata: {"citations":[{"number":1,"document_id":7,"document_title":"FAQ","page_number":3,"chunk_id":9,"snippet":"..."}]}\n\n',
    'event: done\ndata: {"message_id":12,"provider":"openai","model":"gpt-4o-mini","finish_reason":"stop","prompt_tokens":10,"completion_tokens":5,"cost_usd":0.0001,"latency_ms":800,"ttft_ms":120}\n\n',
  ].join("");
  const fetchMock = jest.spyOn(global, "fetch").mockResolvedValue(sseResponse(body));
  const calls: string[] = [];
  let text = "";

  await streamMessage(5, { content: "What is E-4711?" }, {
    onSources: (s) => calls.push(`sources:${s.length}`),
    onToken: (t) => {
      calls.push("token");
      text += t;
    },
    onCitations: (c) => calls.push(`citations:${c[0].page_number}`),
    onDone: (d) => calls.push(`done:${d.message_id}`),
  });

  expect(calls).toEqual(["sources:1", "token", "token", "citations:3", "done:12"]);
  expect(text).toBe("Recalibrate joint 3 [1].");
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/backend/api/conversations/5/messages");
  expect(JSON.parse(init!.body as string)).toEqual({ content: "What is E-4711?", stream: true });
});

it("throws the server's refusal before streaming starts", async () => {
  jest.spyOn(global, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ detail: "No API key stored for provider 'anthropic'." }), { status: 400 }),
  );
  await expect(streamMessage(1, { content: "Q" }, {})).rejects.toEqual(
    new ApiError(400, "No API key stored for provider 'anthropic'."),
  );
});

it("throws when the provider fails mid-stream", async () => {
  jest.spyOn(global, "fetch").mockResolvedValue(
    sseResponse('event: token\ndata: {"text":"Part"}\n\nevent: error\ndata: {"message":"openai returned HTTP 429","status_code":429}\n\n'),
  );
  const tokens: string[] = [];
  await expect(streamMessage(1, { content: "Q" }, { onToken: (t) => tokens.push(t) })).rejects.toMatchObject({
    status: 429,
    message: "openai returned HTTP 429",
  });
  expect(tokens).toEqual(["Part"]);
});

it("signs the user out when the stream is refused with 401", async () => {
  tokenStore.set("expired-token");
  const onUnauthorized = jest.fn();
  setUnauthorizedHandler(onUnauthorized);
  jest.spyOn(global, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ detail: "Could not validate credentials" }), { status: 401 }),
  );
  try {
    await expect(streamMessage(5, { content: "Hi" }, {})).rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  } finally {
    setUnauthorizedHandler(null);
    tokenStore.clear();
  }
});
