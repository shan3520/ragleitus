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
  const keyId = JSON.stringify(key);
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string | null>(null);
  // The key whose request last finished. While it differs from the current
  // key, a request for the new key is in flight: that is "loading".
  const [settledKey, setSettledKey] = useState<string | null>(null);
  const [reloading, setReloading] = useState(false);
  const latest = useRef(0);
  const loadRef = useRef(load);

  useEffect(() => {
    loadRef.current = load;
  });

  const run = useCallback(async (call: number, id: string) => {
    try {
      const result = await loadRef.current();
      if (call === latest.current) {
        setData(result);
        setError(null);
      }
    } catch (err) {
      if (call === latest.current) setError(message(err));
    } finally {
      if (call === latest.current) {
        setSettledKey(id);
        setReloading(false);
      }
    }
  }, []);

  const reload = useCallback(async () => {
    setReloading(true);
    await run(++latest.current, keyId);
  }, [run, keyId]);

  useEffect(() => {
    void run(++latest.current, keyId);
  }, [run, keyId]);

  return { data, error, loading: reloading || settledKey !== keyId, reload };
}
