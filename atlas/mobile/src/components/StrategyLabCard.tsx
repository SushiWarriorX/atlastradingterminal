import React, { useState } from "react";
import { Pressable, View } from "react-native";
import type { LabResult } from "../api/types";
import { signed } from "../lib/journal";
import { busyText } from "../lib/lab";
import { useLabRun } from "../state/queries";
import { color, radius, space } from "../theme";
import { Banner, Chip, Divider, PrimaryButton, Tag, Txt, GCard, Pill } from "./ui";
import { Sparkline } from "./Sparkline";

const LEVEL = { none: "No reliable evidence", weak: "Weak evidence", moderate: "Moderate evidence" } as const;
const pc = (x: number | null | undefined, d = 1) => (x === null || x === undefined ? "n/a" : `${signed(x, d)}%`);

function Row({ r, open, onToggle }: { r: LabResult; open: boolean; onToggle: () => void }) {
  const o = r.out_of_sample;
  return (
    <View>
      <Pressable onPress={onToggle} accessibilityRole="button" testID={`lab-row-${r.id}`} style={{ paddingVertical: 10, gap: 4 }}>
        <View style={{ flexDirection: "row", justifyContent: "space-between", gap: space.md }}>
          <View style={{ flex: 1 }}><Txt variant="body">{r.name}</Txt><Txt variant="tiny">{r.family} · {o.trades} out-of-sample trade{o.trades === 1 ? "" : "s"}</Txt></View>
          <View style={{ alignItems: "flex-end" }}><Txt variant="h2" c={(o.net_return_pct ?? 0) >= 0 ? color.up : color.down}>{pc(o.net_return_pct, 0)}</Txt><Txt variant="tiny">out of sample</Txt></View>
        </View>
        <View style={{ alignSelf: "flex-start" }}><Tag label={LEVEL[r.evidence.level]} tint={r.evidence.level === "none" ? color.warn : r.evidence.level === "weak" ? color.accent2 : color.up} /></View>
      </Pressable>
      {open && (
        <View style={{ gap: space.sm, paddingBottom: space.md }} testID={`lab-detail-${r.id}`}>
          {r.evidence.reasons.map((x, i) => <Txt key={i} variant="small">• {x}</Txt>)}
          <Sparkline values={r.curve.strategy} tint={color.accent} width={280} height={60} />
          <Txt variant="tiny">Equity over the whole history (flat axis scale).</Txt>
          <Txt variant="small">Out of sample: Sharpe {o.sharpe === null ? "n/a" : o.sharpe.toFixed(2)}, worst drop {pc(o.max_drawdown_pct, 0)}, win rate {o.win_rate_pct === null ? "n/a" : `${o.win_rate_pct.toFixed(0)}%`}, profit factor {o.profit_factor === null ? (o.no_losing_trades ? "no losses" : "n/a") : o.profit_factor.toFixed(2)}.</Txt>
          <Txt variant="small" testID={`lab-judgement-${r.id}`}>{r.judgement.plain ?? "Not enough up and down bars out of sample to compare with holding."}{r.judgement.sharpe_lower_bound ? ` Luck check: with ${r.judgement.sharpe_lower_bound.n_compared} strategies in the library to pick from, its safe lower Sharpe estimate is ${r.judgement.sharpe_lower_bound.lower.toFixed(2)} (needs to be above 0).` : r.judgement.luck_check_note ? ` ${r.judgement.luck_check_note}` : ""}</Txt>
          <Txt variant="small">Walk-forward (re-tuned as you go): {pc(r.walk_forward.net_return_pct, 0)}. Nearby settings that made money: {Math.round(r.robustness.share_positive * 100)}%. Doubled costs: {pc(r.robustness.doubled_costs_oos_return_pct, 0)}.</Txt>
          <Txt variant="small">Right now ({r.now.as_of}) the rule is {r.now.rule_position}. {r.now.conditions.map((c) => `${c.met === null ? "?" : c.met ? "✓" : "✗"} ${c.rule}`).join("; ")}</Txt>
          <Txt variant="tiny">{r.now.note}</Txt>
        </View>)}
      <Divider />
    </View>
  );
}

