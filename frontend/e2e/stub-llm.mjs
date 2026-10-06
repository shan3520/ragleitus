// A minimal OpenAI-compatible server so the end-to-end tests need no real key.
//
// Chat answers quote the first retrieved passage and cite it as [1]; judge
// prompts get fixed JSON scores, and prompts that carry a JSON schema (Ragas
// and DeepEval through RAGForge's adapters) get an instance of it.
// Responses stream as SSE like OpenAI's.
// /embeddings returns word-hashing vectors, so texts that share words are close.
// Accepts only the key "stub-key".
//
//   node e2e/stub-llm.mjs            # listens on :9999 (STUB_LLM_PORT to change)
//   STUB_LLM_LATENCY_MS=500 node e2e/stub-llm.mjs   # each chat answer takes that long
import { createHash } from "node:crypto";
import { createServer } from "node:http";

const PORT = Number(process.env.STUB_LLM_PORT ?? 9999);
const KEY = "stub-key";
const LATENCY_MS = Number(process.env.STUB_LLM_LATENCY_MS ?? 0);

function json(res, status, body) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

// A value satisfying a JSON schema, as a judge would answer: statements
// supported ("yes", 1), nothing evasive (noncommittal 0).
function instanceOf(schema, root = schema, name = "") {
  if (schema.$ref) return instanceOf(root.$defs?.[schema.$ref.split("/").pop()] ?? {}, root, name);
  for (const key of ["anyOf", "oneOf", "allOf"]) {
    if (schema[key]) {
      const options = schema[key].filter((s) => s.type !== "null");
      return instanceOf(options[0] ?? schema[key][0], root, name);
    }
  }
  if (schema.enum) return schema.enum.includes("yes") ? "yes" : schema.enum[0];
  if (schema.type === "object" || schema.properties) {
    return Object.fromEntries(Object.entries(schema.properties ?? {}).map(([k, v]) => [k, instanceOf(v, root, k)]));
  }
  if (schema.type === "array") return [instanceOf(schema.items ?? {}, root, name)];
  if (schema.type === "integer") return name.includes("noncommittal") ? 0 : 1;
  if (schema.type === "number") return 1;
  if (schema.type === "boolean") return true;
  if (name.includes("verdict")) return "yes";
  return `A ${name || "value"}.`;
}

const SCHEMA_MARKER = "matches this JSON schema, and nothing else:\n";

function answerFor(messages) {
  const system = messages[0]?.role === "system" ? messages[0].content : "";
  if (system.includes(SCHEMA_MARKER)) return JSON.stringify(instanceOf(JSON.parse(system.split(SCHEMA_MARKER)[1])));
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

const DIMENSION = 256;

function embed(text) {
  const vector = new Array(DIMENSION).fill(0);
  for (const word of String(text).toLowerCase().match(/\w+/g) ?? []) {
    const digest = createHash("md5").update(word).digest();
    vector[digest.readUInt32LE(0) % DIMENSION] += digest[4] % 2 === 0 ? 1 : -1;
  }
  const norm = Math.sqrt(vector.reduce((n, v) => n + v * v, 0)) || 1;
  return vector.map((v) => v / norm);
}

async function readJson(req) {
  let raw = "";
  for await (const chunk of req) raw += chunk;
  return JSON.parse(raw);
}

const server = createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/health") return json(res, 200, { ok: true });
  if (req.headers.authorization !== `Bearer ${KEY}`) return json(res, 401, { error: { message: "Invalid API key" } });
  if (req.method === "GET" && req.url?.endsWith("/models")) return json(res, 200, { data: [{ id: "stub-model" }] });
  if (req.method === "POST" && req.url?.endsWith("/embeddings")) {
    const { input } = await readJson(req);
    const texts = Array.isArray(input) ? input : [input];
    return json(res, 200, {
      data: texts.map((text, index) => ({ index, embedding: embed(text) })),
      usage: { prompt_tokens: texts.join(" ").split(/\s+/).length },
    });
  }
  if (req.method !== "POST" || !req.url?.endsWith("/chat/completions")) return json(res, 404, { error: { message: "Not found" } });
  if (LATENCY_MS > 0) await new Promise((resolve) => setTimeout(resolve, LATENCY_MS));

  const { messages } = await readJson(req);
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
