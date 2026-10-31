import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ColorType, createChart, LineSeries, UTCTimestamp } from "lightweight-charts";
import { api, ApiFailure, HyperliquidSync, ImportPreview, JGroupRow, JNote, JTrade } from "../api";
import { ago, dir, num } from "../fmt";
import { useStore } from "../store";
import { Badge, ErrorBox, Panel } from "../ui";

const err = (e: unknown) => (e instanceof ApiFailure ? `${e.code}: ${e.message}` : String(e));
const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const money = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? "—" : num(x, d));
const signed = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? "—" : `${x >= 0 ? "+" : ""}${num(x, d)}`);
const dur = (s: number | null | undefined) => (s === null || s === undefined ? "—" : s < 3600 ? `${Math.round(s / 60)}m` : s < 172800 ? `${(s / 3600).toFixed(1)}h` : `${(s / 86400).toFixed(1)}d`);
const pc = (x: number | null | undefined, d = 0) => (x === null || x === undefined ? "—" : `${(x * 100).toFixed(d)}%`);

export function JournalTradesWidget() {
  const { journalKey, setJournalKey } = { journalKey: useStore((s) => s.journalKey), setJournalKey: useStore((s) => s.setJournalKey) };
  const [f, setF] = useState({ source: "", status: "", symbol: "" });
  const src = useQuery({ queryKey: ["journal-sources"], queryFn: api.journalSources });
  const q = useQuery({ queryKey: ["journal-trades", f], queryFn: () => api.journalTrades(f), refetchInterval: 20_000 });
  return (
    <Panel title={`TRADES${q.data ? ` · ${q.data.total}` : ""}`}>
      <div className="toolbar">
        <select value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} aria-label="Source filter"><option value="">all sources</option>{src.data?.sources.map((s) => <option key={s.source}>{s.source}</option>)}</select>
        <select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} aria-label="Status filter"><option value="">open + closed</option><option value="closed">closed</option><option value="open">open</option></select>
        <input className="w80" placeholder="symbol" value={f.symbol} onChange={(e) => setF({ ...f, symbol: e.target.value.toUpperCase() })} aria-label="Symbol filter" />
      </div>
      {q.isError && <ErrorBox error={q.error} />}
      <table className="tbl">
        <thead><tr><th>Opened</th><th>Symbol</th><th>Side</th><th className="r">Qty</th><th className="r">Entry</th><th className="r">Exit</th><th className="r">Net P&L</th><th className="r" title="Net P&L / planned risk (needs a planned stop)">R</th><th>Setup</th><th>Src</th></tr></thead>
        <tbody>{q.data?.trades.map((t: JTrade) => (
          <tr key={t.key} className={t.key === journalKey ? "sel" : ""} onClick={() => setJournalKey(t.key)}>
            <td className="dim small">{t.opened_at.slice(0, 16).replace("T", " ")}</td>
            <td><b>{t.symbol}</b>{t.liquidated && <span className="down small" title="Liquidation"> ⚡</span>}{t.has_notes && <span className="dim small" title="Has journal notes"> ✎</span>}</td>
            <td className={t.side === "long" ? "up" : "down"}>{t.side}</td><td className="r mono">{num(Number(t.qty_max), 6).replace(/\.?0+$/, "")}</td>
            <td className="r mono">{t.entry_avg ? num(Number(t.entry_avg), 4) : "—"}</td><td className="r mono">{t.status === "open" ? <span className="dim">open</span> : t.exit_avg ? num(Number(t.exit_avg), 4) : "—"}</td>
            <td className={`r mono ${dir(t.net_pnl_num)}`}>{signed(t.net_pnl_num)}</td><td className={`r mono ${dir(t.r_multiple)}`}>{t.r_multiple === null ? <span className="dim">—</span> : `${t.r_multiple >= 0 ? "+" : ""}${t.r_multiple.toFixed(2)}`}</td>
            <td className="small">{t.setup ?? <span className="dim">—</span>}</td><td className="dim small" title={t.source}>{t.source.length > 12 ? `${t.source.slice(0, 11)}…` : t.source}</td>
          </tr>))}</tbody>
      </table>
      {q.data && !q.data.trades.length && <div className="note">No trades yet. Import a CSV, sync IBKR/paper fills, or add a manual execution (panels below).</div>}
      <div className="note">Trades are derived from executions (FIFO lots; fees and funding included). Open trades show realized P&L so far.</div>
    </Panel>
  );
}

