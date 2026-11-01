import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, DerivHistory, DerivVenue, Pctile } from "../api";
import { ago, dir, num, sgn } from "../fmt";
import { Badge, ErrorBox, Panel } from "../ui";

const usd = (v: number | undefined) => (v === undefined ? "—" : v >= 1e9 ? `$${(v / 1e9).toFixed(2)}B` : `$${(v / 1e6).toFixed(0)}M`);

function Spark({ pts, color }: { pts: { v: number }[]; color: string }) {
  const W = 220, H = 36;
  const d = useMemo(() => {
    let lo = Infinity, hi = -Infinity;
    for (const p of pts) { if (p.v < lo) lo = p.v; if (p.v > hi) hi = p.v; }
    return pts.map((p, i) => `${i ? "L" : "M"}${(i / (pts.length - 1)) * W},${H - ((p.v - lo) / (hi - lo || 1)) * (H - 4) - 2}`).join(" ");
  }, [pts]);
  if (pts.length < 2) return <div className="dim small">collecting history…</div>;
  return <svg width={W} height={H} role="img" aria-label="history"><path d={d} fill="none" stroke={color} strokeWidth="1.5" /></svg>;
}

const ctx = (p: Pctile | undefined, label: string) => !p ? null : p.available
  ? <span title={`${p.points} recorded points in the last 30 days`}>{label}: <b>{num(p.pctile, 0)}th</b> percentile of the last 30 days</span>
  : <span className="dim" title="Percentiles only appear once ATLAS has recorded enough of its own history">{label}: not enough history yet ({p.have} of {p.need} points)</span>;

export function DerivativesWidget() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["derivs"], queryFn: () => api.derivatives(), refetchInterval: 60_000, retry: 0 });
  const h = useQuery({ queryKey: ["derivs-hist"], queryFn: () => api.derivativesHistory(72), refetchInterval: 300_000, retry: 0 });
  const d = q.data, a = d?.aggregate;
  const hist: DerivHistory | undefined = h.data;
  return (
    <Panel title="BTC DERIVATIVES (perpetual swaps)" className="deriv"
      right={d && <span className="dim">{a?.venues_ok}/{a?.venues_expected} venues · {d.demo ? <Badge status="DEMO" /> : "snapshot"} {ago(d.as_of)}</span>}>
      <div className="toolbar">
        <span className="dim small">Positive funding = longs pay shorts</span>
        <button className="mini on spacer" onClick={() => { api.derivatives(true).then((x) => qc.setQueryData(["derivs"], x)).catch(() => undefined); }}>refresh now</button>
      </div>
      {q.isError && <ErrorBox error={q.error} />}
      {q.isLoading && <div className="note">Asking the four exchanges…</div>}
      {d?.demo && <div className="note warn">⚠ Synthetic demo data: not real market data.</div>}
      {d && (
        <>
          <table className="tbl">
            <thead><tr><th>Venue</th><th className="r">Mark</th><th className="r" title="Funding rate per 8 hours (hourly venues are scaled x8)">Funding /8h</th><th className="r" title="Rate x intervals per year, simple not compounded">Annualised</th>
              <th className="r" title="(mark - index) / index: the perpetual's premium to the spot index">Basis</th><th className="r">OI (BTC)</th><th className="r">OI ($)</th><th>Status</th></tr></thead>
            <tbody>
              {d.venues.map((v: DerivVenue) => v.ok ? (
                <tr key={v.venue} title={(v.notes ?? []).join("\n")}>
                  <td><b>{v.label}</b></td><td className="r mono">{num(v.mark, 1)}</td><td className={`r mono ${dir(v.funding_8h_pct)}`}>{sgn(v.funding_8h_pct, 4)}%</td>
                  <td className={`r mono ${dir(v.funding_annual_pct)}`}>{sgn(v.funding_annual_pct, 1)}%</td><td className={`r mono ${dir(v.basis_pct)}`}>{sgn(v.basis_pct, 3)}%</td>
                  <td className="r mono">{num(v.oi_btc, 0)}</td><td className="r mono">{usd(v.oi_usd)}</td><td><Badge status={v.status as never} /></td></tr>
              ) : (
                <tr key={v.venue} className="dim"><td><b>{v.label}</b></td><td colSpan={6} className="down small">✕ {v.error?.message} ({v.error?.code})</td><td><Badge status="UNAVAILABLE" /></td></tr>))}
              {a?.available && (
                <tr><td><b>All answering venues</b></td><td /><td /><td className={`r mono ${dir(a.funding_annual_pct)}`} title="Open-interest-weighted mean of the venues' annualised funding">{sgn(a.funding_annual_pct, 1)}%</td>
                  <td /><td className="r mono">{num(a.oi_btc, 0)}</td><td className="r mono">{usd(a.oi_usd)}</td><td /></tr>)}
            </tbody>
          </table>
          {a?.flags.map((f) => <div key={f} className="note warn">⚠ {f}</div>)}
          {a?.available && (
            <div className="small deriv-ctx">
              <div>{ctx(a.funding_percentile_30d, "Funding")}</div>
              <div>{ctx(a.oi_percentile_30d, "Open interest")}</div>
              <div>{a.oi_change_24h_pct?.available ? <span>Open interest, 24 h: <b className={dir(a.oi_change_24h_pct.value)}>{sgn(a.oi_change_24h_pct.value, 1)}%</b></span>
                : <span className="dim" title={a.oi_change_24h_pct?.reason}>Open interest, 24 h: not enough history yet</span>}</div>
              <div className="dim">Funding spread between venues: {num(a.funding_spread_annual_pct, 1)} pts annualised</div>
            </div>)}
          {hist && !d.demo && (
            <div className="deriv-spark">
              <div><span className="dim small">Funding, annualised (72 h)</span><Spark pts={hist.funding_annual_pct} color="var(--accent)" /></div>
              <div><span className="dim small">Open interest, USD (72 h)</span><Spark pts={hist.oi_usd} color="var(--info)" /></div>
            </div>)}
          {d.notes.map((x) => <div key={x} className="note">{x}</div>)}
        </>)}
    </Panel>
  );
}
