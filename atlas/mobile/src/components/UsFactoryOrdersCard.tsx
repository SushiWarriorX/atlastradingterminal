import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { checkText, durableText, gapsText, headlineText, itemText, monthText } from "../lib/usFactoryOrders";
import { useUsFactoryOrders } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

/** US factory orders (U.S. Census Bureau, Manufacturers' Shipments, Inventories, and Orders, the M3 survey, via FRED), monthly: what US manufacturers were ordered, shipped, held and still owed. Described, not forecast; the sentences come from `lib/usFactoryOrders.ts` and every figure from the server. */
export function UsFactoryOrdersCard() {
  const q = useUsFactoryOrders();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="usfactoryorders-card">
      <View><Txt variant="h2">Factory orders</Txt><Txt variant="tiny">What US manufacturers were ordered, shipped, held and still owed, monthly, from the Census Bureau</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load US factory orders" testID="usfactoryorders-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.durable_month || !d.full || !d.nondurable || !d.durable || !d.recent || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US factory orders unavailable"} testID="usfactoryorders-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="usfactoryorders-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · seasonally adjusted{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="usfactoryorders-headline">{headlineText(d.full, ymdLabel(d.month))}</Txt>
            <Divider />
            <Txt variant="label">Totals</Txt>
            <View style={{ gap: space.sm }} testID="usfactoryorders-full">
              {d.full.map((i) => <Txt key={i.key} variant="small" testID={`usfactoryorders-full-${i.key}`}>{itemText(i)}</Txt>)}
            </View>
            <Divider />
            <Txt variant="label">Nondurable goods</Txt>
            <View style={{ gap: space.sm }} testID="usfactoryorders-nondurable">
              {d.nondurable.map((i) => <Txt key={i.key} variant="small" testID={`usfactoryorders-nondurable-${i.key}`}>{itemText(i)}</Txt>)}
            </View>
            <Divider />
            <Txt variant="label">Durable goods</Txt>
            <Txt variant="tiny" testID="usfactoryorders-durable-month">{durableText(ymdLabel(d.durable_month), !!d.durable_advance)}</Txt>
            <View style={{ gap: space.sm }} testID="usfactoryorders-durable">
              {d.durable.map((i) => <Txt key={i.key} variant="small" testID={`usfactoryorders-durable-${i.key}`}>{itemText(i)}</Txt>)}
            </View>
            <Divider />
            <Txt variant="label">Where the two reports meet</Txt>
            <Txt variant="tiny" testID="usfactoryorders-gaps">{gapsText(d.detail.newest_common, ymdLabel(d.detail.newest_common.month))}</Txt>
            <Divider />
            <Txt variant="label">The last six months</Txt>
            <View style={{ gap: space.sm }} testID="usfactoryorders-recent">
              {d.recent.map((m) => <Txt key={m.month} variant="small" testID={`usfactoryorders-month-${m.month}`}>{monthText(m, ymdLabel(m.month))}</Txt>)}
            </View>
            <Txt variant="tiny" testID="usfactoryorders-check">{checkText(d.detail)}</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: Census Bureau (M3 survey), via FRED</SourceLink>
    </GCard>
  );
}
