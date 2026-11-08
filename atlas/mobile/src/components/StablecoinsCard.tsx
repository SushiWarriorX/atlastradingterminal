import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useStablecoins } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const pc = (x: number | null | undefined) => (x === null || x === undefined ? "n/a" : `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(2)}%`);
const tone = (x: number | null | undefined) => (x === null || x === undefined ? color.dim : x > 0 ? color.up : x < 0 ? color.down : color.text);

/** US-dollar stablecoin supply (DefiLlama): the cash inside crypto. A liquidity gauge, not a price signal. */
export function StablecoinsCard() {
  const q = useStablecoins();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="stablecoins-card">
      <View><Txt variant="h2">Stablecoin supply</Txt><Txt variant="tiny">The cash inside crypto: US-dollar stablecoins in circulation</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load stablecoin supply" testID="stablecoins-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Stablecoin supply unavailable"} testID="stablecoins-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="stablecoins-body">
            <Txt variant="hero">${d.total_billions!.toFixed(1)}B</Txt>
            <Txt variant="tiny">As of {d.date}{d.freshness === "OVERDUE" ? " · overdue" : ""} · {d.peak!.below_peak_pct === 0 ? "at its all-time high" : `${Math.abs(d.peak!.below_peak_pct)}% below its peak of $${d.peak!.total_billions.toFixed(1)}B (${d.peak!.date})`}</Txt>
            <View style={{ gap: 2 }}>{d.changes!.map((c) => <View key={c.label} style={{ flexDirection: "row", justifyContent: "space-between" }}><Txt variant="small">Last {c.label}</Txt><Txt variant="small" c={tone(c.change_pct)}>{pc(c.change_pct)} ({c.change_billions >= 0 ? "+" : "−"}${Math.abs(c.change_billions).toFixed(1)}B)</Txt></View>)}</View>
            <Txt variant="label">Biggest issuers</Txt>
            {d.top!.map((t, i) => (
              <View key={t.symbol}>{i > 0 && <Divider />}
                <View style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: 4, gap: space.md }}>
                  <View style={{ flex: 1 }}><Txt variant="body">{t.symbol}</Txt><Txt variant="tiny">{t.name}</Txt></View>
                  <View style={{ alignItems: "flex-end" }}><Txt variant="body">${t.billions.toFixed(1)}B{t.share_pct !== null ? ` · ${t.share_pct}%` : ""}</Txt><Txt variant="tiny">7d {pc(t.change_7d_pct)} · 30d {pc(t.change_30d_pct)}</Txt></View>
                </View>
              </View>))}
            <Txt variant="tiny">{d.note}</Txt>
            {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: DefiLlama</Txt></Pressable> : null}
          </View>)}
    </GCard>
  );
}
