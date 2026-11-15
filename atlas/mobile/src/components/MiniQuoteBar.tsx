import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { Pressable, View } from "react-native";
import { directionOf, formatPct } from "../lib/format";
import { describeFreshness } from "../lib/freshness";
import { useAsset, useChart, useNow } from "../state/queries";
import { BTC_ID } from "../state/selection";
import { color, dirColor, radius, space } from "../theme";
import { FreshDot } from "./FreshnessLine";
import { Sparkline } from "./Sparkline";
import { Txt } from "./ui";

/** The small floating quote above the tab bar in TradingView's phone app, here for Bitcoin: symbol, price, the change since the basis the server names, a tiny line and a chevron. Tapping it opens Bitcoin. It is left out while there is no usable price, and when the price is stale, rather than showing a number that is not current. */
export function MiniQuoteBar({ onOpen }: { onOpen: () => void }) {
  const now = useNow(20_000);
  const asset = useAsset(BTC_ID);
  const chart = useChart(BTC_ID, "1M");
  const q = asset.data?.quote ?? null;
  if (!q) return null;
  const fresh = describeFreshness(q.prov, now);
  if (fresh.tone === "stale" || fresh.tone === "unavailable") return null;
  const dir = directionOf(q.change_pct);
  const tint = dirColor(dir);
  const spark = chart.data?.points.map((p) => p[1]) ?? null;
  const since = /24h/.test(q.basis) ? "in 24h" : "today";
  return (
    <Pressable onPress={onOpen} accessibilityRole="button" accessibilityLabel={`Bitcoin ${q.display}, ${formatPct(q.change_pct)} ${since}. Open Bitcoin.`} testID="mini-quote"
      style={({ pressed }) => [{ flexDirection: "row", alignItems: "center", gap: space.sm, backgroundColor: color.bg, borderRadius: radius.lg, borderWidth: 1, borderColor: color.border, paddingVertical: 9, paddingHorizontal: space.md, boxShadow: "0 2px 10px rgba(16,24,40,0.08)" }, pressed && { opacity: 0.7 }]}>
      <FreshDot tone={fresh.tone} size={7} />
      <Txt variant="small" c={color.text} style={{ fontWeight: "700" }}>BTC</Txt>
      <Txt variant="small" c={color.text} style={{ fontVariant: ["tabular-nums"], fontWeight: "600" }}>{q.display}</Txt>
      <Txt variant="small" c={tint} style={{ fontWeight: "600", fontVariant: ["tabular-nums"] }}>{formatPct(q.change_pct)} {since}</Txt>
      <View style={{ flex: 1, alignItems: "flex-end" }}><Sparkline values={spark} tint={tint === color.dim ? color.accent : tint} width={52} height={22} /></View>
      <Ionicons name="chevron-up" size={16} color={color.dim} />
    </Pressable>
  );
}
