import React from "react";
import { Text, View } from "react-native";
import { famFor } from "../theme";
import { hueFor, initials } from "../lib/format";

const KNOWN_HUE: Record<string, number> = { BTC: 32, ETH: 228, SOL: 268, USDT: 160, USDC: 214, XRP: 200, DOGE: 46 };

/** The two colours of a round logo: a pale tint of one hue behind dark letters of the same hue (so the letters stay readable). Well-known coins get their usual hue; everything else gets a stable one from its id. */
export function logoColors(id: string, symbol: string): { bg: string; fg: string } {
  const hue = KNOWN_HUE[symbol.toUpperCase()] ?? hueFor(id);
  return { bg: `hsl(${hue}, 85%, 92%)`, fg: `hsl(${hue}, 60%, 26%)` };
}

/** A round logo made of the asset's letters, like the logos in TradingView's lists. ETFs are rounded squares and everything else is a circle, so two assets that share a ticker still look different. */
export function Avatar({ id, symbol, size = 40 }: { id: string; symbol: string; size?: number }) {
  const etf = id.startsWith("ETF:");
  const { bg, fg } = logoColors(id, symbol);
  return (
    <View style={{ width: size, height: size, borderRadius: etf ? size * 0.3 : size / 2, backgroundColor: bg, alignItems: "center", justifyContent: "center" }} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Text style={{ color: fg, fontFamily: famFor(700), fontSize: size * 0.3, letterSpacing: -0.2 }}>{initials(symbol)}</Text>
    </View>
  );
}
