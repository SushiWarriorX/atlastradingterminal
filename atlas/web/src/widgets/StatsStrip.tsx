import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { dir, num, pct, px } from "../fmt";
import { BTC_ID } from "../ids";
import { useSelectedId } from "../scope";
import { useStore } from "../store";
import { Badge } from "../ui";

const money = (x: number) => (x >= 1e9 ? `$${(x / 1e9).toFixed(2)}B` : `$${(x / 1e6).toFixed(1)}M`);

/** A strip of the key numbers for the selected instrument, above the chart. Every value comes from the quote or derivatives feeds, and a missing one reads "n/a". */
export function StatsStrip() {
  const id = useSelectedId();
  const every = useStore((s) => s.updateSeconds) * 1000;
  const inst = useQuery({ queryKey: ["instrument", id], queryFn: () => api.instrument(id), staleTime: 60_000 });
  const q = useQuery({ queryKey: ["quotes", id], queryFn: async () => (await api.quotes([id]))[0], refetchInterval: every });
  const btc = id === BTC_ID;
  const deriv = useQuery({ queryKey: ["derivatives"], queryFn: () => api.derivatives(), enabled: btc, refetchInterval: 60_000, staleTime: 30_000 });
  const d = q.data && !("error" in q.data) ? q.data : null;
  const agg = deriv.data?.aggregate;
  const cell = (label: string, value: string, cls = "", title?: string) => (
    <div className="stat" key={label} title={title}><span className="stat-l">{label}</span><span className={`stat-v mono ${cls} ${value === "n/a" ? "dim" : ""}`}>{value}</span></div>);
  const n = (v: number | null | undefined, f: (x: number) => string = px) => (v === null || v === undefined ? "n/a" : f(v));
  return (
    <div className="stats-strip" data-testid="stats-strip">
      <div className="stat-id"><b>{inst.data?.symbol ?? "…"}</b><span className="dim small">{inst.data?.name ?? ""}</span></div>
      {d ? <>
        <div className="stat stat-px"><span className="stat-l">Price</span><span className="stat-v mono">{px(d.price)}</span></div>
        {cell("Change", `${num(d.change)} (${pct(d.change_pct)})`, dir(d.change_pct), `Change vs ${d.prev_close_basis}`)}
        {cell("Open", n(d.open))}{cell("High", n(d.high))}{cell("Low", n(d.low))}{cell("Prev close", n(d.prev_close))}
        {cell("Volume", n(d.volume, (x) => num(x, 0)))}
        {btc && cell("Funding (annualised)", agg?.available ? n(agg.funding_annual_pct, (x) => pct(x)) : "n/a", "", "Perpetual-swap funding across exchanges, from the derivatives feed")}
        {btc && cell("Open interest", agg?.available ? n(agg.oi_usd, money) : "n/a", "", "Open interest across exchanges, in USD")}
        <div className="stat-r"><Badge status={d.prov.status} /></div>
      </> : <span className="dim">{q.isError || (q.data && "error" in q.data) ? "Price unavailable" : "Loading…"}</span>}
    </div>
  );
}
