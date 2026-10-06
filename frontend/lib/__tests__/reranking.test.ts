import type { RerankOption } from "../api";
import { rerankLabel, rerankModelToSave, selectableRerankOptions } from "../reranking";

const OPTIONS: RerankOption[] = [
  { provider: "none", label: "Off", default_model: "", has_key: true },
  { provider: "local", label: "Local model (on this server)", default_model: "Xenova/ms-marco-MiniLM-L-6-v2", has_key: true },
  { provider: "nvidia", label: "NVIDIA NIM", default_model: "nvidia/llama-3.2-nv-rerankqa-1b-v2", has_key: false },
  { provider: "together", label: "Together AI", default_model: "Salesforce/Llama-Rank-V1", has_key: true },
];

describe("reranking helpers", () => {
  it("labels each kind of choice", () => {
    expect(rerankLabel({ provider: "none", model: "" })).toBe("Off");
    expect(rerankLabel({ provider: "local", model: "Xenova/ms-marco-MiniLM-L-6-v2" })).toBe(
      "Local model (Xenova/ms-marco-MiniLM-L-6-v2)",
    );
    expect(rerankLabel({ provider: "together", model: "Salesforce/Llama-Rank-V1" }, OPTIONS)).toBe(
      "Together AI · Salesforce/Llama-Rank-V1",
    );
    expect(rerankLabel({ provider: "gone", model: "m" }, OPTIONS)).toBe("gone · m");
  });

  it("offers off, local and providers with a key, plus the current choice", () => {
    expect(selectableRerankOptions(OPTIONS).map((o) => o.provider)).toEqual(["none", "local", "together"]);
    expect(selectableRerankOptions(OPTIONS, "nvidia").map((o) => o.provider)).toEqual(["none", "local", "nvidia", "together"]);
  });

  it("sends a model only for providers, blank meaning the default", () => {
    expect(rerankModelToSave("none", "x")).toBeUndefined();
    expect(rerankModelToSave("local", "x")).toBeUndefined();
    expect(rerankModelToSave("together", "  ")).toBeUndefined();
    expect(rerankModelToSave("custom", " bge-reranker ")).toBe("bge-reranker");
  });
});
