import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";
import { ymdLabel as ymd } from "../fmt";

const pc = (x: number | null | undefined) => (x === null || x === undefined ? "n/a" : `${x > 0 ? "+" : ""}${x.toFixed(1)}%`);
const cls = (x: number | null | undefined) => (x === null || x === undefined ? "dim" : x > 0 ? "up" : x < 0 ? "down" : "");

/** The market narrative of the day (Quantum, Nuclear, Robotics ...): a theme picked by fixed rules from price strength, breadth, volume and headlines. A story, not a forecast. */
export function NarrativeWidget() {
  const q = useQuery({ queryKey: ["narrative"], queryFn: () => api.narrative(false), staleTime: 30 * 60_000, retry: 0 });
  const [more, setMore] = useState(false);
  const d = q.data;
  return (
    <Panel title="NARRATIVE OF THE DAY" right={d && <span className={`pill ${d.demo ? "warn" : ""}`}>{d.demo ? "DEMO" : ymd(d.asof)}</span>}>
      {q.isLoading && <div className="note">Reading the market… the first load of the day fetches prices for every theme and can take a few seconds.</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && !d.theme && <div className="note warn" data-testid="narrative-none">No narrative today. {d.notes.join(" ")}</div>}
      {d && d.theme && <div data-testid="narrative">
        {d.demo && <div className="note warn">Demo data: prices are synthetic, so this narrative is not real.</div>}
        <div style={{ display: "flex", gap: 12, alignItems: "baseline" }}><b style={{ fontSize: 18 }} data-testid="narrative-name">{d.name}</b><span className="pill">Score {d.score.toFixed(0)}</span></div>
        <div className="small">{d.context} <span className="dim">({d.context_note})</span></div>
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>WHY IT IS IN FOCUS</span></div>
        {d.why_now.map((w, i) => <div key={i} className="small">• {w}</div>)}
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>THE BASKET</span></div>
        <table className="tbl"><thead><tr><th>Symbol</th><th className="r">Price</th><th className="r">1D</th><th className="r">5D</th><th className="r">1M</th><th className="r">Above 50-day</th><th className="r">Volume vs normal</th></tr></thead><tbody>
          {d.basket.map((b) => b.available ? (
            <tr key={b.symbol}><td><b>{b.symbol}</b></td><td className="r mono">{b.price?.toFixed(2)}</td><td className={`r mono ${cls(b.change_1d_pct)}`}>{pc(b.change_1d_pct)}</td><td className={`r mono ${cls(b.return_5d_pct)}`}>{pc(b.return_5d_pct)}</td>
              <td className={`r mono ${cls(b.return_1m_pct)}`}>{pc(b.return_1m_pct)}</td><td className="r">{b.above_50d === null || b.above_50d === undefined ? "n/a" : b.above_50d ? "yes" : "no"}</td><td className="r mono">{b.volume_vs_normal == null ? "n/a" : `${b.volume_vs_normal.toFixed(1)}x`}</td></tr>
          ) : <tr key={b.symbol}><td><b>{b.symbol}</b></td><td colSpan={6} className="dim small">no data</td></tr>)}
        </tbody></table>
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>RISKS TO WEIGH</span></div>
        {d.risks.map((r, i) => <div key={i} className="small warnc">• {r}</div>)}
        <div className="small dim">{d.volatility_note}</div>
        {d.headlines.length > 0 && <>
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>HEADLINES · from the feeds you follow</span></div>
          {d.headlines.map((h, i) => <div key={i} className="small">{h.link ? <a href={h.link} target="_blank" rel="noreferrer noopener">{h.title}</a> : h.title} <span className="dim">· {h.feed}</span></div>)}</>}
        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>OTHER THEMES TODAY</span><button className="mini" onClick={() => setMore(!more)} data-testid="narrative-more-toggle">{more ? "hide" : "show how it is picked"}</button></div>
        <div className="small">{d.all_themes.map((t) => `${t.name} ${t.score.toFixed(0)}${t.recently_featured ? " (shown recently)" : ""}`).join(" · ")}</div>
        {more && <div data-testid="narrative-method">
          {d.method.steps.map((s, i) => <div key={i} className="small dim">{i + 1}. {s}</div>)}
          {Object.entries(d.method.weights).map(([k, w]) => <div key={k} className="small dim">{Math.round(w * 100)}% · {d.method.scales[k]}</div>)}
          {d.notes.map((n, i) => <div key={i} className="note warn">{n}</div>)}
          <div className="small dim">Not included: {d.gaps.join(" ")}</div></div>}
        <div className="small dim">{d.disclaimer} Prices: {d.data.prices} ({d.data.prices_status.toLowerCase()}).</div>
      </div>}
    </Panel>);
}
