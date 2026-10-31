import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ago, dir, num, pct, px } from "../fmt";
import { useStore } from "../store";
import { Badge, ErrorBox, Panel, ProvLine } from "../ui";

export function QuoteWidget({ instrumentId }: { instrumentId?: string }) {
  const selected = useStore((s) => s.selected);
  const every = useStore((s) => s.updateSeconds) * 1000;
  const id = instrumentId ?? selected;
  const inst = useQuery({ queryKey: ["instrument", id], queryFn: () => api.instrument(id), staleTime: 60_000 });
  const q = useQuery({ queryKey: ["quotes", id], queryFn: async () => (await api.quotes([id]))[0], refetchInterval: every });
  const d = q.data && !("error" in q.data) ? q.data : null;
  const row = (k: string, v: string, unsupported?: string) => (
    <tr key={k}><td className="dim">{k}</td><td className={`r mono ${v === "n/a" ? "dim" : ""}`} title={v === "n/a" ? `${unsupported} not provided by this data source` : undefined}>{v}</td></tr>);
  const u = (f: string, v: number | null | undefined, fmt: (x: number) => string = px) =>
    row(f, v === null || v === undefined ? "n/a" : fmt(v), f);
  return (
    <Panel title={`QUOTE ${inst.data?.symbol ?? ""}`} right={d && <ProvLine prov={d.prov} />}>
      {inst.data && <div className="qname">{inst.data.name} <span className="dim">· {inst.data.id}</span></div>}
      {q.isError && <ErrorBox error={q.error} />}
      {q.data && "error" in q.data && <div className="errbox"><Badge status="UNAVAILABLE" /><div>{q.data.error}</div></div>}
      {d && <>
        <div className="bigpx mono">{px(d.price)} <span className={dir(d.change_pct)}>{num(d.change)} ({pct(d.change_pct)})</span></div>
        <div className="note">Change vs {d.prev_close_basis}</div>
        <table className="tbl kv"><tbody>
          {u("Open", d.open)}{u("High", d.high)}{u("Low", d.low)}{u("Prev close", d.prev_close)}
          {u("Bid", d.bid)}{u("Ask", d.ask)}{u("Spread", d.spread, (x) => num(x, 4))}
          {u("Volume", d.volume, (x) => num(x, 0))}{u("VWAP", d.vwap)}{u("Mkt cap", d.market_cap, (x) => `${(x / 1e9).toFixed(1)}B`)}
          {row("Session", d.prov.session ?? "24/7")}
          {row("Venue", d.prov.venue ?? "—")}
        </tbody></table>
        {d.prov.quality.length > 0 && <div className="note">⚠ {d.prov.quality.join("; ")}</div>}
        {inst.data?.note && <div className="note">ⓘ {inst.data.note}</div>}
      </>}
    </Panel>
  );
}

export function TechWidget() {
  const id = useStore((s) => s.selected);
  const every = useStore((s) => s.updateSeconds) * 1000;
  const inst = useQuery({ queryKey: ["instrument", id], queryFn: () => api.instrument(id), staleTime: 60_000 });
  const iv = inst.data?.supported_intervals?.includes("1h") ? "1h" : "1d";
  const lv = useQuery({ queryKey: ["levels", id, iv], queryFn: () => api.levels(id, iv), enabled: !!inst.data, refetchInterval: every * 4, retry: 1 });
  const px_ = useQuery({ queryKey: ["quotes", id], queryFn: async () => (await api.quotes([id]))[0] });
  const last = px_.data && !("error" in px_.data) ? px_.data.price : null;
  const levels = [...(lv.data?.levels ?? [])].sort((a, b) => b.price - a.price);
  const t = lv.data?.trend;
  return (
    <Panel title={`TECHNICAL ${inst.data?.symbol ?? ""} ${iv}`} right={lv.data && <ProvLine prov={lv.data.prov} />}>
      {lv.isError && <ErrorBox error={lv.error} />}
      {t && <div className="trend">Trend (MA alignment): <b className={t.label === "bullish" ? "up" : t.label === "bearish" ? "down" : ""}>{t.label.toUpperCase()}</b>
        <span className="dim mono"> {Object.entries(t.factors).filter(([, v]) => typeof v === "number").map(([k, v]) => `${k} ${num(v as number)}`).join(" · ")}</span></div>}
      <table className="tbl"><thead><tr><th>Level</th><th className="r">Price</th><th className="r">vs last</th><th>Derivation</th></tr></thead>
        <tbody>{levels.map((l) => (
          <tr key={l.id}><td>{l.kind.replace(/_/g, " ")}</td><td className="r mono">{px(l.price)}</td>
            <td className={`r mono ${last ? dir(l.price - last) : ""}`}>{last ? pct((l.price / last - 1) * 100) : "—"}</td><td className="dim small">{l.derivation}</td></tr>))}</tbody></table>
      <div className="note">Levels computed in code (fractal swings, prior-day range, SMA). Rules shown per row; not trade signals.</div>
    </Panel>
  );
}

