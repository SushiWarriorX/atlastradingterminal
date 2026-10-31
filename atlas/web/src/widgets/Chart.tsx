import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AreaSeries, BarSeries, CandlestickSeries, ColorType, createChart, HistogramSeries, IChartApi, ISeriesApi, LineSeries,
  PriceScaleMode, UTCTimestamp,
} from "lightweight-charts";
import { api, Candle } from "../api";
import { px } from "../fmt";
import { useStore } from "../store";
import { ErrorBox, Panel, ProvLine } from "../ui";
import { CompareView } from "./Compare";

const OVERLAYS: Record<string, { specs: string[]; color: string; label: string }> = {
  sma20: { specs: ["sma:20"], color: "#e8a33d", label: "SMA20" },
  sma50: { specs: ["sma:50"], color: "#5aa9e6", label: "SMA50" },
  sma200: { specs: ["sma:200"], color: "#b57edc", label: "SMA200" },
  ema21: { specs: ["ema:21"], color: "#4cc9a6", label: "EMA21" },
  bb: { specs: ["bb:20:2"], color: "#8a93a3", label: "BB(20,2)" },
  vwap: { specs: ["vwap"], color: "#f2d16b", label: "VWAP" },
};
type ChartType = "candles" | "bars" | "line" | "area";
const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

