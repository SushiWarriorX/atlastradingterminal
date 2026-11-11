import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { useSelectedId } from "../scope";
import { ErrorBox, Panel } from "../ui";
import { ymdLabel as ymd , wordDates } from "../fmt";

const AMOUNTS = [500, 1000, 5000, 10000];
const usd = (x: number) => `${x < 0 ? "-" : ""}$${Math.abs(x).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
const pc = (x: number) => `${x > 0 ? "+" : ""}${x.toFixed(1)}%`;
const cls = (x: number) => (x > 0 ? "up" : x < 0 ? "down" : "");
const sym = (id: string) => {
  const p = id.split(":");
  return /^(SPOT|PERP)$/.test(p[p.length - 1]) && p.length > 1 ? p[p.length - 2] : p[p.length - 1] ?? id;      // CRYPTO:COINBASE:BTC-USD:SPOT -> BTC-USD
};

/** "What if I had bought it?": replays buying the selected asset in the past from its own daily closes. History only; it predicts nothing and places nothing. */
export function WhatIfWidget() {
  const id = useSelectedId();
  const [amount, setAmount] = useState(1000);
  const [custom, setCustom] = useState("");
  const q = useQuery({ queryKey: ["whatif", id, amount], queryFn: () => api.whatIf(id, amount), staleTime: 30 * 60_000, retry: 0, placeholderData: (p) => p });
  const d = q.data;
  const onCustom = (t: string) => {
    const digits = t.replace(/[^0-9]/g, "").slice(0, 8);
    setCustom(digits);
    const n = parseInt(digits, 10);
    if (n >= 1 && n <= 10_000_000) setAmount(n);
  };
  return (
    <Panel title={`WHAT IF I HAD BOUGHT ${sym(id)}`} right={d && <span className={`pill ${d.prov.status === "DEMO" ? "warn" : ""}`}>{d.prov.status === "DEMO" ? "DEMO" : `${ymd(d.from)} to ${ymd(d.to)}`}</span>}>
      <div className="toolbar" data-testid="whatif-controls">
        <span className="savedchip">{AMOUNTS.map((n) => <button key={n} className={`mini ${amount === n && !custom ? "on" : ""}`} onClick={() => { setCustom(""); setAmount(n); }} data-testid={`whatif-amt-${n}`}>{usd(n)}</button>)}</span>
        <input value={custom} onChange={(e) => onCustom(e.target.value)} placeholder="other $" aria-label="Other amount in dollars" data-testid="whatif-custom" style={{ width: 90 }} />
      </div>
      {q.isLoading && <div className="note">Replaying the past…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="whatif">
        {d.prov.status === "DEMO" && <div className="note warn">Demo data: these prices are synthetic, so the results below are not real history.</div>}
        <div className="small dim">Daily closes {ymd(d.from)} to {ymd(d.to)} · {d.prov.provider} · {d.prov.status.toLowerCase()} · {d.adjustment}</div>
        {d.notes.map((n, i) => <div key={i} className="note warn">{n}</div>)}

        <div className="ws-bar" style={{ paddingLeft: 0 }}><span>1 · ONE PURCHASE OF {usd(d.amount)}, HELD TO TODAY</span></div>
        <table className="tbl"><thead><tr><th>Bought</th><th className="r">Worth now</th><th className="r">Return</th><th className="r">Per year</th><th className="r">Lowest vs cost</th><th className="r">Worst fall from peak</th><th className="r">Days below cost</th></tr></thead><tbody>
          {d.lump_sum.map((x) => <tr key={x.label} data-testid="whatif-lump"><td>{wordDates(x.label)} <span className="dim">({ymd(x.buy_date)})</span></td><td className="r mono">{usd(x.value_now)}</td><td className={`r mono ${cls(x.return_pct)}`}>{pc(x.return_pct)}</td><td className="r mono">{x.per_year_pct === null ? "n/a" : pc(x.per_year_pct)}</td><td className="r mono down">{pc(x.lowest_vs_cost_pct)}</td><td className="r mono down">{pc(x.max_drawdown_pct)}</td><td className="r mono">{x.days_below_cost}</td></tr>)}
        </tbody></table>

        {d.monthly.length > 0 && <>
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>2 · THE SAME AMOUNT EVERY MONTH (first trading day)</span></div>
          <table className="tbl"><thead><tr><th>Plan</th><th className="r">Buys</th><th className="r">Put in</th><th className="r">Worth now</th><th className="r">Return</th><th className="r">Average price</th><th className="r">Same money at once</th></tr></thead><tbody>
            {d.monthly.map((m) => <tr key={m.label}><td>{wordDates(m.label)}</td><td className="r mono">{m.buys}</td><td className="r mono">{usd(m.invested)}</td><td className="r mono">{usd(m.value_now)}</td><td className={`r mono ${cls(m.return_pct)}`}>{pc(m.return_pct)}</td><td className="r mono">${m.average_price.toFixed(2)}</td><td className={`r mono ${cls(m.same_money_lump_sum_return_pct)}`}>{pc(m.same_money_lump_sum_return_pct)}</td></tr>)}
          </tbody></table></>}

        {d.every_start.length > 0 && <>
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>3 · WHICHEVER DAY YOU BOUGHT (every possible start date)</span></div>
          <table className="tbl"><thead><tr><th>Holding</th><th className="r">Worst start</th><th className="r">Typical</th><th className="r">Best start</th><th className="r">Made money</th><th className="r">Lost 20%+</th></tr></thead><tbody>
            {d.every_start.map((e) => <tr key={e.label} title={e.note}><td>{wordDates(e.label)}</td><td className={`r mono ${cls(e.worst_pct)}`}>{pc(e.worst_pct)} <span className="dim">{ymd(e.worst_buy_date)}</span></td><td className={`r mono ${cls(e.median_pct)}`}>{pc(e.median_pct)}</td><td className={`r mono ${cls(e.best_pct)}`}>{pc(e.best_pct)} <span className="dim">{ymd(e.best_buy_date)}</span></td><td className="r mono">{Math.round(e.share_positive * 100)}%</td><td className="r mono">{Math.round(e.share_lost_20 * 100)}%</td></tr>)}
          </tbody></table>
          <div className="small dim">{d.every_start[0].note}</div></>}

        {d.exit_rules.length > 0 && <>
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>4 · WITH A RULE FOR GETTING OUT (checked on daily closes)</span></div>
          <table className="tbl"><thead><tr><th>Bought</th>{d.exit_rules[0].rules.map((r) => <th key={r.rule} className="r">{r.label}</th>)}</tr></thead><tbody>
            {d.exit_rules.map((b) => <tr key={b.label}><td>{wordDates(b.label)}</td>{b.rules.map((r) => <td key={r.rule} className={`r mono ${cls(r.result_pct)}`} title={r.sold ? `sold ${r.sold_on}: ${r.why}` : r.why}>{pc(r.result_pct)}</td>)}</tr>)}
          </tbody></table></>}

        {d.bootstrap && <>
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>5 · {d.bootstrap.paths.toLocaleString("en-US")} SHUFFLED YEARS</span><span className="pill warn">Simulation, not a forecast</span></div>
          <table className="tbl kv" data-testid="whatif-boot"><tbody>
            <tr><td className="dim">Bad year (1 in 20 is worse)</td><td className={`r mono ${cls(d.bootstrap.p5_pct)}`}>{pc(d.bootstrap.p5_pct)}</td></tr>
            <tr><td className="dim">Typical year</td><td className={`r mono ${cls(d.bootstrap.median_pct)}`}>{pc(d.bootstrap.median_pct)}</td></tr>
            <tr><td className="dim">Good year (1 in 20 is better)</td><td className={`r mono ${cls(d.bootstrap.p95_pct)}`}>{pc(d.bootstrap.p95_pct)}</td></tr>
            <tr><td className="dim">Ended higher / lost 20%+</td><td className="r mono">{Math.round(d.bootstrap.share_positive * 100)}% / {Math.round(d.bootstrap.share_lost_20 * 100)}%</td></tr>
            <tr><td className="dim">Typical dip along the way</td><td className="r mono down">{pc(d.bootstrap.typical_worst_dip_pct)}</td></tr>
          </tbody></table>
          <div className="small dim">{d.bootstrap.note}</div></>}

        {d.caveats.map((c, i) => <div key={i} className="small dim">{c}</div>)}
      </div>}
    </Panel>);
}
