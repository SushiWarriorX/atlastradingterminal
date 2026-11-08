import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { moneyShort as money } from "../research";
import type { ListingItem } from "../research";
import { useStore } from "../store";
import { ErrorBox, Panel } from "../ui";


function Row({ i }: { i: ListingItem }) {
  const select = useStore((s) => s.select);
  const setWorkspace = useStore((s) => s.setWorkspace);
  const tag = i.status === "trading" ? "confirmed trading" : i.status === "priced" ? "priced, not yet confirmed" : i.status === "upcoming" ? "upcoming" : i.status === "upcoming_date_passed" ? "date passed" : i.status;
  return (
    <div className="note" data-testid={`listing-${i.symbol ?? i.deal_id}`}>
      <b>{i.symbol ?? "(no ticker yet)"}</b> <span className="dim">{i.name}</span> <span className="pill">{i.exchange}{i.exchange_text && i.exchange_text !== i.exchange ? ` · ${i.exchange_text}` : ""}</span> <span className="pill">{i.listing_type}</span> <span className={`pill ${i.status === "trading" ? "" : "warn"}`}>{tag}</span>
      <div className="small">{i.status_text}</div>
      {i.listing_type === "SPAC IPO" && <div className="small warnc" data-testid="spac-note">{i.listing_type_note}</div>}
      <div className="small dim">Offer {i.price ?? "n/a"} · {i.shares_offered?.toLocaleString() ?? "n/a"} shares · {money(i.offer_amount)}{i.expected_date ? ` · expected ${i.expected_date}` : ""}{i.priced_date ? ` · priced ${i.priced_date}` : ""}{i.first_trade_date ? ` · first trade ${i.first_trade_date}` : ""}</div>
      {i.verification && <div className="small">{i.verification.verified ? "✓ " : ""}SEC check: {i.verification.note}{i.verification.evidence?.link ? <> <a href={i.verification.evidence.link} target="_blank" rel="noreferrer noopener">open filing</a></> : null}</div>}
      {i.newness && <div className="small dim">{i.newness.reason}</div>}
      {i.symbol && (i.status === "priced" || i.status === "trading") && i.listing_type !== "SPAC IPO" && <button className="mini" onClick={() => { select(`EQUITY:${(i.exchange ?? "NASDAQ").toUpperCase().replace(" ", "")}:${i.symbol}`); setWorkspace("equities"); }}>Research this company</button>}
    </div>);
}

/** Newly listed companies on NYSE and Nasdaq. Upcoming deals and confirmed trading debuts are kept apart; nothing is invented on a quiet day. */
export function ListingsWidget() {
  const [days, setDays] = useState(30);
  const q = useQuery({ queryKey: ["listings", days], queryFn: () => api.discoverListings(days), staleTime: 10 * 60_000, refetchInterval: 30 * 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title="NEW LISTINGS · NYSE and Nasdaq" right={d?.available ? <span className={`pill ${d.stale ? "warn" : ""}`}>{d.stale ? "STALE · " : ""}fetched {d.fetched_at?.slice(0, 16).replace("T", " ")} UTC</span> : null}>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="new-listings">
        {!d.available ? <div className="note warn">{d.reason}</div> : <>
          <div className="small" data-testid="listings-today"><b>Today:</b> {d.today?.text} <span className="dim">· Rolling window: <select aria-label="Window" value={days} onChange={(e) => setDays(Number(e.target.value))}>{[7, 14, 30, 60, 90].map((n) => <option key={n} value={n}>last {n} days</option>)}</select> · confirmed trading {d.counts?.confirmed_trading} · verified by SEC prospectus {d.counts?.verified_by_sec}</span></div>
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>UPCOMING LISTINGS · not trading yet ({d.upcoming.length})</span></div>
          {d.upcoming.length === 0 ? <div className="small dim">No upcoming NYSE or Nasdaq listings are reported.</div> : d.upcoming.map((i) => <Row key={i.deal_id} i={i} />)}
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>RECENT LISTINGS · priced in the last {d.window_days} days ({d.recent.length})</span></div>
          {d.recent.length === 0 ? <div className="small dim">No new listings in this window.</div> : d.recent.map((i) => <Row key={i.deal_id} i={i} />)}
        </>}
        {(d.errors ?? []).map((e, i) => <div key={i} className="small warnc">{e}</div>)}
        <div className="small dim">{d.coverage} Source: {d.source}.</div>
      </div>}
    </Panel>);
}
