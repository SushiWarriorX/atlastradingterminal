import React from "react";
import { Text, View } from "react-native";
import { color, famFor } from "../theme";
import { initials } from "../lib/format";

/** A neutral tile with the asset's initials. ETFs are rounded squares and everything else is a circle, so two assets that share a ticker still look different. */
export function Avatar({ id, symbol, size = 46 }: { id: string; symbol: string; size?: number }) {
  const etf = id.startsWith("ETF:");
  return (
    <View style={{ width: size, height: size, borderRadius: etf ? size * 0.3 : size / 2, backgroundColor: color.surface2, alignItems: "center", justifyContent: "center" }} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Text style={{ color: color.text, fontFamily: famFor(700), fontSize: size * 0.3, letterSpacing: -0.2 }}>{initials(symbol)}</Text>
    </View>
  );
}
