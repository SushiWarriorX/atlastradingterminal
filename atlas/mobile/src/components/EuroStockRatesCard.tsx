import React from "react";
import { View } from "react-native";
import type { EuroStockRatesRow } from "../api/types";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { cap, checkText, move, partsText, pct, splitText } from "../lib/stockRates";
import { useEuroStockRates } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

/** Euro-area bank interest rates on EXISTING loans and deposits (the average rate on what banks already have on their books), monthly, from the ECB Data Portal, with the ECB's split of each change into a rate part and a weight part. Describes what already happened; not a signal or a forecast. */
export function EuroStockRatesCard() {
  const q = useEuroStockRates();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  const row = (kind: string, r: EuroStockRatesRow, what: string) => {
    const split = splitText(r);
    const parts = partsText(r, what);
    return (
      <View key={r.id} style={{ gap: space.xs }} testID={`eurostock-${kind}-${r.id}`}>
        <Txt variant="small">{cap(r.label)}: {pct(r.rate_pct)} a year, {move(r.change_month_points, "a month earlier")}, {move(r.change_year_points, "a year earlier")}.</Txt>
        {split ? <Txt variant="tiny">{split}</Txt> : null}
        {parts ? <Txt variant="tiny">{parts}</Txt> : null}
        {r.window ? <Txt variant="tiny">Over the past 10 years ({r.window.months} months) it ran from {pct(r.window.lowest.pct)} ({ymdLabel(r.window.lowest.month)}) to {pct(r.window.highest.pct)} ({ymdLabel(r.window.highest.month)}); {r.window.share_lower_pct}% of those months were lower than now.</Txt> : null}
      </View>
    );
  };
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="eurostock-card">
      <View><Txt variant="h2">Euro-area rates on existing loans and deposits</Txt><Txt variant="tiny">The average rate on what banks already have on their books, monthly, from the ECB</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the euro-area rates on existing loans and deposits" testID="eurostock-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.loans || !d.deposits || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Euro-area rates on existing loans and deposits unavailable"} testID="eurostock-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="eurostock-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · loans and deposits outstanding · percent a year{d.provisional ? " · provisional" : ""}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="label">What borrowers pay on loans already made</Txt>
            <View style={{ gap: space.md }} testID="eurostock-loans">{d.loans.map((r) => row("loan", r, "original maturity of the loan"))}</View>
            <Divider />
            <Txt variant="label">What banks pay on deposits already placed</Txt>
            <View style={{ gap: space.md }} testID="eurostock-deposits">{d.deposits.map((r) => row("deposit", r, "agreed maturity"))}</View>
            <Txt variant="tiny">{checkText(d.detail)}</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: European Central Bank (MFI interest rate statistics), via the ECB Data Portal</SourceLink>
    </GCard>
  );
}
