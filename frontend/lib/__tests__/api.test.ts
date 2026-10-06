import { api, ApiError, errorMessage, request, setUnauthorizedHandler, tokenStore } from "../api";

function mockFetch(status: number, body: unknown) {
  return jest.spyOn(global, "fetch").mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

afterEach(() => {
  jest.restoreAllMocks();
  tokenStore.clear();
  setUnauthorizedHandler(null);
});

describe("errorMessage", () => {
  it("reads FastAPI detail strings, validation lists and objects", () => {
    expect(errorMessage(400, { detail: "Unknown provider 'acme'" })).toBe("Unknown provider 'acme'");
    expect(
      errorMessage(422, { detail: [{ loc: ["body", "password"], msg: "String should have at least 8 characters" }] }),
    ).toBe("password: String should have at least 8 characters");
    expect(errorMessage(409, { detail: { message: "Already uploaded", document_id: 3 } })).toBe("Already uploaded");
    expect(errorMessage(500, null)).toBe("Request failed (500)");
    expect(errorMessage(0, null)).toBe("Could not reach the server.");
  });
});

describe("request", () => {
  it("prefixes /backend, sends the bearer token and JSON content type", async () => {
    tokenStore.set("tok123");
    const fetchMock = mockFetch(200, { ok: true });
    await request("/api/x", { method: "POST", body: JSON.stringify({ a: 1 }) });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/backend/api/x");
    const headers = new Headers(init!.headers);
    expect(headers.get("Authorization")).toBe("Bearer tok123");
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("does not force a JSON content type on uploads", async () => {
    const fetchMock = mockFetch(202, { id: 1, title: "a", filename: "a.txt", status: "pending" });
    await api.uploadDocument(new File(["hello"], "a.txt", { type: "text/plain" }));
    const headers = new Headers(fetchMock.mock.calls[0][1]!.headers);
    expect(headers.has("Content-Type")).toBe(false);
    expect(fetchMock.mock.calls[0][1]!.body).toBeInstanceOf(FormData);
  });

  it("throws ApiError with the server's message", async () => {
    mockFetch(400, { detail: "OpenAI rejected the key." });
    await expect(api.saveProviderKey({ provider: "openai", key: "sk-x" })).rejects.toEqual(
      new ApiError(400, "OpenAI rejected the key."),
    );
  });

  it("returns undefined for 204 responses", async () => {
    jest.spyOn(global, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
    await expect(api.deleteDocument(4)).resolves.toBeUndefined();
  });

  it("calls the unauthorized handler when a signed-in request gets 401", async () => {
    tokenStore.set("expired");
    const handler = jest.fn();
    setUnauthorizedHandler(handler);
    mockFetch(401, { detail: "Invalid or expired token" });
    await expect(api.me()).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("reports network failures as status 0", async () => {
    jest.spyOn(global, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(api.documents()).rejects.toMatchObject({ status: 0, message: "Could not reach the server." });
  });
});

describe("api.health", () => {
  it("returns the per-subsystem report even when the API answers 503", async () => {
    mockFetch(503, { db: "healthy", vector_store: "unavailable" });
    await expect(api.health()).resolves.toEqual({ db: "healthy", vector_store: "unavailable" });
  });

  it("still rejects when the API itself is unreachable", async () => {
    mockFetch(502, { detail: "The ragleitus API is not reachable." });
    await expect(api.health()).rejects.toMatchObject({ status: 502 });
  });
});

describe("api.changePassword", () => {
  it("keeps the session going with the token the server returns", async () => {
    tokenStore.set("old-token");
    const fetchMock = mockFetch(200, { access_token: "new-token", token_type: "bearer" });
    await api.changePassword("old password", "new password 1");
    expect(new Headers(fetchMock.mock.calls[0][1]!.headers).get("Authorization")).toBe("Bearer old-token");
    expect(tokenStore.get()).toBe("new-token");
  });

  it("keeps the old token when the change is refused", async () => {
    tokenStore.set("old-token");
    mockFetch(400, { detail: "Current password is incorrect" });
    await expect(api.changePassword("wrong", "new password 1")).rejects.toThrow("Current password is incorrect");
    expect(tokenStore.get()).toBe("old-token");
  });
});
