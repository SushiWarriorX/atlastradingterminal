import React from "react";
import { Text, View } from "react-native";
import { hueFor, initials } from "../lib/format";

/** A round tile with the asset's initials. The colour comes from the stable asset ID, so two assets that share a ticker are visibly different. */
export function Avatar({ id, symbol, size = 44 }: { id: string; symbol: string; size?: number }) {
  const h = hueFor(id);
  return (
    <View style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: `hsl(${h}, 45%, 22%)`, borderWidth: 1, borderColor: `hsl(${h}, 55%, 38%)`, alignItems: "center", justifyContent: "center" }} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Text style={{ color: `hsl(${h}, 80%, 82%)`, fontWeight: "700", fontSize: size * 0.32, letterSpacing: 0.3 }}>{initials(symbol)}</Text>
    </View>
  );
}
