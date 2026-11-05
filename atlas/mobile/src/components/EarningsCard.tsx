import React, { useState } from "react";
import { Pressable, View } from "react-native";
import { useEarnings } from "../state/queries";
import { useOpenAsset } from "../state/selection";
import { color, radius, space } from "../theme";
import { Chip, Txt, GCard } from "./ui";

const WINDOWS = [7, 14, 30, 60];

/** Upcoming earnings dates for the stocks on your watchlist, collapsed until asked for. Tap a row to open that stock. */
export function EarningsCard() {
  const [shown, setShown] = useState(false);
  const [days, setDays] = useState(30);
  const q = useEarnings(days, shown);
  const open = useOpenAsset();
  const d = q.data;
  return (
    <GCard style={{ padding: space.lg, gap: space.sm }} testID="earnings-card">
      <Pressable onPress={() => setShown(!shown)} accessibilityRole="button" testID="earnings-toggle" style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <View style={{ flex: 1 }}><Txt variant="h2">Earnings calendar</Txt><Txt variant="tiny">Next report dates for your watchlist stocks</Txt></View>
        <Txt variant="small" c={color.accent}>{shown ? "Hide" : "Show"}</Txt>
      </Pressable>
      {shown && (
        <View style={{ gap: space.sm }}>
          <View style={{ flexDirection: "row", gap: 4 }}>{WINDOWS.map((n) => <Chip key={n} label={`${n}d`} active={days === n} onPress={() => setDays(n)} testID={`earn-${n}`} />)}</View>
          {q.isLoading ? <Txt variant="small">Checking dates…</Txt>
            : q.isError || !d ? <Txt variant="small" c={color.down} testID="earnings-error">Couldn't load earnings dates{q.error instanceof Error ? `: ${q.error.message}` : "."}</Txt>
            : d.items.length === 0 ? <Txt variant="small" testID="earnings-empty">{d.checked === 0 ? "No stocks on your watchlist to check. Search for a stock and tap + to add it." : `None of your ${d.checked} stocks report in the next ${d.window_days} days, as far as the source knows.`}</Txt>
            : d.items.map((r) => (
              <Pressable key={r.symbol} onPress={() => open(r.instrument_id)} accessibilityRole="button" testID={`earn-row-${r.symbol}`} style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: 6 }}>
                <View style={{ flex: 1 }}><Txt variant="body">{r.symbol}</Txt><Txt variant="tiny">{r.name ?? ""}</Txt></View>
                <View style={{ alignItems: "flex-end" }}><Txt variant="body">{r.date}</Txt><Txt variant="tiny">in {r.days_away} day{r.days_away === 1 ? "" : "s"}</Txt></View>
              </Pressable>))}
          <Txt variant="tiny">Dates come from Yahoo Finance (unofficial, delayed). Confirm with the company.{d?.errors.length ? ` Could not check: ${d.errors.join("; ")}` : ""}</Txt>
        </View>)}
    </GCard>
  );
}