export function ChartWidget({ instrumentId, defaultInterval = "1d", title }: { instrumentId?: string; defaultInterval?: string; title?: string }) {
  const selected = useStore((s) => s.selected);
  const theme = useStore((s) => s.theme);
  const every = useStore((s) => s.updateSeconds) * 1000;
  const id = instrumentId ?? selected;
  const [interval, setIv] = useState(defaultInterval);
  const [type, setType] = useState<ChartType>("candles");
  const [log, setLog] = useState(false);
  const [on, setOn] = useState<string[]>(["sma20"]);
  const [full, setFull] = useState(false);
  const [cmp, setCmp] = useState<string[]>([]);
  const [cmpIv, setCmpIv] = useState("1d");
  const [cmpIn, setCmpIn] = useState("");
  const pendingCompare = useStore((s) => s.pendingCompare);
  const takePendingCompare = useStore((s) => s.takePendingCompare);
  const select = useStore((s) => s.select);
  // `COMPARE A B` from the command bar: the first synced chart (no fixed instrument) takes it
  useEffect(() => {
    if (!pendingCompare || instrumentId) return;
    const c = takePendingCompare();      // only the first synced chart to ask gets it
    if (c) { select(c[0]); setCmp(c.slice(1)); setCmpIv("1d"); }
  }, [pendingCompare]);
  const addCompare = async () => {
    const t = cmpIn.trim();
    if (!t) return;
    try {
      const found = await api.search(t);
      const hit = found.find((i) => i.symbol === t.toUpperCase()) ?? found[0];
      if (hit && hit.id !== id && !cmp.includes(hit.id) && cmp.length < 3) setCmp([...cmp, hit.id]);
    } finally { setCmpIn(""); }
  };
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const main = useRef<ISeriesApi<any> | null>(null);
  const vol = useRef<ISeriesApi<any> | null>(null);
  const overlays = useRef<Record<string, ISeriesApi<any>[]>>({});
  const lastKey = useRef("");

  const inst = useQuery({ queryKey: ["instrument", id], queryFn: () => api.instrument(id), staleTime: 60_000 });
  const supported = inst.data?.supported_intervals ?? [];
  useEffect(() => { if (supported.length && !supported.includes(interval)) setIv(supported.includes("1d") ? "1d" : supported[0]); }, [supported.join(), interval]);
  const ohlcv = useQuery({ queryKey: ["ohlcv", id, interval], queryFn: () => api.ohlcv(id, interval), refetchInterval: every, enabled: !!inst.data && supported.includes(interval), retry: 1 });
  const specs = on.flatMap((k) => OVERLAYS[k].specs);
  const ind = useQuery({ queryKey: ["ind", id, interval, specs.join()], queryFn: () => api.indicators(id, interval, specs), refetchInterval: every * 3, enabled: !!ohlcv.data && specs.length > 0 && !ohlcv.data.line_only, retry: 0 });

  // (re)create chart on theme change
  useEffect(() => {
    if (!host.current) return;
    const c = createChart(host.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: css("--panel") }, textColor: css("--dim"), fontFamily: "ui-monospace, Menlo, Consolas, monospace", fontSize: 11 },
      grid: { vertLines: { color: css("--grid") }, horzLines: { color: css("--grid") } },
      rightPriceScale: { borderColor: css("--border") }, timeScale: { borderColor: css("--border"), timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    });
    chart.current = c; main.current = null; vol.current = null; overlays.current = {}; lastKey.current = "";
    return () => { c.remove(); chart.current = null; };
  }, [theme]);

  useEffect(() => { chart.current?.priceScale("right").applyOptions({ mode: log ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal }); }, [log, theme]);

  // main series
  useEffect(() => {
    const c = chart.current, d = ohlcv.data;
    if (!c || !d) return;
    const lineOnly = d.line_only;
    const kind: ChartType = lineOnly && (type === "candles" || type === "bars") ? "line" : type;
    const key = `${id}|${interval}|${kind}|${theme}`;
    const first = key !== lastKey.current;
    if (first) {
      if (main.current) c.removeSeries(main.current);
      if (vol.current) { c.removeSeries(vol.current); vol.current = null; }
      const up = css("--up"), down = css("--down");
      main.current = kind === "candles" ? c.addSeries(CandlestickSeries, { upColor: up, downColor: down, borderUpColor: up, borderDownColor: down, wickUpColor: up, wickDownColor: down })
        : kind === "bars" ? c.addSeries(BarSeries, { upColor: up, downColor: down })
        : kind === "area" ? c.addSeries(AreaSeries, { lineColor: css("--accent"), topColor: css("--accent-fade"), bottomColor: "transparent" })
        : c.addSeries(LineSeries, { color: css("--accent"), lineWidth: 2 });
      if (!lineOnly && d.candles.some((x) => x.volume > 0)) {
        vol.current = c.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", color: css("--vol") });
        c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      }
      lastKey.current = key;
    }
    const t = (x: Candle) => x.time as UTCTimestamp;
    main.current!.setData(kind === "candles" || kind === "bars"
      ? d.candles.map((x) => ({ time: t(x), open: x.open, high: x.high, low: x.low, close: x.close }))
      : d.candles.map((x) => ({ time: t(x), value: x.close })));
    vol.current?.setData(d.candles.map((x) => ({ time: t(x), value: x.volume, color: x.close >= x.open ? css("--vol-up") : css("--vol-down") })));
    if (first) c.timeScale().fitContent();
  }, [ohlcv.data, type, theme, id, interval]);

  // indicator overlays
  useEffect(() => {
    const c = chart.current, d = ind.data;
    if (!c) return;
    for (const [k, list] of Object.entries(overlays.current)) if (!on.includes(k)) { list.forEach((s) => c.removeSeries(s)); delete overlays.current[k]; }
    if (!d) return;
    for (const k of on) {
      const o = OVERLAYS[k];
      const names = Object.keys(d.series).filter((n) => o.specs.some((sp) => n === sp || n.startsWith(sp + ":")));
      overlays.current[k]?.forEach((s) => c.removeSeries(s));
      overlays.current[k] = names.map((n) => {
        const s = c.addSeries(LineSeries, { color: o.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, title: names.length > 1 ? n.split(":").pop() : o.label,
          lineStyle: n.endsWith(":mid") ? 2 : 0, crosshairMarkerVisible: false });
        s.setData(d.times.flatMap((time, i) => (d.series[n][i] === null ? [] : [{ time: time as UTCTimestamp, value: d.series[n][i] as number }])));
        return s;
      });
    }
  }, [ind.data, on, theme]);

  const last = ohlcv.data?.candles.at(-1);
  const shot = () => {
    const canvas = chart.current?.takeScreenshot();
    if (!canvas) return;
    const a = document.createElement("a");
    a.href = canvas.toDataURL("image/png"); a.download = `${inst.data?.symbol ?? "chart"}-${interval}.png`; a.click();
  };
  const noData = !inst.isLoading && inst.isError ? inst.error : ohlcv.isError ? ohlcv.error : null;

  return (
    <Panel title={title ?? `CHART ${inst.data?.symbol ?? ""} ${interval}`} className={full ? "fullscreen" : ""}
      right={<>{ohlcv.data && <ProvLine prov={ohlcv.data.prov} extra={ohlcv.data.derived_from ? `derived from ${ohlcv.data.derived_from}` : undefined} />}
        <button className="mini" onClick={() => setFull(!full)} title="Toggle full screen">{full ? "✕" : "⤢"}</button></>}>
      <div className="toolbar">
        {supported.map((i) => <button key={i} className={`mini ${i === interval ? "on" : ""}`} onClick={() => setIv(i)}>{i}</button>)}
        <span className="sep" />
        {(["candles", "bars", "line", "area"] as ChartType[]).map((t) => <button key={t} className={`mini ${t === type ? "on" : ""}`} onClick={() => setType(t)}>{t}</button>)}
        <button className={`mini ${log ? "on" : ""}`} onClick={() => setLog(!log)}>log</button>
        <span className="sep" />
        {Object.entries(OVERLAYS).map(([k, o]) => (
          <button key={k} className={`mini ${on.includes(k) ? "on" : ""}`} style={on.includes(k) ? { borderColor: o.color, color: o.color } : undefined}
            disabled={ohlcv.data?.line_only} onClick={() => setOn(on.includes(k) ? on.filter((x) => x !== k) : [...on, k])}>{o.label}</button>))}
        <span className="sep" />
        <input className="w80" value={cmpIn} onChange={(e) => setCmpIn(e.target.value.toUpperCase())} onKeyDown={(e) => e.key === "Enter" && addCompare()} placeholder="compare…" aria-label="Compare symbol" />
        {cmp.map((c) => <button key={c} className="mini on" onClick={() => setCmp(cmp.filter((x) => x !== c))} title="Remove from comparison">{c.split(":")[2]} ✕</button>)}
        <button className="mini" onClick={shot} title="Download PNG">png</button>
        {last && <span className="ohlc mono">O {px(last.open)} H {px(last.high)} L {px(last.low)} C {px(last.close)}</span>}
      </div>
      {cmp.length > 0 && <CompareView ids={[id, ...cmp]} interval={cmpIv} onInterval={setCmpIv} />}
      <div className="chart-host" ref={host} style={cmp.length ? { display: "none" } : undefined} />
      {!cmp.length && noData && <div className="chart-overlay"><ErrorBox error={noData} /></div>}
      {ind.isError && <div className="note">Indicators unavailable: {(ind.error as Error).message}</div>}
    </Panel>
  );
}
