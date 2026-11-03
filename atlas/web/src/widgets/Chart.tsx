import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AreaSeries, BarSeries, CandlestickSeries, ColorType, createChart, HistogramSeries, IChartApi, ISeriesApi, LineSeries,
  PriceScaleMode, UTCTimestamp,
} from "lightweight-charts";
import { api, Candle } from "../api";
import { px } from "../fmt";
import { useStore } from "../store";
import { isEquityId } from "../ids";
import { useDebounced } from "../hooks";
import { useSelectedId } from "../scope";
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

const PIN = "atlas.chartPin.";
const loadPin = (k: string): string | null => { try { return localStorage.getItem(PIN + k); } catch { return null; } };
const savePin = (k: string, id: string | null) => { try { if (id) localStorage.setItem(PIN + k, id); else localStorage.removeItem(PIN + k); } catch { /* per-viewer convenience only */ } };

/** pick="any": this chart has its own asset (type a symbol to change it). pick="equity": typing changes the Equities desk's stock/ETF. No pick: the asset is fixed by the desk. */
const RANGES = [
  { l: "1D", iv: "5m", span: 86_400 }, { l: "1W", iv: "1h", span: 7 * 86_400 }, { l: "1M", iv: "4h", span: 30 * 86_400 },
  { l: "3M", iv: "1d", span: 90 * 86_400 }, { l: "1Y", iv: "1d", span: 365 * 86_400 },
];
const TYPE_ICON: Record<string, JSX.Element> = {
  candles: <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M4 2v12M12 4v10"/><rect x="2.5" y="5" width="3" height="6" fill="currentColor"/><rect x="10.5" y="7" width="3" height="5" fill="currentColor"/></svg>,
  bars: <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="M4 2v12M2 5h2M4 11h2M12 3v11M10 6h2M12 12h2"/></svg>,
  line: <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M1.5 12l4-5 3 3 6-7"/></svg>,
  area: <svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor" stroke="currentColor" strokeWidth="1.2"><path d="M1.5 12l4-5 3 3 6-7V14H1.5z" fillOpacity=".35"/><path d="M1.5 12l4-5 3 3 6-7" fill="none"/></svg>,
};

