import React from "react";
import { View } from "react-native";
import { useTreasury } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Tag, Txt } from "./ui";

const bp = (x: number | null | undefined) => (x === null || x === undefined ? "n/a" : `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x)} bp`);
const tone = (x: number | null | undefined) => (x === null || x === undefined ? color.dim : x > 0 ? color.up : x < 0 ? color.down : color.text);

/** The US Treasury yield curve (1 month to 30 years) with inversion checks, plus total public debt. Official data with its date. */
export function TreasuryCard() {
  const q = useTreasury();
  const d = q.data;
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="treasury-card">
      <View><Txt variant="h2">US Treasury</Txt><Txt variant="tiny">Yield curve and public debt, from the US Treasury</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load Treasury data" testID="treasury-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : (
          <View style={{ gap: space.md }} testID="treasury-body">
            {d.curve.available ? (
              <View style={{ gap: 2 }}>
                <View style={{ flexDirection: "row", gap: 6, alignItems: "center" }}><Txt variant="label">Yield curve</Txt><Txt variant="tiny">{d.curve.date}{d.curve.freshness === "OVERDUE" ? " · overdue" : ""}</Txt></View>
                {d.curve.points!.map((p, i) => (
                  <View key={p.tenor}>{i > 0 && <Divider />}
                    <View style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: 4 }}>
                      <Txt variant="body" style={{ width: 48 }}>{p.tenor}</Txt>
                      <Txt variant="body">{p.rate === null ? "n/a" : `${p.rate.toFixed(2)}%`}</Txt>
                      <Txt variant="small" c={tone(p.change_1d_bp)} style={{ width: 70, textAlign: "right" }}>{bp(p.change_1d_bp)}</Txt>
                      <Txt variant="small" c={tone(p.change_1m_bp)} style={{ width: 70, textAlign: "right" }}>{bp(p.change_1m_bp)}</Txt>
                    </View>
                  </View>))}
                <Txt variant="tiny">Columns: maturity, yield, change vs previous day, change vs about a month ago.</Txt>
                <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap", marginTop: 4 }} testID="treasury-spreads">
                  <Tag label={`2s10s ${bp(d.curve.spreads!["2s10s_bp"])}${d.curve.spreads!["2s10s_inverted"] ? " · inverted" : ""}`} tint={d.curve.spreads!["2s10s_inverted"] ? color.warn : undefined} />
                  <Tag label={`3m10y ${bp(d.curve.spreads!["3m10y_bp"])}${d.curve.spreads!["3m10y_inverted"] ? " · inverted" : ""}`} tint={d.curve.spreads!["3m10y_inverted"] ? color.warn : undefined} />
                </View>
                <Txt variant="tiny">{d.curve.note}</Txt>
              </View>) : <Banner tone={d.demo ? "demo" : "warn"} title={d.demo ? "Demo mode" : "Yield curve unavailable"}>{d.curve.reason}</Banner>}
            {d.debt.available ? (
              <View style={{ gap: 2 }}>
                <Txt variant="label">Total public debt</Txt>
                <Txt variant="h2">${d.debt.total_trillions!.toFixed(2)} trillion</Txt>
                <Txt variant="small">On {d.debt.date}{d.debt.change_vs_previous_day_billions != null ? ` · ${d.debt.change_vs_previous_day_billions >= 0 ? "+" : "−"}$${Math.abs(d.debt.change_vs_previous_day_billions).toFixed(1)}B vs the previous day` : ""}{d.debt.change_vs_a_year_ago_pct != null ? ` · ${d.debt.change_vs_a_year_ago_pct >= 0 ? "+" : "−"}${Math.abs(d.debt.change_vs_a_year_ago_pct).toFixed(1)}% vs a year ago` : ""}</Txt>
                <Txt variant="tiny">Held by the public ${d.debt.held_by_public_trillions!.toFixed(2)}T · intragovernmental ${d.debt.intragovernmental_trillions!.toFixed(2)}T. {d.debt.note}</Txt>
              </View>) : d.debt.reason ? <Txt variant="small" c={color.warn}>{d.debt.reason}</Txt> : null}
          </View>)}
    </GCard>
  );
}
