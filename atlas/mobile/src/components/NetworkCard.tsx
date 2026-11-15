import React from "react";
import { Linking, Pressable, View } from "react-native";
import { ymdLabel } from "../lib/format";
import { safeUrl } from "../lib/links";
import { useNetwork } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Txt } from "./ui";

const n = (x: number) => x.toLocaleString("en-US");
const btc = (x: number, max = 2) => x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: max });
const pc = (x: number) => `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(1)}%`;
const tone = (x: number) => (x > 0 ? color.up : x < 0 ? color.down : color.text);

function Row({ k, v, c }: { k: string; v: string; c?: string }) {
  return <View style={{ flexDirection: "row", justifyContent: "space-between", gap: space.md, paddingVertical: 3 }}><Txt variant="small" style={{ flex: 1 }}>{k}</Txt><Txt variant="body" c={c}>{v}</Txt></View>;
}

/** Bitcoin network health from mempool.space: fees, the mempool queue, the difficulty cycle, hashrate, who found the blocks and what the miners were paid. Each part fails on its own. Not a price signal. */
export function NetworkCard() {
  const q = useNetwork();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="network-card">
      <View><Txt variant="h2">Bitcoin network</Txt><Txt variant="tiny">Fees, the queue of waiting transactions, mining difficulty, hashrate, which pools found the blocks and what miners were paid</Txt></View>
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
            {!d.demo && !d.pools.available ? <Banner tone="warn" title="Mining pools unavailable" testID="network-pools-unavailable">{d.pools.reason}</Banner> : null}
            {d.pools.available ? (
              <View testID="network-pools">
                <Divider />
                <Txt variant="label" style={{ marginTop: space.sm }}>Who found the blocks (last {d.pools.headline_window})</Txt>
                {d.pools.top_pools!.map((p) => <Row key={p.name} k={p.name} v={`${p.share_pct.toFixed(1)}% · ${n(p.blocks)} blocks`} />)}
                <Row k="All other named pools" v={`${d.pools.others_pct!.toFixed(1)}%`} />
                <Row k="Miners the source could not name" v={`${d.pools.unidentified_pct!.toFixed(1)}%`} />
                {d.pools.windows!.map((w) => <Txt key={w.label} variant="small" style={{ marginTop: 2 }}>{w.label}: largest {w.top_pool_pct.toFixed(1)}% · top 3 {w.top3_pct.toFixed(1)}% · {w.nakamoto === null ? "no majority among named pools" : `${w.nakamoto} pools for a majority`} · HHI {n(w.hhi)}</Txt>)}
                <Txt variant="tiny" style={{ marginTop: 2 }}>Shares of all blocks in rolling windows that end at the newest block, as of this request.</Txt>
                <Txt variant="tiny">{d.pools.note}</Txt>
              </View>) : null}
            {!d.demo && !d.revenue.available ? <Banner tone="warn" title="Miner revenue unavailable" testID="network-revenue-unavailable">{d.revenue.reason}</Banner> : null}
            {d.revenue.available ? (
              <View testID="network-revenue">
                <Divider />
                <Txt variant="label" style={{ marginTop: space.sm }}>What miners were paid (last {d.revenue.blocks} blocks, about a day)</Txt>
                <Row k="In all" v={`${btc(d.revenue.reward_btc!)} BTC`} />
                <Row k={`Block subsidy (${d.revenue.subsidy_per_block_btc} a block)`} v={`${btc(d.revenue.subsidy_btc!)} BTC`} />
                <Row k="Transaction fees" v={`${btc(d.revenue.fees_btc!, 4)} BTC`} />
                <Txt variant="small" style={{ marginTop: 2 }}>Fees were {d.revenue.fee_share_pct!.toFixed(2)}% of what miners were paid. {n(d.revenue.transactions!)} transactions were confirmed (about {n(d.revenue.tx_per_block!)} a block), {n(d.revenue.avg_fee_per_tx_sats!)} sats on average in fees each.</Txt>
                <Txt variant="small" style={{ marginTop: 2 }}>Next halving at block {n(d.revenue.halving!.height)}: {n(d.revenue.halving!.blocks_left)} blocks away, about {n(d.revenue.halving!.days_left)} days ({ymdLabel(d.revenue.halving!.estimated_date)}, an estimate). The subsidy then falls to {d.revenue.halving!.subsidy_after_btc} BTC a block.</Txt>
                <Txt variant="tiny" style={{ marginTop: 2 }}>Blocks {n(d.revenue.first_block!)} to {n(d.revenue.last_block!)}, as of this request.</Txt>
                <Txt variant="tiny">{d.revenue.note}</Txt>
              </View>) : null}
            <Txt variant="tiny">Not a price signal: fees can be near zero while price moves a lot.</Txt>
            {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>Source: mempool.space</Txt></Pressable> : null}
          </View>)}
    </GCard>
  );
}
