import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertEvent, AlertRow, AlertRule, api, ApiFailure } from "../api";
import { ago, num } from "../fmt";
import { useStore } from "../store";
import { Badge, ErrorBox, Panel } from "../ui";

const KINDS: Record<string, string> = { price: "Price level", pct_change: "% change", rsi: "RSI", ma: "Price vs SMA", macd: "MACD cross", rvol: "Relative volume (daily)", scan: "Scan: new matches" };
const IVS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];
const COOLDOWNS: [number, string][] = [[300, "5 min"], [900, "15 min"], [3600, "1 hour"], [14400, "4 hours"], [86400, "1 day"]];
type Form = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const blank = (kind: string, instrument: string): Form => ({
  price: { kind, instrument_id: instrument, op: "above", level: "", cooldown_seconds: 3600, severity: "info" },
  pct_change: { kind, instrument_id: instrument, op: "below", threshold: -3, cooldown_seconds: 3600, severity: "info" },
  rsi: { kind, instrument_id: instrument, op: "below", level: 30, period: 14, interval: "1d", on_close: true, cooldown_seconds: 3600, severity: "info" },
  ma: { kind, instrument_id: instrument, op: "above", length: 50, interval: "1d", on_close: true, cooldown_seconds: 3600, severity: "info" },
  macd: { kind, instrument_id: instrument, direction: "bullish", interval: "1d", on_close: true, cooldown_seconds: 3600, severity: "info" },
  rvol: { kind, instrument_id: instrument, threshold: 3, cooldown_seconds: 3600, severity: "info" },
  scan: { kind, preset: "momentum_breakout", interval_seconds: 900, cooldown_seconds: 86400, max_symbols: 10, severity: "info" },
} as Record<string, Form>)[kind];

const err = (e: unknown) => (e instanceof ApiFailure ? `${e.code}: ${e.message}` : String(e));

