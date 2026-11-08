import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errText } from "../api";
import { useSelectedId } from "../scope";
import { moneyShort as money } from "../research";
import type { Changes, FundamentalResearch, QualityRow, RevRow, Rule40, Valuation } from "../research";
import { ErrorBox, Panel } from "../ui";

const sym = (id: string) => id.split(":").pop() ?? id;
const pc = (x: number | null | undefined, d = 1) => (x == null ? "n/a" : `${x.toFixed(d)}%`);
const px = (x: number | null | undefined) => (x == null ? "n/a" : `$${x.toFixed(2)}`);
const KIND: Record<string, string> = { under: "pill", within: "pill", over: "pill warn", none: "pill warn" };

function Source({ r }: { r: RevRow }) {
  return r.source.link ? <a href={r.source.link} target="_blank" rel="noreferrer noopener" title={`${r.source.form} filed ${r.source.filed}`}>{r.source.form}</a> : <span>{r.source.form}</span>;
}

function RevTable({ title, rows, annual }: { title: string; rows: RevRow[]; annual: boolean }) {
  if (rows.length === 0) return <div className="small warnc" data-testid={annual ? "fr-annual-empty" : "fr-quarterly-empty"}>{title}: {annual ? "no full fiscal year has been filed yet" : "no quarter is on file"}. Nothing is shown rather than a guess.</div>;
  return (
    <table className="tbl" data-testid={annual ? "fr-annual" : "fr-quarterly"}>
      <thead><tr><th>{title}</th><th className="r">REVENUE</th><th className="r">{annual ? "GROWTH" : "VS YEAR EARLIER"}</th><th>HOW IT IS KNOWN</th><th>FILING</th></tr></thead>
      <tbody>{rows.map((r) => {
        const g = annual ? r.growth_pct : r.yoy_pct; const why = annual ? r.growth_note : r.yoy_note;
        return <tr key={r.period_end}><td className="mono">{r.period_start} to {r.period_end}</td><td className="r mono">{money(r.value)}</td><td className="r mono" title={why ?? ""}>{g == null ? "n/a" : pc(g)}</td><td className="small dim">{r.basis}</td><td className="small"><Source r={r} /></td></tr>;
      })}</tbody>
    </table>);
}

function Revenue({ d }: { d: FundamentalResearch }) {
  const r = d.revenue;
  if (!r) return null;
  if (!r.available) return <div className="note warn">{r.reason}</div>;
  return (
    <div data-testid="fr-revenue">
      <div className="small">
        {r.ttm ? <>Trailing twelve months to <b className="mono">{r.ttm.period_end}</b>: <b className="mono">{money(r.ttm.value)}</b> <span className="dim">({r.ttm.basis})</span> · </> : <span className="warnc">Trailing-twelve-month revenue is not available. </span>}
        growth: <b className="mono">{r.ttm_growth_pct == null ? "n/a" : pc(r.ttm_growth_pct)}</b>{r.ttm_growth_pct == null && r.ttm_growth_note ? <span className="dim"> ({r.ttm_growth_note})</span> : null}
        {r.cagr ? <> · multi-year growth <b className="mono">{pc(r.cagr.value_pct)}</b> a year ({r.cagr.from} to {r.cagr.to}) <span className="dim" title={r.cagr.formula}>?</span></> : null}
        {r.trend && r.trend.label !== "unknown" ? <> · <span className="pill" title={r.trend.rule}>{r.trend.label}</span> <span className="dim">({pc(r.trend.latest_yoy_pct)} vs earlier average {pc(r.trend.earlier_average_pct)})</span></> : null}
      </div>
      <RevTable title="FIVE FISCAL YEARS" rows={r.annual ?? []} annual />
      <RevTable title="EIGHT QUARTERS" rows={r.quarterly ?? []} annual={false} />
      {(r.per_share ?? []).some((p) => p.revenue_per_diluted_share != null) && (
        <div className="small">Revenue per diluted share: {(r.per_share ?? []).filter((p) => p.revenue_per_diluted_share != null).map((p) => `${p.period_end.slice(0, 4)}: $${p.revenue_per_diluted_share!.toFixed(2)}`).join(" · ")}
          {r.share_count_change ? <> · diluted shares {r.share_count_change.change_pct >= 0 ? "+" : ""}{pc(r.share_count_change.change_pct)} ({r.share_count_change.from} to {r.share_count_change.to})</> : null}</div>)}
      {(r.missing ?? []).length > 0 && <div className="small warnc" data-testid="fr-missing">Missing, not guessed: {(r.missing ?? []).join("; ")}.</div>}
      <div className="small dim">Latest period {r.latest_period_end ?? "n/a"}{r.age_days != null ? ` (${r.age_days} days ago)` : ""}{r.stale ? " · STALE" : ""} · {r.units}. Not in structured SEC data, so not shown (read the filing): {(r.not_in_structured_data ?? []).join("; ")}.</div>
    </div>);
}

