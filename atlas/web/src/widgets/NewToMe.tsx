import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errText } from "../api";
import { moneyShort as money } from "../research";
import type { Candidate } from "../research";
import { useStore } from "../store";
import { ErrorBox, Panel } from "../ui";

const pc = (x: number | null, d = 1) => (x == null ? "n/a" : `${x.toFixed(d)}%`);
const FACT: Record<string, string> = { growth: "Growth", quality: "Revenue quality", resilience: "Resilience", valuation: "Valuation" };
const SECTORS = ["Technology", "Health Care", "Industrials", "Consumer Discretionary", "Consumer Staples", "Energy", "Finance", "Real Estate", "Utilities", "Telecommunications", "Basic Materials"];

function Card({ c, refresh }: { c: Candidate; refresh: () => void }) {
  const select = useStore((s) => s.select);
  const setWorkspace = useStore((s) => s.setWorkspace);
  const [err, setErr] = useState<string | null>(null);
  const st = useMutation({ mutationFn: (s: string) => api.discoverState(c.symbol, s, true), onSuccess: refresh, onError: (e) => setErr(errText(e)) });
  const research = () => { api.discoverState(c.symbol, "opened", true).catch(() => undefined); select(`EQUITY:${c.exchange.toUpperCase()}:${c.symbol}`); setWorkspace("equities"); };
  return (
    <div className="note" data-testid={`cand-${c.symbol}`}>
      <div><b>{c.symbol}</b> <span className="dim">{c.name}</span> <span className="pill">{c.exchange}</span> <span className="pill">{c.sector ?? "unclassified"}</span> <span className="pill">{c.size_bucket} cap {money(c.market_cap)}</span> <span className="pill">score {c.score.toFixed(0)}/100</span>
        {c.why_shown_again && <span className="pill warn">{c.why_shown_again}</span>}</div>
      <div className="small dim">Classification: {c.description.industry ?? "n/a"}{c.description.classification ? ` · SIC ${c.description.classification}` : ""}. {c.description.note}</div>
      <div className="small">Revenue (TTM to {c.revenue.ttm_period_end}): <b className="mono">{money(c.revenue.ttm)}</b> · growth <b className="mono">{pc(c.revenue.growth_pct)}</b> ({c.revenue.trend}) · free-cash-flow margin <b className="mono">{pc(c.revenue.fcf_margin_pct)}</b>
        {c.rule_of_40.applicable ? <> · Rule of 40: <b className="mono">{c.rule_of_40.score == null ? "N/A" : c.rule_of_40.score.toFixed(0)}</b></> : null}</div>
      <div className="small">Valuation under stated assumptions: <b>{c.valuation.label}</b> <span className="dim">(evidence: {c.valuation.evidence})</span> · price {c.price != null ? `$${c.price.toFixed(2)}` : "n/a"} <span className="dim">({c.price_source})</span></div>
      <div className="small"><b>Why it surfaced:</b> {c.why_selected.map((w, i) => <span key={i}>{i ? " · " : ""}{w}</span>)}</div>
      <div className="small"><b>Main opportunity:</b> {c.main_opportunity}. <b>Main risk:</b> <span className="warnc">{c.main_risk}</span></div>
      <div className="small dim">Factors: {Object.entries(FACT).map(([k, l]) => `${l} ${c.factors[k] == null ? "n/a" : c.factors[k]!.toFixed(0)}`).join(" · ")} · filings to {c.revenue.latest_period_end} ({c.revenue.age_days} days ago) · shown {c.state.shown_count}×</div>
      <div><button className="mini on" onClick={research} data-testid={`cand-research-${c.symbol}`}>Research this company</button> <button className="mini" onClick={() => st.mutate("saved")}>save</button> <button className="mini" onClick={() => st.mutate("dismissed")}>dismiss</button></div>
      {err && <div className="small warnc">{err}</div>}
    </div>);
}

