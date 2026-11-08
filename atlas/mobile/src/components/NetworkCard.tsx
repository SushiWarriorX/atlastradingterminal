import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useNetwork } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const n = (x: number) => x.toLocaleString("en-US");
const pc = (x: number) => `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(1)}%`;
const tone = (x: number) => (x > 0 ? color.up : x < 0 ? color.down : color.text);

function Row({ k, v, c }: { k: string; v: string; c?: string }) {
  return <View style={{ flexDirection: "row", justifyContent: "space-between", gap: space.md, paddingVertical: 3 }}><Txt variant="small" style={{ flex: 1 }}>{k}</Txt><Txt variant="body" c={c}>{v}</Txt></View>;
}

/** Bitcoin network health from mempool.space: fees, the mempool queue, the difficulty cycle and hashrate. Each part fails on its own. Not a price signal. */
export function NetworkCard() {
  const q = useNetwork();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="network-card">
      <View><Txt variant="h2">Bitcoin network</Txt><Txt variant="tiny">Fees, the queue of waiting transactions, mining difficulty and hashrate</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load network data" testID="network-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : (
          <View style={{ gap: space.md }} testID="network-body">
            {d.demo ? <Banner tone="demo" title="Demo mode" testID="network-demo">{d.fees.reason}</Banner> : null}
            {!d.demo && !d.fees.available ? <Banner tone="warn" title="Fees unavailable">{d.fees.reason}</Banner> : null}
            {d.fees.available ? (
              <View>
                <Txt variant="label">Fees and queue</Txt>
                <Row k="Fastest (next block)" v={`${d.fees.sat_per_vbyte!.fastest} sat/vB`} />
                <Row k="About an hour" v={`${d.fees.sat_per_vbyte!.hour} sat/vB`} />
                <Row k="Economy" v={`${d.fees.sat_per_vbyte!.economy} sat/vB`} />
                <Row k={`A typical transaction (${d.fees.typical_tx_vbytes} vB), fastest`} v={`${n(d.fees.typical_tx_sats_fastest!)} sats`} />
                {d.fees.mempool ? <Row k="Waiting to be confirmed" v={`${n(d.fees.mempool.transactions)} (about ${d.fees.mempool.blocks_worth} blocks)`} /> : null}
              </View>) : null}
            {!d.demo && !d.difficulty.available ? <Banner tone="warn" title="Difficulty unavailable">{d.difficulty.reason}</Banner> : null}
            {d.difficulty.available ? (
              <View>
                <Divider />
                <Txt variant="label" style={{ marginTop: space.sm }}>Mining difficulty</Txt>
                {d.difficulty.block_height != null ? <Row k="Block height" v={n(d.difficulty.block_height)} /> : null}
                <Row k="Through this 2,016-block cycle" v={`${d.difficulty.progress_pct}%`} />
                <Row k="Estimated next change" v={pc(d.difficulty.estimated_change_pct!)} c={tone(d.difficulty.estimated_change_pct!)} />
                <Row k="Blocks left · estimated date" v={`${n(d.difficulty.remaining_blocks!)} · ${d.difficulty.estimated_date ?? "n/a"}`} />
                <Txt variant="tiny">{d.difficulty.note}</Txt>
              </View>) : null}
            {!d.demo && !d.hashrate.available ? <Banner tone="warn" title="Hashrate unavailable">{d.hashrate.reason}</Banner> : null}
            {d.hashrate.available ? (
              <View>
                <Divider />
                <Txt variant="label" style={{ marginTop: space.sm }}>Hashrate</Txt>
                <Txt variant="h2">{n(d.hashrate.seven_day_average_eh!)} EH/s</Txt>
                <Txt variant="tiny">7-day average to {d.hashrate.date}{d.hashrate.changes!.length ? " · " + d.hashrate.changes!.map((c) => `${c.label} ${pc(c.change_pct)}`).join(" · ") : ""}</Txt>
                <Txt variant="tiny">{d.hashrate.note}</Txt>
              </View>) : null}
            <Txt variant="tiny">Not a price signal: fees can be near zero while price moves a lot.</Txt>
            {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: mempool.space</Txt></Pressable> : null}
          </View>)}
    </GCard>
  );
}
