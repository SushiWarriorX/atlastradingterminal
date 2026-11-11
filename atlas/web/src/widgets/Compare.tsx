import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { ColorType, createChart, LineSeries, UTCTimestamp } from "lightweight-charts";
import { api, PairStats } from "../api";
import { pct } from "../fmt";
import { useStore } from "../store";
import { ErrorBox, ProvLine } from "../ui";
import { ymdLabel as ymd } from "../fmt";

const COLORS = ["--accent", "--info", "--ai", "--warn"];
const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const fmtDate = (t: number) => ymd(new Date(t * 1000).toISOString());
const cc = (x: number | null | undefined) => (x === null || x === undefined ? "—" : x.toFixed(2));

export function CompareView({ ids, interval, onInterval }: { ids: string[]; interval: string; onInterval: (i: string) => void }) {
  const theme = useStore((s) => s.theme);
  const every = useStore((s) => s.updateSeconds) * 1000;
  const host = useRef<HTMLDivElement>(null);
  const q = useQuery({ queryKey: ["compare", ids.join(), interval], queryFn: () => api.compare(ids, interval), refetchInterval: every * 6, retry: 0 });
  const d = q.data;

  useEffect(() => {
    if (!host.current || !d) return;
    const c = createChart(host.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: css("--panel") }, textColor: css("--dim"), fontFamily: "ui-monospace, Menlo, Consolas, monospace", fontSize: 11 },
      grid: { vertLines: { color: css("--grid") }, horzLines: { color: css("--grid") } },
      rightPriceScale: { borderColor: css("--border") }, timeScale: { borderColor: css("--border") },
    });
    Object.values(d.series).forEach((s, i) => {
      const line = c.addSeries(LineSeries, { color: css(COLORS[i % 4]), lineWidth: 2, title: s.symbol, priceFormat: { type: "price", precision: 1, minMove: 0.1 } });
      line.setData(d.times.map((t, j) => ({ time: t as UTCTimestamp, value: s.rebased[j] })));
    });
    c.timeScale().fitContent();
    return () => c.remove();
  }, [d, theme]);

  if (q.isError) return <ErrorBox error={q.error} />;
  const base = d ? d.series[d.base] : null;
  return (
    <div className="compare">
      <div className="toolbar">
        <span className="dim small">interval</span>
        {["1d", "1w", "1h", "15m"].map((i) => <button key={i} className={`mini ${i === interval ? "on" : ""}`} onClick={() => onInterval(i)}
          title={i === "1d" || i === "1w" ? "Calendar-aligned on shared dates" : "Only works when all bars share timestamps"}>{i}</button>)}
        {d && Object.entries(d.series).map(([id, s], i) => (
          <span key={id} className="legend mono" style={{ color: `var(${COLORS[i % 4]})` }}>■ {s.symbol} {pct(s.rebased[s.rebased.length - 1] - 100)}</span>))}
        {base && <span className="dim small spacer"><ProvLine prov={base.prov} /></span>}
      </div>
      <div className="chart-host" ref={host} />
      {q.isLoading && <div className="note">Aligning series…</div>}
      {d && (
        <div className="cmpstats">
          <div className="note">Rebased to 100 · {d.aligned_bars} aligned bars ({fmtDate(d.range[0])} → {fmtDate(d.range[1])}) · dropped: {Object.values(d.series).map((s) => `${s.symbol} ${s.bars_before_alignment - d.aligned_bars}`).join(", ")}</div>
          <table className="tbl">
            <thead><tr><th>vs {base?.symbol}</th><th className="r">Obs</th>{["20", "60", "90", "180"].map((w) => <th key={w} className="r" title={`Correlation of returns over the last ${w} aligned observations (beta in tooltip)`}>ρ {w}</th>)}<th className="r">ρ60 range</th><th className="r">Return</th></tr></thead>
            <tbody>{Object.entries(d.stats).map(([id, st]: [string, PairStats]) => (
              <tr key={id}><td><b>{d.series[id].symbol}</b></td><td className="r mono">{st.observations}</td>
                {["20", "60", "90", "180"].map((w) => {
                  const x = st.windows[w];
                  return <td key={w} className="r mono" title={x.available ? `beta of ${d.series[id].symbol} on ${base?.symbol}: ${cc(x.beta_of_other_on_base)}` : `only ${x.observations} observations`}>
                    {x.available ? cc(x.corr) : <span className="dim">n/a</span>}</td>;
                })}
                <td className="r mono" title={st.rolling_60?.note}>{st.rolling_60 ? `${cc(st.rolling_60.min)} … ${cc(st.rolling_60.max)} (now ${cc(st.rolling_60.latest)})` : <span className="dim">n/a</span>}</td>
                <td className="r mono">{pct(st.total_return_pct.other)} <span className="dim">vs {pct(st.total_return_pct.base)}</span></td></tr>))}</tbody>
          </table>
          <div className="note">{d.notes.join(" ")} n/a = fewer observations than the window.</div>
        </div>)}
    </div>
  );
}