export function ChartWidget({ instrumentId, defaultInterval = "1d", title, wid, pick }: { instrumentId?: string; defaultInterval?: string; title?: string; wid?: string; pick?: "any" | "equity" }) {
  const selected = useSelectedId();
  const [pinned, setPinned] = useState<string | null>(() => (pick === "any" && wid ? loadPin(wid) : null));
  const [symIn, setSymIn] = useState("");
  const [symMsg, setSymMsg] = useState<string | null>(null);
  const dSym = useDebounced(symIn);
  const found = useQuery({ queryKey: ["chart-search", dSym], queryFn: () => api.search(dSym), enabled: !!pick && dSym.trim().length > 0 });
  const choices = (found.data ?? []).filter((i) => pick !== "equity" || isEquityId(i.id)).slice(0, 6);
  const choose = (i: { id: string }) => {
    setSymIn(""); setSymMsg(null);
    if (pick === "equity") useStore.getState().select(i.id);
    else { setPinned(i.id); if (wid) savePin(wid, i.id); }
  };
  const submitSym = async () => {
    const t = symIn.trim().toUpperCase();
    if (!t) return;
    const list = (await api.search(t)).filter((i) => pick !== "equity" || isEquityId(i.id));
    const hit = list.find((i) => i.symbol === t) ?? list[0];
    if (hit) choose(hit); else setSymMsg(pick === "equity" ? `No stock or ETF matches "${t}"` : `No match for "${t}"`);
  };
  const unpin = () => { setPinned(null); if (wid) savePin(wid, null); };
  const theme = useStore((s) => s.theme);
  const every = useStore((s) => s.updateSeconds) * 1000;
  const id = instrumentId ?? pinned ?? selected;
  const [interval, setIv] = useState(defaultInterval);
  const [type, setType] = useState<ChartType>("candles");
  const [tools, setTools] = useState(false);
  const [range, setRange] = useState<string | null>(null);
  const pendingSpan = useRef<number | null>(null);
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
    if (!pendingCompare || instrumentId || pinned) return;
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
    if (pendingSpan.current !== null && d.candles.length) {
      const end = d.candles[d.candles.length - 1].time;
      c.timeScale().setVisibleRange({ from: Math.max(d.candles[0].time, end - pendingSpan.current) as UTCTimestamp, to: end as UTCTimestamp });
      pendingSpan.current = null;
    } else if (first) c.timeScale().fitContent();
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

  const pickRange = (r: typeof RANGES[number]) => {
    const iv = supported.includes(r.iv) ? r.iv : supported.includes("1d") ? "1d" : supported[0];
    setRange(r.l);
    pendingSpan.current = r.span;
    if (iv === interval) {
      const cs = ohlcv.data?.candles;
      if (cs?.length && chart.current) { const end = cs[cs.length - 1].time; chart.current.timeScale().setVisibleRange({ from: Math.max(cs[0].time, end - r.span) as UTCTimestamp, to: end as UTCTimestamp }); pendingSpan.current = null; }
    } else setIv(iv);
  };
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
      {pick && (
        <div className="toolbar chart-pick">
          <div className="addrow">
            <input className="w80" value={symIn} onChange={(e) => { setSymIn(e.target.value.toUpperCase()); setSymMsg(null); }} onKeyDown={(e) => e.key === "Enter" && submitSym()}
              placeholder={`${inst.data?.symbol ?? "symbol"} · change…`} aria-label="Chart symbol" spellCheck={false} />
            {symIn && choices.length > 0 && (
              <div className="dropdown">{choices.map((i) => <div key={i.id} className="opt" onClick={() => choose(i)}><b>{i.symbol}</b> <span className="dim">{i.name}</span></div>)}</div>)}
          </div>
          {pinned && <button className="mini" onClick={unpin} title="Stop using this chart's own asset and follow the selected instrument again">↺ follow selection</button>}
          {symMsg && <span className="warnc small">{symMsg}</span>}
          <span className="dim small">{pick === "equity" ? "stocks and ETFs only" : pinned ? "own asset" : "follows the selected instrument"}</span>
        </div>)}
      <div className="toolbar toolbar-main">
        {supported.map((i) => <button key={i} className={`mini ${i === interval ? "on" : ""}`} onClick={() => setIv(i)}>{i}</button>)}
        <span className="sep" />
        <button className={`mini ${tools || on.length || cmp.length ? "on" : ""}`} onClick={() => setTools(!tools)} title="Chart style, indicators, compare and download">Indicators{on.length + cmp.length ? ` · ${on.length + cmp.length}` : ""}</button>
        {last && <span className="ohlc mono">O {px(last.open)} H {px(last.high)} L {px(last.low)} C {px(last.close)}</span>}
      </div>
      {tools && (
        <div className="toolbar toolbar-tools">
          {(["candles", "bars", "line", "area"] as ChartType[]).map((t) => <button key={t} className={`mini ico ${t === type ? "on" : ""}`} onClick={() => setType(t)} title={t} aria-label={t}>{TYPE_ICON[t]}</button>)}
          <button className={`mini ${log ? "on" : ""}`} onClick={() => setLog(!log)}>log</button>
          <span className="sep" />
          {Object.entries(OVERLAYS).map(([k, o]) => (
            <button key={k} className={`mini ${on.includes(k) ? "on" : ""}`} style={on.includes(k) ? { color: o.color } : undefined}
              disabled={ohlcv.data?.line_only} onClick={() => setOn(on.includes(k) ? on.filter((x) => x !== k) : [...on, k])}>{o.label}</button>))}
          <span className="sep" />
          <input className="w80" value={cmpIn} onChange={(e) => setCmpIn(e.target.value.toUpperCase())} onKeyDown={(e) => e.key === "Enter" && addCompare()} placeholder="compare…" aria-label="Compare symbol" />
          <button className="mini" onClick={shot} title="Download PNG">png</button>
        </div>)}
      {cmp.length > 0 && <div className="toolbar">{cmp.map((c) => <button key={c} className="mini on" onClick={() => setCmp(cmp.filter((x) => x !== c))} title="Remove from comparison">{c.split(":")[2]} ✕</button>)}</div>}
      {cmp.length > 0 && <CompareView ids={[id, ...cmp]} interval={cmpIv} onInterval={setCmpIv} />}
      <div className="chart-host" ref={host} style={cmp.length ? { display: "none" } : undefined} />
      {!cmp.length && !noData && <div className="range-bar" data-testid="range-bar">{RANGES.map((r) => <button key={r.l} className={`mini ${range === r.l ? "on" : ""}`} onClick={() => pickRange(r)} title={`Show the last ${r.l}`}>{r.l}</button>)}</div>}
      {!cmp.length && noData && <div className="chart-overlay"><ErrorBox error={noData} /></div>}
      {ind.isError && <div className="note">Indicators unavailable: {(ind.error as Error).message}</div>}
    </Panel>
  );
}
