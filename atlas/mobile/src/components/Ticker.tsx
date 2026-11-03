import React from "react";
import { Pressable, ScrollView } from "react-native";
import { directionOf, formatPct } from "../lib/format";
import { useWatchlist } from "../state/queries";
import { useSelection } from "../state/selection";
import { color, dirColor, space } from "../theme";
import { Txt } from "./ui";

/** A thin strip of the saved assets across the top, like a market ticker. Tap one to read it. */
export function Ticker() {
  const wl = useWatchlist();
  const { select } = useSelection();
  const items = wl.data?.items ?? [];
  if (!items.length) return null;
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0, borderBottomWidth: 1, borderBottomColor: color.border }} contentContainerStyle={{ paddingHorizontal: space.lg, paddingVertical: 9, gap: space.xl }} testID="ticker">
      {items.map((r) => (
        <Pressable key={r.asset.id} onPress={() => select(r.asset.id)} accessibilityRole="button" accessibilityLabel={`${r.asset.name} ${r.quote?.display ?? "price unavailable"}`} style={{ flexDirection: "row", gap: 8, alignItems: "baseline" }}>
          <Txt variant="small" c={color.text} style={{ fontWeight: "700" }}>{r.asset.symbol}</Txt>
          <Txt variant="small" c={color.text} style={{ fontVariant: ["tabular-nums"] }}>{r.quote?.display ?? "…"}</Txt>
          {r.quote ? <Txt variant="small" c={dirColor(directionOf(r.quote.change_pct))} style={{ fontWeight: "600", fontVariant: ["tabular-nums"] }}>{formatPct(r.quote.change_pct)}</Txt> : null}
        </Pressable>
      ))}
    </ScrollView>
  );
}
