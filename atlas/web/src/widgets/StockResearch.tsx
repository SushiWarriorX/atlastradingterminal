import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errText } from "../api";
import { useSelectedId } from "../scope";
import type { Case, Year } from "../stocks";
import { ErrorBox, Panel } from "../ui";

const money = (x: number | null) => (x === null ? "n/a" : `${x < 0 ? "−" : ""}$${(Math.abs(x) / 1e9).toFixed(2)}B`);
const pc = (x: number | null) => (x === null ? "n/a" : `${x.toFixed(1)}%`);
const x2 = (x: number | null) => (x === null ? "n/a" : `${x.toFixed(2)}x`);
const sym = (id: string) => id.split(":").pop() ?? id;

function Cases({ title, items }: { title: string; items: Case[] }) {
  return (
    <div style={{ flex: 1, minWidth: 220 }}>
      <b>{title}</b> <span className="pill warn">Interpretation (rule-based)</span>
      {items.length === 0 ? <div className="dim small">No rule triggered.</div> : items.map((c) => <div key={c.id} className="small" style={{ margin: "4px 0" }}>{c.text}</div>)}
    </div>);
}

/** Facts from filings, calculated ratios, valuation, earnings, rule-based bull and bear points, filings and news for the selected stock. */
export function StockResearchWidget() {
  const id = useSelectedId();
  const q = useQuery({ queryKey: ["stock-research", id], queryFn: () => api.stockResearch(sym(id)), staleTime: 10 * 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title={`STOCK RESEARCH ${sym(id)}`} right={d && <span className="dim small">{d.company.name ?? ""}</span>}>
      {q.isLoading && <div className="note">Loading filings and valuation…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="stock-research">
        {(d.company.sic_description || d.company.sector) && <div className="small"><b>About:</b> {[d.company.sector, d.company.industry, d.company.sic_description && `SEC industry: ${d.company.sic_description}`, d.company.fiscal_year_end && `fiscal year ends ${d.company.fiscal_year_end.slice(0, 2)}/${d.company.fiscal_year_end.slice(2)}`].filter(Boolean).join(" · ")} <span className="dim">· {d.company.source}</span></div>}
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>FINANCIALS · annual filings (facts) and ratios (calculated)</span></div>
        {!d.financials.available ? <div className="note">No filing data loaded. {d.errors.filter((e) => /SEC|Demo/.test(e)).join(" ")}</div> : <>
          <table className="tbl"><thead><tr><th>Fiscal year end</th>{d.financials.years.map((y: Year) => <th key={y.end} className="r mono">{y.end}</th>)}</tr></thead><tbody>
            {([["Revenue", "revenue", money], ["Revenue growth", "revenue_growth_pct", pc], ["Gross margin", "gross_margin_pct", pc], ["Operating margin", "operating_margin_pct", pc], ["Net margin", "net_margin_pct", pc], ["Net income", "net_income", money], ["Free cash flow", "free_cash_flow", money], ["Net cash (cash − LT debt)", "net_cash", money], ["Debt / equity", "debt_to_equity", x2]] as const).map(([label, k, f]) => (
              <tr key={k}><td>{label}</td>{d.financials.years.map((y: Year) => <td key={y.end} className="r mono">{f(y[k as keyof Year] as number | null)}</td>)}</tr>))}
          </tbody></table>
          {d.financials.revenue_cagr && <div className="small dim">Revenue growth per year, {d.financials.revenue_cagr.from} to {d.financials.revenue_cagr.to}: {pc(d.financials.revenue_cagr.value_pct)} ({d.financials.revenue_cagr.formula}).</div>}
          <div className="small dim">{d.financials.source}. {d.financials.note}</div></>}
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>VALUATION · {d.valuation?.source ?? "unavailable"}{d.valuation?.status ? ` · ${d.valuation.status}` : ""}</span></div>
        {d.valuation ? <table className="tbl kv"><tbody>{d.valuation.rows.map((r) => <tr key={r.key} title={r.basis}><td className="dim">{r.label}</td><td className="r mono">{r.value === null ? <span className="dim">{r.note ?? "n/a"}</span> : r.unit === "$" ? money(r.value) : `${r.value.toFixed(2)}${r.unit}`}</td></tr>)}</tbody></table> : <div className="note">Valuation unavailable.</div>}
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>EARNINGS AND CATALYSTS</span></div>
        <div className="small">Next earnings: <b className="mono">{d.earnings.next_date ?? "not available"}</b> <span className="dim">· {d.earnings.source}</span></div>
        <div className="small dim">Guidance: {d.earnings.guidance.reason} Consensus: {d.earnings.consensus.reason}</div>
        {d.catalysts.map((c, i) => <div key={i} className="small">{c.date} · {c.title} <span className="dim">· {c.source}</span>{c.link && <> · <a href={c.link} target="_blank" rel="noreferrer noopener">filing</a></>}</div>)}
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>BULL AND BEAR POINTS</span></div>
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}><Cases title="Bull" items={d.bull} /><Cases title="Bear" items={d.bear} /></div>
        <div className="small dim">{d.case_note}</div>
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>RECENT FILINGS · SEC EDGAR</span></div>
        {d.filings.length === 0 ? <div className="note">No filings loaded.</div> : d.filings.slice(0, 6).map((f, i) => <div key={i} className="small">{f.filed} · <b>{f.form}</b> {f.items.map((it) => it.meaning).join("; ")} {f.link && <a href={f.link} target="_blank" rel="noreferrer noopener">open</a>}</div>)}
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>NEWS · titles and links as published</span></div>
        {d.news.length === 0 ? <div className="note">No recent headlines for this symbol.</div> : d.news.map((n, i) => <div key={i} className="small">{n.link ? <a href={n.link} target="_blank" rel="noreferrer noopener">{n.title}</a> : n.title} <span className="dim">· {n.feed}</span></div>)}
        {d.errors.length > 0 && <div className="note warn">{d.errors.join(" ")}</div>}
        <div className="note"><b>Not shown:</b> {d.gaps.join(" ")}</div>
      </div>}
    </Panel>);
}

