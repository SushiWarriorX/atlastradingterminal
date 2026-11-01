import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiFailure } from "../api";
import { useStore } from "../store";
import { Badge, Panel } from "../ui";

function TelegramSection() {
  const qc = useQueryClient();
  const st = useQuery({ queryKey: ["telegram"], queryFn: api.telegramStatus, refetchInterval: 60_000 });
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const set = useMutation({
    mutationFn: (p: Parameters<typeof api.setPrefs>[0]) => api.setPrefs(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["telegram"] }),
  });
  const test = useMutation({
    mutationFn: api.telegramTest,
    onSuccess: () => setResult({ ok: true, text: "Test message sent. Check Telegram." }),
    onError: (e) => setResult({ ok: false, text: e instanceof ApiFailure ? `${e.code}: ${e.message}` : String(e) }),
  });
  const d = st.data;
  return (
    <div className="tgbox">
      <div className="aform-h">TELEGRAM ALERT DELIVERY</div>
      {st.isError && <div className="note warn">Could not read Telegram status.</div>}
      {d && !d.configured && (
        <>
          <div className="note"><Badge status="UNAVAILABLE" title="Not configured" /> Not configured. {d.setup}</div>
          <div className="note">The token and chat id live only in the backend environment. They are never shown here or sent to the browser.</div>
        </>)}
      {d?.configured && (
        <table className="tbl kv"><tbody>
          <tr><td>Bot</td><td className="r mono">{d.verified ? `@${d.bot_username}` : "token not verified"} {d.verified ? <span className="up">●</span> : <span className="down">●</span>}</td></tr>
          <tr><td>Chat</td><td className="r mono">{d.chat_hint}</td></tr>
          <tr><td>Send alerts to Telegram</td><td className="r"><input type="checkbox" checked={!!d.enabled} onChange={(e) => set.mutate({ telegram_enabled: e.target.checked })} aria-label="Enable Telegram delivery" /></td></tr>
          <tr><td>Minimum severity</td><td className="r"><select value={d.min_severity} onChange={(e) => set.mutate({ telegram_min_severity: e.target.value as never })} aria-label="Minimum severity">
            <option value="info">info (everything)</option><option value="warning">warning and up</option><option value="critical">critical only</option></select></td></tr>
          <tr><td>Test</td><td className="r"><button className="mini on" disabled={test.isPending} onClick={() => { setResult(null); test.mutate(); }}>Send test message</button></td></tr>
        </tbody></table>)}
      {result && <div className={`note ${result.ok ? "" : "warn"}`}>{result.text}</div>}
      {d?.configured && <div className="note">Alerts based on DEMO data are never sent. Events inside a cooldown are not sent. A failed send is recorded on the event; the in-app alert is always kept.</div>}
    </div>
  );
}

