"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, ApiError, setUnauthorizedHandler, tokenStore, type User } from "./api";

export type AuthState =
  | { status: "loading"; user: null }
  | { status: "signed-out"; user: null }
  | { status: "signed-in"; user: User }
  // A stored token exists but the server could not confirm it (unreachable,
  // 5xx, request aborted). The token is kept: only a 401 means it is invalid.
  | { status: "unverified"; user: null; message: string };

interface AuthContextValue {
  state: AuthState;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => void;
  retry: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  // Without a stored token there is nothing to restore: start signed out.
  // (Server render and first client render both show the same "Loading…"
  // placeholder for these two states, so this does not cause a mismatch.)
  const [state, setState] = useState<AuthState>(() =>
    typeof window !== "undefined" && !tokenStore.get() ? { status: "signed-out", user: null } : { status: "loading", user: null },
  );
  const [attempt, setAttempt] = useState(0);

  const logout = useCallback(() => {
    tokenStore.clear();
    setState({ status: "signed-out", user: null });
  }, []);

  // Restore the session from a stored token.
  useEffect(() => {
    setUnauthorizedHandler(logout);
    if (!tokenStore.get()) return () => setUnauthorizedHandler(null);
    let cancelled = false;
    api
      .me()
      .then((user) => !cancelled && setState({ status: "signed-in", user }))
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) logout();
        else setState({ status: "unverified", user: null, message: err instanceof Error ? err.message : String(err) });
      });
    return () => {
      cancelled = true;
      setUnauthorizedHandler(null);
    };
  }, [logout, attempt]);

  const retry = useCallback(() => {
    setState({ status: "loading", user: null });
    setAttempt((n) => n + 1);
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const { access_token } = await api.login(username, password);
    tokenStore.set(access_token);
    const user = await api.me();
    setState({ status: "signed-in", user });
  }, []);

  const register = useCallback(
    async (username: string, password: string) => {
      await api.register(username, password);
      await login(username, password);
    },
    [login],
  );

  const value = useMemo(() => ({ state, login, register, logout, retry }), [state, login, register, logout, retry]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
