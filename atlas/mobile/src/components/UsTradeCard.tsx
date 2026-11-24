import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { checkText, compareText, groupText, headlineText, monthText, rangeText } from "../lib/trade";
import { useUsTrade } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

/** US international trade in goods and services (Census Bureau and Bureau of Economic Analysis, via FRED): what the country sold abroad, what it bought and the difference, for the total, for goods and for services. Describes what already happened; not a signal or a forecast. */
export function UsTradeCard() {
  const q = useUsTrade();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="ustrade-card">
      <View><Txt variant="h2">US international trade</Txt><Txt variant="tiny">What the US sold to the rest of the world and bought from it, from the Census Bureau and the Bureau of Economic Analysis</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load US trade" testID="ustrade-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.total || !d.goods || !d.services || !d.recent || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US trade unavailable"} testID="ustrade-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="ustrade-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · seasonally adjusted{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="ustrade-headline">{headlineText(d.total, ymdLabel(d.month))}</Txt>
            <Txt variant="small" testID="ustrade-compare">{compareText(d.total)}</Txt>
            <Txt variant="tiny" testID="ustrade-range">{rangeText(d.total.range)}</Txt>
            <Divider />
            <Txt variant="label">Goods and services</Txt>
            <View style={{ gap: space.sm }}>
              <Txt variant="small" testID="ustrade-goods">{groupText("Goods", d.goods)}</Txt>
              <Txt variant="small" testID="ustrade-services">{groupText("Services", d.services)}</Txt>
            </View>
            <Divider />
            <Txt variant="label">The last six months</Txt>
            <View style={{ gap: space.sm }} testID="ustrade-recent">
              {d.recent.map((r) => <Txt key={r.month} variant="small" testID={`ustrade-month-${r.month}`}>{monthText(r, ymdLabel(r.month))}</Txt>)}
            </View>
            <Txt variant="tiny" testID="ustrade-check">{checkText(d.detail)}</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: US Census Bureau and Bureau of Economic Analysis (international trade in goods and services), via FRED</SourceLink>
    </GCard>
  );
}