const FIELDS: [keyof JNote, string, "text" | "area"][] = [["setup", "Setup", "text"], ["catalyst", "Catalyst", "text"], ["timeframe", "Timeframe", "text"], ["thesis", "Thesis", "area"], ["notes", "Notes", "area"], ["lessons", "Lessons", "area"]];

async function toDataUrl(file: File): Promise<string> {
  const raw = await new Promise<string>((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result)); r.onerror = rej; r.readAsDataURL(file); });
  if (raw.length <= 600_000) return raw;
  const img = await new Promise<HTMLImageElement>((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = raw; });
  const k = Math.min(1, 1280 / Math.max(img.width, img.height));
  const c = document.createElement("canvas"); c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
  c.getContext("2d")!.drawImage(img, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.8);
}

export function JournalEditorWidget() {
  const qc = useQueryClient();
  const key = useStore((s) => s.journalKey);
  const d = useQuery({ queryKey: ["journal-trade", key], queryFn: () => api.journalTrade(key!), enabled: !!key });
  const [form, setForm] = useState<Record<string, string>>({});
  const [shot, setShot] = useState<string | null | undefined>(undefined);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const loadedKey = useRef<string | null>(null);
  const toForm = (n: JNote | null | undefined, fallbackStop: string | null | undefined): Record<string, string> => ({
    ...Object.fromEntries(FIELDS.map(([k]) => [k, (n?.[k] as string | null) ?? ""])), planned_stop: n?.planned_stop ?? fallbackStop ?? "",
    targets: (n?.targets ?? []).join(", "), mistakes: (n?.mistakes ?? []).join(", "), tags: (n?.tags ?? []).join(", "),
  });
  // Load the form ONCE per selected trade. A background refetch must never overwrite what the user is typing or clear a status message.
  useEffect(() => {
    if (d.data && d.data.trade.key === key && loadedKey.current !== key) {
      loadedKey.current = key;
      setForm(toForm(d.data.note, d.data.trade.planned_stop));
      setShot(undefined); setMsg(null);
    }
  }, [key, d.data]);
  const list = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
  const save = useMutation({
    mutationFn: () => api.journalNote(key!, { ...Object.fromEntries(FIELDS.map(([k]) => [k, form[k] || null])), planned_stop: form.planned_stop || null, targets: list(form.targets), mistakes: list(form.mistakes), tags: list(form.tags), ...(shot !== undefined ? { screenshot: shot } : {}) } as Partial<JNote>),
    onSuccess: (n) => {
      setForm(toForm(n, null)); setShot(undefined);          // show the server's canonical values (sorted tags, normalised stop)
      setMsg({ ok: true, text: "Saved." });
      for (const k of ["journal-trade", "journal-trades", "journal-stats"]) qc.invalidateQueries({ queryKey: [k] });
    },
    onError: (e) => setMsg({ ok: false, text: err(e) }),
  });
  const t = d.data?.trade;
  const shownShot = shot === undefined ? d.data?.note?.screenshot : shot;
  return (
    <Panel title="TRADE NOTES">
      {!key && <div className="note">Select a trade to add your thesis, mistakes and lessons.</div>}
      {d.isError && <ErrorBox error={d.error} />}
      {t && d.data && (
        <>
          <div className="qname"><span className={t.side === "long" ? "up" : "down"}>{t.side.toUpperCase()}</span> {t.symbol} <span className={`mono ${dir(t.net_pnl_num)}`}>{signed(t.net_pnl_num)} {t.currency}</span>{t.r_multiple !== null && <span className="dim mono"> · {t.r_multiple.toFixed(2)}R</span>}</div>
          <div className="note">{t.status} · gross {num(Number(t.gross_pnl), 2)} · fees {num(Number(t.fees), 4)} · funding {num(Number(t.funding), 4)} · held {dur(t.holding_seconds)} · {t.source}</div>
          <table className="tbl"><thead><tr><th>Time</th><th>Side</th><th className="r">Qty</th><th className="r">Price</th><th className="r">Fee</th><th /></tr></thead>
            <tbody>{d.data.executions.map((e) => <tr key={e.ext_id}><td className="dim small">{e.ts.slice(0, 19).replace("T", " ")}</td><td className={e.side === "buy" ? "up" : "down"}>{e.side}</td><td className="r mono">{e.qty}</td><td className="r mono">{e.price}</td><td className="r mono">{e.fee}</td><td className="dim small">{e.kind !== "trade" ? e.kind : ""}</td></tr>)}</tbody></table>
          <div className="jform">
            {FIELDS.map(([k, label, kind]) => (
              <label key={k}><span className="dim small">{label}</span>
                {kind === "area" ? <textarea rows={2} value={form[k] ?? ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} aria-label={label} /> : <input value={form[k] ?? ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} aria-label={label} />}</label>))}
            <label title="Initial invalidation level: gives this trade an R-multiple"><span className="dim small">Planned stop</span><input value={form.planned_stop ?? ""} onChange={(e) => setForm({ ...form, planned_stop: e.target.value })} aria-label="Planned stop" /></label>
            <label><span className="dim small">Targets (comma)</span><input value={form.targets ?? ""} onChange={(e) => setForm({ ...form, targets: e.target.value })} aria-label="Targets" /></label>
            <label><span className="dim small">Mistakes (comma)</span><input value={form.mistakes ?? ""} onChange={(e) => setForm({ ...form, mistakes: e.target.value })} aria-label="Mistakes" placeholder="e.g. early exit, no stop" /></label>
            <label><span className="dim small">Tags (comma)</span><input value={form.tags ?? ""} onChange={(e) => setForm({ ...form, tags: e.target.value })} aria-label="Tags" /></label>
          </div>
          <div className="toolbar">
            <label className="mini">chart screenshot… <input type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={async (e) => { const f = e.target.files?.[0]; if (f) { try { setShot(await toDataUrl(f)); } catch { setMsg({ ok: false, text: "could not read that image" }); } } }} aria-label="Attach screenshot" /></label>
            {shownShot && <button className="mini" onClick={() => setShot(null)}>remove screenshot</button>}
            <button className="mini on" disabled={save.isPending} onClick={() => save.mutate()}>Save notes</button>
          </div>
          {shownShot && <img className="shot" src={shownShot} alt="trade chart screenshot" />}
          {msg && <div className={`note ${msg.ok ? "" : "warn"}`}>{msg.text}</div>}
        </>)}
    </Panel>
  );
}

