import React from "react";
import { Pressable, StyleSheet, View } from "react-native";
import type { WatchRow } from "../api/types";
import { directionOf, formatChange, formatPct, providerName, spoken, TYPE_LABEL } from "../lib/format";
import { describeFreshness } from "../lib/freshness";
import { color, dirColor, space } from "../theme";
import { Avatar } from "./Avatar";
import { FreshDot } from "./FreshnessLine";
import { Sparkline } from "./Sparkline";
import { IconButton, LOGO_PAD, LogoSlot, Skeleton, Tag, Txt } from "./ui";

interface Props {
  row: WatchRow; now: number; editing: boolean; canUp: boolean; canDown: boolean;
  onOpen: () => void; onRemove: () => void; onMove: (dir: "up" | "down") => void;
}

/** One saved asset, laid out like a row of TradingView's watchlist: a round logo, the symbol in bold with a small grey badge and the name beneath, and on the right the price over the change in colour. A one-line research takeaway, a small line of recent prices and the freshness dot stay, because they say how far to trust the price. */
export function WatchRowItem({ row, now, editing, canUp, canDown, onOpen, onRemove, onMove }: Props) {
  const { asset, quote, error } = row;
  const fresh = describeFreshness(quote?.prov, now);
  const dir = directionOf(quote?.change_pct);
  const tint = dirColor(dir);
  const move = quote && quote.change !== null && quote.change !== undefined ? formatChange(quote.change) : null;
  // The words the row shows, in the order it shows them (the logo is outside the button), then what only the dot says.
  const label = spoken(asset.symbol, TYPE_LABEL[asset.type], asset.support === "unverified" && "Unverified", asset.name, row.takeaway ? row.takeaway.text : error ? error.message : null, quote ? quote.display : row.loading ? null : "Unavailable", move, quote ? formatPct(quote.change_pct) : null)
    + (row.loading ? ". Loading price." : quote ? `. ${fresh.label}.` : ".");
  return (
    <View style={s.wrap} testID={`row-${asset.id}`}>
      {editing && <IconButton name="remove-circle" tint={color.down} label={`Remove ${asset.name} from watchlist`} onPress={onRemove} testID={`remove-${asset.id}`} />}
      <View style={s.box}>
      <Pressable onPress={editing ? undefined : onOpen} disabled={editing} accessibilityRole="button" accessibilityLabel={label} style={({ pressed }) => [s.row, pressed && { opacity: 0.7 }]}>
        <View style={s.mid}>
          <View style={s.sub}>
            <Txt variant="h2" numberOfLines={1} style={{ fontWeight: "700", marginRight: 6, flexShrink: 1 }}>{asset.symbol}</Txt>
            <Tag label={TYPE_LABEL[asset.type]} />
            {asset.support === "unverified" && <View style={{ marginLeft: 6 }}><Tag label="Unverified" tint={color.warn} /></View>}
          </View>
          <Txt variant="small" numberOfLines={1}>{asset.name}</Txt>
          {row.takeaway ? <Txt variant="tiny" numberOfLines={1} style={{ marginTop: 2 }}>{row.takeaway.text}</Txt> : error ? <Txt variant="tiny" c={color.warn} numberOfLines={1} style={{ marginTop: 2 }}>{error.message}</Txt> : null}
        </View>
        {!editing && quote && row.spark ? <View style={s.spark}><Sparkline values={row.spark} tint={tint === color.dim ? color.accent : tint} width={52} height={26} /></View> : null}
        {!editing && (
          <View style={s.right}>
            {quote ? (
              <>
                <View style={s.priceLine}>
                  <FreshDot tone={fresh.tone} size={6} />
                  <Txt variant="h2" testID={`price-${asset.id}`} style={{ fontVariant: ["tabular-nums"], fontWeight: "700" }}>{quote.display}</Txt>
                </View>
                <Txt variant="small" c={tint} style={{ fontWeight: "600", marginTop: 2, fontVariant: ["tabular-nums"] }}>{quote.change !== null && quote.change !== undefined ? `${formatChange(quote.change)}  ` : ""}{formatPct(quote.change_pct)}</Txt>
              </>
            ) : row.loading ? (
              <View style={{ alignItems: "flex-end", gap: 6 }} testID={`loading-${asset.id}`}><Skeleton w={72} h={18} /><Skeleton w={44} h={12} /></View>
            ) : (
              <Txt variant="small" c={color.warn} style={{ fontWeight: "600" }}>Unavailable</Txt>
            )}
          </View>
        )}
      </Pressable>
      <LogoSlot><Avatar id={asset.id} symbol={asset.symbol} /></LogoSlot>
      </View>
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
  box: { flex: 1 },
  row: { flexDirection: "row", alignItems: "center", gap: space.md, paddingVertical: 12, paddingLeft: LOGO_PAD },
  mid: { flex: 1, minWidth: 0 },
  sub: { flexDirection: "row", alignItems: "center" },
  spark: { width: 52 },
  right: { alignItems: "flex-end", minWidth: 96 },
  priceLine: { flexDirection: "row", alignItems: "center", gap: 6 },
  edit: { flexDirection: "row", gap: 2 },
});
