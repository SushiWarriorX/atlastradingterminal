import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";
import React, { useMemo, useState } from "react";
import { RefreshControl, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ApiError } from "../api/client";
import type { AgentName, ChartRange } from "../api/types";
import { StockResearchCard } from "./StockResearchCard";
import { WhatIfCard } from "./WhatIfCard";
import { SentimentCard } from "./SentimentCard";
import { PositioningCard } from "./PositioningCard";
import { StablecoinsCard } from "./StablecoinsCard";
import { NetworkCard } from "./NetworkCard";
import { StrategyTrackerCard } from "./StrategyTrackerCard";
import { CryptoMarketCard } from "./CryptoMarketCard";
import { SecFilingsCard } from "./SecFilingsCard";
import { StrategyLabCard } from "./StrategyLabCard";
import { BTC_ID } from "../state/selection";
import { AgentRow } from "./AgentRow";
import { BriefingCard } from "./BriefingCard";
import { FreshnessLine } from "./FreshnessLine";
import { PriceChart, type Scrub } from "./PriceChart";
import { Banner, Chip, ErrorState, IconButton, Skeleton, Tag, TextButton, Txt } from "./ui";
import { AGENT_ORDER } from "../lib/briefing";
import { directionOf, formatPct, formatPrice, localDateTime, providerName, TYPE_LABEL } from "../lib/format";
import { describeFreshness } from "../lib/freshness";
import { useAddToWatchlist, useAsset, useChart, useNow, useRefreshAgent, useRemoveFromWatchlist, useResearch } from "../state/queries";
import { color, dirColor, radius, space } from "../theme";