function Quality({ d }: { d: FundamentalResearch }) {
  const q = d.quality;
  if (!q) return null;
  if (!q.available) return <div className="note warn">{q.reason}</div>;
  const row = (r: QualityRow) => <tr key={r.key}><td>{r.label}</td><td className="r mono">{r.value == null ? "n/a" : r.unit === "%" ? pc(r.value) : `${r.value.toFixed(2)}x`}</td><td className="small dim">{r.note ?? ""}</td></tr>;
  const b = q.balance;
  return (
    <div data-testid="fr-quality">
      <div className="small dim">{q.basis}</div>
      <table className="tbl"><thead><tr><th>MEASURE</th><th className="r">VALUE</th><th>NOTE</th></tr></thead><tbody>{(q.rows ?? []).map(row)}</tbody></table>
      {b && <div className="small">Cash {money(b.cash?.value)} · long-term debt {money(b.debt?.value)} · net cash {money(b.net_cash)} <span className="dim">({b.note})</span></div>}
      {q.capitalised_software_ttm != null && <div className="small warnc">Capitalised software costs of {money(q.capitalised_software_ttm)} are filed separately and not subtracted from free cash flow above.</div>}
    </div>);
}

function Rule40Panel({ r }: { r: Rule40 | undefined }) {
  if (!r) return null;
  if (!r.applicable) return <div className="note" data-testid="fr-rule40"><b>Rule of 40: Not applicable.</b> {r.reason}</div>;
  const c = r.current; const hist = r.history ?? [];
  return (
    <div data-testid="fr-rule40">
      <div className="small dim">{r.definition}</div>
      {c?.available ? (
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "baseline" }}>
          <span>TTM revenue growth <b className="mono">{pc(c.growth_pct)}</b></span><span>+ TTM free-cash-flow margin <b className="mono">{pc(c.margin_pct)}</b></span>
          <span>= <b className="mono" style={{ fontSize: 20 }}>{c.score!.toFixed(1)}</b> points <span className={c.reaches_40 ? "pill" : "pill warn"}>{c.reaches_40 ? "reaches 40" : "below 40"}</span></span>
        </div>) : <div className="note warn">N/A: {c?.reason ?? r.reason}</div>}
      {c?.available && <div className="small dim">Growth: TTM revenue {money(c.ttm_revenue)} vs {money(c.ttm_revenue_previous)} a year earlier. Margin: (operating cash flow {money(c.ttm_operating_cash_flow)} - capital expenditures {money(c.ttm_capital_expenditures)}) / revenue.</div>}
      {hist.length > 1 && <div className="small">Trend of the score by quarter end: {hist.map((h) => `${h.end.slice(0, 7)}: ${h.score.toFixed(0)}`).join(" · ")}</div>}
      {r.ebitda_variant?.available && <div className="small" data-testid="fr-rule40-ebitda"><b>Separate measure, not the default:</b> Rule of 40 (EBITDA basis) = {pc(r.ebitda_variant.growth_pct)} + {pc(r.ebitda_variant.margin_pct)} = {r.ebitda_variant.score!.toFixed(1)}. It is never substituted for the free-cash-flow score above.</div>}
      {r.capitalised_software_note && <div className="small warnc">{r.capitalised_software_note}</div>}
      <div className="small dim">{r.peers?.reason}</div>
      <div className="small dim">{r.caveat}</div>
    </div>);
}

