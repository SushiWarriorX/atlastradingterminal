import React from "react";
import { Linking, Pressable, View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useCommodityPositioning, useFuturesPositioning } from "../state/queries";
import type { FuturesPositioningData } from "../api/types";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const n = (x: number) => `${x < 0 ? "−" : ""}${Math.abs(x).toLocaleString("en-US")}`;
const moved = (x: number | null | undefined) => (x == null ? "no change shown" : x === 0 ? "unchanged" : `${x > 0 ? "up" : "down"} ${Math.abs(x).toLocaleString("en-US")}`);

/** Who holds S&P 500, Nasdaq-100, 2-year and 10-year Treasury and dollar index futures (CFTC Commitments of Traders), weekly. Checked against the report's own totals; describes what already happened, not a signal. */
export function FuturesPositioningCard() {
  return <PositioningCard id="futurespos" heading="Futures positioning" sub="Who holds stock, Treasury and dollar futures, from the CFTC" q={useFuturesPositioning()} />;
}

/** Same layout for gold, crude oil, copper and natural gas (CFTC Disaggregated report). */
export function CommodityPositioningCard() {
  return <PositioningCard id="commoditypos" heading="Commodity positioning" sub="Who holds gold, oil, copper and natural gas futures, from the CFTC" q={useCommodityPositioning()} />;
}

function PositioningCard({ id, heading, sub, q }: { id: string; heading: string; sub: string; q: { data?: FuturesPositioningData; isLoading: boolean; isError: boolean; error: unknown } }) {
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID={`${id}-card`}>
      <View><Txt variant="h2">{heading}</Txt><Txt variant="tiny">{sub}</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the positioning" testID={`${id}-error`}>{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Positioning unavailable"} testID={`${id}-unavailable`}>{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID={`${id}-body`}>
            {(d.contracts ?? []).map((c, i) => (
              <View key={c.code} style={{ gap: 2 }}>
                {i > 0 ? <Divider /> : null}
                <Txt variant="label">{c.name}{c.available ? ` · as of ${ymdLabel(c.date)}${c.freshness === "OVERDUE" ? " · overdue" : ""}` : ""}</Txt>
                {!c.available ? <Txt variant="tiny" c={color.down}>{c.reason}</Txt> : (<>
                  <Txt variant="tiny">{c.what}. {c.open_interest!.toLocaleString("en-US")} open contracts ({moved(c.open_interest_change)} from the week before).</Txt>
                  {(c.groups ?? []).map((g) => (
                    <Txt key={g.key} variant="small">{g.name}: net {n(g.net)} ({moved(g.net_change)} from the week before){g.net_rank_1y != null ? `, at or above ${g.net_rank_1y}% of the last 52 weeks` : ""}</Txt>
                  ))}
                </>)}
              </View>))}
            <Txt variant="tiny">Each week is checked against the report's own totals before it is shown.</Txt>
            <Txt variant="tiny">{d.note}</Txt>
          </View>)}
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: CFTC Commitments of Traders</Txt></Pressable> : null}
    </GCard>
  );
}
