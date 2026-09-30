"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface ApiState<T> {
  data: T | undefined;
  error: string | null;
  loading: boolean;
  reload: () => Promise<void>;
}

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

/**
 * Load data from the API on mount and whenever `key` changes. The latest
 * request wins, so a slow earlier response never overwrites a newer one.
 * While a refresh runs, the previous data stays on screen.
 */
export function useApi<T>(load: () => Promise<T>, key: unknown[] = []): ApiState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const latest = useRef(0);
  const loadRef = useRef(load);

  useEffect(() => {
    loadRef.current = load;
  });

  const run = useCallback(async (call: number) => {
    try {
      const result = await loadRef.current();
      if (call === latest.current) {
        setData(result);
        setError(null);
      }
    } catch (err) {
      if (call === latest.current) setError(message(err));
    } finally {
      if (call === latest.current) setLoading(false);
    }
  }, []);

  const reload = useCallback(async () => {
    setLoading(true);
    await run(++latest.current);
  }, [run]);

  useEffect(() => {
    void run(++latest.current);
    // `key` is the caller's dependency list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, key);

  return { data, error, loading, reload };
}
