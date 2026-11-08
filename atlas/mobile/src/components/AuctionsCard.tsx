import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useAuctions } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const pts = (x: number | null) => (x == null ? "no earlier auction" : `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(3)} pts vs the previous`);

/** US Treasury note and bond auction results by term. Describes finished auctions; not a signal. */
export function AuctionsCard() {
  const q = useAuctions();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="auctions-card">
      <View><Txt variant="h2">Treasury auctions</Txt><Txt variant="tiny">What the Treasury paid to sell notes and bonds, from the US Treasury</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load Treasury auctions" testID="auctions-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Treasury auctions unavailable"} testID="auctions-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="auctions-body">
            {(d.tenors ?? []).map((t, i) => (
              <View key={t.tenor} style={{ gap: 2 }}>
                {i > 0 ? <Divider /> : null}
                <Txt variant="label">{t.tenor}{t.reopening ? " (reopening)" : ""} · {t.auction_date}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
                <Txt variant="h2">{t.high_yield.toFixed(3)}%</Txt>
                <Txt variant="small">{pts(t.yield_change)}</Txt>
                <Txt variant="tiny">Bid-to-cover {t.bid_to_cover.toFixed(2)}{t.average_bid_to_cover != null ? ` (average of the previous ${t.compared_with}: ${t.average_bid_to_cover.toFixed(2)})` : ""}{t.offering_billions != null ? ` · offered $${t.offering_billions}B` : ""}</Txt>
              </View>))}
            {(d.pending_results ?? []).length > 0 ? <Txt variant="tiny">Results not yet published by the source: {d.pending_results!.map((p) => `${p.tenor} auction of ${p.auction_date}`).join(", ")}.</Txt> : null}
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Treasury FiscalData</Txt></Pressable> : null}
    </GCard>
  );
}
