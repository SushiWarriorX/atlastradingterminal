import React, { useState } from "react";
import { Linking, Pressable, TextInput, View } from "react-native";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { FundamentalResearch, RevRow } from "../api/types";
import { safeUrl } from "../lib/links";
import { moneyShort as money } from "../lib/money";
import { useConnection } from "../state/connection";
import { useFundamentalResearch, useResearchChanges } from "../state/queries";
import { color, radius, space } from "../theme";
import { Banner, Divider, GCard, Pill, Skeleton, TextButton, Txt } from "./ui";

const pc = (x: number | null | undefined, d = 1) => (x == null ? "n/a" : `${x.toFixed(d)}%`);
const px = (x: number | null | undefined) => (x == null ? "n/a" : `$${x.toFixed(2)}`);

function Block({ title, children, testID }: { title: string; children: React.ReactNode; testID?: string }) {
  return <View style={{ gap: 6 }} testID={testID}><Txt variant="label">{title}</Txt>{children}</View>;
}

function Rows({ rows, annual }: { rows: RevRow[]; annual: boolean }) {
  if (rows.length === 0) return <Txt variant="small" c={color.warn} testID={annual ? "fr-annual-empty" : "fr-quarterly-empty"}>{annual ? "No full fiscal year has been filed yet" : "No quarter is on file"}. Nothing is shown rather than a guess.</Txt>;
  return (
    <View>
      {rows.map((r, i) => {
        const g = annual ? r.growth_pct : r.yoy_pct;
        const link = safeUrl(r.source.link);
        return (
          <View key={r.period_end}>{i > 0 ? <Divider /> : null}
            <View style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: 6 }}>
              <View style={{ flex: 1 }}><Txt variant="small">{annual ? `FY ${r.period_end.slice(0, 4)}` : r.period_end}</Txt><Txt variant="tiny">{r.basis}</Txt></View>
              <View style={{ alignItems: "flex-end" }}><Txt variant="body">{money(r.value)}</Txt><Txt variant="tiny">{g == null ? "growth n/a" : `${g >= 0 ? "+" : ""}${g.toFixed(1)}% ${annual ? "" : "vs year earlier"}`}</Txt>
                {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>{r.source.form}</Txt></Pressable> : <Txt variant="tiny">{r.source.form}</Txt>}</View>
            </View></View>);
      })}
    </View>);
}

function Mine({ symbol, d }: { symbol: string; d: FundamentalResearch }) {
  const { api } = useConnection();
  const qc = useQueryClient();
  const ch = useResearchChanges(symbol, d.available);
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["fundResearch"] }); qc.invalidateQueries({ queryKey: ["fundChanges"] }); };
  const onError = (e: Error) => setErr(e.message);
  const add = useMutation({ mutationFn: () => api!.researchNoteAdd(symbol, text), onSuccess: () => { setText(""); setErr(null); refresh(); }, onError });
  const del = useMutation({ mutationFn: (id: number) => api!.researchNoteDelete(id), onSuccess: refresh, onError });
  const review = useMutation({ mutationFn: () => api!.researchReview(symbol), onSuccess: () => { setErr(null); refresh(); }, onError });
  const state = useMutation({ mutationFn: (s: [string, boolean]) => api!.discoverState(symbol, s[0], s[1]), onSuccess: refresh, onError });
  const m = d.my_state; const saved = !!m?.state.saved_at;
  const c = ch.data;
  return (
    <View style={{ gap: space.sm }} testID="fr-mine">
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: space.sm }}>
        <TextButton solid label="Mark as reviewed now" onPress={() => review.mutate()} disabled={!d.available || review.isPending} testID="fr-review" />
        <TextButton label={saved ? "Saved · remove" : "Save to my research list"} onPress={() => state.mutate(["saved", !saved])} testID="fr-save" />
        <TextButton label="Dismiss" onPress={() => state.mutate(["dismissed", true])} testID="fr-dismiss" />
      </View>
      {m?.last_review ? <Txt variant="tiny">Last reviewed {m.last_review.reviewed_at.slice(0, 10)}</Txt> : null}
      {c ? (c.has_review && c.changed ? <Txt variant="small" testID="fr-changes">Changes since you last reviewed ({c.reviewed_at?.slice(0, 10)}): {c.changed.length === 0 ? "nothing in the tracked figures has changed." : c.changed.map((r) => `${r.label}: ${String(r.before ?? "n/a")} → ${String(r.after ?? "n/a")}`).join(" · ")}</Txt>
        : <Txt variant="tiny">{c.note ?? c.reason ?? "Nothing to compare with yet."}</Txt>) : null}
      <TextInput value={text} onChangeText={setText} placeholder="A note for yourself: what you checked, what you still doubt…" placeholderTextColor={color.faint} multiline accessibilityLabel="Research note" testID="fr-note-input"
        style={{ minHeight: 56, borderRadius: radius.md, padding: space.md, color: color.text, backgroundColor: "rgba(255,255,255,0.06)" }} />
      <TextButton label="Add note" onPress={() => add.mutate()} disabled={!text.trim() || add.isPending} testID="fr-note-add" />
      {(m?.notes ?? []).map((n) => <View key={n.id} style={{ flexDirection: "row", justifyContent: "space-between", gap: space.sm }} testID="fr-note"><Txt variant="small" style={{ flex: 1 }}>• {n.body} ({n.created_at.slice(0, 10)})</Txt><TextButton label="Delete" onPress={() => del.mutate(n.id)} /></View>)}
      {err ? <Txt variant="small" c={color.down}>{err}</Txt> : null}
    </View>);
}