function ValuationPanel({ v, policy, setPolicy }: { v: Valuation | undefined; policy: Record<string, string>; setPolicy: (p: Record<string, string>) => void }) {
  if (!v) return null;
  const sc = v.scenarios ?? [];
  return (
    <div data-testid="fr-valuation">
      <div><span className={KIND[v.label_key] ?? "pill"} style={{ fontSize: 14 }} data-testid="fr-label">{v.label}</span> <span className="small dim">evidence quality: <b>{v.evidence.level}</b></span></div>
      <div className="small">{v.reason}</div>
      {(v.warnings ?? []).map((w, i) => <div key={i} className="small warnc" data-testid="fr-warning">⚠ {w}</div>)}
      {v.evidence.checks.some((c) => c.essential && !c.ok && !(v.warnings ?? []).includes(c.text)) && <div className="small" data-testid="fr-limits"><b>Why the evidence is limited:</b>{v.evidence.checks.filter((c) => c.essential && !c.ok && !(v.warnings ?? []).includes(c.text)).map((c) => <div key={c.key} className="warnc">• {c.text}</div>)}</div>}
      <div className="small dim">Price {px(v.price)} {v.price_time ? `at ${v.price_time.slice(0, 16).replace("T", " ")} UTC` : ""} · {v.price_source ?? "no price source"}. {v.caveat}</div>
      {sc.length > 0 && <>
        <table className="tbl" data-testid="fr-scenarios"><thead><tr><th>SCENARIO</th><th className="r">FAIR VALUE / SHARE</th><th className="r">VS PRICE</th><th className="r">START GROWTH</th><th className="r">FCF MARGIN (START to END)</th><th className="r">DISCOUNT</th><th className="r">TERMINAL</th><th className="r">DILUTION / YR</th></tr></thead>
          <tbody>{sc.map((s) => <tr key={s.name}><td><b>{s.name}</b></td><td className="r mono">{px(s.fair_value_per_share)}</td><td className="r mono">{s.upside_pct >= 0 ? "+" : ""}{pc(s.upside_pct)}</td><td className="r mono">{pc(s.assumptions.start_growth_pct)}</td>
            <td className="r mono">{pc(s.assumptions.fcf_margin_start_pct)} to {pc(s.assumptions.fcf_margin_end_pct)}</td><td className="r mono">{pc(s.assumptions.discount_rate_pct)}</td><td className="r mono">{pc(s.assumptions.terminal_growth_pct)}</td><td className="r mono">{pc(s.assumptions.annual_dilution_pct)}</td></tr>)}</tbody></table>
        <div className="small dim">Over {sc[0].assumptions.years} years, growth fading linearly to the terminal rate; free cash flow discounted; debt and cash adjust the equity value; value per share uses today's diluted shares grown by the dilution rate. Terminal value is {pc(sc[1]?.terminal_share_of_ev_pct, 0)} of the base-case enterprise value.</div>
      </>}
      {v.reverse_dcf && <div className="small" data-testid="fr-reverse">{v.reverse_dcf.available ? <><b>What the price implies:</b> starting growth of about <b className="mono">{pc(v.reverse_dcf.implied_growth_pct)}</b> a year (reported trailing growth {pc(v.reverse_dcf.reported_ttm_growth_pct)}; difference {v.reverse_dcf.difference_pp! >= 0 ? "+" : ""}{v.reverse_dcf.difference_pp!.toFixed(1)} points). <span className="dim">{v.reverse_dcf.reading}</span></> : <span className="warnc">{v.reverse_dcf.reason}</span>}</div>}
      {v.methods?.dcf && !v.methods.dcf.available && v.methods.dcf.reason !== v.reason && !(v.reason ?? "").includes(v.methods.dcf.reason ?? "~") && <div className="small warnc">{v.methods.dcf.reason}</div>}
      {(v.multiples ?? []).length > 0 && <table className="tbl" data-testid="fr-multiples"><thead><tr><th>MEASURE</th><th className="r">VALUE</th><th>BASIS / WHY NOT SHOWN</th></tr></thead><tbody>{(v.multiples ?? []).map((m) => <tr key={m.key}><td>{m.label}</td><td className="r mono">{m.value == null ? "n/a" : m.key.endsWith("pct") ? pc(m.value) : m.key.startsWith("market") || m.key === "enterprise_value" ? money(m.value) : `${m.value.toFixed(2)}x`}</td><td className="small dim">{m.value == null ? m.note : m.basis}</td></tr>)}</tbody></table>}
      {v.sensitivity && <details><summary className="small">Sensitivity: base-case fair value per share by discount rate and starting growth</summary>
        <table className="tbl"><thead><tr><th>{v.sensitivity.rows} \ {v.sensitivity.cols}</th>{v.sensitivity.growths.map((g) => <th key={g} className="r">{g.toFixed(1)}%</th>)}</tr></thead>
          <tbody>{v.sensitivity.values.map((row, i) => <tr key={i}><td className="mono">{v.sensitivity!.discount_rates[i].toFixed(1)}%</td>{row.map((x, j) => <td key={j} className="r mono">{px(x)}</td>)}</tr>)}</tbody></table>
        <div className="small dim">Most influential inputs (swing in base value): {(v.influence ?? []).map((i) => `${i.input}: ${px(i.swing)}`).join(" · ")}</div></details>}
      {(v.invalidators ?? []).length > 0 && <div className="small"><b>What would invalidate this:</b>{(v.invalidators ?? []).map((t, i) => <div key={i}>• {t}</div>)}</div>}
      <details><summary className="small">Evidence quality, classification policy and limits</summary>
        {v.evidence.checks.map((c) => <div key={c.key} className={`small ${c.ok ? "" : "warnc"}`}>{c.ok ? "✓" : "✗"} {c.text}</div>)}
        {v.evidence.limits.map((t, i) => <div key={i} className="small dim">• {t}</div>)}
        {v.classification_rule && <div className="small dim">{v.classification_rule}</div>}
        {v.methods?.peers && <div className="small dim">{v.methods.peers.reason} {v.methods.own_history?.reason}</div>}
      </details>
      <div className="small" style={{ marginTop: 6 }}>Assumptions (configurable, limits enforced): discount rate <input aria-label="Discount rate" className="mono" style={{ width: 52 }} value={policy.discount_rate_pct} onChange={(e) => setPolicy({ ...policy, discount_rate_pct: e.target.value })} />% ·
        terminal growth <input aria-label="Terminal growth" className="mono" style={{ width: 44 }} value={policy.terminal_growth_pct} onChange={(e) => setPolicy({ ...policy, terminal_growth_pct: e.target.value })} />% · fair-value band ±<input aria-label="Band" className="mono" style={{ width: 44 }} value={policy.band_pct} onChange={(e) => setPolicy({ ...policy, band_pct: e.target.value })} />%
        <span className="dim"> (allowed: discount 6 to 20, terminal 0 to 4, band 5 to 50)</span></div>
    </div>);
}