/** Next earnings dates for the symbols on the first watchlist, plus any tickers typed in, with a window filter and add-to-watchlist. */
export function EarningsWidget() {
  const qc = useQueryClient();
  const [days, setDays] = useState(30);
  const [extra, setExtra] = useState("");
  const [typed, setTyped] = useState<string[]>([]);
  const wls = useQuery({ queryKey: ["watchlists"], queryFn: api.watchlists });
  const wl = wls.data?.[0];
  const names = [...new Set([...(wl?.items ?? []).filter((i) => i.startsWith("EQUITY:")).map(sym), ...typed])];
  const q = useQuery({ queryKey: ["earnings", names.join(","), days], queryFn: () => api.earningsCal(names, days), enabled: names.length > 0, staleTime: 10 * 60_000 });
  const add = useMutation({ mutationFn: (iid: string) => api.wlAdd(wl!.id, iid), onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlists"] }) });
  return (
    <Panel title="EARNINGS CALENDAR" right={<span>{[7, 14, 30, 60].map((n) => <button key={n} className={`mini ${days === n ? "on" : ""}`} onClick={() => setDays(n)}>{n}d</button>)}</span>}>
      <div className="toolbar"><input placeholder="check other tickers: NVDA, MSFT" value={extra} onChange={(e) => setExtra(e.target.value)} aria-label="Tickers to check" />
        <button className="mini" onClick={() => { setTyped(extra.split(/[ ,]+/).map((s) => s.trim().toUpperCase()).filter((s) => /^[A-Z.\-]{1,6}$/.test(s)).slice(0, 20)); }}>check</button></div>
      {names.length === 0 && <div className="note">Add stocks to your watchlist or type tickers above. No free source lists every company's next earnings date reliably, so only the symbols you ask about are checked.</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {q.data && q.data.items.length === 0 && <div className="note">None of the {q.data.checked} symbols report in the next {q.data.window_days} days (as far as the source knows).</div>}
      {q.data && q.data.items.length > 0 && <table className="tbl" data-testid="earnings-list"><thead><tr><th>Date</th><th>Symbol</th><th>Name</th><th>In</th><th>Sector</th><th /></tr></thead><tbody>{q.data.items.map((r) => (
        <tr key={r.symbol}><td className="mono">{r.date}</td><td><b>{r.symbol}</b></td><td className="dim">{r.name}</td><td className="mono">{r.days_away}d</td><td className="dim">{r.sector}</td>
          <td>{wl && !wl.items.includes(r.instrument_id) && <button className="mini" onClick={() => add.mutate(r.instrument_id)}>add to watchlist</button>}</td></tr>))}</tbody></table>}
      {add.isError && <div className="warnc small">{errText(add.error)}</div>}
      {q.data && <div className="small dim">{q.data.note} Dates: Yahoo Finance (unofficial, delayed); confirm with the company. {q.data.errors.length ? `Could not check: ${q.data.errors.join("; ")}` : ""}</div>}
    </Panel>);
}
