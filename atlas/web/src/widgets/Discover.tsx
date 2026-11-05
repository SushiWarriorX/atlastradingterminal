import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errText } from "../api";
import type { Pick } from "../discover";
import { useStore } from "../store";
import { ErrorBox, Panel } from "../ui";

const FACTOR = { growth: "Growth", profitability: "Profitability", momentum: "Momentum", valuation: "Valuation", balance_sheet: "Balance sheet", liquidity: "Liquidity" } as const;
const val = (v: number | null, u: string) => (v === null ? "n/a" : `${v.toFixed(u === "x" ? 1 : 1)}${u === "%" ? "%" : u === "x" ? "x" : ""}`);

function Card({ p, onAdd, saved }: { p: Pick; onAdd: () => void; saved: boolean }) {
  const [open, setOpen] = useState(false);
  const select = useStore((s) => s.select);
  return (
    <div className="note" data-testid={`pick-${p.symbol}`}>
      <div><b>#{p.rank} {p.symbol}</b> <span className="dim">{p.name} · {p.sector}</span> <span className="pill">score {p.score.toFixed(0)}/100 · {p.coverage} of {p.of} factors</span>
        <span style={{ float: "right" }}><button className="mini" onClick={() => select(p.asset_id)}>open</button> <button className="mini on" disabled={saved} onClick={onAdd}>{saved ? "on watchlist" : "add to watchlist"}</button></span></div>
      <div className="small" style={{ marginTop: 4 }}><b>Why it ranks well</b></div>
      {p.reasons.map((r, i) => <div key={i} className="small">• {r}</div>)}
      <div className="small" style={{ marginTop: 4 }}><b>Risks to weigh</b></div>
      {p.risks.map((r, i) => <div key={i} className="small warnc">• {r}</div>)}
      <button className="mini" onClick={() => setOpen(!open)}>{open ? "hide evidence" : "show evidence and score breakdown"}</button>
      {open && <>
        <table className="tbl"><thead><tr><th>Evidence</th><th className="r">Value</th><th>Source</th><th>As of</th></tr></thead><tbody>{p.evidence.map((e) => <tr key={e.label}><td>{e.label}</td><td className="r mono">{val(e.value, e.unit)}</td><td className="dim small">{e.source}</td><td className="mono small">{e.as_of}</td></tr>)}</tbody></table>
        <div className="small">{Object.entries(FACTOR).map(([k, label]) => <span key={k} style={{ marginRight: 12 }}>{label}: <b className="mono">{p.factors[k] ? p.factors[k]!.score.toFixed(0) : "n/a"}</b></span>)}</div></>}
    </div>);
}

