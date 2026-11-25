import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { checkText, compareText, headlineText, itemText, monthText, rangeText } from "../lib/usBuildingPermits";
import { useUsBuildingPermits } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

/** US building permits (U.S. Census Bureau and U.S. Department of Housing and Urban Development, New Residential Construction, via FRED), monthly: how many new homes local governments gave permission to build, by type and by region. Described, not forecast; the sentences come from `lib/usBuildingPermits.ts` and every figure from the server. */
export function UsBuildingPermitsCard() {
  const q = useUsBuildingPermits();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="usbuildingpermits-card">
      <View><Txt variant="h2">Building permits</Txt><Txt variant="tiny">Permission to build new homes in the US, monthly, from the Census Bureau and the Department of Housing and Urban Development</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load US building permits" testID="usbuildingpermits-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.total || !d.types || !d.regions || !d.recent || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US building permits unavailable"} testID="usbuildingpermits-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="usbuildingpermits-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · seasonally adjusted annual rate{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="usbuildingpermits-headline">{headlineText(d.total, d.types, ymdLabel(d.month))}</Txt>
            <Txt variant="small" testID="usbuildingpermits-compare">{compareText(d.total)}</Txt>
            <Txt variant="tiny" testID="usbuildingpermits-range">{rangeText(d.total.growth_range)}</Txt>
            <Divider />
            <Txt variant="label">By type of home</Txt>
            <View style={{ gap: space.sm }} testID="usbuildingpermits-types">
              {d.types.map((i) => <Txt key={i.key} variant="small" testID={`usbuildingpermits-type-${i.key}`}>{itemText(i)}</Txt>)}
            </View>
            <Divider />
            <Txt variant="label">By region</Txt>
            <View style={{ gap: space.sm }} testID="usbuildingpermits-regions">
              {d.regions.map((i) => <Txt key={i.key} variant="small" testID={`usbuildingpermits-region-${i.key}`}>{itemText(i)}</Txt>)}
            </View>
            <Divider />
            <Txt variant="label">The last six months</Txt>
            <View style={{ gap: space.sm }} testID="usbuildingpermits-recent">
              {d.recent.map((m) => <Txt key={m.month} variant="small" testID={`usbuildingpermits-month-${m.month}`}>{monthText(m, ymdLabel(m.month))}</Txt>)}
            </View>
            <Txt variant="tiny" testID="usbuildingpermits-check">{checkText(d.detail)}</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: Census Bureau and HUD (New Residential Construction), via FRED</SourceLink>
    </GCard>
  );
}
