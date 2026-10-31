import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiFailure, OrderBody, OrderPreview, RiskCheck } from "../api";
import { ago, dir, num, pct } from "../fmt";
import { useStore } from "../store";
import { Badge, ErrorBox, Panel } from "../ui";

const n = (x: string | number | null | undefined) => (x === null || x === undefined || x === "" ? null : Number(x));
const money = (x: string | number | null | undefined, d = 2) => (n(x) === null ? "—" : num(n(x), d));
const signed = (x: string | number | null | undefined, d = 2) => (n(x) === null ? "—" : `${n(x)! >= 0 ? "+" : ""}${num(n(x), d)}`);
const err = (e: unknown) => (e instanceof ApiFailure ? `${e.code}: ${e.message}` : String(e));
const px = (x: string | null | undefined) => (n(x) === null ? "—" : num(n(x), Math.abs(n(x)!) >= 100 ? 2 : 4));

/** The selected portfolio is global: the portfolio, ticket, orders and risk panels must always show the SAME account. */
export function usePortfolioId() {
  const list = useQuery({ queryKey: ["portfolios"], queryFn: api.portfolios });
  const stored = useStore((s) => s.portfolioId);
  const setPid = useStore((s) => s.setPortfolioId);
  const valid = list.data?.some((p) => p.id === stored);
  const id = valid ? stored : (list.data?.find((p) => p.kind === "paper") ?? list.data?.[0])?.id;
  return { list, pid: id, setPid, current: list.data?.find((p) => p.id === id) };
}

