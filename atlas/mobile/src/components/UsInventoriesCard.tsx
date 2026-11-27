import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { checkText, compareText, headlineText, monthText, rangeText, sectorText } from "../lib/usInventories";
import { useUsInventories } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

/** US business inventories and sales (US Census Bureau, Manufacturing and Trade Inventories and Sales, via FRED), monthly: what manufacturers, wholesalers and retailers hold, what they sold and how many months of sales the shelves hold. Describes what already happened; not a signal or a forecast. */
export function UsInventoriesCard() {
  const q = useUsInventories();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="usinventories-card">
      <View><Txt variant="h2">Business inventories and sales</Txt><Txt variant="tiny">What US manufacturers, wholesalers and retailers hold on their shelves, what they sold, and how many months of sales that is, monthly, from the Census Bureau</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load US business inventories" testID="usinventories-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.total || !d.sectors || !d.recent || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US business inventories unavailable"} testID="usinventories-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="usinventories-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · seasonally adjusted{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="usinventories-headline">{headlineText(d.total, ymdLabel(d.month))}</Txt>
            <Txt variant="small" testID="usinventories-compare">{compareText(d.total)}</Txt>
            <Txt variant="tiny" testID="usinventories-range">{rangeText("the total ratio", d.total.ratio_range)}</Txt>
            <Divider />
            <Txt variant="label">By kind of business, most inventories first</Txt>
            <View style={{ gap: space.sm }} testID="usinventories-sectors">
              {d.sectors.map((s) => (
                <View key={s.key} style={{ gap: 2 }}>
                  <Txt variant="small" testID={`usinventories-sector-${s.key}`}>{sectorText(s)}</Txt>
                  <Txt variant="tiny" testID={`usinventories-range-${s.key}`}>{rangeText("its ratio", s.ratio_range)}</Txt>
                </View>))}
            </View>
            <Divider />
            <Txt variant="label">The last six months, all businesses</Txt>
            <View style={{ gap: space.sm }} testID="usinventories-recent">
              {d.recent.map((m) => <Txt key={m.month} variant="small" testID={`usinventories-month-${m.month}`}>{monthText(m, ymdLabel(m.month))}</Txt>)}
            </View>
            <Txt variant="tiny" testID="usinventories-check">{checkText(d.detail)}</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: US Census Bureau (Manufacturing and Trade Inventories and Sales), via FRED</SourceLink>
    </GCard>
  );
}
