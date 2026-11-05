import React, { useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import type { Asset, DiscoverPick } from "../api/types";
import { idsOf } from "../lib/watchlist";
import { useAddToWatchlist, useDiscover, useRemoveFromWatchlist, useWatchlist } from "../state/queries";
import { useOpenAsset } from "../state/selection";
import { color, radius, space } from "../theme";
import { ScreenHeader } from "./ScreenHeader";
import { Banner, Divider, ErrorState, GCard, PrimaryButton, Skeleton, Tag, TextButton, Txt } from "./ui";

const FACTOR: Record<string, string> = { growth: "Growth", profitability: "Profitability", momentum: "Momentum", valuation: "Valuation", balance_sheet: "Balance sheet", liquidity: "Liquidity" };
const num = (v: number | null, u: string) => (v === null ? "n/a" : `${v.toFixed(1)}${u === "%" ? "%" : u === "x" ? "x" : ""}`);

function Card({ p, saved, onToggle, onOpen }: { p: DiscoverPick; saved: boolean; onToggle: () => void; onOpen: () => void }) {
  const [more, setMore] = useState(false);
  return (
    <GCard style={{ padding: space.lg, gap: space.sm }} testID={`pick-${p.symbol}`}>
      <Pressable onPress={onOpen} accessibilityRole="button" style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <View style={{ flex: 1 }}><Txt variant="h2">#{p.rank} {p.symbol}</Txt><Txt variant="tiny">{p.name} · {p.sector}</Txt></View>
        <View style={{ alignItems: "flex-end" }}><Txt variant="h2" c={p.score >= 80 ? color.up : p.score >= 65 ? color.accent3 : color.warn} style={{ fontSize: 26 }}>{p.score.toFixed(0)}<Txt variant="tiny">/100</Txt></Txt><Txt variant="tiny">{p.coverage} of {p.of} factors</Txt></View>
      </Pressable>
      <Txt variant="label">Why it ranks well</Txt>
      {p.reasons.map((r, i) => <Txt key={i} variant="small">• {r}</Txt>)}
      <Txt variant="label">Risks to weigh</Txt>
      {p.risks.map((r, i) => <Txt key={i} variant="small" c={color.warn}>• {r}</Txt>)}
      {more && (
        <View style={{ gap: 4 }}>
          <Txt variant="label">Evidence</Txt>
          {p.evidence.map((e) => <View key={e.label}><View style={{ flexDirection: "row", justifyContent: "space-between" }}><Txt variant="small">{e.label}</Txt><Txt variant="body">{num(e.value, e.unit)}</Txt></View><Txt variant="tiny">{e.source} · as of {e.as_of}</Txt></View>)}
          <Txt variant="label" style={{ marginTop: 6 }}>Score breakdown</Txt>
          <Txt variant="small">{Object.entries(FACTOR).map(([k, l]) => `${l} ${p.factors[k] ? p.factors[k]!.score.toFixed(0) : "n/a"}`).join(" · ")}</Txt>
        </View>)}
      <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
        <TextButton label={more ? "Hide evidence" : "Show evidence"} onPress={() => setMore(!more)} testID={`pick-more-${p.symbol}`} />
        <TextButton label={saved ? "On your watchlist · remove" : "Add to watchlist"} onPress={onToggle} testID={`pick-save-${p.symbol}`} />
      </View>
    </GCard>
  );
}

/** Today's five stocks to research, with reasons, risks, evidence and dates. Rule-based and the same every day; not advice. */
export function DiscoverView() {
  const q = useDiscover();
  const wl = useWatchlist();
  const add = useAddToWatchlist();
  const remove = useRemoveFromWatchlist();
  const open = useOpenAsset();
  const [how, setHow] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const saved = new Set(idsOf(wl.data));
  const d = q.data;
  const toggle = (p: DiscoverPick) => {
    setErr(null);
    const a: Asset = { id: p.asset_id, symbol: p.symbol, name: p.name ?? p.symbol, type: "stock", venue: p.asset_id.split(":")[1] ?? "US", support: "supported", note: null } as Asset;
    const onError = (e: Error) => setErr(e.message);
    if (saved.has(p.asset_id)) remove.mutate(p.asset_id, { onError }); else add.mutate(a, { onError });
  };
  return (
    <View style={{ flex: 1, backgroundColor: color.bg }}>
      <ScreenHeader title="Discover" subtitle={d ? `Scan of ${d.asof}` : undefined} />
      {q.isLoading ? <View style={{ padding: space.lg, gap: space.lg }} testID="discover-loading"><Txt variant="small">Scanning the universe and reading filings. The first scan of the day takes about 20 seconds.</Txt>{[0, 1, 2].map((i) => <Skeleton key={i} h={90} r={16} />)}</View>
        : q.isError || !d ? <ErrorState testID="discover-error" title="Can't load the shortlist" body={q.error instanceof Error ? q.error.message : "Something went wrong."} onRetry={() => q.refetch()} />
        : (
          <ScrollView contentContainerStyle={{ padding: space.lg, gap: space.lg, paddingBottom: space.xxl * 2 }} testID="discover-body">
            <Txt variant="small">Five stocks to research today, picked by fixed rules. Not a recommendation, rating or forecast.</Txt>
            {d.demo ? <Banner tone="demo" title="Demo data" testID="discover-demo">Prices and company figures are synthetic.</Banner> : null}
            {d.stale_notice ? <Banner tone="warn" title="Showing the last saved shortlist">{d.stale_notice}</Banner> : null}
            {d.notes.map((n, i) => <Banner key={i} tone="warn" title="Note">{n}</Banner>)}
            {d.shortlist.length === 0 && !d.notes.length ? <Txt variant="small">No stock had enough data to be ranked today.</Txt> : null}
            {d.shortlist.map((p) => <Card key={p.symbol} p={p} saved={saved.has(p.asset_id)} onToggle={() => toggle(p)} onOpen={() => open(p.asset_id)} />)}
            {err ? <Txt variant="small" c={color.down}>{err}</Txt> : null}
            <Txt variant="tiny">{d.universe.name}: {d.universe.size} stocks, {d.universe.priced} priced, {d.universe.liquid} liquid enough, {d.universe.scored} scored. Prices: {d.data.prices} ({d.data.prices_status.toLowerCase()}). Financials: {d.data.fundamentals}.</Txt>
            <TextButton label={how ? "Hide how this works" : "How this works"} onPress={() => setHow(!how)} testID="discover-how" />
            {how && (
              <View style={{ gap: space.sm }} testID="discover-method">
                {d.method.steps.map((s, i) => <Txt key={i} variant="small">{i + 1}. {s}</Txt>)}
                <Divider />
                {Object.entries(d.method.weights).map(([k, w]) => <View key={k}><Txt variant="body">{FACTOR[k]} · {Math.round(w * 100)}%</Txt><Txt variant="tiny">{d.method.scales[k]}</Txt></View>)}
                <Txt variant="tiny">{d.method.note}</Txt>
              </View>)}
            <Txt variant="tiny"><Txt variant="tiny" c={color.warn}>Not included: </Txt>{d.gaps.join(" ")}</Txt>
          </ScrollView>)}
    </View>
  );
}