export function PortfolioWidget() {
  const qc = useQueryClient();
  const every = useStore((s) => s.updateSeconds) * 1000;
  const select = useStore((s) => s.select);
  const selected = useStore((s) => s.selected);
  const { list, pid, setPid, current } = usePortfolioId();
  const q = useQuery({ queryKey: ["portfolio", pid], queryFn: () => api.portfolio(pid), enabled: pid !== undefined, refetchInterval: every, retry: 1 });
  const [form, setForm] = useState({ symbol: "", qty: "", cost: "" });
  const [cash, setCash] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["portfolio"] }); qc.invalidateQueries({ queryKey: ["portfolios"] }); };
  const addPos = useMutation({ mutationFn: () => api.manualPosition(pid!, form.symbol.trim().toUpperCase(), form.qty, form.cost), onSuccess: () => { setForm({ symbol: "", qty: "", cost: "" }); setMsg(null); refresh(); }, onError: (e) => setMsg(err(e)) });
  const setCashM = useMutation({ mutationFn: () => api.manualCash(pid!, cash), onSuccess: () => { setCash(""); setMsg(null); refresh(); }, onError: (e) => setMsg(err(e)) });
  const create = useMutation({ mutationFn: (v: { name: string; kind: string; cash: string }) => api.portfolioCreate(v.name, v.kind, v.cash), onSuccess: (p) => { setPid(p.id); refresh(); }, onError: (e) => setMsg(err(e)) });
  const reset = useMutation({ mutationFn: () => api.paperReset(pid!), onSuccess: refresh, onError: (e) => setMsg(err(e)) });
  const d = q.data;
  const manual = current?.kind === "manual" && current?.venue === "sim";     // only user-entered holdings are editable
  const ibkr = current?.venue === "ibkr";
  const tag = ibkr ? (current?.kind === "paper" ? "IBKR PAPER ACCOUNT · REAL BROKER FILLS" : "IBKR · READ-ONLY") : manual ? "MANUAL HOLDINGS" : "PAPER ACCOUNT · SIMULATED";
  return (
    <Panel title={`PORTFOLIO ${current ? `· ${current.name}` : ""}`} right={<span className="env-tag">{tag}</span>}>
      <div className="toolbar">
        {list.data?.map((p) => <button key={p.id} className={`mini ${p.id === pid ? "on" : ""}`} onClick={() => setPid(p.id)}>{p.name}{p.kind === "manual" ? " (manual)" : ""}</button>)}
        <button className="mini" onClick={() => { const nm = prompt("Portfolio name"); if (!nm?.trim()) return; const k = confirm("OK = paper account (simulated trading)\nCancel = manual holdings (you enter positions yourself)") ? "paper" : "manual"; const c = prompt("Starting cash (USD)", "100000"); if (c) create.mutate({ name: nm.trim(), kind: k, cash: c }); }}>+ portfolio</button>
        {ibkr && <button className="mini" onClick={() => api.ibkrSync().then(refresh).catch((e) => setMsg(err(e)))} title="Pull cash and positions from IBKR now">sync from IBKR</button>}
        {current && !manual && !ibkr && <button className="mini" onClick={() => confirm(`Reset "${current.name}"?\nThis deletes its orders, fills and history and restores starting cash.`) && reset.mutate()}>reset paper</button>}
      </div>
      {q.isError && <ErrorBox error={q.error} />}
      {d && (
        <>
          <div className="stats">
            <div><span className="dim">EQUITY</span><b className="mono">{money(d.equity)}</b></div>
            <div><span className="dim">CASH</span><b className="mono">{money(d.cash)}</b></div>
            <div><span className="dim">UNREALIZED</span><b className={`mono ${dir(n(d.unrealized_total))}`}>{signed(d.unrealized_total)}</b></div>
            <div><span className="dim">REALIZED</span><b className={`mono ${dir(n(d.realized_total))}`}>{signed(d.realized_total)}</b></div>
            <div><span className="dim">DAY P&L</span><b className={`mono ${dir(n(d.day_pnl_total))}`}>{signed(d.day_pnl_total)}</b></div>
            <div title="Gross exposure / equity. No margin: cash only."><span className="dim">GROSS</span><b className="mono">{pct(n(d.exposure.gross_pct)).replace("+", "")}</b></div>
          </div>
          {d.valuation_note && <div className="note warn">⚠ {d.valuation_note}</div>}
          {d.halted && <div className="note warn">⛔ Trading is HALTED (kill switch). New orders are blocked.</div>}
          <table className="tbl">
            <thead><tr><th>Symbol</th><th className="r">Qty</th><th className="r">Avg cost</th><th className="r">Mark</th><th className="r">Value</th><th className="r">Unreal.</th><th className="r">Wt%</th><th className="r" title="Planned stop (risk sizing only; not an order)">Stop</th><th>Data</th></tr></thead>
            <tbody>{d.positions.map((p) => (
              <tr key={p.instrument_id} className={p.instrument_id === selected ? "sel" : ""} onClick={() => select(p.instrument_id)}>
                <td><b>{p.symbol}</b></td><td className="r mono">{num(n(p.qty), 6).replace(/\.?0+$/, "")}</td><td className="r mono">{px(p.avg_cost)}</td>
                <td className="r mono">{px(p.mark)}</td><td className="r mono">{money(p.value)}</td>
                <td className={`r mono ${dir(n(p.unrealized))}`}>{signed(p.unrealized)}{p.unrealized_pct ? <span className="dim small"> {pct(n(p.unrealized_pct))}</span> : null}</td>
                <td className="r mono">{p.weight_pct ? num(n(p.weight_pct), 1) : "—"}</td><td className="r mono">{p.planned_stop ? px(p.planned_stop) : <span className="dim">none</span>}</td>
                <td>{p.valuation === "at_cost" ? <Badge status="UNAVAILABLE" title="No price: valued at cost" /> : p.data ? <Badge status={p.data.status} /> : null}</td>
              </tr>))}</tbody>
          </table>
          {!d.positions.length && <div className="note">No positions.{manual ? " Add your holdings below." : " Place a paper order with the ticket."}</div>}
          <div className="expo">
            {Object.entries(d.exposure.by_asset_class).map(([k, v]) => <span key={k} className="dim small">{k} {v.pct ? num(n(v.pct), 1) : "—"}%</span>)}
            {Object.entries(d.exposure.by_sector).map(([k, v]) => <span key={k} className="dim small">· {k} {v.pct ? num(n(v.pct), 1) : "—"}%</span>)}
          </div>
          {manual && (
            <div className="aform">
              <div className="aform-h">EDIT HOLDINGS (your own data; nothing is invented)</div>
              <div className="frow">
                <input className="w80" placeholder="Symbol" value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} aria-label="Holding symbol" />
                <input className="w80" placeholder="Qty (0 removes)" value={form.qty} onChange={(e) => setForm({ ...form, qty: e.target.value })} aria-label="Holding quantity" />
                <input className="w80" placeholder="Avg cost" value={form.cost} onChange={(e) => setForm({ ...form, cost: e.target.value })} aria-label="Holding average cost" />
                <button className="mini on" disabled={addPos.isPending || !form.symbol || !form.qty || !form.cost} onClick={() => addPos.mutate()}>Save holding</button>
              </div>
              <div className="frow">
                <input className="w100" placeholder="Cash balance" value={cash} onChange={(e) => setCash(e.target.value)} aria-label="Cash balance" />
                <button className="mini" disabled={!cash || setCashM.isPending} onClick={() => setCashM.mutate()}>Set cash</button>
              </div>
            </div>)}
          {msg && <div className="note warn" onClick={() => setMsg(null)}>{msg}</div>}
        </>)}
    </Panel>
  );
}

