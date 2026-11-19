import React, { useState } from "react";
import { View } from "react-native";
import type { TrackerEntry } from "../api/types";
import { useStrategyTracker } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Tag, TextButton, Txt } from "./ui";

const pc = (x: number | null | undefined) => (x === null || x === undefined ? "n/a" : `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x) >= 1000 ? Math.round(Math.abs(x)).toLocaleString("en-US") : Math.abs(x).toFixed(1)}%`);
const tone = (x: number | null | undefined) => (x === null || x === undefined ? color.dim : x > 0 ? color.up : x < 0 ? color.down : color.text);
const EVID: Record<string, string> = { none: "No reliable evidence", weak: "Weak evidence", moderate: "Moderate evidence" };

function Row({ k, v, c }: { k: string; v: string; c?: string }) {
  return <View style={{ flexDirection: "row", justifyContent: "space-between", gap: space.md, paddingVertical: 3 }}><Txt variant="small" style={{ flex: 1 }}>{k}</Txt><Txt variant="body" c={c}>{v}</Txt></View>;
}

function Entry({ e }: { e: TrackerEntry }) {
  const [more, setMore] = useState(false);
  const s = e.snapshot, fw = e.forward;
  return (
    <View style={{ gap: space.sm }} testID={`tracker-${e.id}`}>
      <View style={{ flexDirection: "row", gap: 6, alignItems: "center", flexWrap: "wrap" }}><Txt variant="body" style={{ fontWeight: "700" }}>{e.name}</Txt><Tag label={EVID[s.evidence.level]} tint={s.evidence.level === "none" ? color.warn : undefined} /></View>
      <Txt variant="tiny">Added {e.added_at} · {e.family}</Txt>
      <Txt variant="small">{e.idea}</Txt>
      <Txt variant="label">Backtest (frozen on {e.added_at})</Txt>
      <Row k="Whole history, rule vs holding BTC" v={`${pc(s.full.net_return_pct)} vs ${pc(s.buy_and_hold.full.net_return_pct)}`} c={tone(s.full.net_return_pct)} />
      <Row k="Last 30% (not used to design it)" v={`${pc(s.out_of_sample.net_return_pct)} vs ${pc(s.buy_and_hold.out_of_sample.net_return_pct)}`} c={tone(s.out_of_sample.net_return_pct)} />
      <Row k="Worst drop, rule vs holding" v={`${pc(s.full.max_drawdown_pct)} vs ${pc(s.buy_and_hold.full.max_drawdown_pct)}`} c={color.down} />
      {s.evidence.reasons.map((r, i) => <Txt key={i} variant="tiny" c={color.warn}>• {r}</Txt>)}
      <Txt variant="label">Forward record (bars after {e.added_at})</Txt>
      {fw === null ? <Txt variant="small">Forward tracking needs real prices, so it is not shown in demo mode.</Txt>
        : fw.error ? <Txt variant="small" c={color.warn}>{fw.error}</Txt>
        : (
          <View testID={`tracker-forward-${e.id}`}>
            {fw.strategy ? <Row k={`${fw.days} days, rule vs holding BTC`} v={`${pc(fw.strategy.return_pct)} vs ${pc(fw.buy_and_hold?.return_pct)}`} c={tone(fw.strategy.return_pct)} /> : null}
            <Row k="Position now" v={fw.position_now === "long" ? "In BTC (long)" : "Flat (in cash)"} />
            <Txt variant="tiny" c={fw.enough ? undefined : color.warn}>{fw.note}</Txt>
          </View>)}
      {more ? (
        <View style={{ gap: 4 }}>
          <Txt variant="label">The rule</Txt>
          {e.rule ? <><Txt variant="small">{e.rule.summary}</Txt><Txt variant="tiny">Entry: {e.rule.entry}</Txt><Txt variant="tiny">Exit: {e.rule.exit}</Txt></> : null}
          <Txt variant="tiny">Why it was tested: {e.why}</Txt>
          <Txt variant="tiny">Nearby settings made money out of sample in {Math.round(s.robustness.share_positive * 100)}% of cases; with doubled costs {pc(s.robustness.doubled_costs_oos_return_pct)}. The luck check counted {s.library_size} rules.</Txt>
          {fw?.conditions ? fw.conditions.map((c, i) => <Txt key={i} variant="tiny">{c.met === null ? "·" : c.met ? "✓" : "✗"} {c.rule}: {c.value}</Txt>) : null}
        </View>) : null}
      <TextButton label={more ? "Hide details" : "Show the rule and details"} onPress={() => setMore(!more)} testID={`tracker-more-${e.id}`} />
    </View>
  );
}

/** Strategies added by the research loop: a frozen backtest on all BTC history up to the day each was added, and a forward record on the bars after. Research only. */
export function StrategyTrackerCard() {
  const q = useStrategyTracker();
  const d = q.data;
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="tracker-card">
      <View><Txt variant="h2">Strategy tracker</Txt><Txt variant="tiny">New rules: a frozen backtest, then a forward record on new bars</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the tracker" testID="tracker-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : (
          <View style={{ gap: space.md }} testID="tracker-body">
            {d.entries.length === 0 ? <Txt variant="small">No strategies have been added to the tracker yet.</Txt> : null}
            {d.entries.map((e, i) => <View key={e.id}>{i > 0 && <Divider />}<Entry e={e} /></View>)}
            {d.notes.map((n, i) => <Txt key={i} variant="tiny">{n}</Txt>)}
          </View>)}
    </GCard>
  );
}
