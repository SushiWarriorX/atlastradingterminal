import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errText, JEntry } from "../api";
import { dir, num } from "../fmt";
import { useStore } from "../store";
import { ErrorBox, Panel } from "../ui";

const FIELDS = ["symbol", "direction", "size", "entry_price", "exit_price", "entry_at", "exit_at", "fees", "planned_stop", "note", "thesis", "risk_plan", "outcome"] as const;
type Form = Record<(typeof FIELDS)[number], string> & { screenshot: string | null };
const BLANK: Form = { symbol: "", direction: "long", size: "", entry_price: "", exit_price: "", entry_at: "", exit_at: "", fees: "", planned_stop: "", note: "", thesis: "", risk_plan: "", outcome: "", screenshot: null };
const day = (iso: string | null) => (iso ? iso.slice(0, 10) : "");
const signed = (x: number | null | undefined) => (x === null || x === undefined ? "—" : `${x >= 0 ? "+" : ""}${num(x, 2)}`);

const fromEntry = (e: JEntry): Form => ({
  symbol: e.symbol, direction: e.direction, size: e.size ?? "", entry_price: e.entry_price ?? "", exit_price: e.exit_price ?? "", entry_at: day(e.entry_at), exit_at: day(e.exit_at),
  fees: e.fees && e.fees !== "0" ? e.fees : "", planned_stop: e.planned_stop ?? "", note: e.note ?? "", thesis: e.thesis ?? "", risk_plan: e.risk_plan ?? "", outcome: e.outcome ?? "", screenshot: e.screenshot ?? null,
});

