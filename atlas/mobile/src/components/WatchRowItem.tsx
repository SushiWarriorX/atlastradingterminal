import { Ionicons } from "@expo/vector-icons";
import React from "react";
import { Pressable, StyleSheet, View } from "react-native";
import type { WatchRow } from "../api/types";
import { directionOf, formatPct, providerName, TYPE_LABEL } from "../lib/format";
import { describeFreshness } from "../lib/freshness";
import { color, dirColor, space } from "../theme";
import { Avatar } from "./Avatar";
import { FreshDot } from "./FreshnessLine";
import { Sparkline } from "./Sparkline";
import { IconButton, Skeleton, Txt } from "./ui";

interface Props {
  row: WatchRow; now: number; editing: boolean; canUp: boolean; canDown: boolean;
  onOpen: () => void; onRemove: () => void; onMove: (dir: "up" | "down") => void;
}

/** One saved asset: identity, a one-line research takeaway, sparkline, price, change and a discreet freshness dot. */
export function WatchRowItem({ row, now, editing, canUp, canDown, onOpen, onRemove, onMove }: Props) {
  const { asset, quote, error } = row;
  const fresh = describeFreshness(quote?.prov, now);
  const dir = directionOf(quote?.change_pct);
  const tint = dirColor(dir);
  const label = `${asset.name}, ${asset.symbol}, ${TYPE_LABEL[asset.type]}. ${row.loading ? "Loading price." : quote ? `${quote.display}, ${formatPct(quote.change_pct)}. ${fresh.label}.` : "Price unavailable."}`;
  return (
    <View style={s.wrap} testID={`row-${asset.id}`}>
      {editing && <IconButton name="remove-circle" tint={color.down} label={`Remove ${asset.name} from watchlist`} onPress={onRemove} testID={`remove-${asset.id}`} />}
      <Pressable onPress={editing ? undefined : onOpen} disabled={editing} accessibilityRole="button" accessibilityLabel={label} style={({ pressed }) => [s.row, pressed && { opacity: 0.7 }]}>
        <Avatar id={asset.id} symbol={asset.symbol} />
        <View style={s.mid}>
          <Txt variant="h2" numberOfLines={1}>{asset.name}</Txt>
          <View style={s.sub}>
            <Txt variant="small" numberOfLines={1}>{asset.symbol} · {TYPE_LABEL[asset.type]}</Txt>
            {asset.support === "unverified" && <Txt variant="tiny" c={color.warn}> · unverified</Txt>}
          </View>
          {row.takeaway ? <Txt variant="tiny" numberOfLines={1} style={{ marginTop: 2 }}>{row.takeaway.text}</Txt> : error ? <Txt variant="tiny" c={color.warn} numberOfLines={1} style={{ marginTop: 2 }}>{error.message}</Txt> : null}
        </View>
        {!editing && (
          <View style={s.right}>
            {quote ? (
              <>
                <View style={s.priceLine}>
                  <FreshDot tone={fresh.tone} size={7} />
                  <Txt variant="h2" testID={`price-${asset.id}`}>{quote.display}</Txt>
                </View>
                <Txt variant="small" c={tint} style={{ fontWeight: "600" }}>{formatPct(quote.change_pct)}</Txt>
              </>
            ) : row.loading ? (
              <View style={{ alignItems: "flex-end", gap: 6 }} testID={`loading-${asset.id}`}><Skeleton w={72} h={18} /><Skeleton w={44} h={12} /></View>
            ) : (
              <Txt variant="small" c={color.warn} style={{ fontWeight: "600" }}>Unavailable</Txt>
            )}
            {quote && row.spark ? <View style={{ marginTop: 2 }}><Sparkline values={row.spark} tint={tint === color.dim ? color.accent : tint} /></View> : null}
          </View>
        )}
      </Pressable>
      {editing && (
        <View style={s.edit}>
          <IconButton name="chevron-up" label={`Move ${asset.name} up`} onPress={() => onMove("up")} disabled={!canUp} testID={`up-${asset.id}`} />
          <IconButton name="chevron-down" label={`Move ${asset.name} down`} onPress={() => onMove("down")} disabled={!canDown} testID={`down-${asset.id}`} />
        </View>
      )}
    </View>
  );
}

export const providerLine = (row: WatchRow) => (row.quote ? providerName(row.quote.prov.provider) : "");

const s = StyleSheet.create({
  wrap: { flexDirection: "row", alignItems: "center", gap: space.sm, paddingHorizontal: space.lg },
  row: { flex: 1, flexDirection: "row", alignItems: "center", gap: space.md, paddingVertical: space.md },
  mid: { flex: 1, minWidth: 0 },
  sub: { flexDirection: "row", alignItems: "center" },
  right: { alignItems: "flex-end", minWidth: 96 },
  priceLine: { flexDirection: "row", alignItems: "center", gap: 6 },
  edit: { flexDirection: "row", gap: 2 },
});
