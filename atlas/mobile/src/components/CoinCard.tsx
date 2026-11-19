import React from "react";
import { Pressable, View } from "react-native";
import { color, radius, space } from "../theme";
import { Avatar } from "./Avatar";
import { Sparkline } from "./Sparkline";
import { Txt } from "./ui";

/** One of the cards in TradingView's horizontal row: a round logo and a name, the value with a small "USD", a coloured change line, a line with a faded area under it and a dot on its last point, and a caption. */
export function CoinCard({ id, symbol, name, value, change, tint, sparkTint, spark, caption, onPress, testID, width = 184 }: { id: string; symbol: string; name: string; value: string; change: string; tint: string; sparkTint?: string; spark?: number[] | null; caption?: string; onPress?: () => void; testID?: string; width?: number }) {
  const inner = (
    <View style={{ width, borderRadius: radius.lg, borderWidth: 1, borderColor: color.border, backgroundColor: color.bg, padding: space.md, gap: 6 }} testID={testID}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: space.sm }}>
        <Avatar id={id} symbol={symbol} size={30} />
        <Txt variant="label" c={color.text} numberOfLines={2} style={{ flex: 1, lineHeight: 16 }}>{name}</Txt>
      </View>
      <View style={{ flexDirection: "row", alignItems: "baseline", gap: 4 }}>
        <Txt variant="h2" style={{ fontSize: 19, fontWeight: "700", fontVariant: ["tabular-nums"] }}>{value}</Txt>
        <Txt variant="tiny">USD</Txt>
      </View>
      <Txt variant="small" c={tint} style={{ fontWeight: "600" }}>{change}</Txt>
      {spark && spark.length >= 2 ? <View style={{ height: 44, justifyContent: "flex-end" }}><Sparkline values={spark} tint={sparkTint ?? tint} width={width - 2 * space.md - 2} height={44} area dot /></View> : null}
      {caption ? <Txt variant="tiny" numberOfLines={3}>{caption}</Txt> : null}
    </View>
  );
  return onPress ? <Pressable onPress={onPress} accessibilityRole="button" style={({ pressed }) => pressed && { opacity: 0.7 }}>{inner}</Pressable> : inner;
}
