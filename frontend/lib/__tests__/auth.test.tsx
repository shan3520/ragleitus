import { act, render, screen, waitFor } from "@testing-library/react";

import { tokenStore } from "../api";
import { AuthProvider, useAuth } from "../auth";

function Status() {
  const { state } = useAuth();
  return <p data-testid="status">{state.status}</p>;
}

const renderWithAuth = () =>
  render(
    <AuthProvider>
      <Status />
    </AuthProvider>,
  );

afterEach(() => {
  jest.restoreAllMocks();
  tokenStore.clear();
});

it("starts signed out when no token is stored", () => {
  renderWithAuth();
  expect(screen.getByTestId("status")).toHaveTextContent("signed-out");
});

it("restores the session from a stored token", async () => {
  tokenStore.set("good");
  jest.spyOn(global, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ id: 1, username: "ada", created_at: "2026-01-01" }), { status: 200 }),
  );
  renderWithAuth();
  await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("signed-in"));
});

it("signs out and forgets the token when the server rejects it", async () => {
  tokenStore.set("expired");
  jest.spyOn(global, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Invalid or expired token" }), { status: 401 }));
  renderWithAuth();
  await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("signed-out"));
  expect(tokenStore.get()).toBeNull();
});

it.each([
  ["the server is unreachable", () => Promise.reject(new TypeError("Failed to fetch"))],
  ["the request is aborted by navigation", () => Promise.reject(new DOMException("aborted", "AbortError"))],
  ["the server errors", () => Promise.resolve(new Response("{}", { status: 503 }))],
])("keeps the token when %s", async (_case, fetchImpl) => {
  tokenStore.set("still-valid");
  jest.spyOn(global, "fetch").mockImplementation(fetchImpl as typeof fetch);
  renderWithAuth();
  await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unverified"));
  expect(tokenStore.get()).toBe("still-valid");
});

it("can retry after the server comes back", async () => {
  tokenStore.set("still-valid");
  const fetchMock = jest.spyOn(global, "fetch").mockRejectedValueOnce(new TypeError("Failed to fetch"));
  function Retry() {
    return <button onClick={useAuth().retry}>retry</button>;
  }
  render(
    <AuthProvider>
      <Status />
      <Retry />
    </AuthProvider>,
  );
  await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unverified"));
  fetchMock.mockResolvedValue(new Response(JSON.stringify({ id: 1, username: "ada", created_at: "x" }), { status: 200 }));
  act(() => screen.getByRole("button", { name: "retry" }).click());
  await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("signed-in"));
});
