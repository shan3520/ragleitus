import type { EmbeddingOption } from "../api";
import { embeddingLabel, modelToSave, selectableOptions } from "../embeddings";

const options: EmbeddingOption[] = [
  { provider: "local", label: "Local model (on this server)", default_model: "BAAI/bge-small-en-v1.5", has_key: true },
  { provider: "openai", label: "OpenAI", default_model: "text-embedding-3-small", has_key: true },
  { provider: "gemini", label: "Google Gemini", default_model: "gemini-embedding-001", has_key: false },
  { provider: "custom", label: "OpenAI-compatible (self-hosted)", default_model: "", has_key: false },
];

it("labels the local model and provider models", () => {
  expect(embeddingLabel({ provider: "local", model: "BAAI/bge-small-en-v1.5" }, options)).toBe(
    "Local model (BAAI/bge-small-en-v1.5)",
  );
  expect(embeddingLabel({ provider: "openai", model: "text-embedding-3-large" }, options)).toBe(
    "OpenAI · text-embedding-3-large",
  );
  expect(embeddingLabel({ provider: "mystery", model: "m" })).toBe("mystery · m");
});

it("offers the local model and providers with a key, keeping the current choice", () => {
  expect(selectableOptions(options).map((o) => o.provider)).toEqual(["local", "openai"]);
  expect(selectableOptions(options, "gemini").map((o) => o.provider)).toEqual(["local", "openai", "gemini"]);
});

it("sends no model for the local choice or a blank one", () => {
  expect(modelToSave("local", "anything")).toBeUndefined();
  expect(modelToSave("openai", "  ")).toBeUndefined();
  expect(modelToSave("custom", " nomic-embed-text ")).toBe("nomic-embed-text");
});
