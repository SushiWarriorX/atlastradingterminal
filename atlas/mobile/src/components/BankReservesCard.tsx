import React from "react";
import { View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useBankReserves } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const trillionsFromMillions = (m: number | null | undefined) => (m == null ? "n/a" : `$${(m / 1_000_000).toFixed(2)} trillion`);
const trillionsFromBillions = (b: number | null | undefined) => (b == null ? "n/a" : `$${(b / 1000).toFixed(2)} trillion`);
const billions = (b: number | null | undefined) => (b == null ? "n/a" : `$${b.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} billion`);
const vs = (x: number | null | undefined, when: string) => (x == null ? `not available against ${when}` : x === 0 ? `the same as ${when}` : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}% on ${when}`);
const off = (x: number) => (x === 0 ? "the same as" : `${Math.abs(x).toFixed(2)}% ${x < 0 ? "under" : "over"}`);

/** Bank reserves, currency in circulation and the monetary base (Federal Reserve Board, via FRED). Describes what already happened; not a signal or a forecast. */
export function BankReservesCard() {
  const q = useBankReserves();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="reserves-card">
      <View><Txt variant="h2">Bank reserves and currency</Txt><Txt variant="tiny">Balances banks hold at the Federal Reserve and cash in circulation, weekly and monthly, from the Federal Reserve Board</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load bank reserves" testID="reserves-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.weekly || !d.monthly || !d.crosscheck ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Bank reserves unavailable"} testID="reserves-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="reserves-body">
            <Txt variant="label">Week ending Wednesday {ymdLabel(d.weekly.date)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small">Bank reserves at the Fed were {trillionsFromMillions(d.weekly.reserves_millions)}, {vs(d.weekly.reserves_change_1w_pct, "the week before")}. Currency in circulation was {trillionsFromMillions(d.weekly.currency_millions)}.</Txt>
            <Txt variant="tiny">Reserves: {vs(d.weekly.reserves_change_4w_pct, "four weeks ago")}, {vs(d.weekly.reserves_change_1y_pct, "a year ago")}. Past year: low {trillionsFromMillions(d.weekly.reserves_year_low_millions)}, high {trillionsFromMillions(d.weekly.reserves_year_high_millions)}; {d.weekly.reserves_rank_in_year}% of its {d.weekly.weeks_in_year} weeks were at or below this level. Currency: {vs(d.weekly.currency_change_1y_pct, "a year ago")}.</Txt>
            <Divider />
            <Txt variant="small">Monetary base (monthly): {trillionsFromBillions(d.monthly.base_billions)} in {ymdLabel(d.monthly.month)} = currency {trillionsFromBillions(d.monthly.currency_billions)} + reserve balances {trillionsFromBillions(d.monthly.reserves_billions)}; the three figures add up to within $0.1 billion{d.monthly.freshness === "OVERDUE" ? " (overdue)" : ""}.</Txt>
            <Txt variant="tiny">The base was {vs(d.monthly.base_change_1m_pct, "a month ago")}, {vs(d.monthly.base_change_1y_pct, "a year ago")}.</Txt>
            <Divider />
            <Txt variant="small">Cross-check: the weekly figures for {ymdLabel(d.crosscheck.newest.month)} ({d.crosscheck.newest.weeks} weeks) add up to an average of {billions(d.crosscheck.newest.weekly_average_billions)}, {off(d.crosscheck.newest.diff_pct)} the monthly base.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: Federal Reserve Board, via FRED</SourceLink>
    </GCard>
  );
}
