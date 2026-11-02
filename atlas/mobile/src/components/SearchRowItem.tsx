import React from "react";
import { Pressable, StyleSheet, View } from "react-native";
import type { Asset } from "../api/types";
import { TYPE_LABEL } from "../lib/format";
import { color, space } from "../theme";
import { Avatar } from "./Avatar";
import { IconButton, Txt } from "./ui";

/** A search result. The type and venue are always shown so two assets that share a ticker are never mistaken for each other. */
export function SearchRowItem({ asset, saved, busy, onOpen, onToggle }: { asset: Asset; saved: boolean; busy?: boolean; onOpen: () => void; onToggle: () => void }) {
  return (
    <View style={s.wrap} testID={`result-${asset.id}`}>
      <Pressable onPress={onOpen} accessibilityRole="button" accessibilityLabel={`${asset.name}, ${asset.symbol}, ${TYPE_LABEL[asset.type]} on ${asset.venue}. Open research.`} style={({ pressed }) => [s.row, pressed && { opacity: 0.7 }]}>
        <Avatar id={asset.id} symbol={asset.symbol} />
        <View style={{ flex: 1, minWidth: 0 }}>
          <Txt variant="h2" numberOfLines={1}>{asset.name}</Txt>
          <Txt variant="small" numberOfLines={1}>{asset.symbol} · {TYPE_LABEL[asset.type]} · {asset.venue}</Txt>
          {asset.support === "unverified" && <Txt variant="tiny" c={color.warn} numberOfLines={2}>Unverified: {asset.note ?? "not in Signal's list, so some research may not apply."}</Txt>}
        </View>
      </Pressable>
      <IconButton name={saved ? "checkmark-circle" : "add-circle-outline"} tint={saved ? color.up : color.accent} size={28} label={saved ? `Remove ${asset.name} from watchlist` : `Add ${asset.name} to watchlist`} onPress={onToggle} testID={`toggle-${asset.id}`} disabled={busy} />
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flexDirection: "row", alignItems: "center", gap: space.sm, paddingHorizontal: space.lg },
  row: { flex: 1, flexDirection: "row", alignItems: "center", gap: space.md, paddingVertical: space.md },
});
