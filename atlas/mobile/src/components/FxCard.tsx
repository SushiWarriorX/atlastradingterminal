import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useFx } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const pc = (x: number | null | undefined) => (x === null || x === undefined ? "n/a" : `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(2)}%`);
const tone = (x: number | null | undefined) => (x === null || x === undefined ? color.dim : x > 0 ? color.up : x < 0 ? color.down : color.text);

/** How the US dollar is doing against the major currencies, from the ECB's daily euro reference rates. For information, not tradable quotes. */
export function FxCard() {
  const q = useFx();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="fx-card">
      <View><Txt variant="h2">US dollar vs major currencies</Txt><Txt variant="tiny">ECB daily reference rates</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load exchange rates" testID="fx-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Exchange rates unavailable"} testID="fx-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="fx-body">
            <Txt variant="small">As of {d.date}{d.freshness === "OVERDUE" ? " · overdue" : ""}. Stronger than a month ago against {d.breadth!.stronger_30d} of {d.breadth!.of} of these currencies.</Txt>
            {d.pairs!.map((p, i) => (
              <View key={p.pair}>{i > 0 && <Divider />}
                <View style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: 5, gap: space.md }}>
                  <View style={{ flex: 1 }}><Txt variant="body">{p.pair}</Txt><Txt variant="tiny">{p.rate}</Txt></View>
                  <View style={{ alignItems: "flex-end" }}><Txt variant="small">Dollar 1d <Txt variant="small" c={tone(p.dollar_vs_1d_pct)}>{pc(p.dollar_vs_1d_pct)}</Txt></Txt><Txt variant="small">30d <Txt variant="small" c={tone(p.dollar_vs_30d_pct)}>{pc(p.dollar_vs_30d_pct)}</Txt></Txt></View>
                </View>
              </View>))}
            <Txt variant="tiny">{d.note}</Txt>
            {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: European Central Bank</Txt></Pressable> : null}
          </View>)}
    </GCard>
  );
}