export function HealthWidget() {
  const st = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 10_000 });
  return (
    <Panel title="DATA HEALTH">
      {st.isError && <ErrorBox error={st.error} />}
      {st.data && <>
        <table className="tbl"><thead><tr><th>Provider</th><th>Entitlement</th><th className="r">OK/Fail</th><th>Last ok</th><th>Last error</th></tr></thead>
          <tbody>{Object.entries(st.data.providers).map(([n, p]) => (
            <tr key={n}><td><b>{n}</b> <span className={`dot ${p.consecutive_failures > 0 ? "bad" : p.ok > 0 ? "good" : "idle"}`} /></td>
              <td className="dim small">{p.entitlement}{p.delay_seconds ? ` · ~${p.delay_seconds / 60}m delay` : ""}</td>
              <td className="r mono">{p.ok}/{p.fail}</td><td className="dim">{ago(p.last_ok)}</td>
              <td className="down small" title={p.last_error ?? ""}>{p.last_error ? p.last_error.slice(0, 48) : ""}</td></tr>))}</tbody></table>
        <div className="note">Broker: <b>{st.data.broker_env}</b> · live trading {st.data.live_trading_enabled ? "ENABLED" : "disabled"} · NY session {st.data.ny.state}{st.data.ny.early_close ? " (early close)" : ""}</div>
        {st.data.demo_mode && <div className="note warn">DEMO MODE: all prices are synthetic.</div>}
      </>}
    </Panel>
  );
}

export function UnavailableWidget({ view, title }: { view: string; title?: string }) {
  const v = useQuery({ queryKey: ["views"], queryFn: api.views, staleTime: Infinity });
  const m = v.data?.[view];
  return (
    <Panel title={(title ?? view).toUpperCase()} right={<Badge status="UNAVAILABLE" title="Feature not built yet" />}>
      <div className="unavail">
        <div className="big">Not built yet{m?.phase ? ` · roadmap Phase ${m.phase}` : ""}</div>
        <div>{m?.description ?? view}</div>
        <div className="dim">No placeholder data is shown. See docs/roadmap.md and docs/implementation-status.md.</div>
      </div>
    </Panel>
  );
}

export function YieldsWidget() {
  const every = useStore((s) => s.updateSeconds) * 1000;
  const ids = ["MACRO:FRED:DGS10", "MACRO:FRED:DGS2"];
  const q = useQuery({ queryKey: ["quotes", ids.join()], queryFn: () => api.quotes(ids), refetchInterval: every * 12 });
  const [a, b] = q.data ?? [];
  const ok = a && b && !("error" in a) && !("error" in b);
  return (
    <Panel title="US TREASURY YIELDS (FRED)" right={ok && <ProvLine prov={a.prov} extra={`obs ${a.prov.event_time?.slice(0, 10)}`} />}>
      {q.isError && <ErrorBox error={q.error} />}
      <table className="tbl"><tbody>
        {[a, b].map((x, i) => x && !("error" in x) ? (
          <tr key={i}><td><b>{i ? "2Y" : "10Y"}</b></td><td className="r mono">{num(x.price, 2)}%</td>
            <td className={`r mono ${dir(x.change)}`}>{x.change !== null ? `${x.change >= 0 ? "+" : ""}${(x.change * 100).toFixed(0)} bp` : "—"}</td></tr>) : null)}
        {ok && <tr><td><b>2s10s</b></td><td className="r mono">{((a.price - b.price) * 100).toFixed(0)} bp</td><td className="dim small">10Y − 2Y, same observation date only if equal</td></tr>}
      </tbody></table>
      <div className="note">Daily series. Observation date lags publication; not real-time.</div>
    </Panel>
  );
}
