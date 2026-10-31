import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, MtfFactor } from "../api";
import { dir, num, px } from "../fmt";
import { useStore } from "../store";
import { Badge, ErrorBox, Panel } from "../ui";

const FACTOR_LABEL: Record<string, string> = { trend: "Trend", structure: "Structure", momentum: "Momentum", volume: "Volume", relative_strength: "Relative strength", volatility: "Volatility" };
const tone = (l?: string | null) => (l === "bullish" || l === "uptrend" ? "up" : l === "bearish" || l === "downtrend" ? "down" : "dim");

function Bar({ f }: { f: MtfFactor }) {
  const v = f.value ?? 0;
  return (
    <div className="divbar" title={f.available ? `value ${v.toFixed(2)} (−1 … +1)` : "unavailable: excluded from the score"}>
      <div className="mid" />
      {f.available && <div className={`fill ${v >= 0 ? "pos" : "neg"}`} style={v >= 0 ? { left: "50%", width: `${v * 50}%` } : { right: "50%", width: `${-v * 50}%` }} />}
    </div>
  );
}

export function MtfWidget() {
  const id = useStore((s) => s.selected);
  const every = useStore((s) => s.updateSeconds) * 1000;
  const [bench, setBench] = useState<string>("");   // "" = automatic (SPY for US equities, none for crypto)
  const inst = useQuery({ queryKey: ["instrument", id], queryFn: () => api.instrument(id), staleTime: 60_000 });
  const q = useQuery({ queryKey: ["mtf", id, bench], queryFn: () => api.mtf(id, bench || undefined), refetchInterval: every * 12, retry: 0 });
  const d = q.data;
  const sc = d?.score;
  return (
    <Panel title={`MULTI-TIMEFRAME ${inst.data?.symbol ?? ""}`} right={<span className="dim">benchmark
      <select value={bench} onChange={(e) => setBench(e.target.value)} aria-label="Benchmark"><option value="">auto</option><option value="none">none</option><option>SPY</option><option>QQQ</option><option>IWM</option></select></span>}>
      {q.isError && <ErrorBox error={q.error} />}
      {q.isLoading && <div className="note">Analysing 5 timeframes…</div>}
      {d && (
        <>
          <div className="mtf-top">
            <div className="verdict"><b>{d.alignment.verdict.toUpperCase()}</b><div className="small">{d.alignment.text}</div></div>
            {sc && <div className="scorebox" title={sc.disclaimer}><div className="scorenum mono">{sc.score ?? "—"}</div><div className={`small ${sc.label === "bullish tilt" ? "up" : sc.label === "bearish tilt" ? "down" : "dim"}`}>{sc.label ?? "no data"}</div></div>}
          </div>
          <table className="tbl">
            <thead><tr><th>TF</th><th>Trend</th><th>Structure</th><th>Event</th><th className="r">RSI</th><th className="r">MACD</th><th className="r">ATR%</th><th className="r">RVOL</th><th className="r">Support</th><th className="r">Resist.</th><th>Data</th></tr></thead>
            <tbody>{d.timeframes.map((t) => t.available ? (
              <tr key={t.interval}>
                <td><b>{t.interval}</b></td><td className={tone(t.trend)}>{t.trend}</td>
                <td className={tone(t.structure?.label)} title={t.structure?.derivation}>{t.structure?.label?.replace("_", " ")}</td>
                <td className="small">{t.structure?.event ?? <span className="dim">—</span>}</td>
                <td className="r mono">{num(t.rsi14, 0)}</td><td className={`r mono ${dir(t.macd_hist)}`}>{t.macd_hist === null || t.macd_hist === undefined ? "—" : t.macd_hist >= 0 ? "▲" : "▼"}</td>
                <td className="r mono">{t.atr_pct === null || t.atr_pct === undefined ? "—" : `${num(t.atr_pct, 1)}%`}</td><td className="r mono">{t.rvol === null || t.rvol === undefined ? "—" : `${num(t.rvol, 1)}x`}</td>
                <td className="r mono">{px(t.nearest_support)}</td><td className="r mono">{px(t.nearest_resistance)}</td>
                <td>{t.data && <Badge status={t.data.status} title={`${t.data.provider}${t.data.derived_from ? ` · derived from ${t.data.derived_from}` : ""}`} />}{t.data?.derived_from && <span className="dim small"> d</span>}</td>
              </tr>) : (
              <tr key={t.interval} className="dim"><td><b>{t.interval}</b></td><td colSpan={9} title={t.reason}>unavailable: {t.reason?.slice(0, 90)}</td><td><Badge status="UNAVAILABLE" /></td></tr>))}</tbody>
          </table>
          {sc && (
            <>
              <div className="aform-h" style={{ marginTop: 6 }}>SCORE FACTORS (tilt {sc.tilt === null ? "n/a" : sc.tilt.toFixed(2)}{d.benchmark ? ` · benchmark ${d.benchmark}` : ""})</div>
              <table className="tbl">
                <thead><tr><th>Factor</th><th style={{ width: 150 }}>−1 … +1</th><th className="r">Weight</th><th className="r">Used</th><th className="r">Contrib.</th><th>Inputs</th></tr></thead>
                <tbody>{Object.entries(sc.factors).map(([k, f]) => (
                  <tr key={k} className={f.available ? "" : "dim"} title={sc.rules[k]}>
                    <td>{FACTOR_LABEL[k] ?? k}{f.context_only && <span className="dim small"> (context)</span>}</td><td><Bar f={f} /></td>
                    <td className="r mono">{f.weight.toFixed(2)}</td><td className="r mono">{f.available && f.effective_weight > 0 ? f.effective_weight.toFixed(2) : "—"}</td>
                    <td className={`r mono ${dir(f.contribution)}`}>{f.effective_weight > 0 ? f.contribution.toFixed(2) : "—"}</td>
                    <td className="dim small">{f.available ? Object.entries(f.inputs).map(([a, b]) => `${a}: ${typeof b === "number" ? num(b, 2) : String(b)}`).join(" · ") : `excluded${f.note ? `: ${f.note}` : ""}`}</td>
                  </tr>))}</tbody>
              </table>
              <div className="note">Weights of unavailable factors are redistributed, never imputed. Hover a factor for its rule. {sc.disclaimer} Swing structure uses k={d.swing_k} bars each side. Trend/structure use the last completed bar.</div>
            </>)}
        </>)}
    </Panel>
  );
}
