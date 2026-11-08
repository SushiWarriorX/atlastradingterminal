import React from "react";
import { Linking, Pressable, View } from "react-native";
import type { ListingItem } from "../api/types";
import { safeUrl } from "../lib/links";
import { moneyShort as money } from "../lib/money";
import { useListings } from "../state/queries";
import { useOpenAsset } from "../state/selection";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, TextButton, Txt } from "./ui";

function Row({ i, onOpen }: { i: ListingItem; onOpen: (id: string) => void }) {
  const tag = i.status === "trading" ? "confirmed trading" : i.status === "priced" ? "priced, not yet confirmed" : i.status === "upcoming" ? "upcoming, not trading yet" : i.status === "upcoming_date_passed" ? "date passed" : i.status;
  const link = safeUrl(i.verification?.evidence?.link ?? null);
  return (
    <View style={{ gap: 3 }} testID={`listing-${i.symbol ?? i.deal_id}`}>
      <Txt variant="label">{i.symbol ?? "(no ticker yet)"} · {i.name}</Txt>
      <Txt variant="tiny">{i.exchange}{i.exchange_text && i.exchange_text !== i.exchange ? ` · ${i.exchange_text}` : ""} · {i.listing_type} · {tag}</Txt>
      <Txt variant="small">{i.status_text}</Txt>
      <Txt variant="tiny">Offer {i.price ?? "n/a"} · {i.shares_offered?.toLocaleString() ?? "n/a"} shares · {money(i.offer_amount)}{i.expected_date ? ` · expected ${i.expected_date}` : ""}{i.priced_date ? ` · priced ${i.priced_date}` : ""}</Txt>
      {i.listing_type === "SPAC IPO" ? <Txt variant="tiny" c={color.warn} testID="spac-note">{i.listing_type_note}</Txt> : null}
      {i.verification ? (
        <View><Txt variant="tiny">{i.verification.verified ? "✓ " : ""}SEC check: {i.verification.note}</Txt>
          {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Open the filing</Txt></Pressable> : null}</View>) : null}
      {i.newness ? <Txt variant="tiny">{i.newness.reason}</Txt> : null}
      {i.symbol && (i.status === "priced" || i.status === "trading") && i.listing_type !== "SPAC IPO"
        ? <TextButton label="Research this company" onPress={() => onOpen(`EQUITY:${(i.exchange ?? "NASDAQ").toUpperCase().replace(" ", "")}:${i.symbol}`)} testID={`listing-research-${i.symbol}`} /> : null}
    </View>);
}

/** Newly listed companies on NYSE and Nasdaq. Upcoming deals and confirmed trading debuts are kept apart; nothing is invented on a quiet day. */
export function ListingsCard() {
  const q = useListings();
  const open = useOpenAsset();
  const d = q.data;
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="listings-card">
      <View><Txt variant="h2">New listings</Txt><Txt variant="tiny">NYSE and Nasdaq: upcoming deals and recent pricings</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load new listings" testID="listings-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone="warn" title="New listings unavailable" testID="listings-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.md }} testID="listings-body">
            <Txt variant="small" testID="listings-today">Today: {d.today?.text}{d.stale ? " (the feed is stale)" : ""}</Txt>
            <Txt variant="tiny">Confirmed trading {d.counts?.confirmed_trading} · verified by SEC prospectus {d.counts?.verified_by_sec} · fetched {d.fetched_at?.slice(0, 16).replace("T", " ")} UTC</Txt>
            <Txt variant="label">Upcoming listings · not trading yet ({d.upcoming.length})</Txt>
            {d.upcoming.length === 0 ? <Txt variant="small">No upcoming NYSE or Nasdaq listings are reported.</Txt> : d.upcoming.map((i, k) => <View key={i.deal_id}>{k > 0 ? <Divider /> : null}<Row i={i} onOpen={open} /></View>)}
            <Divider />
            <Txt variant="label">Recent listings · priced in the last {d.window_days} days ({d.recent.length})</Txt>
            {d.recent.length === 0 ? <Txt variant="small">No new listings in this window.</Txt> : d.recent.slice(0, 12).map((i, k) => <View key={i.deal_id}>{k > 0 ? <Divider /> : null}<Row i={i} onOpen={open} /></View>)}
            {d.recent.length > 12 ? <Txt variant="tiny">{d.recent.length - 12} more not shown here; the terminal lists them all.</Txt> : null}
            {(d.errors ?? []).map((e, k) => <Txt key={k} variant="tiny" c={color.warn}>{e}</Txt>)}
          </View>)}
      <Txt variant="tiny">{d?.coverage} Source: {d?.source}.</Txt>
    </GCard>
  );
}