/** Companies I have not researched, saved or dismissed, picked from SEC filings by fixed rules: fewer when evidence is weak, varied by sector, filtered by me. Not ratings or advice. */
export function NewToMeWidget() {
  const qc = useQueryClient();
  const [f, setF] = useState({ sector: "", minCap: "300", maxCap: "50000", minVol: "1", country: "", exchange: "", maxAge: "" });
  const qs = new URLSearchParams();
  if (f.sector) qs.set("sectors", f.sector);
  if (f.minCap) qs.set("min_market_cap", String(Number(f.minCap) * 1e6));
  if (f.maxCap) qs.set("max_market_cap", String(Number(f.maxCap) * 1e6));
  if (f.minVol) qs.set("min_dollar_volume", String(Number(f.minVol) * 1e6));
  if (f.country) qs.set("countries", f.country);
  if (f.exchange) qs.set("exchanges", f.exchange);
  if (f.maxAge) qs.set("max_listing_age_years", f.maxAge);
  const key = qs.toString();
  const q = useQuery({ queryKey: ["newtome", key], queryFn: () => api.discoverCandidates(key), staleTime: 5 * 60_000, retry: 0 });
  const d = q.data;
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <Panel title="NEW TO ME · companies you have not researched, with the evidence for each" right={d?.available ? <span className={`pill ${d.stale ? "warn" : ""}`}>{d.stale ? "STALE · " : ""}study of {d.asof}</span> : null}>
      <div className="small" data-testid="newtome-filters">Filters: sector <select aria-label="Sector" value={f.sector} onChange={set("sector")}><option value="">all</option>{SECTORS.map((s) => <option key={s}>{s}</option>)}</select>{" "}
        market value $<input aria-label="Min market value" className="mono" style={{ width: 54 }} value={f.minCap} onChange={set("minCap")} />M to $<input aria-label="Max market value" className="mono" style={{ width: 64 }} value={f.maxCap} onChange={set("maxCap")} />M{" "}
        daily trading ≥ $<input aria-label="Min dollar volume" className="mono" style={{ width: 36 }} value={f.minVol} onChange={set("minVol")} />M · country <input aria-label="Country" style={{ width: 90 }} placeholder="any" value={f.country} onChange={set("country")} />{" "}
        exchange <select aria-label="Exchange" value={f.exchange} onChange={set("exchange")}><option value="">both</option><option>Nasdaq</option><option>NYSE</option></select> · listed within <input aria-label="Max listing age" className="mono" style={{ width: 34 }} placeholder="any" value={f.maxAge} onChange={set("maxAge")} /> years</div>
      {q.isLoading && <div className="note">Loading…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="new-to-me">
        {!d.available ? <div className="note warn" data-testid="newtome-unavailable">{d.reason}</div> : <>
          <div className="small" data-testid="newtome-note">{d.evidence_note}</div>
          {d.items.map((c) => <Card key={c.symbol} c={c} refresh={() => qc.invalidateQueries({ queryKey: ["newtome"] })} />)}
          <details><summary className="small">How this was chosen, what was left out and why</summary>
            {d.study && <div className="small">Universe {d.study.universe} listed companies → {d.study.after_filters} after basic filters → {d.study.studied} studied from filings → {d.study.passed} passed the evidence gate. Left out: {Object.entries(d.study.left_out_reasons).map(([k, v]) => `${v}× ${k}`).join("; ") || "none"}. Could not study: {Object.entries(d.study.could_not_study).map(([k, v]) => `${v}× ${k}`).join("; ") || "none"}.</div>}
            {d.excluded_by_my_filters && Object.keys(d.excluded_by_my_filters).length > 0 && <div className="small">Hidden by my filters: {Object.entries(d.excluded_by_my_filters).map(([k, v]) => `${v}× ${k}`).join("; ")}.</div>}
            {(d.hidden_because_seen ?? []).length > 0 && <div className="small">Not repeated: {(d.hidden_because_seen ?? []).map((h) => `${h.symbol} (${h.reason})`).join("; ")}.</div>}
            {d.method && <div className="small dim">Score weights {Object.entries(d.method.weights).map(([k, v]) => `${FACT[k] ?? k} ${v}%`).join(", ")}; minimum score {d.method.min_total}; at most {d.method.max_per_sector} per sector; a company is not shown again for {d.method.cooldown_days} days unless a new quarter is filed or its valuation reading changes. Novelty is not part of the score.</div>}
          </details>
        </>}
        {(d.gaps ?? []).map((g, i) => <div key={i} className="small dim">• {g}</div>)}
      </div>}
    </Panel>);
}
