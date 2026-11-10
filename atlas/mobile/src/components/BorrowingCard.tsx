import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useBorrowing } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const day = (iso?: string | null) => (iso ? new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }) : "");
const monthYear = (iso?: string) => (iso ? new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" }) : "");
const bn = (x: number) => `${x < 0 ? "-" : x > 0 ? "+" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
const plain = (x: number) => `$${x.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
const vsYear = (x: number | null | undefined) => (x == null ? "No year-ago figure for this point" : `Same point a year earlier: ${bn(x)}`);

/** US Treasury marketable borrowing from the Daily Treasury Statement. Describes what already happened; not a signal. */
export function BorrowingCard() {
  const q = useBorrowing();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="borrowing-card">
      <View><Txt variant="h2">Treasury borrowing</Txt><Txt variant="tiny">New debt the US sold and old debt it paid back, from the US Treasury</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the borrowing figures" testID="borrowing-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Borrowing figures unavailable"} testID="borrowing-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="borrowing-body">
            <Txt variant="label">{monthYear(d.date)} so far · through {day(d.date)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="hero">{bn(d.month_to_date!.net_billions)}</Txt>
            <Txt variant="small">Net new borrowing this month. {vsYear(d.month_to_date!.year_ago_net_billions)}.</Txt>
            <Txt variant="tiny">Sold {plain(d.month_to_date!.issues_billions)} · paid back {plain(d.month_to_date!.redemptions_billions)}</Txt>
            <Divider />
            <Txt variant="label">Fiscal {d.fiscal_year} so far · since Oct 1</Txt>
            <Txt variant="h2">{bn(d.fiscal_year_to_date!.net_billions)}</Txt>
            <Txt variant="small">{vsYear(d.fiscal_year_to_date!.year_ago_net_billions)}.</Txt>
            <Txt variant="tiny">Sold {plain(d.fiscal_year_to_date!.issues_billions)} · paid back {plain(d.fiscal_year_to_date!.redemptions_billions)}</Txt>
            <Divider />
            <Txt variant="label">By type, net this month</Txt>
            {(d.by_security ?? []).map((r) => (
              <View key={r.key} style={{ flexDirection: "row", justifyContent: "space-between", gap: space.md }}>
                <Txt variant="small" style={{ flex: 1 }}>{r.label}</Txt>
                <Txt variant="small">{bn(r.mtd_net_billions)}</Txt>
              </View>))}
            {d.mtd_check ? <Txt variant="tiny" c={d.mtd_check.match ? undefined : color.down}>{d.mtd_check.match ? "Checked: the daily amounts add up to the source's own month-to-date totals." : "DOES NOT MATCH: the daily amounts differ from the source's own month-to-date totals."}</Txt> : null}
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Treasury FiscalData</Txt></Pressable> : null}
    </GCard>
  );
}
