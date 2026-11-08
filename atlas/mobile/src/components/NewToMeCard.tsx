import React, { useState } from "react";
import { View } from "react-native";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Candidate } from "../api/types";
import { useConnection } from "../state/connection";
import { moneyShort as money } from "../lib/money";
import { useCandidates } from "../state/queries";
import { useOpenAsset } from "../state/selection";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, TextButton, Txt } from "./ui";

const pc = (x: number | null, d = 1) => (x == null ? "n/a" : `${x.toFixed(d)}%`);
const FACT: Record<string, string> = { growth: "Growth", quality: "Revenue quality", resilience: "Resilience", valuation: "Valuation" };
const SECTORS = ["Technology", "Health Care", "Industrials", "Consumer Discretionary", "Finance"];
const SIZES: [string, string, string][] = [["any size", "", ""], ["small $0.3-2B", "300000000", "2000000000"], ["mid $2-10B", "2000000000", "10000000000"], ["large $10-50B", "10000000000", "50000000000"]];

function Card({ c, onOpen, onState }: { c: Candidate; onOpen: (id: string) => void; onState: (s: string) => void }) {
  return (
    <View style={{ gap: 3 }} testID={`cand-${c.symbol}`}>
      <Txt variant="h2">{c.symbol} <Txt variant="small">{c.name}</Txt></Txt>
      <Txt variant="tiny">{c.exchange} · {c.sector ?? "unclassified"} · {c.size_bucket} cap {money(c.market_cap)} · score {c.score.toFixed(0)}/100{c.why_shown_again ? ` · ${c.why_shown_again}` : ""}</Txt>
      <Txt variant="tiny">Classification: {c.description.industry ?? "n/a"}. {c.description.note}</Txt>
      <Txt variant="small">Revenue (TTM to {c.revenue.ttm_period_end}) {money(c.revenue.ttm)} · growth {pc(c.revenue.growth_pct)} ({c.revenue.trend}) · free-cash-flow margin {pc(c.revenue.fcf_margin_pct)}{c.rule_of_40.applicable ? ` · Rule of 40: ${c.rule_of_40.score == null ? "N/A" : c.rule_of_40.score.toFixed(0)}` : ""}</Txt>
      <Txt variant="small">Valuation under stated assumptions: {c.valuation.label} (evidence: {c.valuation.evidence}) · price {c.price != null ? `$${c.price.toFixed(2)}` : "n/a"} ({c.price_source})</Txt>
      <Txt variant="small">Why it surfaced: {c.why_selected.join(" ")}</Txt>
      <Txt variant="small">Main opportunity: {c.main_opportunity}. <Txt variant="small" c={color.warn}>Main risk: {c.main_risk}</Txt></Txt>
      <Txt variant="tiny">Factors: {Object.entries(FACT).map(([k, l]) => `${l} ${c.factors[k] == null ? "n/a" : c.factors[k]!.toFixed(0)}`).join(" · ")} · filings to {c.revenue.latest_period_end} ({c.revenue.age_days} days ago)</Txt>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: space.sm }}>
        <TextButton solid label="Research this company" onPress={() => { onState("opened"); onOpen(`EQUITY:${c.exchange.toUpperCase()}:${c.symbol}`); }} testID={`cand-research-${c.symbol}`} />
        <TextButton label="Save" onPress={() => onState("saved")} testID={`cand-save-${c.symbol}`} />
        <TextButton label="Dismiss" onPress={() => onState("dismissed")} testID={`cand-dismiss-${c.symbol}`} />
      </View>
    </View>);
}

/** Companies I have not researched, saved or dismissed, picked from SEC filings by fixed rules: fewer when evidence is weak, varied by sector, filtered by me. Not ratings or advice. */
export function NewToMeCard() {
  const [sector, setSector] = useState("");
  const [size, setSize] = useState(0);
  const [exchange, setExchange] = useState("");
  const qs = new URLSearchParams();
  qs.set("min_market_cap", SIZES[size][1] || "300000000");
  qs.set("max_market_cap", SIZES[size][2] || "50000000000");
  qs.set("min_dollar_volume", "1000000");
  if (sector) qs.set("sectors", sector);
  if (exchange) qs.set("exchanges", exchange);
  const q = useCandidates(qs.toString());
  const { api } = useConnection();
  const qc = useQueryClient();
  const open = useOpenAsset();
  const state = useMutation({ mutationFn: (v: { symbol: string; state: string }) => api!.discoverState(v.symbol, v.state, true), onSuccess: () => qc.invalidateQueries({ queryKey: ["candidates"] }) });
  const d = q.data;
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="newtome-card">
      <View><Txt variant="h2">New to me</Txt><Txt variant="tiny">Companies you have not researched, with the evidence for each</Txt></View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: space.xs }} testID="newtome-filters">
        <TextButton solid={!sector} label="all sectors" onPress={() => setSector("")} />
        {SECTORS.map((s) => <TextButton key={s} solid={sector === s} label={s} onPress={() => setSector(sector === s ? "" : s)} testID={`filter-sector-${s}`} />)}
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: space.xs }}>
        {SIZES.map(([l], k) => <TextButton key={l} solid={size === k} label={l} onPress={() => setSize(k)} testID={`filter-size-${k}`} />)}
        {["", "Nasdaq", "NYSE"].map((e) => <TextButton key={e || "both"} solid={exchange === e} label={e || "both exchanges"} onPress={() => setExchange(e)} />)}
      </View>
      {q.isLoading ? <Skeleton h={100} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load candidates" testID="newtome-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone="warn" title="No candidates yet" testID="newtome-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.md }} testID="newtome-body">
            <Txt variant="small" testID="newtome-note">{d.evidence_note}{d.stale ? " The study is more than two days old." : ""}</Txt>
            {d.items.map((c, k) => <View key={c.symbol}>{k > 0 ? <Divider /> : null}<Card c={c} onOpen={open} onState={(s) => state.mutate({ symbol: c.symbol, state: s })} /></View>)}
            {d.study ? <Txt variant="tiny">Universe {d.study.universe} → {d.study.after_filters} after basic filters → {d.study.studied} studied from filings → {d.study.passed} passed the evidence gate. Novelty is not part of the score; a company is not shown again for {d.method?.cooldown_days} days unless a new quarter is filed or its valuation reading changes.</Txt> : null}
          </View>)}
      {(d?.gaps ?? []).map((g, k) => <Txt key={k} variant="tiny">• {g}</Txt>)}
    </GCard>
  );
}
