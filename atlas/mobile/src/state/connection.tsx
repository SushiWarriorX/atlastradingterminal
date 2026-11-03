import { useQueryClient } from "@tanstack/react-query";
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, createApi, normalizeBaseUrl, type Api } from "../api/client";
import { storage } from "./storage";

export type Status = "loading" | "needs_server" | "needs_login" | "ready";
const DEFAULT_URL = process.env.EXPO_PUBLIC_ATLAS_URL ?? "";

interface Conn {
  status: Status;
  baseUrl: string | null;
  defaultUrl: string;
  api: Api | null;
  authRequired: boolean;
  /** Save the server address and, if the server asks for a password, log in. Throws ApiError with a message the form can show. */
  connect: (url: string, password?: string) => Promise<void>;
  logout: () => Promise<void>;
}
const Ctx = createContext<Conn | null>(null);
export const useConnection = () => {
  const c = useContext(Ctx);
  if (!c) throw new Error("useConnection must be used inside ConnectionProvider");
  return c;
};

export function ConnectionProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<Status>("loading");
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [authRequired, setAuthRequired] = useState(false);
  const tokenRef = useRef<string | null>(null);
  tokenRef.current = token;

  const api = useMemo(() => (baseUrl ? createApi({ baseUrl, token, onAuthRequired: () => { setToken(null); storage.clearToken(); setAuthRequired(true); setStatus("needs_login"); } }) : null), [baseUrl, token]);

  useEffect(() => {
    (async () => {
      const [url, tok] = await Promise.all([storage.getBaseUrl(), storage.getToken()]);
      const start = url ?? (normalizeBaseUrl(DEFAULT_URL) || null);
      if (!start) { setStatus("needs_server"); return; }
      setBaseUrl(start);
      setToken(tok);
      try {
        const s = await createApi({ baseUrl: start, token: tok }).authStatus();
        setAuthRequired(s.required);
        setStatus(s.required && !s.authenticated ? "needs_login" : url ? "ready" : "needs_server");
      } catch {
        setStatus(url ? "ready" : "needs_server");              // unreachable right now: open with the saved watchlist and an offline notice rather than blocking
      }
    })();
  }, []);

  const connect = useCallback(async (rawUrl: string, password?: string) => {
    const url = normalizeBaseUrl(rawUrl);
    if (!url) throw new ApiError("INVALID_URL", "Enter the server address, for example http://192.168.1.20:8000 or https://signal.example.com");
    const probe = createApi({ baseUrl: url });
    const s = await probe.authStatus();
    let tok: string | null = null;
    if (s.required) {
      if (!password) throw new ApiError("PASSWORD_REQUIRED", "This server needs a password.");
      const r = await probe.login(password);
      tok = r.token ?? null;
      if (!tok) throw new ApiError("NO_TOKEN", "The server did not return a login token.");
    }
    await storage.setBaseUrl(url);
    if (tok) await storage.setToken(tok); else await storage.clearToken();
    if (url !== baseUrl) { await storage.clearWatchlistCache(); }
    qc.clear();
    setBaseUrl(url); setToken(tok); setAuthRequired(s.required); setStatus("ready");
  }, [baseUrl, qc]);

  const logout = useCallback(async () => {
    await storage.clearToken();
    setToken(null);
    qc.clear();
    setStatus(authRequired ? "needs_login" : "ready");
  }, [qc, authRequired]);

  const value = useMemo<Conn>(() => ({ status, baseUrl, defaultUrl: DEFAULT_URL, api, authRequired, connect, logout }), [status, baseUrl, api, authRequired, connect, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
