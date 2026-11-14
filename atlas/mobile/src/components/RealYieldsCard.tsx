import React from "react";
import { Linking, Pressable, View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useRealYields } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const pc = (x: number | null | undefined) => (x == null ? "n/a" : `${x.toFixed(2)}%`);
const moved = (bp: number | null | undefined) => (bp == null ? "not available" : bp === 0 ? "unchanged" : `${bp > 0 ? "up" : "down"} ${(Math.abs(bp) / 100).toFixed(2)} points`);

/** US Treasury real (TIPS) yields and breakeven inflation, 5 to 30 years. Describes what already happened; not a forecast of inflation or prices. */
export function RealYieldsCard() {
  const q = useRealYields();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="realyields-card">
      <View><Txt variant="h2">Real yields and breakeven inflation</Txt><Txt variant="tiny">What Treasury bonds pay above inflation, from the US Treasury</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the real yields" testID="realyields-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Real yields unavailable"} testID="realyields-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="realyields-body">
            <Txt variant="label">As of {ymdLabel(d.date)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            {(d.rows ?? []).map((r, i) => (
              <View key={r.tenor} style={{ gap: 2 }}>
                {i > 0 ? <Divider /> : null}
                <Txt variant="small">{r.tenor.replace("Y", "-year")}: breakeven inflation {pc(r.breakeven_pct)} (regular yield {pc(r.nominal_pct)}, real yield {pc(r.real_pct)})</Txt>
                <Txt variant="tiny">Breakeven {moved(r.breakeven_change_1m_bp)} from a month ago and {moved(r.breakeven_change_1y_bp)} from a year ago. Real yield {moved(r.real_change_1y_bp)} from a year ago.</Txt>
              </View>))}
            <Txt variant="tiny">Compared with {d.month_ago_date ? ymdLabel(d.month_ago_date) : "a month ago (no day close enough)"} and {d.year_ago_date ? ymdLabel(d.year_ago_date) : "a year ago (no day close enough)"}. Checked: both curves are for the same day and every value is in a plausible range.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: US Treasury, par yield curve rates</Txt></Pressable> : null}
    </GCard>
  );
}