const RANGES: ChartRange[] = ["1D", "1W", "1M", "3M", "1Y", "5Y"];
/** The research for one asset: identity, price, chart, briefing and the four agents. A full screen on a phone; the centre pane on a wide screen (`embedded`). */
export function AssetView({ id, embedded, hideBack }: { id: string; embedded?: boolean; hideBack?: boolean }) {
  const insets = useSafeAreaInsets();
  const now = useNow(20_000);
  const asset = useAsset(id);
  const [range, setRange] = useState<ChartRange>("1M");
  const chart = useChart(id, range);
  const research = useResearch(id);
  const add = useAddToWatchlist();
  const remove = useRemoveFromWatchlist();
  const refresh = useRefreshAgent(id);
  const [scrub, setScrub] = useState<Scrub | null>(null);
  const [open, setOpen] = useState<Partial<Record<AgentName, boolean>>>({});
  const [msgs, setMsgs] = useState<Partial<Record<AgentName, string>>>({});
  const [refreshing, setRefreshing] = useState<AgentName | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const a = asset.data?.asset ?? research.data?.asset;
  const q = asset.data?.quote ?? null;
  const fresh = describeFreshness(q?.prov, now);
  const saved = !!asset.data?.saved;
  const c = chart.data;
  const rangeDir = directionOf(c?.change_pct ?? q?.change_pct);
  const tint = dirColor(rangeDir) === color.dim ? color.accent : dirColor(rangeDir);
  const demo = !!(research.data?.demo || asset.data?.quote?.prov.status === "DEMO");

  function toggleSave() {
    if (!a) return;
    setSaveError(null);
    const onError = (e: Error) => setSaveError(e.message);
    if (saved) remove.mutate(a.id, { onError }); else add.mutate(a, { onError });
  }
  async function refreshAgent(agent: AgentName) {
    setRefreshing(agent); setMsgs((m) => ({ ...m, [agent]: undefined }));
    try { await refresh.mutateAsync(agent); } catch (e) { setMsgs((m) => ({ ...m, [agent]: e instanceof ApiError ? e.message : "Could not refresh." })); }
    finally { setRefreshing(null); }
  }
  const scrubLabel = useMemo(() => (scrub ? (range === "1D" || range === "1W" ? localDateTime(new Date(scrub.t * 1000).toISOString()) : new Date(scrub.t * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })) : null), [scrub, range]);
  const pullRefresh = () => { asset.refetch(); chart.refetch(); research.refetch(); };

  return (
    <View style={{ flex: 1, backgroundColor: color.bg, paddingTop: embedded ? 0 : (hideBack ? insets.top : insets.top) }}>
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.md, paddingVertical: space.sm }}>
        {embedded || hideBack ? <View style={{ width: 34 }} /> : <IconButton name="chevron-back" size={26} label="Back" onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} testID="back" />}
        <Txt variant="small" testID="asset-bar-symbol">{a?.symbol ?? ""}</Txt>
        <IconButton name={saved ? "star" : "star-outline"} size={24} tint={color.text} label={saved ? "Remove from watchlist" : "Add to watchlist"} onPress={toggleSave} testID="watch-toggle" disabled={!a || add.isPending || remove.isPending} />
      </View>
      <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + space.xxl }} refreshControl={<RefreshControl refreshing={false} onRefresh={pullRefresh} tintColor={color.accent} />} testID="asset-scroll">
        <View style={{ paddingHorizontal: space.lg, gap: space.md }}>
          {demo && <Banner tone="demo" title="Demo data" testID="demo-banner">Everything on this screen is synthetic, for trying the app.</Banner>}
          {saveError && <Banner tone="warn" title="Couldn't save" action={<TextButton label="Dismiss" onPress={() => setSaveError(null)} />}>{saveError}</Banner>}

          {a ? (
            <View>
              <Txt variant="title" numberOfLines={2} testID="asset-name">{a.name}</Txt>
              <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 6, marginTop: 4 }} testID="asset-sub"><Txt variant="small" style={{ fontWeight: "600" }}>{a.symbol}</Txt><Tag label={TYPE_LABEL[a.type]} /><Tag label={a.venue} /></View>
              <Txt variant="tiny" testID="asset-id">{a.id}</Txt>
              {a.support === "unverified" && <Txt variant="tiny" c={color.warn} style={{ marginTop: 2 }}>Unverified listing: {a.note ?? "type and exchange are not confirmed, so some research may not apply."}</Txt>}
            </View>
          ) : asset.isError ? null : <Skeleton w="60%" h={28} />}

          {q ? (
            <View>
              <Txt variant="hero" testID="asset-price">{scrub ? formatPrice(scrub.v) : q.display}</Txt>
              {scrub ? <Txt variant="small">{scrubLabel}</Txt> : (
                <Txt variant="body" c={dirColor(rangeDir)} style={{ fontWeight: "600" }} testID="asset-change">
                  {c ? `${formatPct(c.change_pct)} ${range}` : formatPct(q.change_pct)}{" "}
                  <Txt variant="tiny">{c ? "over the range shown" : `vs ${q.basis}`}</Txt>
                </Txt>
              )}
              <View style={{ marginTop: space.sm }}><FreshnessLine prov={q.prov} now={now} source={providerName(q.prov.provider)} testID="asset-freshness" /></View>
            </View>
          ) : asset.isError ? (
            <Banner tone="warn" title="Couldn't load this asset" testID="asset-error">{asset.error instanceof Error ? asset.error.message : "Something went wrong."}</Banner>
          ) : asset.data && !asset.data.quote ? (
            <Banner tone="warn" title="Price unavailable" testID="price-unavailable">{asset.data.error?.message ?? "No price could be loaded right now."} Research below may still be available.</Banner>
          ) : <Skeleton w="45%" h={40} />}

          {fresh.tone === "stale" && <Banner tone="warn" title="This price is stale" testID="stale-banner">The last update was {fresh.detail.replace("last update ", "")}. Do not treat it as current.</Banner>}
        </View>

        <View style={{ marginTop: space.lg }}>
          {chart.isError ? (
            <View style={{ paddingHorizontal: space.lg }}><ErrorState testID="chart-error" title="Chart unavailable" body={chart.error instanceof Error ? chart.error.message : "Something went wrong."} onRetry={() => chart.refetch()} /></View>
          ) : c ? (
            <View>
              <PriceChart points={c.points} tint={tint} onScrub={setScrub} height={embedded ? 300 : 210} />
              <Txt variant="tiny" style={{ paddingHorizontal: space.lg, marginTop: 4 }} testID="chart-meta">{providerName(c.prov.provider)} · {c.prov.status.toLowerCase()} · {c.interval} bars{c.derived_from ? ` (built from ${c.derived_from})` : ""}</Txt>
            </View>
          ) : <View style={{ height: 210, justifyContent: "center", paddingHorizontal: space.lg }}><Skeleton h={160} r={16} /></View>}
          <View style={{ flexDirection: "row", justifyContent: "space-between", paddingHorizontal: space.md, marginTop: space.sm }} testID="ranges">
            {RANGES.map((r) => <Chip key={r} label={r} active={r === range} onPress={() => { setRange(r); setScrub(null); }} testID={`range-${r}`} />)}
          </View>
        </View>

        <View style={{ paddingHorizontal: space.lg, gap: space.md, marginTop: space.xl }}>
          <BriefingCard research={research.data} loading={research.isLoading} now={now} />
          {research.isError && !research.data ? <Banner tone="warn" title="Research unavailable" testID="research-error" action={<TextButton label="Retry" onPress={() => research.refetch()} />}>{research.error instanceof Error ? research.error.message : "Something went wrong."}</Banner> : null}
          <View style={{ backgroundColor: color.surface, borderRadius: radius.lg, overflow: "hidden" }}>
            {AGENT_ORDER.map((ag, i) => (
              <AgentRow key={ag} first={i === 0} agent={ag} finding={research.data?.findings[ag]} now={now} expanded={!!open[ag]} onToggle={() => setOpen((o) => ({ ...o, [ag]: !o[ag] }))}
                onRefresh={() => refreshAgent(ag)} refreshing={refreshing === ag} refreshMessage={msgs[ag] ?? null} />
            ))}
          </View>
          {a?.type === "stock" ? <SecFilingsCard symbol={a.symbol} /> : null}
          {a?.type === "stock" ? <StockResearchCard symbol={a.symbol} /> : null}
          {a ? <WhatIfCard assetId={a.id} symbol={a.symbol} /> : null}
          {a?.id === BTC_ID ? <SentimentCard /> : null}
          {a?.id === BTC_ID ? <PositioningCard /> : null}
          {a?.id === BTC_ID ? <CryptoMarketCard /> : null}
          {a?.id === BTC_ID ? <StablecoinsCard /> : null}
          {a?.id === BTC_ID ? <NetworkCard /> : null}
          {a?.id === BTC_ID ? <StrategyLabCard /> : null}
          {a?.id === BTC_ID ? <StrategyTrackerCard /> : null}
          <View style={{ flexDirection: "row", gap: space.sm, alignItems: "flex-start", marginTop: space.md }}>
            <Ionicons name="information-circle-outline" size={16} color={color.faint} />
            <Txt variant="tiny" style={{ flex: 1 }}>Research only. Signal cannot place trades, and nothing here is financial advice. Figures are calculated by the server from the sources shown; written explanations only describe them.</Txt>
          </View>
        </View>
      </ScrollView>
    </View>
  );
}
