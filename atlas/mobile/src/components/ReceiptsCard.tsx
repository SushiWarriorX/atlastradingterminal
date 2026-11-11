import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useReceipts } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const bn = (x: number) => `${x < 0 ? "−" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
const move = (x: number | null) => (x == null ? "n/a" : x === 0 ? "unchanged" : `${x > 0 ? "up" : "down"} ${Math.abs(x)}%`);
const monthName = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });

/** Where US federal revenue comes from: the seven receipt categories for the fiscal year so far versus last year (Monthly Treasury Statement). Describes what already happened; not a signal. */
export function ReceiptsCard() {
  const q = useReceipts();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="receipts-card">
      <View><Txt variant="h2">Where federal revenue comes from</Txt><Txt variant="tiny">Taxes the US government kept, by source, from the US Treasury</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the federal receipts" testID="receipts-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Federal receipts unavailable"} testID="receipts-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="receipts-body">
            <Txt variant="label">Fiscal {d.fiscal_year} so far ({d.months_in_year} {d.months_in_year === 1 ? "month" : "months"} from October) · through {monthName(d.date!)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="hero">{bn(d.total!.year_so_far_billions)}</Txt>
            <Txt variant="small">{move(d.total!.change_vs_last_year_pct)} from {bn(d.total!.same_point_last_year_billions)} at the same point last year. {monthName(d.date!)} alone: {bn(d.total!.month_billions)}.</Txt>
            <Divider />
            {(d.categories ?? []).map((c) => (
              <View key={c.name} style={{ gap: 2 }}>
                <Txt variant="small">{c.name}: {bn(c.year_so_far_billions)} ({c.share_of_year_pct == null ? "n/a" : `${c.share_of_year_pct}%`} of the year so far), {move(c.change_vs_last_year_pct)} from {bn(c.same_point_last_year_billions)}</Txt>
              </View>))}
            <Txt variant="tiny">Checked: the seven sources add up to the source's own total for the month, the year so far and last year's same point, and on-budget plus off-budget equals it too.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Treasury, Monthly Treasury Statement</Txt></Pressable> : null}
    </GCard>
  );
}
