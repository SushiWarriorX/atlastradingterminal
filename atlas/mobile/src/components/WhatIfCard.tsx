import React, { useState } from "react";
import { Pressable, TextInput, View } from "react-native";
import { useWhatIf } from "../state/queries";
import { color, radius, space } from "../theme";
import { Banner, Chip, Divider, GCard, Pill, Skeleton, Tag, Txt } from "./ui";

const AMOUNTS = [500, 1000, 5000, 10000];
const usd = (x: number) => `${x < 0 ? "−" : ""}$${Math.abs(x).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
const pc = (x: number, signed = true) => `${signed && x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(1)}%`;
const tone = (x: number) => (x > 0 ? color.up : x < 0 ? color.down : color.text);

function Row({ k, v, c }: { k: string; v: string; c?: string }) {
  return <View style={{ flexDirection: "row", justifyContent: "space-between", gap: space.md, paddingVertical: 4 }}><Txt variant="small" style={{ flex: 1 }}>{k}</Txt><Txt variant="body" c={c}>{v}</Txt></View>;
}
function Block({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return <View style={{ gap: 6 }}><View><Txt variant="label">{title}</Txt>{sub ? <Txt variant="tiny">{sub}</Txt> : null}</View>{children}</View>;
}

/** "What if I had bought it?": replays buying this asset in the past from its own daily closes. History only; it predicts nothing. */
export function WhatIfCard({ assetId, symbol }: { assetId: string; symbol: string }) {
  const [shown, setShown] = useState(false);
  const [amount, setAmount] = useState(1000);
  const [custom, setCustom] = useState("");
  const q = useWhatIf(assetId, amount, shown);
  const d = q.data;
  const apply = (t: string) => {
    const digits = t.replace(/[^0-9]/g, "").slice(0, 8);
    setCustom(digits);
    const n = parseInt(digits, 10);
    if (n >= 1 && n <= 10_000_000) setAmount(n);
  };
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="whatif-card">
      <Pressable onPress={() => setShown(!shown)} accessibilityRole="button" testID="whatif-toggle" style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <View style={{ flex: 1 }}><Txt variant="h2">What if I had bought {symbol}?</Txt><Txt variant="tiny">Replays the past: one purchase, monthly buying, every start date, stops and targets</Txt></View>
        <Pill label={shown ? "Hide" : "Show"} />
      </Pressable>
      {shown && (
        <View style={{ gap: space.lg }}>
          <View style={{ gap: 6 }}>
            <Txt variant="label">Amount</Txt>
            <View style={{ flexDirection: "row", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
              {AMOUNTS.map((n) => <Chip key={n} label={usd(n)} active={amount === n && !custom} onPress={() => { setCustom(""); setAmount(n); }} testID={`whatif-amt-${n}`} />)}
              <TextInput value={custom} onChangeText={apply} placeholder="Other" placeholderTextColor={color.faint} keyboardType="number-pad" accessibilityLabel="Other amount in dollars" testID="whatif-custom"
                style={{ minWidth: 80, paddingHorizontal: 12, paddingVertical: 7, borderRadius: radius.pill, backgroundColor: color.surface2, color: color.text }} />
            </View>
          </View>
          {q.isLoading ? <View style={{ gap: space.md }} testID="whatif-loading">{[0, 1, 2].map((i) => <Skeleton key={i} h={44} />)}</View>
            : q.isError || !d ? <Banner tone="warn" title="Couldn't run the simulation" testID="whatif-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
            : (
              <View style={{ gap: space.lg }} testID="whatif-body">
                {d.prov.status === "DEMO" ? <Banner tone="demo" title="Demo data">These prices are synthetic. The results below are not real history.</Banner> : null}
                <Txt variant="tiny">Daily closes from {d.from} to {d.to} · {d.prov.provider} · {d.prov.status.toLowerCase()} · {d.adjustment}</Txt>
                {d.notes.map((n, i) => <Txt key={i} variant="tiny" c={color.warn}>{n}</Txt>)}

                <Block title="1 · One purchase, held to today" sub={`If you had put in ${usd(d.amount)} on that day`}>
                  {d.lump_sum.map((x, i) => (
                    <View key={x.label}>{i > 0 && <Divider />}
                      <View style={{ paddingVertical: 4 }} testID={`whatif-lump-${i}`}>
                        <Row k={`${x.label} (${x.buy_date})`} v={`${usd(x.value_now)} · ${pc(x.return_pct)}`} c={tone(x.return_pct)} />
                        <Txt variant="tiny">{x.per_year_pct !== null ? `${pc(x.per_year_pct)} per year · ` : ""}it dipped to {pc(x.lowest_vs_cost_pct)} versus what you paid, was below cost on {x.days_below_cost} days, and at one point had fallen {pc(Math.abs(x.max_drawdown_pct), false)} from its peak.</Txt>
                      </View>
                    </View>))}
                </Block>

                {d.monthly.length > 0 && (
                  <Block title="2 · The same amount every month" sub="Bought on the first trading day of each month">
                    {d.monthly.map((m, i) => (
                      <View key={m.label}>{i > 0 && <Divider />}
                        <View style={{ paddingVertical: 4 }} testID={`whatif-monthly-${i}`}>
                          <Row k={m.label} v={`${usd(m.value_now)} · ${pc(m.return_pct)}`} c={tone(m.return_pct)} />
                          <Txt variant="tiny">{m.buys} buys, {usd(m.invested)} in total, average price ${m.average_price.toFixed(2)}. The same total in one go at the start: {pc(m.same_money_lump_sum_return_pct)}.</Txt>
                        </View>
                      </View>))}
                  </Block>)}

                {d.every_start.length > 0 && (
                  <Block title="3 · Whichever day you bought" sub="Every possible start date, so you can see how much timing luck matters">
                    {d.every_start.map((e, i) => (
                      <View key={e.label}>{i > 0 && <Divider />}
                        <View style={{ paddingVertical: 4 }} testID={`whatif-every-${i}`}>
                          <Txt variant="body">{e.label}</Txt>
                          <Row k="Worst start" v={`${pc(e.worst_pct)} (bought ${e.worst_buy_date})`} c={tone(e.worst_pct)} />
                          <Row k="Typical (middle)" v={pc(e.median_pct)} c={tone(e.median_pct)} />
                          <Row k="Best start" v={`${pc(e.best_pct)} (bought ${e.best_buy_date})`} c={tone(e.best_pct)} />
                          <Txt variant="tiny">Made money in {Math.round(e.share_positive * 100)}% of starts; lost 20% or more in {Math.round(e.share_lost_20 * 100)}%. {e.note}</Txt>
                        </View>
                      </View>))}
                  </Block>)}

                {d.exit_rules.length > 0 && (
                  <Block title="4 · With a rule for getting out" sub="Checked on daily closes only">
                    {d.exit_rules.map((blk, i) => (
                      <View key={blk.label} style={{ paddingVertical: 4 }} testID={`whatif-exit-${i}`}>
                        {i > 0 && <Divider />}
                        <Txt variant="body">{blk.label}</Txt>
                        {blk.rules.map((r) => <Row key={r.rule} k={`${r.label}${r.sold && r.sold_on ? ` (sold ${r.sold_on})` : ""}`} v={pc(r.result_pct)} c={tone(r.result_pct)} />)}
                      </View>))}
                  </Block>)}

                {d.bootstrap ? (
                  <Block title="5 · 2,000 shuffled years" sub="Made-up years built by reshuffling this asset's own past daily moves">
                    <View testID="whatif-boot">
                      <Tag label="Simulation, not a forecast" tint={color.warn} />
                      <Row k="Bad year (1 in 20 is worse)" v={pc(d.bootstrap.p5_pct)} c={tone(d.bootstrap.p5_pct)} />
                      <Row k="Typical year" v={pc(d.bootstrap.median_pct)} c={tone(d.bootstrap.median_pct)} />
                      <Row k="Good year (1 in 20 is better)" v={pc(d.bootstrap.p95_pct)} c={tone(d.bootstrap.p95_pct)} />
                      <Txt variant="tiny">Ended higher in {Math.round(d.bootstrap.share_positive * 100)}% of the made-up years and lost 20% or more in {Math.round(d.bootstrap.share_lost_20 * 100)}%. A typical year had a dip of {pc(d.bootstrap.typical_worst_dip_pct)} along the way. {d.bootstrap.note}</Txt>
                    </View>
                  </Block>) : null}

                <View style={{ gap: 2 }}>{d.caveats.map((c, i) => <Txt key={i} variant="tiny">{c}</Txt>)}</View>
              </View>)}
        </View>)}
    </GCard>
  );
}
