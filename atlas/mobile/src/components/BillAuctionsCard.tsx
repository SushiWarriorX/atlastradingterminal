import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useBillAuctions } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const day = (iso?: string) => (iso ? new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }) : "");
const termName = (t: string) => t.replace("-Week", " weeks");
const points = (bps: number | null | undefined) => (bps == null ? "no earlier auction to compare" : bps === 0 ? "unchanged" : `${bps > 0 ? "up" : "down"} ${Math.abs(bps / 100).toFixed(2)} points`);

/** US Treasury bill auction results by term. Describes auctions that already happened; not a signal. */
export function BillAuctionsCard() {
  const q = useBillAuctions();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="bills-card">
      <View><Txt variant="h2">Treasury bill auctions</Txt><Txt variant="tiny">What the US pays to borrow for weeks and months, from the US Treasury</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the bill auctions" testID="bills-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Bill auctions unavailable"} testID="bills-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="bills-body">
            <Txt variant="label">Newest completed auction · {day(d.date)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            {d.freshness === "OVERDUE" ? <Banner tone="warn" title="Newer auctions are not published yet" testID="bills-overdue">The source's newest completed bill auction is from {day(d.date)} ({d.age_days} days ago).</Banner> : null}
            {(d.terms ?? []).map((t, i) => (
              <View key={t.term} style={{ gap: 2 }} testID={`bill-${t.term}`}>
                {i > 0 ? <Divider /> : null}
                <View style={{ flexDirection: "row", justifyContent: "space-between", gap: space.md }}>
                  <Txt variant="h2">{t.term.replace("-Week", "-week")}</Txt>
                  <Txt variant="h2">{t.investment_rate.toFixed(3)}%</Txt>
                </View>
                <Txt variant="small">{day(t.auction_date)} · rate {points(t.rate_change_bps)}</Txt>
                <Txt variant="tiny">Bid-to-cover {t.bid_to_cover.toFixed(2)}{t.average_bid_to_cover != null ? ` (average of the last ${t.compared_with}: ${t.average_bid_to_cover.toFixed(2)})` : ""}{t.accepted_billions != null ? ` · accepted $${t.accepted_billions.toFixed(1)}B` : ""}{t.mix ? ` · indirect bidders ${t.mix.indirect_pct.toFixed(0)}%` : ""}</Txt>
              </View>))}
            {d.pending_results?.length ? <Txt variant="tiny">Results not published yet: {d.pending_results.map((p) => `${termName(p.term)} (${day(p.auction_date)})`).join(", ")}.</Txt> : null}
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Treasury FiscalData</Txt></Pressable> : null}
    </GCard>
  );
}
