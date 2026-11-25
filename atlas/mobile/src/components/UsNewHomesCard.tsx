import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { checkText, compareText, headlineText, itemText, monthText, priceRangeText, pricesText, rangeText, stockText, supplyRangeText } from "../lib/usNewHomes";
import { useUsNewHomes } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

/** US new home sales (U.S. Census Bureau and U.S. Department of Housing and Urban Development, New Residential Sales, via FRED), monthly: how many new houses were sold, in the four regions, how many are for sale and what they sold for. Described, not forecast; the sentences come from `lib/usNewHomes.ts` and every figure from the server. */
export function UsNewHomesCard() {
  const q = useUsNewHomes();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="usnewhomes-card">
      <View><Txt variant="h2">New home sales</Txt><Txt variant="tiny">New houses sold and for sale in the US, monthly, from the Census Bureau</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load US new home sales" testID="usnewhomes-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.sales || !d.regions || !d.stock || !d.prices || !d.recent || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US new home sales unavailable"} testID="usnewhomes-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="usnewhomes-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · seasonally adjusted annual rate{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="usnewhomes-headline">{headlineText(d.sales, d.regions, ymdLabel(d.month))}</Txt>
            <Txt variant="small" testID="usnewhomes-compare">{compareText(d.sales)}</Txt>
            <Txt variant="tiny" testID="usnewhomes-range">{rangeText(d.sales.growth_range)}</Txt>
            <Divider />
            <Txt variant="label">The four regions</Txt>
            <View style={{ gap: space.sm }} testID="usnewhomes-regions">
              {d.regions.map((i) => <Txt key={i.key} variant="small" testID={`usnewhomes-region-${i.key}`}>{itemText(i)}</Txt>)}
            </View>
            <Divider />
            <Txt variant="label">For sale and months' supply</Txt>
            <Txt variant="small" testID="usnewhomes-stock">{stockText(d.stock)}</Txt>
            <Txt variant="tiny" testID="usnewhomes-supply-range">{supplyRangeText(d.stock.supply_range)}</Txt>
            <Divider />
            <Txt variant="label">Prices</Txt>
            <Txt variant="small" testID="usnewhomes-prices">{pricesText(d.prices)}</Txt>
            <Txt variant="tiny" testID="usnewhomes-price-range">{priceRangeText(d.prices.median_range)}</Txt>
            <Divider />
            <Txt variant="label">The last six months</Txt>
            <View style={{ gap: space.sm }} testID="usnewhomes-recent">
              {d.recent.map((m) => <Txt key={m.month} variant="small" testID={`usnewhomes-month-${m.month}`}>{monthText(m, ymdLabel(m.month))}</Txt>)}
            </View>
            <Txt variant="tiny" testID="usnewhomes-check">{checkText(d.detail)}</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: Census Bureau and HUD (New Residential Sales), via FRED</SourceLink>
    </GCard>
  );
}
