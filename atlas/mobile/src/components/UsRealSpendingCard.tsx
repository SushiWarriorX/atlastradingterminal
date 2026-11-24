import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { checkText, monthText, move, rangeText, trillions, yearText } from "../lib/realSpending";
import { useUsRealSpending } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

/** US real consumer spending (the Bureau of Economic Analysis' monthly Personal Income and Outlays, via FRED): spending with the effect of price changes taken out, next to spending in the dollars of the day and the PCE price index. Describes what already happened; not a signal or a forecast. */
export function UsRealSpendingCard() {
  const q = useUsRealSpending();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="usrealspending-card">
      <View><Txt variant="h2">US real consumer spending</Txt><Txt variant="tiny">What US households spend once rising prices are taken out, from the Bureau of Economic Analysis</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load US real spending" testID="usrealspending-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.real || !d.nominal || !d.prices || !d.year || !d.recent || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US real spending unavailable"} testID="usrealspending-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="usrealspending-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · annual rate · seasonally adjusted{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="usrealspending-headline">Real consumer spending was {trillions(d.real.level_billions)} a year in {ymdLabel(d.month)}, measured in 2017 dollars: {move(d.real.change_year_pct)} on a year earlier and {move(d.real.change_pct)} on the month before.</Txt>
            <Txt variant="tiny" testID="usrealspending-range">{rangeText(d.real.range)}</Txt>
            <Divider />
            <Txt variant="label">Spending in dollars, prices and the amount bought</Txt>
            <View style={{ gap: space.sm }}>
              <Txt variant="small" testID="usrealspending-nominal">Spending in the dollars of the day: {trillions(d.nominal.level_billions)} a year, {move(d.nominal.change_pct)} on the month and {move(d.nominal.change_year_pct)} on a year earlier</Txt>
              <Txt variant="small" testID="usrealspending-prices">Prices (the PCE price index, 2017 = 100): {d.prices.index.toFixed(3)}, {move(d.prices.change_pct)} on the month and {move(d.prices.change_year_pct)} on a year earlier; without food and energy: {d.prices.core_index.toFixed(3)}, {move(d.prices.core_change_pct)} and {move(d.prices.core_change_year_pct)}</Txt>
              <Txt variant="small" testID="usrealspending-year">{yearText(d.year)}</Txt>
            </View>
            <Divider />
            <Txt variant="label">The last six months</Txt>
            <View style={{ gap: space.sm }} testID="usrealspending-recent">
              {d.recent.map((r) => <Txt key={r.month} variant="small" testID={`usrealspending-month-${r.month}`}>{monthText(r, ymdLabel(r.month))}</Txt>)}
            </View>
            <Txt variant="tiny" testID="usrealspending-check">{checkText(d.detail)}</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: US Bureau of Economic Analysis (personal income and outlays), via FRED</SourceLink>
    </GCard>
  );
}