function IbkrSection() {
  const qc = useQueryClient();
  const st = useQuery({ queryKey: ["ibkr"], queryFn: api.ibkrStatus, refetchInterval: 10_000 });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const done = (text: string) => { setMsg({ ok: true, text }); for (const k of ["ibkr", "portfolios", "portfolio", "journal-trades", "journal-sources"]) qc.invalidateQueries({ queryKey: [k] }); };
  const fail = (e: unknown) => setMsg({ ok: false, text: e instanceof ApiFailure ? `${e.code}: ${e.message}` : String(e) });
  const connect = useMutation({ mutationFn: api.ibkrConnect, onSuccess: () => done("Connected."), onError: fail });
  const disconnect = useMutation({ mutationFn: api.ibkrDisconnect, onSuccess: () => done("Disconnected."), onError: fail });
  const sync = useMutation({ mutationFn: api.ibkrSync, onSuccess: (r) => done(`Journal: ${r.journal.inserted} new execution(s), ${r.journal.duplicates} already known. ${r.journal.note}`), onError: fail });
  const d = st.data;
  return (
    <div className="tgbox">
      <div className="aform-h">INTERACTIVE BROKERS (TWS / IB GATEWAY, LOCAL)</div>
      {d && !d.configured && <div className="note"><Badge status="UNAVAILABLE" title="Not configured" /> Not configured. {d.help}</div>}
      {d?.configured && (
        <>
          <table className="tbl kv"><tbody>
            <tr><td>Mode</td><td className="r mono">{d.mode === "paper_trading" ? "PAPER TRADING (orders → paper account only)" : "READ-ONLY (positions & executions)"}</td></tr>
            <tr><td>Connection</td><td className="r mono">{d.connected ? <span className="up">● connected</span> : <span className="dim">○ not connected</span>} {d.host}:{d.port}</td></tr>
            <tr><td>Account</td><td className="r mono">{d.account ?? "—"} {d.account ? (d.account_is_paper ? <span className="up small">paper</span> : <span className="warnc small">LIVE account (read-only)</span>) : null}</td></tr>
            {d.market_data && <tr title={d.market_data.note}><td>Market data from IBKR</td><td className="r mono">{d.market_data.active ? <span className="up">active (US stocks/ETFs)</span> : d.market_data.enabled ? <span className="warnc">enabled, waiting for connection</span> : "off"}</td></tr>}
            <tr><td>Can place orders</td><td className="r mono">{d.can_trade ? <span className="up">yes (paper)</span> : "no"}</td></tr>
          </tbody></table>
          {d.last_error && <div className="note warn">Last error: {d.last_error}</div>}
          <div className="toolbar">
            {!d.connected ? <button className="mini on" disabled={connect.isPending} onClick={() => connect.mutate()}>{connect.isPending ? "connecting…" : "Connect"}</button> : <button className="mini" onClick={() => disconnect.mutate()}>Disconnect</button>}
            <button className="mini" disabled={!d.connected || sync.isPending} onClick={() => sync.mutate()} title="Copy IBKR executions into the journal">Sync executions to journal</button>
          </div>
          <div className="note">{d.note}. ATLAS never routes orders to a live account: paper mode refuses live accounts and live ports, and read-only mode opens the API connection read-only.</div>
        </>)}
      {msg && <div className={`note ${msg.ok ? "" : "warn"}`} onClick={() => setMsg(null)}>{msg.text}</div>}
    </div>
  );
}

export function SettingsWidget() {
  const { theme, setTheme, updateSeconds, setUpdateSeconds } = useStore();
  const st = useQuery({ queryKey: ["status"], queryFn: api.status });
  return (
    <Panel title="SETTINGS">
      <table className="tbl kv"><tbody>
        <tr><td>Theme</td><td className="r"><button className={`mini ${theme === "dark" ? "on" : ""}`} onClick={() => setTheme("dark")}>dark</button>
          <button className={`mini ${theme === "light" ? "on" : ""}`} onClick={() => setTheme("light")}>light</button></td></tr>
        <tr><td>Update frequency (s)</td><td className="r"><select value={updateSeconds} onChange={(e) => setUpdateSeconds(Number(e.target.value))} aria-label="Update frequency">
          {[2, 5, 10, 30, 60].map((s) => <option key={s} value={s}>{s}s</option>)}</select></td></tr>
        <tr><td>Broker environment</td><td className="r mono">{st.data?.broker_env ?? "—"}</td></tr>
        <tr><td>Live trading</td><td className="r mono">{st.data?.live_trading_enabled ? "ENABLED" : "disabled (no order routes in this build)"}</td></tr>
        <tr><td>AI model</td><td className="r mono">{st.data?.ai.model ?? "not configured"}</td></tr>
        <tr><td>Data mode</td><td className="r mono">{st.data?.demo_mode ? "DEMO (synthetic)" : "live providers"}</td></tr>
      </tbody></table>
      <IbkrSection />
      <TelegramSection />
      <div className="note">Preferences, watchlists and layouts are stored on the backend and survive restarts. API keys live only in the backend environment.</div>
    </Panel>
  );
}
