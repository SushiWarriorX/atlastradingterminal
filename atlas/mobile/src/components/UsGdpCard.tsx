import React from "react";
import { View } from "react-native";
import type { UsGdpRange } from "../api/types";
import { safeUrl } from "../lib/links";
import { useUsGdp } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const quarter = (q: string) => `${q.slice(5)} ${q.slice(0, 4)}`;                       // 2026-Q3 is shown as Q3 2026
const grouped = (x: number, digits = 1) => Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const dollars = (x: number) => `${x < 0 ? "-" : ""}$${grouped(x)} billion`;
const trillion = (x: number) => `$${(x / 1000).toFixed(3)} trillion`;
const move = (billions: number, pct: number) => (billions === 0 ? "unchanged" : `${billions > 0 ? "up" : "down"} $${grouped(billions)} billion (${Math.abs(pct).toFixed(2)}%)`);
const yearMove = (pct: number) => (pct === 0 ? "unchanged" : `${pct > 0 ? "up" : "down"} ${Math.abs(pct).toFixed(2)}%`);
const clause = (x: number) => (x > 0 ? `grew ${x.toFixed(1)}%` : x < 0 ? `shrank ${Math.abs(x).toFixed(1)}%` : "was unchanged");
const plain = (x: number) => `${x.toFixed(1)}%`;
const signed = (x: number, digits = 2) => (x > 0 ? `+${x.toFixed(digits)}` : x < 0 ? `-${Math.abs(x).toFixed(digits)}` : (0).toFixed(digits));
const span = (r: UsGdpRange) =>
  `Over the last ${Math.round(r.quarters / 4)} years (${r.quarters} quarters) real growth ran from ${plain(r.lowest.value)} (${quarter(r.lowest.quarter)}) to ${plain(r.highest.value)} (${quarter(r.highest.quarter)}); ${r.share_lower_pct}% of those quarters were lower than now.`;

/** US GDP by component (the Bureau of Economic Analysis' quarterly national accounts, via FRED). Describes what already happened; not a signal or a forecast. */
export function UsGdpCard() {
  const q = useUsGdp();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="usgdp-card">
      <View><Txt variant="h2">US GDP by component</Txt><Txt variant="tiny">The quarterly national accounts from the Bureau of Economic Analysis: what the economy produced, what it was spent on, and how fast it grew</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load US GDP" testID="usgdp-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.quarter || !d.gdp || !d.growth || !d.components || !d.trade || !d.recent || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "US GDP unavailable"} testID="usgdp-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="usgdp-body">
            <Txt variant="label">{quarter(d.quarter)} · quarterly · annual rate · seasonally adjusted{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small" testID="usgdp-headline">The US economy produced {trillion(d.gdp.level_billions)} of goods and services at an annual rate in {quarter(d.quarter)}, {move(d.gdp.change_billions, d.gdp.change_pct)} on the quarter before and {yearMove(d.gdp.change_year_pct)} on a year earlier, in the prices of the time.</Txt>
            <Txt variant="small" testID="usgdp-growth">With price changes taken out, real GDP {clause(d.growth.pct)} at an annual rate in {quarter(d.quarter)} ({plain(d.growth.quarter_before_pct)} in the quarter before and {plain(d.growth.year_ago_pct)} a year earlier).</Txt>
            <Txt variant="tiny">{span(d.growth.range)}</Txt>
            <Divider />
            <Txt variant="label">What it was spent on, and what it added to growth</Txt>
            <View style={{ gap: space.sm }} testID="usgdp-components">
              {d.components.map((c) => (
                <Txt key={c.key} variant="small" testID={`usgdp-part-${c.key}`}>{c.label}: {dollars(c.level_billions)}, {plain(c.share_pct)} of GDP, {signed(c.contribution_points)} points of the real growth</Txt>
              ))}
            </View>
            <Txt variant="tiny" testID="usgdp-trade">Net exports are exports of {dollars(d.trade.exports_billions)} minus imports of {dollars(d.trade.imports_billions)}. The four contributions add to {signed(d.growth.contributions_sum_points)} points; the published growth is {plain(d.growth.pct)}.</Txt>
            <Divider />
            <Txt variant="label">Real growth by quarter, at an annual rate</Txt>
            <View style={{ gap: space.sm }} testID="usgdp-recent">
              {d.recent.map((r) => <Txt key={r.quarter} variant="small" testID={`usgdp-quarter-${r.quarter}`}>{quarter(r.quarter)}: {signed(r.growth_pct, 1)}%</Txt>)}
            </View>
            <Txt variant="tiny">Check: in each of the {d.detail.quarters_checked} quarters from {quarter(d.detail.first_quarter)} to {quarter(d.detail.last_quarter)} the twelve series covered the same quarters with none missing and every figure lay inside its range (plain checks, not the source's sums); three checks that follow from the national accounts' own arithmetic held: consumer spending plus private investment plus government spending plus net exports equal GDP (largest gap {d.detail.largest_gdp_gap.toFixed(3)} billion, which is rounding), exports minus imports equal net exports (largest gap {d.detail.largest_net_exports_gap.toFixed(3)} billion, rounding), and the four contributions add up to real growth (largest gap {d.detail.largest_contribution_gap.toFixed(2)} points, rounding). These show the series belong together, not that the figures are right.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: US Bureau of Economic Analysis (national accounts), via FRED</SourceLink>
    </GCard>
  );
}
