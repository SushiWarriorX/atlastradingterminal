import React from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useCryptoMarket } from "../state/queries";
import { color, space } from "../theme";
import { Banner, GCard, Skeleton, Txt } from "./ui";

function Row({ k, v }: { k: string; v: string }) {
  return <View style={{ flexDirection: "row", justifyContent: "space-between", gap: space.md, paddingVertical: 3 }}><Txt variant="small" style={{ flex: 1 }}>{k}</Txt><Txt variant="body">{v}</Txt></View>;
}

/** The whole crypto market (CoinGecko): total value, 24h change and volume, and how it splits between Bitcoin, Ether, stablecoins and the rest. Descriptive, not a signal. */
export function CryptoMarketCard() {
  const q = useCryptoMarket();
  const d = q.data;
  const link = safeUrl(d?.url ?? null);
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="market-card">
      <View><Txt variant="h2">Crypto market</Txt><Txt variant="tiny">Total size and how it splits between Bitcoin, Ether and the rest</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the crypto market" testID="market-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : !d.available ? <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Crypto market unavailable"} testID="market-unavailable">{d.reason}</Banner>
        : (
          <View style={{ gap: space.sm }} testID="market-body">
            <Txt variant="hero">${d.total_market_cap_trillions!.toFixed(2)}T</Txt>
            <Txt variant="small" c={d.change_24h_pct! > 0 ? color.up : d.change_24h_pct! < 0 ? color.down : undefined}>{d.change_24h_pct! > 0 ? "+" : d.change_24h_pct! < 0 ? "−" : ""}{Math.abs(d.change_24h_pct!)}% in 24 hours · {d.age_minutes} min old{d.freshness === "OVERDUE" ? " · overdue" : ""}</Txt>
            <Row k="24h trading volume" v={`$${d.volume_24h_billions}B (${d.volume_to_cap_pct}% of value)`} />
            <Row k={'Bitcoin share ("dominance")'} v={`${d.btc_dominance_pct}%`} />
            <Row k="Ether share" v={`${d.eth_dominance_pct}%`} />
            <Row k="Everything else" v={`${d.other_pct}%`} />
            {d.stablecoin_share_pct != null ? <Row k="Tether + USD Coin share (cash-like)" v={`${d.stablecoin_share_pct}%`} /> : null}
            <Txt variant="tiny">Largest: {d.top!.map((t) => `${t.symbol} ${t.share_pct}%`).join(" · ")}. {d.coins!.toLocaleString("en-US")} coins tracked.</Txt>
          </View>)}
      <Txt variant="tiny">{d?.note ?? "Describes the crypto market's size and structure. Descriptive, not a signal."}</Txt>
      {link ? <Pressable onPress={() => Linking.openURL(link).catch(() => undefined)} accessibilityRole="link"><Txt variant="tiny" c={color.accent}>{d?.credit ?? "Data provided by CoinGecko"}</Txt></Pressable> : null}
    </GCard>
  );
}