const STATUS_CLS: Record<RiskCheck["status"], string> = { pass: "up", warn: "warnc", fail: "down", needs_data: "down", not_checked: "dim" };
const STATUS_ICON: Record<RiskCheck["status"], string> = { pass: "✓", warn: "!", fail: "✕", needs_data: "?", not_checked: "–" };
const VERDICT: Record<string, string> = { APPROVE_FOR_PAPER_REVIEW: "APPROVED FOR PAPER REVIEW", REJECT: "REJECTED", NEEDS_MORE_DATA: "NEEDS MORE DATA" };

export function TicketWidget() {
  const qc = useQueryClient();
  const selected = useStore((s) => s.selected);
  const draft = useStore((s) => s.ticketDraft);
  const setDraft = useStore((s) => s.setTicketDraft);
  const { pid, current } = usePortfolioId();
  const inst = useQuery({ queryKey: ["instrument", selected], queryFn: () => api.instrument(selected), staleTime: 60_000 });
  const lastQuote = useQuery({ queryKey: ["quotes", selected], queryFn: async () => (await api.quotes([selected]))[0], refetchInterval: 5000 });
  const [f, setF] = useState({ symbol: "", side: "buy", type: "market", qty: "", limit: "", stop: "", planned: "", tif: "GTC" });
  const [pv, setPv] = useState<{ p: OrderPreview; at: number; body: OrderBody } | null>(null);
  const [now, setNow] = useState(Date.now());
  const [msg, setMsg] = useState<{ ok: boolean; text: string; checks?: RiskCheck[] } | null>(null);
  const [sizeInfo, setSizeInfo] = useState<string | null>(null);
  const set = (k: string, v: string) => { setF((x) => ({ ...x, [k]: v })); setPv(null); setMsg(null); };
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  useEffect(() => { if (inst.data && !f.symbol) setF((x) => ({ ...x, symbol: inst.data!.symbol })); }, [inst.data]);
  useEffect(() => {
    if (!draft) return;
    const sym = (draft.instrument_id ?? "").split(":")[2] ?? "";
    setF({ symbol: sym, side: draft.side ?? "buy", type: draft.type ?? "market", qty: draft.qty ?? "", limit: draft.limit_price ?? "", stop: draft.stop_price ?? "", planned: draft.planned_stop ?? "", tif: "GTC" });
    setPv(null); setMsg({ ok: true, text: "Drafted from the command bar. Review it, then press Preview. Nothing has been sent." }); setDraft(null);
  }, [draft]);

  const body = useMemo<OrderBody>(() => ({
    instrument_id: f.symbol.trim().toUpperCase(), side: f.side as "buy" | "sell", qty: f.qty, type: f.type, tif: f.tif, portfolio_id: pid,
    ...(f.limit ? { limit_price: f.limit } : {}), ...(f.stop ? { stop_price: f.stop } : {}), ...(f.planned ? { planned_stop: f.planned } : {}),
  }), [f, pid]);
  const preview = useMutation({ mutationFn: () => api.orderPreview(body), onSuccess: (p) => { setPv({ p, at: Date.now(), body }); setMsg(null); }, onError: (e) => { setPv(null); setMsg({ ok: false, text: err(e) }); } });
  const submit = useMutation({
    mutationFn: () => api.orderSubmit(pv!.body, pv!.p.preview_id, `ticket-${pv!.p.preview_id}`),     // key = preview id: a double click is idempotent
    onSuccess: (r) => {
      setMsg({ ok: true, text: `${r.duplicate ? "Already submitted: " : ""}Paper order #${r.order.id} ${r.order.state}${r.order.avg_fill_price ? ` @ ${px(r.order.avg_fill_price)}` : ""}` });
      setPv(null); setF((x) => ({ ...x, qty: "", limit: "", stop: "", planned: "" }));
      for (const k of ["portfolio", "orders", "fills", "alert-events"]) qc.invalidateQueries({ queryKey: [k] });
    },
    onError: (e) => setMsg({ ok: false, text: err(e), checks: e instanceof ApiFailure ? (e.extra.checks as RiskCheck[] | undefined) : undefined }),
  });
  const size = useMutation({
    mutationFn: () => api.riskSize(f.symbol.trim().toUpperCase(), f.limit || String(n(lastQuote.data && "price" in lastQuote.data ? lastQuote.data.price : null) ?? ""), f.planned, pid),
    onSuccess: (r) => { setF((x) => ({ ...x, qty: r.qty })); setPv(null); setSizeInfo(`Sized to ${r.qty} (binding: ${r.binding_constraint}; planned risk ${money(r.planned_risk)}). ${r.note}`); },
    onError: (e) => setSizeInfo(err(e)),
  });
  const left = pv ? Math.max(0, Math.round(pv.p.expires_in_seconds - (now - pv.at) / 1000)) : 0;
  const expired = !!pv && left === 0;
  const ok = pv?.p.verdict === "APPROVE_FOR_PAPER_REVIEW" && !expired;
  const price = lastQuote.data && "price" in lastQuote.data ? lastQuote.data.price : null;
  const needLimit = f.type === "limit" || f.type === "stop_limit", needStop = f.type === "stop" || f.type === "stop_limit";

  return (
    <Panel title="ORDER TICKET" right={<span className="env-tag">{current?.venue === "ibkr" ? "ROUTED TO IBKR PAPER ACCOUNT" : "PAPER ONLY · SIMULATED FILLS"}</span>}>
      {current?.kind === "manual" && <div className="note warn">{current.venue === "ibkr" ? "This IBKR account is linked read-only: it cannot trade." : "Manual portfolios cannot trade."} Switch to a paper portfolio.</div>}
      <div className="frow">
        <button className={`mini ${f.side === "buy" ? "on" : ""}`} style={f.side === "buy" ? { color: "var(--up)", borderColor: "var(--up)" } : undefined} onClick={() => set("side", "buy")}>BUY</button>
        <button className={`mini ${f.side === "sell" ? "on" : ""}`} style={f.side === "sell" ? { color: "var(--down)", borderColor: "var(--down)" } : undefined} onClick={() => set("side", "sell")}>SELL</button>
        <input className="w100" value={f.symbol} onChange={(e) => set("symbol", e.target.value.toUpperCase())} aria-label="Order symbol" placeholder="Symbol" />
        <button className="mini" onClick={() => set("symbol", selected.split(":")[2] ?? "")} title="Use the selected instrument">use selected</button>
        <span className="dim small mono">{price !== null ? `last ${num(price, price >= 100 ? 2 : 4)}` : ""}</span>
      </div>
      <div className="frow">
        <select value={f.type} onChange={(e) => set("type", e.target.value)} aria-label="Order type"><option value="market">market</option><option value="limit">limit</option><option value="stop">stop</option><option value="stop_limit">stop-limit</option></select>
        <input className="w80" value={f.qty} onChange={(e) => set("qty", e.target.value)} placeholder="Qty" aria-label="Order quantity" />
        {needLimit && <input className="w80" value={f.limit} onChange={(e) => set("limit", e.target.value)} placeholder="Limit" aria-label="Limit price" />}
        {needStop && <input className="w80" value={f.stop} onChange={(e) => set("stop", e.target.value)} placeholder="Stop" aria-label="Stop price" />}
        <select value={f.tif} onChange={(e) => set("tif", e.target.value)} aria-label="Time in force"><option>GTC</option><option>DAY</option></select>
      </div>
      <div className="frow">
        <input className="w100" value={f.planned} onChange={(e) => set("planned", e.target.value)} placeholder="Planned stop" aria-label="Planned stop" title="Invalidation level used for risk sizing. It does NOT place a stop order." />
        <button className="mini" disabled={!f.planned || size.isPending} onClick={() => size.mutate()} title="Quantity from your risk limits, the planned stop and available cash">size from risk</button>
        <button className="mini on" disabled={preview.isPending || !f.qty || !f.symbol || current?.kind === "manual"} onClick={() => preview.mutate()}>{preview.isPending ? "checking…" : "Preview + risk check"}</button>
      </div>
      {sizeInfo && <div className="note" onClick={() => setSizeInfo(null)}>{sizeInfo}</div>}
      {msg && <div className={`note ${msg.ok ? "" : "warn"}`} onClick={() => setMsg(null)}>{msg.text}</div>}
      {msg?.checks && <div className="checks">{msg.checks.filter((c) => c.status === "fail" || c.status === "needs_data").map((c) => <div key={c.name} className="down"><b>✕</b> {c.name.replace(/_/g, " ")}<span className="dim small"> · {c.detail}</span></div>)}</div>}
      {pv && (
        <div className={`pvbox ${pv.p.verdict}`}>
          <div className="pv-h"><b>{VERDICT[pv.p.verdict]}</b>{pv.p.data && <Badge status={pv.p.data.status} />}<span className="dim small">{expired ? "expired: preview again" : `valid ${left}s`}</span></div>
          <table className="tbl kv"><tbody>
            <tr><td>Est. price</td><td className="r mono">{px(pv.p.estimate.price)}</td></tr>
            <tr><td>Notional</td><td className="r mono">{money(pv.p.estimate.notional)}</td></tr>
            <tr><td>Est. fee</td><td className="r mono">{money(pv.p.estimate.fee, 4)}</td></tr>
            <tr><td>Total cost</td><td className="r mono">{money(pv.p.estimate.total_cost)}</td></tr>
            <tr><td>Cash after</td><td className="r mono">{pv.p.estimate.cash_available_after ? money(pv.p.estimate.cash_available_after) : "—"} <span className="dim small">(was {money(pv.p.estimate.cash_available_before)})</span></td></tr>
          </tbody></table>
          <div className="checks">{pv.p.checks.map((c) => <div key={c.name} className={STATUS_CLS[c.status]} title={c.detail}><b>{STATUS_ICON[c.status]}</b> {c.name.replace(/_/g, " ")}<span className="dim small"> · {c.detail}</span></div>)}</div>
          <div className="note">{pv.p.disclaimer} {pv.p.simulator}</div>
          <button className="confirm" disabled={!ok || submit.isPending} onClick={() => submit.mutate()}>{submit.isPending ? "submitting…" : `Confirm and submit PAPER ${pv.body.side.toUpperCase()}`}</button>
          {!ok && !expired && <div className="note warn">Cannot be submitted: {VERDICT[pv.p.verdict].toLowerCase()}. Fix the failing checks above (or adjust the order) and preview again.</div>}
        </div>)}
      <div className="note">Live trading is not available in this build. There is no live broker connection.</div>
    </Panel>
  );
}

