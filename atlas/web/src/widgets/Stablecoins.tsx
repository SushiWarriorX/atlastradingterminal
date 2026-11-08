import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

const pc = (x: number | null | undefined) => (x === null || x === undefined ? "n/a" : `${x > 0 ? "+" : ""}${x.toFixed(2)}%`);
const cls = (x: number | null | undefined) => (x === null || x === undefined ? "dim" : x > 0 ? "up" : x < 0 ? "down" : "");

/** US-dollar stablecoin supply (DefiLlama): the cash inside crypto, with changes over time and the biggest issuers. A liquidity gauge, not a price signal. */
export function StablecoinsWidget() {
  const q = useQuery({ queryKey: ["btc-stablecoins"], queryFn: api.btcStablecoins, staleTime: 60 * 60_000, refetchInterval: 2 * 60 * 60_000, retry: 0 });
  const d = q.data;
  const hist = d?.history ?? [];
  const lo = hist.length ? Math.min(...hist.map((h) => h.total_billions)) : 0;
  const hi = hist.length ? Math.max(...hist.map((h) => h.total_billions)) : 1;
  return (
    <Panel title="STABLECOIN SUPPLY · cash inside crypto" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? "OVERDUE" : d.date}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="stablecoins">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <div style={{ display: "flex", gap: 14, alignItems: "baseline", flexWrap: "wrap" }}>
            <b className="mono" style={{ fontSize: 22 }}>${d.total_billions!.toFixed(1)}B</b>
            {d.changes!.map((c) => <span key={c.label} className={`small ${cls(c.change_pct)}`}>{c.label}: {pc(c.change_pct)} ({c.change_billions >= 0 ? "+" : ""}${c.change_billions.toFixed(1)}B)</span>)}
          </div>
          <div className="small dim">{d.peak!.below_peak_pct === 0 ? "At its all-time high" : `${Math.abs(d.peak!.below_peak_pct)}% below its peak of $${d.peak!.total_billions.toFixed(1)}B on ${d.peak!.date}`}</div>
          <div style={{ display: "flex", gap: 1, alignItems: "flex-end", height: 28, margin: "6px 0" }} aria-label="Last 90 days of total supply">
            {hist.map((h) => <span key={h.date} title={`${h.date}: $${h.total_billions}B`} style={{ flex: 1, height: `${Math.max(((h.total_billions - lo) / Math.max(hi - lo, 0.001)) * 90 + 10, 10)}%`, background: "var(--accent)", opacity: 0.6 }} />)}
          </div>
          <table className="tbl"><thead><tr><th>Stablecoin</th><th className="r">Supply</th><th className="r">Share</th><th className="r">7 days</th><th className="r">30 days</th></tr></thead><tbody>
            {d.top!.map((t) => <tr key={t.symbol}><td><b>{t.symbol}</b> <span className="dim">{t.name}</span></td><td className="r mono">${t.billions.toFixed(2)}B</td><td className="r mono">{t.share_pct === null ? "n/a" : `${t.share_pct}%`}</td>
              <td className={`r mono ${cls(t.change_7d_pct)}`}>{pc(t.change_7d_pct)}</td><td className={`r mono ${cls(t.change_30d_pct)}`}>{pc(t.change_30d_pct)}</td></tr>)}
          </tbody></table>
          <div className="small dim">{d.note} Source: <a href={d.url} target="_blank" rel="noreferrer noopener">{d.source}</a>.</div></>}
      </div>}
    </Panel>);
}
