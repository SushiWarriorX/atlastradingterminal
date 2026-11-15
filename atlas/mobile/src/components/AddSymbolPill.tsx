import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { Pressable } from "react-native";
import { color, famFor, font, radius } from "../theme";
import { Txt } from "./ui";

/** "+ Add symbol": the grey pill at the end of TradingView's watchlist. Opens Search, where an asset is saved with its + button. */
export function AddSymbolPill({ onPress }: { onPress: () => void }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel="Add symbol" testID="add-symbol" style={({ pressed }) => [{ flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: color.surface2, borderRadius: radius.pill, paddingVertical: 10, paddingHorizontal: 18 }, pressed && { opacity: 0.6 }]}>
      <Ionicons name="add" size={18} color={color.text} />
      <Txt variant="body" style={{ fontSize: font.md, fontFamily: famFor(600) }}>Add symbol</Txt>
    </Pressable>
  );
}
