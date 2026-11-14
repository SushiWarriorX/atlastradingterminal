import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useCustoms } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const bn = (x: number) => `${x < 0 ? "−" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}B`;
const monthName = (iso: string) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });

/** US customs duties (tariff revenue): collected, refunded and net, by month and fiscal year so far (Monthly Treasury Statement). Describes what already happened; not a signal. */
export function CustomsCard() {
  const q = useCustoms();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="customs-card">
      <View><Txt variant="h2">Customs duties</Txt><Txt variant="tiny">Tariff revenue the Treasury collected, refunded and kept, from the US Treasury</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the customs duties" testID="customs-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Customs duties unavailable"} testID="customs-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="customs-body">
            <Txt variant="label">{monthName(d.date!)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="hero">{bn(d.latest!.net_billions)}</Txt>
            <Txt variant="small">Kept after refunds. Collected {bn(d.latest!.gross_billions)}, paid back in refunds {bn(d.latest!.refunds_billions)}{d.latest!.refunds_share_of_gross_pct != null ? ` (${d.latest!.refunds_share_of_gross_pct}% of what was collected)` : ""}.</Txt>
            <Divider />
            <Txt variant="label">Fiscal {d.fiscal_year} so far ({d.year_so_far!.months} {d.year_so_far!.months === 1 ? "month" : "months"} from October)</Txt>
            <Txt variant="small">Kept {bn(d.year_so_far!.net_billions)} (collected {bn(d.year_so_far!.gross_billions)}, refunded {bn(d.year_so_far!.refunds_billions)}).</Txt>
            <Txt variant="tiny">Same point last year: {bn(d.year_so_far!.same_point_last_year_net_billions)}{d.year_so_far!.change_vs_last_year_pct != null ? ` · ${d.year_so_far!.change_vs_last_year_pct > 0 ? "up" : "down"} ${Math.abs(d.year_so_far!.change_vs_last_year_pct)}%` : ""}</Txt>
            <Divider />
            <Txt variant="label">Last {(d.months ?? []).length} months, kept after refunds</Txt>
            {[...(d.months ?? [])].reverse().map((m) => <Txt key={m.date} variant="small">{monthName(m.date)}: {bn(m.net_billions)} (collected {bn(m.gross_billions)}, refunded {bn(m.refunds_billions)})</Txt>)}
            <Txt variant="tiny">Checked: each month's collected minus refunded equals what was kept, and the year-so-far total equals the sum of that year's months.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Treasury, Monthly Treasury Statement</Txt></Pressable> : null}
    </GCard>
  );
}
