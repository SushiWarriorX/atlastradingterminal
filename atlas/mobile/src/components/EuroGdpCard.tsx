import React from "react";
import { View } from "react-native";
import { safeUrl } from "../lib/links";
import { useEuroGdp } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const quarter = (q: string) => `${q.slice(5)} ${q.slice(0, 4)}`;                       // 2026-Q3 is shown as Q3 2026
const pct = (x: number) => `${x.toFixed(2)}%`;
const signed = (x: number) => (x > 0 ? `+${x.toFixed(2)}` : x < 0 ? `-${Math.abs(x).toFixed(2)}` : "0.00");
const clause = (x: number) => (x > 0 ? `grew ${pct(x)}` : x < 0 ? `shrank ${pct(Math.abs(x))}` : "was unchanged");
const billion = (x: number) => `€${x.toFixed(1).replace(/\B(?=(\d{3})+(?!\d))/g, ",")} billion`;

/** Euro-area GDP (Eurostat's quarterly national accounts for the euro area, seasonally adjusted, published on the ECB Data Portal), quarterly. Describes growth that already happened; not a signal or a forecast. */
export function EuroGdpCard() {
  const q = useEuroGdp();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="eurogdp-card">
      <View><Txt variant="h2">Euro-area GDP</Txt><Txt variant="tiny">Eurostat's quarterly national accounts for the euro area (21 countries), seasonally adjusted, quarterly</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the euro-area GDP" testID="eurogdp-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || !d.quarter || !d.growth || !d.recent || !d.breakdown || !d.detail ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Euro-area GDP unavailable"} testID="eurogdp-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="eurogdp-body">
            <Txt variant="label">{quarter(d.quarter)} · quarterly · seasonally adjusted · real GDP{d.provisional ? " · provisional" : ""}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small">Real GDP {clause(d.growth.quarter_on_quarter)} from the previous quarter ({quarter(d.growth.previous_quarter)}) and {clause(d.growth.year_on_year)} from the same quarter a year earlier ({quarter(d.growth.year_earlier)}).</Txt>
            {d.window ? <Txt variant="tiny">Over the past {d.window.years} years ({d.window.quarters} quarters) growth on the quarter was lower than now in {d.window.share_lower_pct}% of the quarters; the middle quarter was {pct(d.window.median)}, the lowest {pct(d.window.lowest.value)} ({quarter(d.window.lowest.quarter)}) and the highest {pct(d.window.highest.value)} ({quarter(d.window.highest.quarter)}).</Txt> : null}
            <Divider />
            <Txt variant="label">Real GDP growth by quarter</Txt>
            <View style={{ gap: space.sm }} testID="eurogdp-recent">
              {d.recent.map((r) => (
                <Txt key={r.quarter} variant="small" testID={`eurogdp-quarter-${r.quarter}`}>{quarter(r.quarter)}: {signed(r.quarter_on_quarter)}% on the previous quarter, {signed(r.year_on_year)}% on a year earlier</Txt>
              ))}
            </View>
            <Divider />
            <Txt variant="label">What GDP was made of</Txt>
            <Txt variant="small">GDP at current prices in {quarter(d.breakdown.quarter)} (the newest quarter with a breakdown): {billion(d.breakdown.gdp)} for the quarter, seasonally adjusted and not annualised; domestic demand {billion(d.breakdown.domestic_demand)} plus exports {billion(d.breakdown.exports)} minus imports {billion(d.breakdown.imports)}.</Txt>
            <Txt variant="small">Contributions to that quarter's real growth of {pct(d.breakdown.growth)}: domestic demand {signed(d.breakdown.contributions.domestic_demand)} points and net trade {signed(d.breakdown.contributions.net_trade)} points (exports {signed(d.breakdown.contributions.exports)}, imports {signed(d.breakdown.contributions.imports)}).</Txt>
            <Txt variant="tiny">Check: in each of the last {d.detail.quarters_checked} quarters every figure lay inside its range and nominal GDP moved by no more than 15% in a quarter (plain checks, not the ECB's sums); the growth rates follow from the real GDP level (the ECB calculates them from it); and two checks that are the source's own arithmetic held: nominal GDP equals domestic demand plus exports minus imports in each of the last {d.detail.quarters_checked} quarters (to within 0.02 million euros), and the contributions of domestic demand, exports and imports add up to real GDP growth in each of the last {d.detail.contribution_quarters_checked} quarters (to within 0.000001 points). They show the series belong together, not that the figures are right.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: European Central Bank (euro-area GDP, from Eurostat's quarterly national accounts), via the ECB Data Portal</SourceLink>
    </GCard>
  );
}