/** Today's shortlist of five stocks to research, with reasons, risks and evidence, plus the full ranked list with filters. Rule-based; not advice. */
export function DiscoverWidget() {
  const qc = useQueryClient();
  const run = useQuery({ queryKey: ["discover"], queryFn: () => api.discoverShortlist(false), staleTime: 30 * 60_000, retry: 0 });
  const [sector, setSector] = useState("");
  const [minScore, setMinScore] = useState("");
  const [maxPe, setMaxPe] = useState("");
  const [minGrowth, setMinGrowth] = useState("");
  const q = new URLSearchParams({ ...(sector && { sector }), ...(minScore && { min_score: minScore }), ...(maxPe && { max_pe: maxPe }), ...(minGrowth && { min_growth: minGrowth }), limit: "30" }).toString();
  const ranked = useQuery({ queryKey: ["discover-ranked", q, run.data?.created_at], queryFn: () => api.discoverRanked(q), enabled: !!run.data });
  const wls = useQuery({ queryKey: ["watchlists"], queryFn: api.watchlists });
  const wl = wls.data?.[0];
  const add = useMutation({ mutationFn: (id: string) => api.wlAdd(wl!.id, id), onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlists"] }) });
  const rescan = useMutation({ mutationFn: () => api.discoverShortlist(true), onSuccess: (d) => { qc.setQueryData(["discover"], d); } });
  const d = run.data;
  const onList = (id: string) => !!wl?.items.includes(id);
  return (
    <Panel title="DISCOVER · today's shortlist" right={d && <span><span className={`pill ${d.demo ? "warn" : ""}`}>{d.demo ? "DEMO" : "HISTORICAL"}</span> <button className="mini" disabled={rescan.isPending} onClick={() => rescan.mutate()}>{rescan.isPending ? "scanning…" : "scan again"}</button></span>}>
      {run.isLoading && <div className="note">Scanning the universe and reading filings. The first scan of the day takes about 20 seconds…</div>}
      {run.isError && <ErrorBox error={run.error} />}
      {d && <div data-testid="discover">
        <div className="small dim">{d.universe.name}: {d.universe.size} stocks, {d.universe.priced} with prices, {d.universe.liquid} liquid enough, {d.universe.scored} scored · scan of {d.asof} · prices {d.data.prices} ({d.data.prices_status.toLowerCase()}{d.data.prices_as_of ? `, as of ${d.data.prices_as_of.slice(0, 10)}` : ""}) · financials: {d.data.fundamentals}</div>
        {d.stale_notice && <div className="note warn">{d.stale_notice}</div>}
        {d.notes.map((n, i) => <div key={i} className="note warn">{n}</div>)}
        {d.shortlist.length === 0 && !d.notes.length && <div className="note">No stock had enough data to be ranked today.</div>}
        {d.shortlist.map((p) => <Card key={p.symbol} p={p} saved={onList(p.asset_id)} onAdd={() => add.mutate(p.asset_id)} />)}
        {add.isError && <div className="warnc small">{errText(add.error)}</div>}
        <details className="note"><summary className="small"><b>How this works</b> (the method is fixed and the same every day)</summary>
          {d.method.steps.map((s, i) => <div key={i} className="small">{i + 1}. {s}</div>)}
          <table className="tbl"><tbody>{Object.entries(d.method.weights).map(([k, w]) => <tr key={k}><td><b>{FACTOR[k as keyof typeof FACTOR]}</b> <span className="mono">{Math.round(w * 100)}%</span></td><td className="small">{d.method.scales[k]}</td></tr>)}</tbody></table>
          <div className="small dim">{d.method.note}</div></details>
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>FULL RANKING</span></div>
        <div className="toolbar">
          <select value={sector} onChange={(e) => setSector(e.target.value)} aria-label="Sector"><option value="">all sectors</option>{(ranked.data?.sectors ?? []).map((s) => <option key={s}>{s}</option>)}</select>
          <input className="w80" placeholder="min score" value={minScore} onChange={(e) => setMinScore(e.target.value)} aria-label="Minimum score" />
          <input className="w80" placeholder="max P/E" value={maxPe} onChange={(e) => setMaxPe(e.target.value)} aria-label="Maximum P/E" />
          <input className="w80" placeholder="min growth %" value={minGrowth} onChange={(e) => setMinGrowth(e.target.value)} aria-label="Minimum revenue growth" />
        </div>
        {ranked.data && <table className="tbl" data-testid="discover-ranked"><thead><tr><th>Symbol</th><th>Sector</th><th className="r">Score</th><th className="r">Rev growth</th><th className="r">P/E</th><th /></tr></thead><tbody>{ranked.data.items.map((p) => (
          <tr key={p.symbol}><td><b>{p.symbol}</b> <span className="dim small">{p.name}</span></td><td className="dim">{p.sector}</td><td className="r mono">{p.score.toFixed(0)}</td><td className="r mono">{val(p.revenue_growth_pct, "%")}</td><td className="r mono">{val(p.pe, "x")}</td>
            <td>{!onList(p.asset_id) && <button className="mini" onClick={() => add.mutate(p.asset_id)}>add</button>}</td></tr>))}</tbody></table>}
        {ranked.data && ranked.data.items.length === 0 && <div className="note">Nothing matches these filters.</div>}
        <div className="note"><b>Not included:</b> {d.gaps.join(" ")}</div>
        <div className="small dim">{d.disclaimer}</div>
      </div>}
    </Panel>);
}
