import React from "react";
import { View } from "react-native";
import { atOrBelow, ymdLabel } from "../lib/format";
import { crudeText } from "../lib/gasoline";
import { safeUrl } from "../lib/links";
import { useGasolinePrices } from "../state/queries";
import { space } from "../theme";
import { Banner, Divider, GCard, Skeleton, SourceLink, Txt } from "./ui";

const usd3 = (x: number | null | undefined) => (x == null ? "n/a" : `$${x.toFixed(3)}`);
const usd2 = (x: number | null | undefined) => (x == null ? "n/a" : `$${x.toFixed(2)}`);
const cents = (x: number | null | undefined) => (x == null ? "not available on the week" : x === 0 ? "unchanged on the week" : `${x > 0 ? "up" : "down"} ${(Math.abs(x) * 100).toFixed(1)} cents on the week`);
const vs = (x: number | null | undefined, when: string) => (x == null ? `not available against ${when}` : x === 0 ? `the same as ${when}` : `${x > 0 ? "up" : "down"} ${Math.abs(x).toFixed(1)}% on ${when}`);

/** US regular gasoline, weekly national average (US Energy Information Administration, via FRED). Describes what already happened; not a signal or a forecast. */
export function GasolinePricesCard() {
  const q = useGasolinePrices();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  const where = atOrBelow(d?.rank_in_year, d?.weeks_in_year, "weeks", "price");
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="gasoline-card">
      <View><Txt variant="h2">Gasoline prices</Txt><Txt variant="tiny">Regular gasoline at the pump, weekly US average, from the US Energy Information Administration</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load gasoline prices" testID="gasoline-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available || d.price == null || !d.crude ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Gasoline prices unavailable"} testID="gasoline-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="gasoline-body">
            <Txt variant="label">Monday {ymdLabel(d.date)}{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Txt variant="small">Regular gasoline {usd3(d.price)} a gallon: {d.reading}.</Txt>
            <Txt variant="tiny">{cents(d.change_1w)}, {vs(d.change_4w_pct, "four weeks ago")}, {vs(d.change_1y_pct, "a year ago")}. Past year: low {usd3(d.year_low)}, high {usd3(d.year_high)}{where ? `; ${where}` : "."}</Txt>
            <Divider />
            <Txt variant="small" testID="gasoline-crude">{crudeText(d.crude, d.date)}</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      <SourceLink url={link}>Source: US Energy Information Administration, via FRED</SourceLink>
    </GCard>
  );
}