const ZONES = ["UTC", "America/New_York", "America/Chicago", "America/Los_Angeles", "Europe/London", "Europe/Zurich", "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney"];

export function JournalImportWidget() {
  const qc = useQueryClient();
  const presets = useQuery({ queryKey: ["journal-presets"], queryFn: api.journalPresets, staleTime: Infinity });
  const [source, setSource] = useState("variational");
  const [preset, setPreset] = useState("variational");
  const [kind, setKind] = useState<"trades" | "flows">("trades");
  const [text, setText] = useState("");
  const [filename, setFilename] = useState<string | undefined>();
  const [tz, setTz] = useState("UTC");
  const [invert, setInvert] = useState(false);
  const [mapping, setMapping] = useState<Record<string, string | null> | null>(null);
  const [pv, setPv] = useState<ImportPreview | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const body = () => ({ source, kind, text, preset, filename, ...(mapping ? { mapping } : {}), options: { tz, ...(invert ? { amount_sign: "invert" } : {}) } });
  const preview = useMutation({ mutationFn: (m?: Record<string, string | null> | null) => api.journalPreview({ ...body(), ...(m ? { mapping: m } : {}) }), onSuccess: (p) => { setPv(p); setMapping(p.mapping); setMsg(null); }, onError: (e) => { setPv(null); setMsg({ ok: false, text: err(e) }); } });
  const run = useMutation({
    mutationFn: () => api.journalImport(body()),
    onSuccess: (r) => { setMsg({ ok: true, text: `Imported ${r.inserted} new rows (${r.duplicates} already present, ${r.errors} errors).` }); setPv(null); setText(""); for (const k of ["journal-sources", "journal-trades", "journal-stats"]) qc.invalidateQueries({ queryKey: [k] }); },
    onError: (e) => setMsg({ ok: false, text: err(e) }),
  });
  const roles = presets.data?.roles[kind] ?? [];
  const info = presets.data?.presets[preset];
  return (
    <Panel title="IMPORT TRADES (CSV)">
      <div className="frow">
        <input className="w100" value={source} onChange={(e) => setSource(e.target.value)} aria-label="Import source name" list="jsrc" placeholder="source" /><datalist id="jsrc"><option>variational</option><option>ibkr:flex</option><option>manual-import</option></datalist>
        <select value={preset} onChange={(e) => { setPreset(e.target.value); setMapping(null); setPv(null); if (e.target.value === "variational") setSource("variational"); if (e.target.value === "ibkr_flex") setSource("ibkr:flex"); }} aria-label="Import preset">
          {presets.data && Object.entries(presets.data.presets).map(([k, v]) => <option key={k} value={k}>{v.label}{v.verified ? "" : " (unverified)"}</option>)}</select>
        <select value={kind} onChange={(e) => { setKind(e.target.value as "trades" | "flows"); setMapping(null); setPv(null); }} aria-label="File kind"><option value="trades">trades / fills</option><option value="flows">funding, fees, transfers</option></select>
      </div>
      {info && !info.verified && <div className="note warn">⚠ {info.note}</div>}
      <div className="frow">
        <label className="mini">choose file… <input type="file" accept=".csv,.txt,text/csv" hidden aria-label="CSV file" onChange={async (e) => { const f = e.target.files?.[0]; if (f) { setText(await f.text()); setFilename(f.name); setPv(null); setMapping(null); } }} /></label>
        <span className="dim small">{filename ?? "or paste below"}</span>
        <span className="dim small">timestamps are in</span>
        <select value={tz} onChange={(e) => setTz(e.target.value)} aria-label="Timestamp timezone">{ZONES.map((z) => <option key={z}>{z}</option>)}</select>
        {kind === "flows" && <label className="small" title="Tick if payments you MADE show as positive numbers"><input type="checkbox" checked={invert} onChange={(e) => setInvert(e.target.checked)} /> invert amount sign</label>}
      </div>
      <textarea className="paste" rows={4} value={text} onChange={(e) => { setText(e.target.value); setPv(null); }} placeholder="Paste CSV text (header row + rows)…" aria-label="CSV text" />
      <div className="toolbar"><button className="mini on" disabled={!text.trim() || preview.isPending} onClick={() => preview.mutate(undefined)}>{preview.isPending ? "reading…" : "Preview (nothing is saved)"}</button></div>
      {msg && <div className={`note ${msg.ok ? "" : "warn"}`} onClick={() => setMsg(null)}>{msg.text}</div>}
      {pv && (
        <div className="pvbox APPROVE_FOR_PAPER_REVIEW">
          <div className="pv-h"><b>{pv.parsed} of {pv.rows_total} rows parsed</b><span className="dim small">{pv.will_insert} new · {pv.already_imported} already imported · {pv.errors_total} errors · {Object.values(pv.skipped).reduce((a, b) => a + b, 0)} skipped</span></div>
          {pv.time_range && <div className="note">First row {pv.time_range[0].slice(0, 19).replace("T", " ")} UTC · last {pv.time_range[1].slice(0, 19).replace("T", " ")} UTC. Check these against your file: wrong timezone skews time-of-day statistics.</div>}
          <table className="tbl kv"><thead><tr><th>Field</th><th>Your column</th></tr></thead><tbody>{roles.map((r) => (
            <tr key={r}><td>{r}</td><td className="r"><select value={mapping?.[r] ?? ""} onChange={(e) => setMapping({ ...(mapping ?? {}), [r]: e.target.value || null })} aria-label={`Map ${r}`}><option value="">(none)</option>{pv.headers.map((h) => <option key={h}>{h}</option>)}</select></td></tr>))}</tbody></table>
          <div className="toolbar"><button className="mini" onClick={() => preview.mutate(mapping)}>re-check with this mapping</button></div>
          {pv.warnings.map((w) => <div key={w} className="note warn">⚠ {w}</div>)}
          {Object.entries(pv.skipped).map(([k, v]) => <div key={k} className="note">skipped {v}: {k}</div>)}
          {Object.keys(pv.kinds).length > 0 && <div className="note">types: {Object.entries(pv.kinds).map(([k, v]) => `${k} ${v}`).join(" · ")}</div>}
          {pv.errors.map((e) => <div key={e.line} className="note warn">line {e.line}: {e.error}</div>)}
          {pv.sample.length > 0 && <table className="tbl"><tbody>{pv.sample.map((r, i) => <tr key={i} className="small">{Object.entries(r).map(([k, v]) => <td key={k} className="mono">{v}</td>)}</tr>)}</tbody></table>}
          <button className="confirm" disabled={run.isPending || pv.will_insert === 0} onClick={() => run.mutate()}>{run.isPending ? "importing…" : `Import ${pv.will_insert} new row(s)`}</button>
          {pv.will_insert === 0 && <div className="note">Nothing new to import{pv.parsed === 0 ? ": fix the mapping above." : " (all rows already exist)."}</div>}
        </div>)}
    </Panel>
  );
}