export function AlertsWidget() {
  const qc = useQueryClient();
  const selected = useStore((s) => s.selected);
  const draft = useStore((s) => s.alertDraft);
  const setDraft = useStore((s) => s.setAlertDraft);
  const [form, setForm] = useState<Form>(() => blank("price", selected));
  const [editing, setEditing] = useState<number | null>(null);
  const [fromDraft, setFromDraft] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: api.alerts, refetchInterval: 10_000 });
  const presets = useQuery({ queryKey: ["scan-presets"], queryFn: api.scanPresets, staleTime: Infinity });
  const tg = useQuery({ queryKey: ["telegram"], queryFn: api.telegramStatus, staleTime: 60_000 });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["alerts"] }); qc.invalidateQueries({ queryKey: ["alert-events"] }); };

  useEffect(() => {
    if (!draft) return;
    const merged: Form = { ...blank(String(draft.kind), selected), ...draft };
    if (merged.kind === "scan" && merged.spec) delete merged.preset;   // a scan alert takes a preset OR a spec, never both
    setForm(merged); setEditing(null); setFromDraft(true); setDraft(null);
  }, [draft]);
  const set = (k: string, v: unknown) => setForm((f) => ({ ...f, [k]: v }));

  const save = useMutation({
    mutationFn: () => {
      const rule = { ...form } as AlertRule;
      for (const k of ["level", "threshold", "length", "period"]) if (k in rule && rule[k] !== "") rule[k] = Number(rule[k]);
      return editing ? api.alertUpdate(editing, rule) : api.alertCreate(rule);
    },
    onSuccess: (a) => { setMsg(`${editing ? "Updated" : "Created"}: ${a.name}. It arms on its next check and only fires on a NEW transition.`); setEditing(null); setFromDraft(false); setForm(blank(String(form.kind), selected)); refresh(); },
    onError: (e) => setMsg(err(e)),
  });
  const toggle = useMutation({
    mutationFn: (a: AlertRow) => api.alertEnable(a.id, !a.enabled),
    onMutate: async (a) => {   // optimistic: the checkbox flips immediately, rolled back if the server refuses
      await qc.cancelQueries({ queryKey: ["alerts"] });
      const prev = qc.getQueryData<AlertRow[]>(["alerts"]);
      qc.setQueryData<AlertRow[]>(["alerts"], (rows) => rows?.map((r) => (r.id === a.id ? { ...r, enabled: !a.enabled } : r)));
      return { prev };
    },
    onError: (_e, _a, ctx) => ctx?.prev && qc.setQueryData(["alerts"], ctx.prev),
    onSettled: refresh,
  });
  const del = useMutation({ mutationFn: (id: number) => api.alertDelete(id), onSuccess: refresh });
  const check = useMutation({ mutationFn: api.alertEvaluate, onSuccess: (r) => { setMsg(`Checked ${r.evaluated} alert(s): ${r.events.length} event(s).`); refresh(); }, onError: (e) => setMsg(err(e)) });

  const k = String(form.kind);
  const needsInstrument = k !== "scan";
  return (
    <Panel title="ALERTS" right={<button className="mini" disabled={check.isPending} onClick={() => check.mutate()} title="Run one evaluation pass now (the server also checks on a timer)">check now</button>}>
      <div className="aform">
        <div className="aform-h">{editing ? `Editing alert #${editing} (saving re-baselines it)` : fromDraft ? "Draft: review and press Create" : "New alert"}</div>
        <div className="frow">
          <select value={k} onChange={(e) => { setForm(blank(e.target.value, selected)); setEditing(null); }} aria-label="Alert type">{Object.entries(KINDS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
          {needsInstrument && <input className="w100" value={String(form.instrument_id ?? "")} onChange={(e) => set("instrument_id", e.target.value.toUpperCase())} aria-label="Symbol" placeholder="Symbol" />}
          {needsInstrument && <button className="mini" onClick={() => set("instrument_id", selected.split(":").slice(2, 3)[0])} title="Use the selected instrument">use selected</button>}
        </div>
        <div className="frow">
          {(k === "price" || k === "rsi" || k === "ma") && <select value={form.op} onChange={(e) => set("op", e.target.value)} aria-label="Condition"><option>above</option><option>below</option></select>}
          {k === "pct_change" && <select value={form.op} onChange={(e) => set("op", e.target.value)} aria-label="Condition"><option value="above">change ≥</option><option value="below">change ≤</option></select>}
          {k === "macd" && <select value={form.direction} onChange={(e) => set("direction", e.target.value)} aria-label="Direction"><option>bullish</option><option>bearish</option></select>}
          {(k === "price" || k === "rsi") && <input className="w80" type="number" value={form.level} onChange={(e) => set("level", e.target.value)} aria-label="Level" placeholder={k === "rsi" ? "RSI level" : "Price"} />}
          {(k === "pct_change" || k === "rvol") && <input className="w80" type="number" value={form.threshold} onChange={(e) => set("threshold", e.target.value)} aria-label="Threshold" />}
          {k === "ma" && <><span className="dim">SMA</span><input className="w60" type="number" value={form.length} onChange={(e) => set("length", e.target.value)} aria-label="SMA length" /></>}
          {(k === "rsi" || k === "ma" || k === "macd") && <select value={form.interval} onChange={(e) => set("interval", e.target.value)} aria-label="Interval">{IVS.map((i) => <option key={i}>{i}</option>)}</select>}
          {(k === "rsi" || k === "ma" || k === "macd") && <label className="small" title="Evaluate the last COMPLETED candle. Off = react to the forming candle (can flip back before it closes)."><input type="checkbox" checked={form.on_close} onChange={(e) => set("on_close", e.target.checked)} /> on candle close</label>}
          {k === "scan" && <select value={form.spec ? "__custom" : form.preset} onChange={(e) => { const { spec: _s, ...rest } = form; void _s; setForm({ ...rest, preset: e.target.value }); }} aria-label="Scan preset">
            {form.spec && <option value="__custom">{String((form.spec as { name?: string }).name ?? "custom scan")} (from scanner)</option>}
            {presets.data?.presets.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>}
        </div>
        <div className="frow">
          <span className="dim small">cooldown</span>
          <select value={form.cooldown_seconds} onChange={(e) => set("cooldown_seconds", Number(e.target.value))} aria-label="Cooldown">{COOLDOWNS.map(([s, l]) => <option key={s} value={s}>{l}</option>)}</select>
          <span className="dim small">severity</span>
          <select value={form.severity} onChange={(e) => set("severity", e.target.value)} aria-label="Severity"><option>info</option><option>warning</option><option>critical</option></select>
          <input className="grow" value={form.name ?? ""} onChange={(e) => set("name", e.target.value)} placeholder="Name (optional)" aria-label="Alert name" />
          {tg.data?.configured && <label className="small" title="Also send this alert to Telegram (subject to the minimum severity set in Settings)"><input type="checkbox" checked={form.telegram !== false} onChange={(e) => set("telegram", e.target.checked)} /> Telegram</label>}
          <button className="mini on" disabled={save.isPending} onClick={() => save.mutate()}>{editing ? "Update" : "Create"}</button>
          {(editing || fromDraft) && <button className="mini" onClick={() => { setEditing(null); setFromDraft(false); setForm(blank(k, selected)); }}>cancel</button>}
        </div>
        {msg && <div className={`note ${msg.includes(":") && /[A-Z_]{5,}:/.test(msg) ? "warn" : ""}`} onClick={() => setMsg(null)}>{msg}</div>}
        <div className="note">Alerts fire when a condition <b>turns true</b> (not while it stays true), only on fresh data, then wait out the cooldown. Stale or unavailable data skips the check.</div>
      </div>
      {alerts.isError && <ErrorBox error={alerts.error} />}
      <table className="tbl">
        <thead><tr><th>On</th><th>Alert</th><th>Last check</th><th>Data</th><th className="r">Last</th><th className="r">Fires</th><th /></tr></thead>
        <tbody>{alerts.data?.map((a) => (
          <tr key={a.id} className={a.enabled ? "" : "dim"}>
            <td><input type="checkbox" checked={a.enabled} onChange={() => toggle.mutate(a)} aria-label={`Enable ${a.name}`} /></td>
            <td title={`v${a.version} · ${JSON.stringify(a.rule)}`}><b>{a.name}</b>{a.state.error && <div className="down small">error: {a.state.error}</div>}{a.state.last_skip && <div className="note warn">skipped: {a.state.last_skip}</div>}</td>
            <td className="dim">{a.state.last_eval_at ? ago(new Date(a.state.last_eval_at * 1000).toISOString()) : a.enabled ? "pending" : "—"}</td>
            <td>{a.state.last_status ? <Badge status={a.state.last_status as never} /> : <span className="dim">—</span>}</td>
            <td className="r mono">{a.state.last_value !== undefined && a.state.last_value !== null ? num(a.state.last_value, 2) : "—"}</td>
            <td className="r mono">{a.state.fires ?? 0}</td>
            <td className="r"><button className="mini" onClick={() => { setForm({ ...a.rule }); setEditing(a.id); setFromDraft(false); }}>edit</button>
              <button className="mini" aria-label={`Delete ${a.name}`} onClick={() => confirm(`Delete "${a.name}"?`) && del.mutate(a.id)}>✕</button></td>
          </tr>))}</tbody>
      </table>
      {alerts.data && !alerts.data.length && <div className="note">No alerts yet. Try the command bar: <span className="mono">ALERT BTC ABOVE 70000</span>.</div>}
    </Panel>
  );
}

export function AlertEventsWidget() {
  const qc = useQueryClient();
  const select = useStore((s) => s.select);
  const [perm, setPerm] = useState<string>(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
  const ev = useQuery({ queryKey: ["alert-events"], queryFn: () => api.alertEvents(100), refetchInterval: 8000 });
  const read = useMutation({ mutationFn: (ids: number[] | null) => api.alertRead(ids), onSuccess: () => qc.invalidateQueries({ queryKey: ["alert-events"] }) });
  const open = (e: AlertEvent) => { const id = e.trigger.rule?.instrument_id; if (id) select(id); if (!e.read) read.mutate([e.id]); };
  return (
    <Panel title={`ALERT EVENTS${ev.data?.unread ? ` · ${ev.data.unread} unread` : ""}`}
      right={<><button className="mini" disabled={!ev.data?.unread} onClick={() => read.mutate(null)}>mark all read</button>
        {perm === "default" && <button className="mini" onClick={async () => setPerm(await Notification.requestPermission())} title="Show desktop notifications while this tab is open">enable browser notifications</button>}
        {perm === "granted" && <span className="dim">browser notifications on</span>}</>}>
      {ev.isError && <ErrorBox error={ev.error} />}
      <div className="events">
        {ev.data?.events.map((e) => {
          const sup = e.delivery.startsWith("suppressed");
          return (
            <div key={e.id} className={`event ${e.severity} ${e.read ? "isread" : ""} ${sup ? "sup" : ""}`} onClick={() => open(e)}>
              <div className="event-h"><span className={`sev ${e.severity}`}>{sup ? "SUPPRESSED" : e.severity.toUpperCase()}</span>
                <span className="dim small">{new Date(e.ts).toLocaleString("en-GB")} · {ago(e.ts)}</span>
                {e.trigger.data?.status && <Badge status={e.trigger.data.status} />}</div>
              <div className="event-m">{e.message}</div>
              <div className="meta">rule v{e.rule_version} · {e.delivery}{sup ? " (inside cooldown: recorded, not notified)" : ""}{e.trigger.data?.provider ? ` · data: ${e.trigger.data.provider}` : ""}</div>
            </div>);
        })}
        {ev.data && !ev.data.events.length && <div className="note">No events yet. Events appear here when an alert condition turns true.</div>}
      </div>
    </Panel>
  );
}
