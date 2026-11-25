import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { checkText, compareText, headlineText, itemText, monthText, rangeText } from "../lib/usConstruction";
import { useUsConstruction } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

/** US construction spending (U.S. Census Bureau, Construction Spending, the value of construction put in place, via FRED), monthly: how much construction work was done, by who pays, by use and in the four parts of that table. Described, not forecast; the sentences come from `lib/usConstruction.ts` and every figure from the server. */
export function UsConstructionCard() {
  const q = useUsConstruction();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="usconstruction-card">
      <View><Txt variant="h2">Construction spending</Txt><Txt variant="tiny">Construction work done in the US, monthly, from the Census Bureau</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load US construction spending" testID="usconstruction-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.total || !d.owners || !d.uses || !d.parts || !d.recent || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US construction spending unavailable"} testID="usconstruction-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="usconstruction-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · seasonally adjusted annual rate{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="usconstruction-headline">{headlineText(d.total, d.owners, ymdLabel(d.month))}</Txt>
            <Txt variant="small" testID="usconstruction-compare">{compareText(d.total)}</Txt>
            <Txt variant="tiny" testID="usconstruction-range">{rangeText(d.total.growth_range)}</Txt>
            <Divider />
            <Txt variant="label">By who pays</Txt>
            <View style={{ gap: space.sm }} testID="usconstruction-owners">
              {d.owners.map((i) => <Txt key={i.key} variant="small" testID={`usconstruction-owner-${i.key}`}>{itemText(i)}</Txt>)}
            </View>
            <Divider />
            <Txt variant="label">By use</Txt>
            <View style={{ gap: space.sm }} testID="usconstruction-uses">
              {d.uses.map((i) => <Txt key={i.key} variant="small" testID={`usconstruction-use-${i.key}`}>{itemText(i)}</Txt>)}
            </View>
            <Divider />
            <Txt variant="label">The four parts together</Txt>
            <View style={{ gap: space.sm }} testID="usconstruction-parts">
              {d.parts.map((i) => <Txt key={i.key} variant="small" testID={`usconstruction-part-${i.key}`}>{itemText(i)}</Txt>)}
            </View>
            <Divider />
            <Txt variant="label">The last six months</Txt>
            <View style={{ gap: space.sm }} testID="usconstruction-recent">
              {d.recent.map((m) => <Txt key={m.month} variant="small" testID={`usconstruction-month-${m.month}`}>{monthText(m, ymdLabel(m.month))}</Txt>)}
            </View>
            <Txt variant="tiny" testID="usconstruction-check">{checkText(d.detail)}</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: Census Bureau (Construction Spending), via FRED</SourceLink>
    </GCard>
  );
}