export function JournalSourcesWidget() {
  const qc = useQueryClient();
  const src = useQuery({ queryKey: ["journal-sources"], queryFn: api.journalSources, refetchInterval: 30_000 });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [m, setM] = useState({ symbol: "", side: "buy", qty: "", price: "", fee: "0", ts: "", asset_class: "stock" });
  const refresh = () => { for (const k of ["journal-sources", "journal-trades", "journal-stats"]) qc.invalidateQueries({ queryKey: [k] }); };
  const del = useMutation({ mutationFn: (s: string) => api.journalDelete(s), onSuccess: (r) => { setMsg({ ok: true, text: `Deleted ${r.executions_deleted} executions.` }); refresh(); }, onError: (e) => setMsg({ ok: false, text: err(e) }) });
  const sync = useMutation({ mutationFn: api.journalSync, onSuccess: (r) => { setMsg({ ok: true, text: `Synced: ${JSON.stringify(r)}` }); refresh(); }, onError: (e) => setMsg({ ok: false, text: err(e) }) });
  const [hlAddr, setHlAddr] = useState(() => { try { return localStorage.getItem("atlas.hlAddress") ?? ""; } catch { return ""; } });
  const [hlRes, setHlRes] = useState<HyperliquidSync | null>(null);
  const hl = useMutation({
    mutationFn: () => api.journalHyperliquid(hlAddr.trim()),
    onSuccess: (r) => { setHlRes(r); setMsg(null); refresh(); try { localStorage.setItem("atlas.hlAddress", hlAddr.trim()); } catch { /* per-viewer convenience only */ } },
    onError: (e) => { setHlRes(null); setMsg({ ok: false, text: err(e) }); },
  });
  const add = useMutation({ mutationFn: () => api.journalManual(m), onSuccess: () => { setMsg({ ok: true, text: "Execution added." }); setM({ ...m, qty: "", price: "" }); refresh(); }, onError: (e) => setMsg({ ok: false, text: err(e) }) });
  return (
    <Panel title="JOURNAL SOURCES">
      <div className="toolbar"><button className="mini on" disabled={sync.isPending} onClick={() => sync.mutate()} title="Copy paper fills and (if connected) IBKR executions into the journal">sync paper + IBKR</button>
        <a className="mini" href="/api/journal/export.csv" download>export trades CSV</a></div>
      {src.isError && <ErrorBox error={src.error} />}
      <table className="tbl"><thead><tr><th>Source</th><th className="r">Execs</th><th className="r">Flows</th><th>Range</th><th /></tr></thead>
        <tbody>{src.data?.sources.map((s) => <tr key={s.source}><td><b>{s.source}</b></td><td className="r mono">{s.executions}</td><td className="r mono">{s.cashflows}</td><td className="dim small">{s.first?.slice(0, 10)} → {s.last?.slice(0, 10)}</td>
          <td className="r"><button className="mini" onClick={() => confirm(`Delete ALL data from "${s.source}" (executions, cash flows and notes on its trades)?`) && del.mutate(s.source)}>delete</button></td></tr>)}</tbody></table>
      {src.data && !src.data.sources.length && <div className="note">No sources yet.</div>}
      <div className="aform" id="hl-box"><div className="aform-h">HYPERLIQUID (read-only, public address)</div>
        <div className="frow"><input className="fval" style={{ width: 330 }} placeholder="0x… public wallet address (42 characters)" value={hlAddr} onChange={(e) => setHlAddr(e.target.value)} aria-label="Hyperliquid address" spellCheck={false} />
          <button className="mini on" disabled={hl.isPending || !hlAddr.trim()} onClick={() => hl.mutate()} title="Reads fills and funding from Hyperliquid's public API. Re-syncing only adds new rows.">{hl.isPending ? "syncing…" : "Sync"}</button></div>
        <div className="note">Paste only the PUBLIC address. Never a private key or API-wallet secret: none is needed and a key-shaped value is refused. Field names are from the public docs and unverified against the live API.</div>
        {hlRes && (
          <div className="note" role="status">
            <b>{hlRes.source}</b>: {hlRes.executions.inserted} new fills ({hlRes.executions.duplicates} already known), {hlRes.funding.inserted} funding payments.
            {" "}Hyperliquid reports realized P&L of {hlRes.reported.closed_pnl} (before fees); compare with the journal's gross P&L. {hlRes.reported.note}
            {hlRes.history_limit_note && <div className="warn">⚠ {hlRes.history_limit_note}</div>}
            {Object.entries(hlRes.skipped).map(([k, v]) => <div key={k} className="warn">⚠ {v} skipped: {k}</div>)}
            {hlRes.warnings.map((w) => <div key={w} className="warn">⚠ {w}</div>)}
          </div>)}</div>
      <div className="aform"><div className="aform-h">ADD A TRADE MANUALLY (executed elsewhere)</div>
        <div className="frow"><input className="w80" placeholder="Symbol" value={m.symbol} onChange={(e) => setM({ ...m, symbol: e.target.value })} aria-label="Manual symbol" />
          <select value={m.side} onChange={(e) => setM({ ...m, side: e.target.value })} aria-label="Manual side"><option>buy</option><option>sell</option></select>
          <input className="w60" placeholder="Qty" value={m.qty} onChange={(e) => setM({ ...m, qty: e.target.value })} aria-label="Manual quantity" />
          <input className="w80" placeholder="Price" value={m.price} onChange={(e) => setM({ ...m, price: e.target.value })} aria-label="Manual price" />
          <input className="w60" placeholder="Fee" value={m.fee} onChange={(e) => setM({ ...m, fee: e.target.value })} aria-label="Manual fee" /></div>
        <div className="frow"><input className="w140" placeholder="2026-03-09 14:30 (UTC)" value={m.ts} onChange={(e) => setM({ ...m, ts: e.target.value })} aria-label="Manual time" />
          <select value={m.asset_class} onChange={(e) => setM({ ...m, asset_class: e.target.value })} aria-label="Manual asset class"><option>stock</option><option>crypto</option><option>future</option><option>forex</option></select>
          <button className="mini on" disabled={add.isPending || !m.symbol || !m.qty || !m.price || !m.ts} onClick={() => add.mutate()}>Add</button></div></div>
      {msg && <div className={`note ${msg.ok ? "" : "warn"}`} onClick={() => setMsg(null)}>{msg.text}</div>}
      {src.data && src.data.batches.length > 0 && <div className="note">Recent imports: {src.data.batches.slice(0, 4).map((b) => `${b.source} ${b.inserted}+${b.duplicates}dup (${ago(b.created_at)})`).join(" · ")}</div>}
    </Panel>
  );
}

