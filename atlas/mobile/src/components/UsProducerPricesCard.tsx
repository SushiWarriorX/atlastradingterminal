import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { checkText, headlineText, itemText, monthText, rangeText } from "../lib/usProducerPrices";
import { useUsProducerPrices } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

/** US producer prices (U.S. Bureau of Labor Statistics, Producer Price Index, via FRED), monthly: how the prices producers get change, for final demand and its core, for finished goods and for what producers pay (intermediate demand), each as an index with its own base. Described, not forecast; the sentences come from `lib/usProducerPrices.ts` and the figures from the server, which checks them. */
export function UsProducerPricesCard() {
  const q = useUsProducerPrices();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="usproducerprices-card">
      <View><Txt variant="h2">Producer prices</Txt><Txt variant="tiny">What US producers get for what they sell, monthly, from the Bureau of Labor Statistics</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load US producer prices" testID="usproducerprices-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.headline || !d.groups || !d.recent || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US producer prices unavailable"} testID="usproducerprices-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="usproducerprices-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · seasonally adjusted indexes{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="usproducerprices-headline">{headlineText(d.headline, ymdLabel(d.month))}</Txt>
            <Txt variant="tiny" testID="usproducerprices-range">{rangeText(d.headline.range)}</Txt>
            {d.groups.map((g) => (
              <View key={g.key} style={{ gap: space.sm }} testID={`usproducerprices-group-${g.key}`}>
                <Divider />
                <Txt variant="label">{g.label}</Txt>
                {g.items.map((i) => <Txt key={i.key} variant="small" testID={`usproducerprices-item-${i.key}`}>{itemText(i)}</Txt>)}
              </View>
            ))}
            <Divider />
            <Txt variant="label">The last six months</Txt>
            <View style={{ gap: space.sm }} testID="usproducerprices-recent">
              {d.recent.map((m) => <Txt key={m.month} variant="small" testID={`usproducerprices-month-${m.month}`}>{monthText(m, ymdLabel(m.month))}</Txt>)}
            </View>
            <Txt variant="tiny" testID="usproducerprices-check">{checkText(d.detail)}</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: Bureau of Labor Statistics (Producer Price Index), via FRED</SourceLink>
    </GCard>
  );
}