export function OrdersWidget() {
  const qc = useQueryClient();
  const { pid } = usePortfolioId();
  const [tab, setTab] = useState<"open" | "all" | "fills">("open");
  const orders = useQuery({ queryKey: ["orders", pid, tab], queryFn: () => api.orders(pid, tab === "open" ? "open" : undefined), enabled: pid !== undefined && tab !== "fills", refetchInterval: 4000 });
  const fills = useQuery({ queryKey: ["fills", pid], queryFn: () => api.fills(pid), enabled: pid !== undefined && tab === "fills", refetchInterval: 6000 });
  const [msg, setMsg] = useState<string | null>(null);
  const cancel = useMutation({ mutationFn: (id: number) => api.orderCancel(id), onSuccess: () => { setMsg(null); for (const k of ["orders", "portfolio"]) qc.invalidateQueries({ queryKey: [k] }); }, onError: (e) => setMsg(err(e)) });
  return (
    <Panel title="ORDERS & FILLS">
      <div className="toolbar">{(["open", "all", "fills"] as const).map((t) => <button key={t} className={`mini ${tab === t ? "on" : ""}`} onClick={() => setTab(t)}>{t === "open" ? "open orders" : t === "all" ? "order history" : "fills"}</button>)}</div>
      {msg && <div className="note warn" onClick={() => setMsg(null)}>{msg}</div>}
      {orders.isError && <ErrorBox error={orders.error} />}
      {tab !== "fills" && (
        <table className="tbl">
          <thead><tr><th>#</th><th>Symbol</th><th>Side</th><th>Type</th><th className="r">Qty</th><th className="r">Price</th><th className="r">Filled</th><th>State</th><th>Last event</th><th /></tr></thead>
          <tbody>{orders.data?.map((o) => {
            const last = o.events[o.events.length - 1];
            return (
              <tr key={o.id} title={o.events.map((e) => `${e.ts.slice(11, 19)} ${e.event} ${e.detail}`).join("\n")}>
                <td className="dim">{o.id}</td><td><b>{o.symbol}</b></td><td className={o.side === "buy" ? "up" : "down"}>{o.side}</td><td>{o.type}{o.tif === "DAY" ? " (day)" : ""}</td>
                <td className="r mono">{num(n(o.qty), 6).replace(/\.?0+$/, "")}</td><td className="r mono">{o.limit_price ?? o.stop_price ?? "mkt"}</td>
                <td className="r mono">{num(n(o.filled_qty), 6).replace(/\.?0+$/, "") || "0"}{o.avg_fill_price ? <span className="dim small"> @{px(o.avg_fill_price)}</span> : null}</td>
                <td className={o.state === "filled" ? "up" : o.state === "rejected" || o.state === "cancelled" || o.state === "expired" ? "dim" : ""}>{o.state}</td>
                <td className="dim small">{last ? `${last.event}${last.detail && !last.detail.startsWith("{") ? `: ${last.detail.slice(0, 48)}` : ""}` : ""}</td>
                <td className="r">{(o.state === "working" || o.state === "partially_filled") && <button className="mini" disabled={cancel.isPending} onClick={() => cancel.mutate(o.id)}>cancel</button>}</td>
              </tr>);
          })}</tbody>
        </table>)}
      {tab !== "fills" && orders.data && !orders.data.length && <div className="note">{tab === "open" ? "No open orders." : "No orders yet."}</div>}
      {tab === "fills" && (
        <table className="tbl">
          <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th className="r">Qty</th><th className="r">Price</th><th className="r">Fee</th><th>Data</th><th>How it was simulated</th></tr></thead>
          <tbody>{fills.data?.map((x) => (
            <tr key={x.id}><td className="dim">{ago(x.ts)}</td><td><b>{x.symbol}</b></td><td className={x.side === "buy" ? "up" : "down"}>{x.side}</td>
              <td className="r mono">{num(n(x.qty), 6).replace(/\.?0+$/, "")}</td><td className="r mono">{px(x.price)}</td><td className="r mono">{money(x.fee, 4)}</td>
              <td>{x.data_status === "BROKER" ? <span className="chip" title="Executed by IBKR (paper account)">IBKR</span> : x.data_status ? <Badge status={x.data_status as never} /> : null}</td><td className="dim small">{x.note}</td></tr>))}</tbody>
        </table>)}
      {tab === "fills" && fills.data && !fills.data.length && <div className="note">No fills yet.</div>}
    </Panel>
  );
}