/** The simple journal: write a trade down like a note. Everything but the symbol is optional; P&L appears when entry, exit and size are all there. */
export function JournalQuickWidget() {
  const qc = useQueryClient();
  const setWorkspace = useStore((s) => s.setWorkspace);
  const [f, setF] = useState({ q: "", status: "", direction: "" });
  const [form, setForm] = useState<Form>(BLANK);
  const [editing, setEditing] = useState<string | null>(null);   // entry id being edited, or null when adding
  const [more, setMore] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const log = useQuery({ queryKey: ["journal-log", f], queryFn: () => api.journalLog(f), refetchInterval: 30_000 });
  const done = () => { setForm(BLANK); setEditing(null); setMore(false); setMsg(null); qc.invalidateQueries({ queryKey: ["journal-log"] }); };
  const body = (): Record<string, string | null> => {
    const b: Record<string, string | null> = {};
    for (const k of FIELDS) {
      const v = form[k].trim();
      if (editing) b[k] = v === "" && k !== "symbol" && k !== "direction" && k !== "entry_at" ? null : v;      // editing: an emptied field is cleared
      else if (v) b[k] = v;
    }
    if (editing) b.screenshot = form.screenshot; else if (form.screenshot) b.screenshot = form.screenshot;
    if (editing && !b.entry_at) delete b.entry_at;
    return b;
  };
  const save = useMutation({ mutationFn: () => (editing ? api.entryUpdate(editing, body()) : api.entryCreate(body())), onSuccess: done, onError: (e) => setMsg(errText(e)) });
  const del = useMutation({ mutationFn: (id: string) => api.entryDelete(id), onSuccess: done, onError: (e) => setMsg(errText(e)) });
  const open = async (e: JEntry) => {
    if (!e.editable) { setMsg("Imported trades are read-only here. Open the detailed journal to add notes to them."); return; }
    const full = await api.entryGet(e.id);
    setForm(fromEntry(full)); setEditing(e.id); setMore(true); setMsg(null);
  };
  const pick = (file: File | undefined) => {
    if (!file) return;
    const r = new FileReader();
    r.onload = () => setForm((x) => ({ ...x, screenshot: String(r.result) }));
    r.readAsDataURL(file);
  };
  const set = (k: keyof Form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const st = log.data?.stats;
  return (
    <Panel title={`JOURNAL${log.data ? ` · ${log.data.total}` : ""}`} right={<button className="mini" onClick={() => setWorkspace("journal-advanced")}>imports and detailed analytics</button>}>
      {st && st.n > 0 && (
        <div className="stats jq-stats" data-testid="journal-stats">
          <div><span className="dim small">Closed trades</span><b>{st.n}</b></div>
          <div><span className="dim small">Net P&L</span><b className={dir(st.net_pnl ?? 0)}>{signed(st.net_pnl)}</b></div>
          <div><span className="dim small">Win rate</span><b>{st.win_rate === undefined ? "—" : `${Math.round(st.win_rate * 100)}%`}</b></div>
          <div><span className="dim small">Profit factor</span><b>{st.profit_factor == null ? "—" : num(st.profit_factor, 2)}</b></div>
          {st.note && <span className="note warn">{st.note}</span>}
        </div>)}
      <div className="jq-form" data-testid="journal-form">
        <div className="jq-row">
          <input className="w80" placeholder="symbol" value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value.toUpperCase() })} aria-label="Symbol" />
          <span className="savedchip">
            <button className={`mini ${form.direction === "long" ? "on" : ""}`} onClick={() => setForm({ ...form, direction: "long" })}>long</button>
            <button className={`mini ${form.direction === "short" ? "on" : ""}`} onClick={() => setForm({ ...form, direction: "short" })}>short</button>
          </span>
          <input className="w80" placeholder="size" value={form.size} onChange={set("size")} aria-label="Size" />
          <input className="w80" placeholder="entry" value={form.entry_price} onChange={set("entry_price")} aria-label="Entry price" />
          <input className="w80" placeholder="exit" value={form.exit_price} onChange={set("exit_price")} aria-label="Exit price" />
          <input type="date" value={form.entry_at} onChange={set("entry_at")} aria-label="Entry date" />
        </div>
        <div className="jq-row">
          <input className="jq-note" placeholder="Write a note: why you took it, what you saw…" value={form.note} onChange={set("note")} aria-label="Note" />
          <button className="mini" onClick={() => setMore(!more)}>{more ? "fewer details" : "more details"}</button>
          <button className="mini on" disabled={save.isPending || !form.symbol.trim()} onClick={() => save.mutate()}>{editing ? "save" : "add"}</button>
          {editing && <><button className="mini" onClick={done}>cancel</button><button className="mini" onClick={() => window.confirm("Delete this entry?") && del.mutate(editing)}>delete</button></>}
        </div>
        {more && (
          <div className="jq-more">
            <label>Exit date<input type="date" value={form.exit_at} onChange={set("exit_at")} /></label>
            <label>Fees<input className="w80" value={form.fees} onChange={set("fees")} /></label>
            <label>Planned stop<input className="w80" value={form.planned_stop} onChange={set("planned_stop")} /></label>
            <label className="jq-wide">Thesis<textarea rows={2} value={form.thesis} onChange={set("thesis")} /></label>
            <label className="jq-wide">Risk plan<textarea rows={2} value={form.risk_plan} onChange={set("risk_plan")} /></label>
            <label className="jq-wide">Outcome<textarea rows={2} value={form.outcome} onChange={set("outcome")} /></label>
            <label className="jq-wide">Screenshot<input type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => pick(e.target.files?.[0])} /></label>
            {form.screenshot && <div className="jq-wide"><img className="shot" src={form.screenshot} alt="Attached screenshot" /> <button className="mini" onClick={() => setForm({ ...form, screenshot: null })}>remove</button></div>}
          </div>)}
        {msg && <div className="warnc small" data-testid="journal-msg">{msg}</div>}
      </div>
      <div className="toolbar">
        <input placeholder="search notes and symbols" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} aria-label="Search journal" />
        <select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} aria-label="Status filter"><option value="">all</option><option value="closed">closed</option><option value="open">open</option><option value="note">notes</option></select>
        <select value={f.direction} onChange={(e) => setF({ ...f, direction: e.target.value })} aria-label="Direction filter"><option value="">long + short</option><option value="long">long</option><option value="short">short</option></select>
      </div>
      {log.isError && <ErrorBox error={log.error} />}
      {log.data && log.data.items.length === 0 && <div className="note">{log.data.total === 0 && !f.q && !f.status && !f.direction ? "No entries yet. Add your first above: a symbol and a note is enough." : "Nothing matches these filters."}</div>}
      {log.data && log.data.items.length > 0 && (
        <table className="tbl" data-testid="journal-list">
          <thead><tr><th>Date</th><th>Symbol</th><th>Side</th><th className="r">Size</th><th className="r">Entry</th><th className="r">Exit</th><th className="r">P&L</th><th className="r">Return</th><th>Note</th></tr></thead>
          <tbody>{log.data.items.map((e) => (
            <tr key={e.id} className={editing === e.id ? "sel" : ""} onClick={() => open(e)} title={e.status === "note" ? "A note: add size, entry and exit to see P&L" : e.pnl_missing.length ? `P&L needs: ${e.pnl_missing.join(", ")}` : undefined}>
              <td className="dim">{day(e.entry_at)}</td><td><b>{e.symbol}</b>{e.origin === "imported" && <span className="pill"> imported</span>}</td><td className={e.status === "note" ? "dim" : ""}>{e.status === "note" ? "note" : e.direction}</td>
              <td className="r mono">{e.size ?? "—"}</td><td className="r mono">{e.entry_price ?? "—"}</td><td className="r mono">{e.exit_price ?? "—"}</td>
              <td className={`r mono ${dir(e.net_pnl_num ?? 0)}`}>{e.status === "closed" ? signed(e.net_pnl_num) : e.status === "open" ? "open" : "—"}</td>
              <td className={`r mono ${dir(e.return_pct ?? 0)}`}>{e.return_pct === null ? "—" : `${signed(e.return_pct)}%`}</td>
              <td className="dim">{(e.note ?? e.thesis ?? "").slice(0, 60)}</td>
            </tr>))}</tbody>
        </table>)}
    </Panel>
  );
}
