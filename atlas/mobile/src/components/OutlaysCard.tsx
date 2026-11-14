import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useOutlays } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const bn = (x: number) => `${x < 0 ? "−" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
const move = (x: number | null) => (x == null ? "n/a" : x === 0 ? "unchanged" : `${x > 0 ? "up" : "down"} ${Math.abs(x)}%`);
const monthName = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });

/** Where US federal money goes: net outlays by purpose, receipts and the deficit for the fiscal year so far versus last year (Monthly Treasury Statement). Describes what already happened; not a signal. */
export function OutlaysCard() {
  const q = useOutlays();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="outlays-card">
      <View><Txt variant="h2">Where federal money goes</Txt><Txt variant="tiny">What the US government spent, by purpose, from the US Treasury</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the federal spending" testID="outlays-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Federal spending unavailable"} testID="outlays-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="outlays-body">
            <Txt variant="label">Fiscal {d.fiscal_year} so far ({d.months_in_year} {d.months_in_year === 1 ? "month" : "months"} from October) · through {monthName(d.date!)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="hero">{bn(d.outlays!.year_so_far_billions)}</Txt>
            <Txt variant="small">Spent, {move(d.outlays!.change_vs_last_year_pct)} from {bn(d.outlays!.same_point_last_year_billions)} at the same point last year. Income was {bn(d.receipts!.year_so_far_billions)} ({move(d.receipts!.change_vs_last_year_pct)}), so spending ran ahead of income by {bn(d.deficit!.year_so_far_billions)} ({move(d.deficit!.change_vs_last_year_pct)} from {bn(d.deficit!.same_point_last_year_billions)}).</Txt>
            <Divider />
            {(d.functions ?? []).map((f) => (
              <Txt key={f.name} variant="small">{f.name}: {bn(f.year_so_far_billions)} ({f.share_of_outlays_pct == null ? "n/a" : `${f.share_of_outlays_pct}%`} of spending), {move(f.change_vs_last_year_pct)} from {bn(f.same_point_last_year_billions)}</Txt>))}
            <Txt variant="tiny">Checked: the purposes add up to the source's own total spending, and the receipts lines to its total receipts, for the month, the year so far and last year's same point.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Treasury, Monthly Treasury Statement</Txt></Pressable> : null}
    </GCard>
  );
}