const GROUP_LABELS: Record<string, string> = { setup: "Setup", symbol: "Symbol", source: "Source", side: "Side", hour_et: "Entry hour (ET)", weekday_et: "Weekday (ET)", holding: "Holding time", r_bucket: "R bucket", tag: "Tags / mistakes" };

export function PerformanceWidget2() {
  const theme = useStore((s) => s.theme);
  const setAsk = useStore((s) => s.setPendingAsk);
  const setWorkspace = useStore((s) => s.setWorkspace);
  const [f, setF] = useState({ source: "", symbol: "", since: "", until: "" });
  const [tab, setTab] = useState("setup");
  const host = useRef<HTMLDivElement>(null);
  const src = useQuery({ queryKey: ["journal-sources"], queryFn: api.journalSources });
  const q = useQuery({ queryKey: ["journal-stats", f], queryFn: () => api.journalStats(f), refetchInterval: 30_000 });
  const d = q.data, s = d?.summary;
  useEffect(() => {
    if (!host.current || !d || d.equity_curve.length < 2) return;
    const c = createChart(host.current, { autoSize: true, layout: { background: { type: ColorType.Solid, color: css("--panel") }, textColor: css("--dim"), fontSize: 11 }, grid: { vertLines: { color: css("--grid") }, horzLines: { color: css("--grid") } },
      rightPriceScale: { borderColor: css("--border") }, timeScale: { borderColor: css("--border"), timeVisible: false } });
    const ser = c.addSeries(LineSeries, { color: css("--accent"), lineWidth: 2 });
    ser.setData(d.equity_curve.map((p, i) => ({ time: (Math.floor(new Date(p.ts).getTime() / 1000) + i) as UTCTimestamp, value: p.cum })));
    c.timeScale().fitContent();
    return () => c.remove();
  }, [d, theme]);
  const rows = useMemo<JGroupRow[]>(() => d?.groups[tab] ?? [], [d, tab]);
  const ask = (t: string) => { setAsk(t); setWorkspace("ai"); };
  return (
    <Panel title="PERFORMANCE ANALYSIS" right={d?.currency ? <span className="dim">{d.currency}</span> : null}>
      <div className="toolbar">
        <select value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} aria-label="Performance source"><option value="">all sources</option>{src.data?.sources.map((x) => <option key={x.source}>{x.source}</option>)}</select>
        <input className="w80" placeholder="symbol" value={f.symbol} onChange={(e) => setF({ ...f, symbol: e.target.value.toUpperCase() })} aria-label="Performance symbol" />
        <input className="w100" type="date" value={f.since} onChange={(e) => setF({ ...f, since: e.target.value })} aria-label="Since" /><span className="dim small">to</span>
        <input className="w100" type="date" value={f.until} onChange={(e) => setF({ ...f, until: e.target.value })} aria-label="Until" />
        <button className="mini ai" onClick={() => ask("Which of my setups have performed best, and is the sample large enough to say?")}>Ask desk: best setups</button>
        <button className="mini ai" onClick={() => ask("Do I perform better on BTC or on US equities? Check sample sizes before concluding.")}>Ask desk: BTC vs equities</button>
      </div>
      {q.isError && <ErrorBox error={q.error} />}
      {s && !s.reliable && <div className="note warn" role="alert">⚠ {s.n === 0 ? "No closed trades yet." : s.note}</div>}
      {d && Object.keys(d.excluded).length > 0 && <div className="note warn">Other currencies are NOT added in: {Object.entries(d.excluded).map(([k, v]) => `${k} (${v} trades)`).join(", ")}.</div>}
      {s && s.n > 0 && (
        <>
          <div className="stats">
            <div><span className="dim">TRADES</span><b className="mono">{s.n}</b></div>
            <div title={s.win_rate_ci95 ? `95% interval ${pc(s.win_rate_ci95[0])} to ${pc(s.win_rate_ci95[1])}` : ""}><span className="dim">WIN RATE</span><b className="mono">{pc(s.win_rate)}</b><span className="dim small">{s.win_rate_ci95 ? `${pc(s.win_rate_ci95[0])}–${pc(s.win_rate_ci95[1])}` : ""}</span></div>
            <div><span className="dim">NET P&L</span><b className={`mono ${dir(s.net_pnl)}`}>{signed(s.net_pnl)}</b></div>
            <div title={s.expectancy_ci95 ? `95% interval ${money(s.expectancy_ci95[0])} to ${money(s.expectancy_ci95[1])}` : "interval only from 30 trades"}><span className="dim">EXPECTANCY</span><b className={`mono ${dir(s.expectancy)}`}>{signed(s.expectancy)}</b><span className="dim small">{s.expectancy_ci95 ? `${money(s.expectancy_ci95[0])}…${money(s.expectancy_ci95[1])}` : "n<30"}</span></div>
            <div title={s.profit_factor_note ?? ""}><span className="dim">PROFIT FACTOR</span><b className="mono">{s.profit_factor === null || s.profit_factor === undefined ? "n/a" : s.profit_factor.toFixed(2)}</b></div>
            <div><span className="dim">AVG W / L</span><b className="mono">{money(s.avg_win, 1)} / {money(s.avg_loss, 1)}</b></div>
            <div><span className="dim">AVG R</span><b className="mono">{s.r?.avg_r === null || s.r?.avg_r === undefined ? "—" : s.r.avg_r.toFixed(2)}</b><span className="dim small">{s.r ? `${s.r.n} with stop` : ""}</span></div>
            <div><span className="dim">MAX DD</span><b className="mono down">{money(s.max_drawdown)}</b></div>
            <div><span className="dim">STREAKS W/L</span><b className="mono">{s.max_win_streak}/{s.max_loss_streak}</b></div>
            <div><span className="dim">AVG HOLD</span><b className="mono">{dur(s.avg_hold_seconds)}</b></div>
          </div>
          {s.expectancy_note && <div className={`note ${s.expectancy_ci95 && s.expectancy_ci95[0] <= 0 ? "warn" : ""}`}>{s.expectancy_note}</div>}
          {s.r?.note && <div className="note">{s.r.note}. Add a planned stop in the trade notes.</div>}
          {d && d.equity_curve.length >= 2 ? <div className="chart-host" ref={host} style={{ minHeight: 140, flex: "0 0 160px" }} /> : <div className="note">Equity curve needs at least 2 closed trades.</div>}
          <div className="toolbar" style={{ marginTop: 6 }}>{Object.entries(GROUP_LABELS).map(([k, l]) => <button key={k} className={`mini ${tab === k ? "on" : ""}`} onClick={() => setTab(k)}>{l}</button>)}</div>
          <table className="tbl"><thead><tr><th>{GROUP_LABELS[tab]}</th><th className="r">n</th><th className="r">Win %</th><th className="r">Net P&L</th><th className="r">Expect.</th><th className="r">PF</th><th className="r">Avg R</th><th>Sample</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.key} className={r.reliable ? "" : "dim"}>
                <td><b>{r.key}</b></td><td className="r mono">{r.n}</td><td className="r mono" title={r.win_rate_ci95 ? `95% CI ${pc(r.win_rate_ci95[0])}–${pc(r.win_rate_ci95[1])}` : ""}>{pc(r.win_rate)}</td>
                <td className={`r mono ${dir(r.net_pnl)}`}>{signed(r.net_pnl)}</td><td className={`r mono ${dir(r.expectancy)}`}>{signed(r.expectancy)}</td>
                <td className="r mono">{r.profit_factor === null ? "—" : r.profit_factor.toFixed(2)}</td><td className="r mono">{r.avg_r === null ? "—" : r.avg_r.toFixed(2)}</td>
                <td>{r.reliable ? <Badge status="HISTORICAL" title="30+ trades: still descriptive, not predictive" /> : <span className="warnc small" title="Fewer than 30 trades: anecdotal">⚠ n&lt;30</span>}</td>
              </tr>))}</tbody></table>
          <div className="note">{d?.caveats.join(" ")}</div>
        </>)}
    </Panel>
  );
}
