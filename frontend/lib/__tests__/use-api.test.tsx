import { act, renderHook, waitFor } from "@testing-library/react";

import { useApi } from "../use-api";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

it("reports loading while a new key's request is in flight, keeping the old data", async () => {
  const pending: Record<number, ReturnType<typeof deferred<string>>> = { 7: deferred(), 90: deferred() };
  const { result, rerender } = renderHook(({ days }) => useApi(() => pending[days].promise, [days]), {
    initialProps: { days: 7 },
  });
  expect(result.current.loading).toBe(true);
  await act(async () => pending[7].resolve("seven"));
  expect(result.current).toMatchObject({ data: "seven", loading: false });

  rerender({ days: 90 });
  expect(result.current).toMatchObject({ data: "seven", loading: true });
  await act(async () => pending[90].resolve("ninety"));
  expect(result.current).toMatchObject({ data: "ninety", loading: false });
});

it("keeps the newest response when an older one arrives later", async () => {
  const pending: Record<number, ReturnType<typeof deferred<string>>> = { 1: deferred(), 2: deferred() };
  const { result, rerender } = renderHook(({ id }) => useApi(() => pending[id].promise, [id]), { initialProps: { id: 1 } });
  rerender({ id: 2 });
  await act(async () => pending[2].resolve("new"));
  await act(async () => pending[1].resolve("old"));
  await waitFor(() => expect(result.current).toMatchObject({ data: "new", loading: false }));
});

it("reload marks loading and refreshes the data", async () => {
  let n = 0;
  const { result } = renderHook(() => useApi(async () => ++n));
  await waitFor(() => expect(result.current.data).toBe(1));
  await act(() => result.current.reload());
  expect(result.current).toMatchObject({ data: 2, loading: false });
});