function Mine({ sym, d }: { sym: string; d: FundamentalResearch }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["fundresearch", sym] });
  const add = useMutation({ mutationFn: () => api.researchNoteAdd(sym, text), onSuccess: () => { setText(""); setErr(null); refresh(); }, onError: (e) => setErr(errText(e)) });
  const del = useMutation({ mutationFn: (id: number) => api.researchNoteDelete(id), onSuccess: refresh, onError: (e) => setErr(errText(e)) });
  const review = useMutation({ mutationFn: () => api.researchReview(sym), onSuccess: () => { setErr(null); refresh(); qc.invalidateQueries({ queryKey: ["fundchanges", sym] }); }, onError: (e) => setErr(errText(e)) });
  const state = useMutation({ mutationFn: (s: [string, boolean]) => api.discoverState(sym, s[0], s[1]), onSuccess: refresh, onError: (e) => setErr(errText(e)) });
  const ch = useQuery({ queryKey: ["fundchanges", sym], queryFn: () => api.researchChanges(sym), retry: 0, staleTime: 60_000 });
  const m = d.my_state; const saved = !!m?.state.saved_at;
  return (
    <div data-testid="fr-mine">
      <div className="small">
        <button className="mini on" disabled={!d.available || review.isPending} onClick={() => review.mutate()} data-testid="fr-review">mark as reviewed now</button>{" "}
        <button className="mini" onClick={() => state.mutate(["saved", !saved])} data-testid="fr-save">{saved ? "saved · remove" : "save to my research list"}</button>{" "}
        <button className="mini" onClick={() => state.mutate(["dismissed", true])}>dismiss (don't suggest again)</button>
        {m?.last_review && <span className="dim"> · last reviewed {m.last_review.reviewed_at.slice(0, 10)}</span>}
      </div>
      {ch.data && <ChangesView c={ch.data} />}
      <div style={{ marginTop: 6 }}>
        <textarea aria-label="Research note" value={text} onChange={(e) => setText(e.target.value)} placeholder="A note for yourself: what you checked, what you still doubt…" rows={2} style={{ width: "100%" }} />
        <button className="mini on" disabled={!text.trim() || add.isPending} onClick={() => add.mutate()} data-testid="fr-note-add">add note</button>
      </div>
      {(m?.notes ?? []).map((n) => <div key={n.id} className="small" data-testid="fr-note">• {n.body} <span className="dim">({n.created_at.slice(0, 10)})</span> <button className="mini" onClick={() => del.mutate(n.id)}>delete</button></div>)}
      {err && <div className="small warnc">{err}</div>}
    </div>);
}

