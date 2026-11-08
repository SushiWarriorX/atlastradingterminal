import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ErrorBox, Panel } from "../ui";

/** The whole crypto market (CoinGecko): total value, 24h change and volume, and how it splits between Bitcoin, Ether, stablecoins and the rest. Descriptive, not a signal. */
export function CryptoMarketWidget() {
  const q = useQuery({ queryKey: ["crypto-market"], queryFn: api.btcMarket, staleTime: 10 * 60_000, refetchInterval: 15 * 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title="CRYPTO MARKET · size and split (CoinGecko)" right={d && d.available && <span className={`pill ${d.freshness === "OVERDUE" ? "warn" : ""}`}>{d.freshness === "OVERDUE" ? "OVERDUE" : `${d.age_minutes} min old`}</span>}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="crypto-market">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <div style={{ display: "flex", gap: 18, alignItems: "baseline", flexWrap: "wrap" }}>
            <b className="mono" style={{ fontSize: 22 }}>${d.total_market_cap_trillions!.toFixed(2)}T</b>
            <span className={`small ${d.change_24h_pct! > 0 ? "up" : d.change_24h_pct! < 0 ? "down" : ""}`}>{d.change_24h_pct! > 0 ? "+" : ""}{d.change_24h_pct}% in 24 hours</span>
            <span className="small dim">24h volume ${d.volume_24h_billions}B ({d.volume_to_cap_pct}% of value)</span>
          </div>
          <div style={{ display: "flex", height: 14, margin: "8px 0 4px" }} aria-label="Market split">
            <span title={`Bitcoin ${d.btc_dominance_pct}%`} style={{ width: `${d.btc_dominance_pct}%`, background: "var(--accent)" }} />
            <span title={`Ether ${d.eth_dominance_pct}%`} style={{ width: `${d.eth_dominance_pct}%`, background: "var(--accent)", opacity: 0.55 }} />
            <span title={`Everything else ${d.other_pct}%`} style={{ flex: 1, background: "var(--border)" }} />
          </div>
          <table className="tbl kv"><tbody>
            <tr><td className="dim">Bitcoin share ("dominance")</td><td className="r mono">{d.btc_dominance_pct}%</td></tr>
            <tr><td className="dim">Ether share</td><td className="r mono">{d.eth_dominance_pct}%</td></tr>
            <tr><td className="dim">Everything else</td><td className="r mono">{d.other_pct}%</td></tr>
            {d.stablecoin_share_pct != null && <tr><td className="dim">Tether + USD Coin share (cash-like)</td><td className="r mono">{d.stablecoin_share_pct}%</td></tr>}
          </tbody></table>
          <div className="small dim">Largest: {d.top!.map((t) => `${t.symbol} ${t.share_pct}%`).join(" · ")}. {d.coins!.toLocaleString("en-US")} coins tracked.</div></>}
        <div className="small dim">{d.note} <a href={d.url} target="_blank" rel="noreferrer noopener">{d.credit}</a>. {d.source}.</div>
      </div>}
    </Panel>);
}
