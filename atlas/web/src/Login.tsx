import { FormEvent, ReactNode, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, errText } from "./api";

/** Shows a password screen when the server asks for one (cloud hosting). Local use: the server says no login is required and this is invisible. */
export function LoginGate({ children }: { children: ReactNode }) {
  const s = useQuery({ queryKey: ["auth"], queryFn: api.authStatus, retry: false, staleTime: 0 });
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const on = () => { s.refetch(); };
    window.addEventListener("atlas-auth-required", on);
    return () => window.removeEventListener("atlas-auth-required", on);
  }, [s]);
  if (s.isLoading) return <div className="boot">Loading…</div>;
  if (!s.data?.required || s.data.authenticated) return <>{children}</>;            // a failed status call falls through to the app's own error display
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try { await api.login(pw); setPw(""); await s.refetch(); } catch (x) { setErr(errText(x)); } finally { setBusy(false); }
  };
  return (
    <div className="boot" style={{ display: "grid", placeItems: "center", height: "100vh" }}>
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 8, width: 280 }}>
        <div style={{ color: "var(--accent)", fontWeight: 700, letterSpacing: ".06em" }}>ATLAS TERMINAL</div>
        <input type="password" autoFocus autoComplete="current-password" placeholder="Password" aria-label="Password" value={pw} onChange={(e) => setPw(e.target.value)} />
        <button className="mini on" type="submit" disabled={busy || !pw}>{busy ? "Checking…" : "Log in"}</button>
        {err && <div className="down small">{err}</div>}
        <div className="dim small">Research and paper trading only. Live trading is disabled.</div>
      </form>
    </div>
  );
}