function ChangesView({ c }: { c: Changes }) {
  if (!c.available && !c.has_review) return <div className="small dim">Changes since your last review: {c.reason ?? "nothing to compare yet."}</div>;
  if (!c.has_review) return <div className="small dim">{c.note}</div>;
  if (!c.changed) return <div className="small dim">Changes since your last review: {c.reason ?? "not available right now."}</div>;
  return (
    <div className="small" data-testid="fr-changes"><b>Changes since you last reviewed ({c.reviewed_at?.slice(0, 10)}):</b>{" "}
      {c.changed.length === 0 ? "nothing in the tracked figures has changed." : c.changed.map((r) => `${r.label}: ${String(r.before ?? "n/a")} → ${String(r.after ?? "n/a")}`).join(" · ")}</div>);
}

/** Revenue-first fundamental research for the selected stock, from SEC filings: revenue, quality, Rule of 40, valuation under stated assumptions, thesis questions, my notes and review. Not advice. */
export function FundamentalResearchWidget() {
  const id = useSelectedId();
  const s = sym(id);
  const [policy, setPolicy] = useState<Record<string, string>>({ discount_rate_pct: "10", terminal_growth_pct: "2.5", band_pct: "20" });
  const [applied, setApplied] = useState(policy);
  const q = useQuery({ queryKey: ["fundresearch", s, applied], queryFn: () => api.fundamentalResearch(s, Object.fromEntries(Object.entries(applied).map(([k, v]) => [k, Number(v)]))), staleTime: 10 * 60_000, retry: 0 });
  const d = q.data;
  return (
    <Panel title={`FUNDAMENTAL RESEARCH ${s} · revenue first, from SEC filings`} right={d?.company?.name ? <span className="dim small">{d.company.name}</span> : null}>
      {q.isLoading && <div className="note">Reading filings…</div>}
      {q.isError && <ErrorBox error={q.error} />}
      {d && <div data-testid="fundamental-research">
        {!d.available ? <div className="note warn" data-testid="fr-unavailable">{d.reason}</div> : <>
          {d.company?.special_sector_note && <div className="note warn">This company is a {d.company.special_sector_note}.</div>}
          {d.errors.map((e, i) => <div key={i} className="small warnc">{e}</div>)}
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>REVENUE · reported, derived and calculated figures are labelled</span></div>
          <Revenue d={d} />
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>REVENUE QUALITY · margins, cash, dilution and balance sheet</span></div>
          <Quality d={d} />
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>RULE OF 40 · software companies only</span></div>
          <Rule40Panel r={d.rule_of_40} />
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>VALUATION · what today's price implies under stated assumptions</span></div>
          <ValuationPanel v={d.valuation} policy={policy} setPolicy={setPolicy} />
          <button className="mini" onClick={() => setApplied(policy)} data-testid="fr-apply">apply assumptions</button>
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>THESIS · built from the figures above, not from opinion</span></div>
          <div data-testid="fr-thesis">
            <div className="small"><b>What needs to be true for this investment thesis to work?</b>{d.thesis?.what_must_be_true.map((t, i) => <div key={i}>• {t}</div>)}</div>
            <div className="small"><b>What evidence would disprove it?</b>{d.thesis?.what_would_disprove_it.map((t, i) => <div key={i}>• {t}</div>)}</div>
            <div className="small"><b>What should I research next?</b>{d.thesis?.research_next.map((t, i) => <div key={i}>• {t}</div>)}</div>
          </div>
          <div className="ws-bar" style={{ paddingLeft: 0 }}><span>MY NOTES AND REVIEW</span></div>
          <Mine sym={s} d={d} />
          <details><summary className="small">Data coverage and limits</summary>
            <div className="small"><b>Covered:</b>{d.coverage?.covered.map((t, i) => <div key={i}>• {t}</div>)}</div>
            <div className="small"><b>Not covered:</b>{d.coverage?.not_covered.map((t, i) => <div key={i}>• {t}</div>)}</div>
            <div className="small dim">Source: {d.sources?.filings?.source} ({d.sources?.filings?.origin}, fetched {d.sources?.filings?.fetched_at?.slice(0, 16).replace("T", " ")} UTC).</div></details>
        </>}
      </div>}
    </Panel>);
}