/** Revenue-first fundamental research for a US stock, from SEC filings: revenue, quality, Rule of 40, valuation under stated assumptions, thesis questions, my notes and review. Not advice. */
export function FundamentalResearchCard({ symbol, startOpen = false }: { symbol: string; startOpen?: boolean }) {
  const [shown, setShown] = useState(startOpen);
  const q = useFundamentalResearch(symbol, shown);
  const d = q.data;
  const r = d?.revenue; const v = d?.valuation; const r40 = d?.rule_of_40; const qual = d?.quality;
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="fr-card">
      <Pressable onPress={() => setShown(!shown)} accessibilityRole="button" testID="fr-toggle" style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <View style={{ flex: 1 }}><Txt variant="h2">Fundamental research</Txt><Txt variant="tiny">Revenue first, from SEC filings: quality, Rule of 40, valuation, thesis, my notes</Txt></View>
        <Pill label={shown ? "Hide" : "Show"} />
      </Pressable>
      {shown && (q.isLoading ? <View style={{ gap: space.md }}>{[0, 1, 2].map((i) => <Skeleton key={i} h={36} />)}</View>
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the research" testID="fr-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Research unavailable"} testID="fr-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.lg }} testID="fr-body">
            {d.company?.special_sector_note ? <Banner tone="warn" title="Sector-specific company">This company is a {d.company.special_sector_note}.</Banner> : null}
            {d.errors.map((e, i) => <Txt key={i} variant="tiny" c={color.warn}>{e}</Txt>)}
            <Block title="Revenue (reported, derived and calculated figures are labelled)" testID="fr-revenue">
              {!r?.available ? <Txt variant="small" c={color.warn}>{r?.reason}</Txt> : (
                <View style={{ gap: 6 }}>
                  <Txt variant="small">{r.ttm ? `Trailing twelve months to ${r.ttm.period_end}: ${money(r.ttm.value)} (${r.ttm.basis})` : "Trailing-twelve-month revenue is not available."} · growth {r.ttm_growth_pct == null ? `n/a${r.ttm_growth_note ? ` (${r.ttm_growth_note})` : ""}` : pc(r.ttm_growth_pct)}
                    {r.cagr ? ` · multi-year growth ${pc(r.cagr.value_pct)} a year (${r.cagr.from} to ${r.cagr.to})` : ""}{r.trend && r.trend.label !== "unknown" ? ` · growth is ${r.trend.label} (${pc(r.trend.latest_yoy_pct)} vs earlier average ${pc(r.trend.earlier_average_pct)})` : ""}</Txt>
                  <Txt variant="label">Five fiscal years</Txt><Rows rows={r.annual ?? []} annual />
                  <Txt variant="label">Eight quarters</Txt><Rows rows={r.quarterly ?? []} annual={false} />
                  {(r.per_share ?? []).some((p) => p.revenue_per_diluted_share != null) ? <Txt variant="tiny">Revenue per diluted share: {(r.per_share ?? []).filter((p) => p.revenue_per_diluted_share != null).map((p) => `${p.period_end.slice(0, 4)}: $${p.revenue_per_diluted_share!.toFixed(2)}`).join(" · ")}{r.share_count_change ? ` · diluted shares ${r.share_count_change.change_pct >= 0 ? "+" : ""}${pc(r.share_count_change.change_pct)} (${r.share_count_change.from} to ${r.share_count_change.to})` : ""}</Txt> : null}
                  {(r.missing ?? []).length ? <Txt variant="small" c={color.warn} testID="fr-missing">Missing, not guessed: {(r.missing ?? []).join("; ")}.</Txt> : null}
                  <Txt variant="tiny">Latest period {r.latest_period_end ?? "n/a"}{r.age_days != null ? ` (${r.age_days} days ago)` : ""}{r.stale ? " · STALE" : ""} · {r.units}. Not in structured SEC data, so not shown (read the filing): {(r.not_in_structured_data ?? []).join("; ")}.</Txt>
                </View>)}
            </Block>
            <Block title="Revenue quality" testID="fr-quality">
              {!qual?.available ? <Txt variant="small" c={color.warn}>{qual?.reason}</Txt> : (
                <View>
                  <Txt variant="tiny">{qual.basis}</Txt>
                  {(qual.rows ?? []).map((row, i) => <View key={row.key}>{i > 0 ? <Divider /> : null}<View style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: 5 }}><View style={{ flex: 1 }}><Txt variant="small">{row.label}</Txt>{row.note ? <Txt variant="tiny">{row.note}</Txt> : null}</View><Txt variant="body">{row.value == null ? "n/a" : row.unit === "%" ? pc(row.value) : `${row.value.toFixed(2)}x`}</Txt></View></View>)}
                  {qual.balance ? <Txt variant="tiny">Cash {money(qual.balance.cash?.value)} · long-term debt {money(qual.balance.debt?.value)} · net cash {money(qual.balance.net_cash)}. {qual.balance.note}</Txt> : null}
                </View>)}
            </Block>
            <Block title="Rule of 40 (software companies only)" testID="fr-rule40">
              {!r40 ? null : !r40.applicable ? <Txt variant="small"><Txt variant="small" c={color.warn}>Not applicable.</Txt> {r40.reason}</Txt> : (
                <View style={{ gap: 4 }}>
                  <Txt variant="tiny">{r40.definition}</Txt>
                  {r40.current?.available ? <Txt variant="small">TTM revenue growth {pc(r40.current.growth_pct)} + TTM free-cash-flow margin {pc(r40.current.margin_pct)} = <Txt variant="h2">{r40.current.score!.toFixed(1)}</Txt> points · {r40.current.reaches_40 ? "reaches 40" : "below 40"}</Txt>
                    : <Txt variant="small" c={color.warn}>N/A: {r40.current?.reason ?? r40.reason}</Txt>}
                  {r40.ebitda_variant?.available ? <Txt variant="tiny" testID="fr-rule40-ebitda">Separate measure, not the default: Rule of 40 (EBITDA basis) = {pc(r40.ebitda_variant.growth_pct)} + {pc(r40.ebitda_variant.margin_pct)} = {r40.ebitda_variant.score!.toFixed(1)}. It never replaces the free-cash-flow score.</Txt> : null}
                  {(r40.history ?? []).length > 1 ? <Txt variant="tiny">Score by quarter end: {(r40.history ?? []).map((h) => `${h.end.slice(0, 7)}: ${h.score.toFixed(0)}`).join(" · ")}</Txt> : null}
                  {r40.capitalised_software_note ? <Txt variant="tiny" c={color.warn}>{r40.capitalised_software_note}</Txt> : null}
                  <Txt variant="tiny">{r40.peers?.reason} {r40.caveat}</Txt>
                </View>)}
            </Block>
            <Block title="Valuation: what today's price implies under stated assumptions" testID="fr-valuation">
              {!v ? null : (
                <View style={{ gap: 5 }}>
                  <Txt variant="h2" testID="fr-label">{v.label}</Txt>
                  <Txt variant="small">{v.reason}</Txt>
                  <Txt variant="tiny">Evidence quality: {v.evidence.level}. Price {px(v.price)}{v.price_time ? ` at ${v.price_time.slice(0, 16).replace("T", " ")} UTC` : ""} · {v.price_source ?? "no price source"}.</Txt>
                  {(v.warnings ?? []).map((w, i) => <Txt key={i} variant="small" c={color.warn} testID="fr-warning">⚠ {w}</Txt>)}
                  {v.evidence.checks.filter((c) => c.essential && !c.ok && !(v.warnings ?? []).includes(c.text)).length ? <View testID="fr-limits"><Txt variant="small">Why the evidence is limited:</Txt>{v.evidence.checks.filter((c) => c.essential && !c.ok && !(v.warnings ?? []).includes(c.text)).map((c) => <Txt key={c.key} variant="tiny" c={color.warn}>• {c.text}</Txt>)}</View> : null}
                  {(v.scenarios ?? []).map((s) => (
                    <View key={s.name} testID={`fr-scenario-${s.name}`}>
                      <Txt variant="small">{s.name[0].toUpperCase() + s.name.slice(1)}: {px(s.fair_value_per_share)} per share ({s.upside_pct >= 0 ? "+" : ""}{pc(s.upside_pct)} vs price)</Txt>
                      <Txt variant="tiny">Starting growth {pc(s.assumptions.start_growth_pct)} fading to {pc(s.assumptions.terminal_growth_pct)} over {s.assumptions.years} years · free-cash-flow margin {pc(s.assumptions.fcf_margin_start_pct)} to {pc(s.assumptions.fcf_margin_end_pct)} · discount rate {pc(s.assumptions.discount_rate_pct)} · dilution {pc(s.assumptions.annual_dilution_pct)} a year</Txt>
                    </View>))}
                  {v.reverse_dcf ? <Txt variant="small" testID="fr-reverse">{v.reverse_dcf.available ? `What the price implies: starting growth of about ${pc(v.reverse_dcf.implied_growth_pct)} a year (reported trailing growth ${pc(v.reverse_dcf.reported_ttm_growth_pct)}).` : v.reverse_dcf.reason}</Txt> : null}
                  {v.methods?.dcf && !v.methods.dcf.available && !(v.reason ?? "").includes(v.methods.dcf.reason ?? "~") ? <Txt variant="small" c={color.warn}>{v.methods.dcf.reason}</Txt> : null}
                  {(v.multiples ?? []).map((m) => <Txt key={m.key} variant="tiny">{m.label}: {m.value == null ? `n/a (${m.note})` : m.key.endsWith("pct") ? pc(m.value) : m.key === "market_value" || m.key === "enterprise_value" ? money(m.value) : `${m.value.toFixed(2)}x`}</Txt>)}
                  {(v.invalidators ?? []).length ? <View><Txt variant="small">What would invalidate this:</Txt>{(v.invalidators ?? []).map((t, i) => <Txt key={i} variant="tiny">• {t}</Txt>)}</View> : null}
                  {v.classification_rule ? <Txt variant="tiny">{v.classification_rule}</Txt> : null}
                  <Txt variant="tiny">{v.caveat}</Txt>
                </View>)}
            </Block>
            <Block title="Thesis (built from the figures above, not from opinion)" testID="fr-thesis">
              <Txt variant="small">What needs to be true for this investment thesis to work?</Txt>{d.thesis?.what_must_be_true.map((t, i) => <Txt key={i} variant="tiny">• {t}</Txt>)}
              <Txt variant="small">What evidence would disprove it?</Txt>{d.thesis?.what_would_disprove_it.map((t, i) => <Txt key={i} variant="tiny">• {t}</Txt>)}
              <Txt variant="small">What should I research next?</Txt>{d.thesis?.research_next.map((t, i) => <Txt key={i} variant="tiny">• {t}</Txt>)}
            </Block>
            <Block title="My notes and review"><Mine symbol={symbol} d={d} /></Block>
            <Txt variant="tiny">Covered: {d.coverage?.covered.join("; ")}. Not covered: {d.coverage?.not_covered.join("; ")}. Source: {d.sources?.filings?.source}.</Txt>
          </View>))}
    </GCard>
  );
}