/** Compare tested BTC rules on history they were not tuned to. Collapsed until asked for; the server does the work. */
export function StrategyLabCard() {
  const [shown, setShown] = useState(false);
  const [market, setMarket] = useState<"spot" | "perp">("spot");
  const [tf, setTf] = useState("1d");
  const [lev, setLev] = useState(1);
  const [openId, setOpenId] = useState<string | null>(null);
  const run = useLabRun();
  const d = run.data;
  const go = () => { setOpenId(null); run.mutate({ timeframe: tf, market, leverage: market === "perp" ? lev : 1, long_short: false }); };
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="lab-card">
      <Pressable onPress={() => setShown(!shown)} accessibilityRole="button" testID="lab-toggle" style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <View style={{ flex: 1 }}><Txt variant="h2">Strategy Lab</Txt><Txt variant="tiny">Five tested BTC rules, compared after costs</Txt></View>
        <Pill label={shown ? "Hide" : "Show"} />
      </Pressable>
      {shown && (
        <View style={{ gap: space.md }}>
          <Txt variant="small">Each rule is fixed in advance and tested after fees, slippage and funding on history it was not tuned to. A rule being on now describes the rule; it is not a forecast.</Txt>
          <View style={{ flexDirection: "row", gap: 4, flexWrap: "wrap" }}>
            <Chip label="Spot" active={market === "spot"} onPress={() => setMarket("spot")} testID="lab-spot" />
            <Chip label="Perpetual" active={market === "perp"} onPress={() => setMarket("perp")} testID="lab-perp" />
            {["1d", "4h", "1h"].map((x) => <Chip key={x} label={x} active={tf === x} onPress={() => setTf(x)} testID={`lab-tf-${x}`} />)}
            {market === "perp" && [1, 2, 3].map((x) => <Chip key={x} label={`${x}x`} active={lev === x} onPress={() => setLev(x)} testID={`lab-lev-${x}`} />)}
          </View>
          <PrimaryButton label="Compare five strategies" onPress={go} busy={run.isPending} testID="lab-run" />
          {run.isPending ? <Txt variant="small" testID="lab-busy">{busyText(market, tf)}</Txt> : null}
          {run.isError ? <Banner tone="warn" title="Couldn't run the comparison" testID="lab-error">{run.error instanceof Error ? run.error.message : "Something went wrong."}</Banner> : null}
          {d && (
            <View testID="lab-results">
              <Txt variant="tiny">{d.period.from} to {d.period.to} · {d.period.bars.toLocaleString()} {d.settings.timeframe} bars · {d.data.source}</Txt>
              {d.data.demo ? <Banner tone="demo" title="Demo data">These prices are synthetic.</Banner> : null}
              {[...d.data.notes, ...d.notes].map((n, i) => <Txt key={i} variant="tiny" c={color.warn}>{n}</Txt>)}
              <Txt variant="small" style={{ marginTop: 6 }}>Buy and hold, out of sample: {pc(d.results[0]?.buy_and_hold.out_of_sample.net_return_pct, 0)}</Txt>
              <Divider />
              {d.results.map((r) => <Row key={r.id} r={r} open={openId === r.id} onToggle={() => setOpenId(openId === r.id ? null : r.id)} />)}
              <Txt variant="label" style={{ marginTop: 8 }}>What the research found so far ({d.findings.as_of}; past data, not a forecast)</Txt>
              {d.findings.points.map((x, i) => <Txt key={i} variant="small">• {x}</Txt>)}
              {d.skipped.map((s) => <Txt key={s.id} variant="tiny">{s.id}: {s.reason}</Txt>)}
              <Txt variant="tiny" style={{ marginTop: 6 }}>{d.caveats.join(" ")}</Txt>
            </View>)}
        </View>)}
    </GCard>
  );
}
