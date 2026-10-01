// A minimal OpenAI-compatible server so the end-to-end tests need no real key.
//
// Chat answers quote the first retrieved passage and cite it as [1]; judge
// prompts get fixed JSON scores. Responses stream as SSE like OpenAI's.
// Accepts only the key "stub-key".
//
//   node e2e/stub-llm.mjs            # listens on :9999 (STUB_LLM_PORT to change)
import { createServer } from "node:http";

const PORT = Number(process.env.STUB_LLM_PORT ?? 9999);
const KEY = "stub-key";

function json(res, status, body) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

function answerFor(messages) {
  const system = messages[0]?.role === "system" ? messages[0].content : "";
  if (system.includes("impartial evaluator")) {
    return JSON.stringify({
      faithfulness: 0.95,
      answer_relevancy: 0.9,
      context_precision: 0.7,
      context_recall: null,
      rationale: "Stub judge.",
    });
  }
  const passage = /\[1\] \([^)]*\)\n(.+)/.exec(system);
  return passage ? `According to the documents: ${passage[1].trim()} [1]` : "I could not find this in the documents.";
}

const server = createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/health") return json(res, 200, { ok: true });
  if (req.headers.authorization !== `Bearer ${KEY}`) return json(res, 401, { error: { message: "Invalid API key" } });
  if (req.method === "GET" && req.url?.endsWith("/models")) return json(res, 200, { data: [{ id: "stub-model" }] });
  if (req.method !== "POST" || !req.url?.endsWith("/chat/completions")) return json(res, 404, { error: { message: "Not found" } });

  let raw = "";
  for await (const chunk of req) raw += chunk;
  const { messages } = JSON.parse(raw);
  const answer = answerFor(messages);
  const words = answer.split(" ");

  res.writeHead(200, { "Content-Type": "text/event-stream" });
  for (const word of words) {
    res.write(`data: ${JSON.stringify({ model: "stub-model", choices: [{ delta: { content: `${word} ` } }] })}\n\n`);
  }
  const usage = {
    prompt_tokens: messages.reduce((n, m) => n + String(m.content).split(/\s+/).length, 0),
    completion_tokens: words.length,
  };
  res.write(`data: ${JSON.stringify({ model: "stub-model", choices: [{ delta: {}, finish_reason: "stop" }], usage })}\n\n`);
  res.end("data: [DONE]\n\n");
});

server.listen(PORT, () => console.log(`stub LLM on http://localhost:${PORT}/v1`));
