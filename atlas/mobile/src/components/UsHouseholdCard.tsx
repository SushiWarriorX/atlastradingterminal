import React from "react";
import { View } from "react-native";
import type { UsHouseholdRange } from "../api/types";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useUsHousehold } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const quarter = (q: string) => `${q.slice(5)} ${q.slice(0, 4)}`;                       // 2026-Q3 is shown as Q3 2026
const grouped = (x: number, digits = 1) => Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const amount = (x: number) => `${x < 0 ? "-" : ""}$${Math.abs(x) >= 1000 ? `${(Math.abs(x) / 1000).toFixed(3)} trillion` : `${grouped(x)} billion`}`;
const plain = (x: number) => `${x.toFixed(1)}%`;
const move = (pct: number) => (pct === 0 ? "unchanged" : `${pct > 0 ? "up" : "down"} ${Math.abs(pct).toFixed(2)}%`);
const swing = (billions: number) => (billions === 0 ? "unchanged" : `${billions > 0 ? "up" : "down"} $${grouped(billions)} billion`);
const signed = (x: number) => (x > 0 ? `+${x.toFixed(2)}` : x < 0 ? `-${Math.abs(x).toFixed(2)}` : (0).toFixed(2));
const from = (now: number, then: number) => (now === then ? "unchanged from" : `${now > then ? "up" : "down"} from`);
const span = (r: UsHouseholdRange) =>
  `Over the last ${Math.round(r.months / 12)} years (${r.months} months) the saving rate ran from ${plain(r.lowest.value)} (${ymdLabel(r.lowest.month)}) to ${plain(r.highest.value)} (${ymdLabel(r.highest.month)}); ${r.share_lower_pct}% of those months were lower than now.`;

/** US household income, spending and saving (the Bureau of Economic Analysis' monthly Personal Income and Outlays and the quarterly split of consumer spending, via FRED). Describes what already happened; not a signal or a forecast. */
export function UsHouseholdCard() {
  const q = useUsHousehold();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="ushousehold-card">
      <View><Txt variant="h2">US household income and saving</Txt><Txt variant="tiny">What households earned, paid in tax, spent and saved each month, from the Bureau of Economic Analysis, with the quarterly split of consumer spending</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load US household figures" testID="ushousehold-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.month || !d.saving || !d.income || !d.outlays || !d.split || !d.recent || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US household figures unavailable"} testID="ushousehold-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="ushousehold-body">
            <Txt variant="label">{ymdLabel(d.month)} · monthly · annual rate · seasonally adjusted{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="ushousehold-headline">Households saved {plain(d.saving.rate_pct)} of their after-tax income in {ymdLabel(d.month)}. That is {from(d.saving.rate_pct, d.saving.month_before_pct)} {plain(d.saving.month_before_pct)} the month before and {from(d.saving.rate_pct, d.saving.year_ago_pct)} {plain(d.saving.year_ago_pct)} a year earlier.</Txt>
            <Txt variant="tiny" testID="ushousehold-range">{span(d.saving.range)}</Txt>
            <Divider />
            <Txt variant="label">Income, tax, spending and saving, at an annual rate</Txt>
            <View style={{ gap: space.sm }} testID="ushousehold-income">
              {d.income.map((l) => (
                <Txt key={l.key} variant="small" testID={`ushousehold-line-${l.key}`}>{l.label}: {amount(l.level_billions)}, {move(l.change_pct)} on the month and {move(l.change_year_pct)} on a year earlier</Txt>
              ))}
              <Txt variant="small" testID="ushousehold-outlays">Spent (personal outlays): {amount(d.outlays.level_billions)}, {move(d.outlays.change_pct)} on the month and {move(d.outlays.change_year_pct)} on a year earlier</Txt>
              {d.outlays.parts.map((p) => (
                <Txt key={p.key} variant="small" testID={`ushousehold-part-${p.key}`}>{p.label}: {amount(p.level_billions)}, {plain(p.share_pct)} of what was spent{p.change_pct == null || p.change_year_pct == null ? "" : `, ${move(p.change_pct)} on the month and ${move(p.change_year_pct)} on a year earlier`}</Txt>
              ))}
              <Txt variant="small" testID="ushousehold-saving">Saved (disposable income minus what was spent): {amount(d.saving.level_billions)}, {swing(d.saving.change_billions)} on the month and {swing(d.saving.change_year_billions)} on a year earlier</Txt>
            </View>
            <Divider />
            <Txt variant="label">Consumer spending by type, {quarter(d.split.quarter)} (quarterly)</Txt>
            <View style={{ gap: space.sm }} testID="ushousehold-split">
              <Txt variant="small" testID="ushousehold-split-total">Consumer spending in total: {amount(d.split.total_billions)} at an annual rate, {move(d.split.total_change_year_pct)} on a year earlier</Txt>
              {d.split.parts.map((p) => (
                <Txt key={p.key} variant="small" testID={`ushousehold-type-${p.key}`}>{p.label}: {amount(p.level_billions)}, {plain(p.share_pct)} of consumer spending, {move(p.change_year_pct)} on a year earlier</Txt>
              ))}
            </View>
            <Divider />
            <Txt variant="label">The last six months</Txt>
            <View style={{ gap: space.sm }} testID="ushousehold-recent">
              {d.recent.map((r) => <Txt key={r.month} variant="small" testID={`ushousehold-month-${r.month}`}>{ymdLabel(r.month)}: saving rate {plain(r.saving_rate_pct)}, income after tax {signed(r.income_change_pct)}%, consumer spending {signed(r.spending_change_pct)}% on the month before</Txt>)}
            </View>
            <Txt variant="tiny" testID="ushousehold-check">Check: in each of the {d.detail.months_checked} months from {ymdLabel(d.detail.first_month)} to {ymdLabel(d.detail.last_month)} and the {d.detail.quarters_checked} quarters from {quarter(d.detail.first_quarter)} to {quarter(d.detail.last_quarter)} the twelve series covered the same months or quarters with none missing and every figure lay inside its range (plain checks, not the source's sums); the source's own accounting held, which shows that the series belong to one release, not that the figures are right: personal income minus taxes equalled disposable income and disposable income minus spending equalled saving (largest gaps {d.detail.largest_income_gap.toFixed(1)} and {d.detail.largest_saving_gap.toFixed(1)} billion, the rounding of the published tenths), the saving rate equalled saving over disposable income (largest gap {d.detail.largest_rate_gap.toFixed(3)} points), the three types of consumer spending added up to the quarterly total (largest gap {d.detail.largest_split_gap.toFixed(3)} billion) and consumer spending plus interest never exceeded outlays (the rest was never below {amount(d.detail.smallest_other_outlays)}). One check is between two tables: in {d.detail.quarters_compared} quarters the quarterly consumer spending equalled the average of its three monthly figures to within {d.detail.largest_mean_gap.toFixed(3)} billion.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: US Bureau of Economic Analysis (personal income and outlays), via FRED</SourceLink>
    </GCard>
  );
}
