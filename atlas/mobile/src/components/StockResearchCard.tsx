import React, { useState } from "react";
import { Linking, Pressable, View } from "react-native";
import { safeUrl } from "../lib/links";
import { useStockResearch } from "../state/queries";
import { color, radius, space } from "../theme";
import { SEC_OFF_POINTER, isSecOff, withoutSecOff } from "../lib/secOff";
import { Banner, Divider, Skeleton, Tag, Txt, GCard, Pill } from "./ui";

const money = (x: number | null) => (x === null ? "n/a" : `${x < 0 ? "−" : ""}$${(Math.abs(x) / 1e9).toFixed(2)}B`);
const pc = (x: number | null) => (x === null ? "n/a" : `${x.toFixed(1)}%`);
const open = (u: string | null) => { const s = safeUrl(u); if (s) Linking.openURL(s).catch(() => undefined); };

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return <View style={{ gap: 6 }}><Txt variant="label">{title}</Txt>{children}</View>;
}

/** The company deep-dive for a US stock, collapsed until asked for (it fetches filings, so it is not loaded with the page). */
export function StockResearchCard({ symbol }: { symbol: string }) {
  const [shown, setShown] = useState(false);
  const q = useStockResearch(symbol, shown);
  const d = q.data;
  const last = d?.financials.years[d.financials.years.length - 1];
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="stock-card">
      <Pressable onPress={() => setShown(!shown)} accessibilityRole="button" testID="stock-toggle" style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <View style={{ flex: 1 }}><Txt variant="h2">Company deep-dive</Txt><Txt variant="tiny">Filings, valuation, earnings, bull and bear points</Txt></View>
        <Pill label={shown ? "Hide" : "Show"} />
      </Pressable>
      {shown && (q.isLoading ? <View style={{ gap: space.md }}>{[0, 1, 2].map((i) => <Skeleton key={i} h={36} />)}</View>
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load the deep-dive" testID="stock-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : (
          <View style={{ gap: space.lg }} testID="stock-body">
            {d.errors.some(isSecOff) ? <Banner tone="warn" title="Company filings are switched off" testID="stock-sec-off">{SEC_OFF_POINTER}</Banner> : null}
            {d.company.sic_description || d.company.sector ? <Txt variant="small">{[d.company.sector, d.company.industry, d.company.sic_description && `SEC industry: ${d.company.sic_description}`].filter(Boolean).join(" · ")}</Txt> : null}
            <Block title="Financials (annual filings)">
              {!d.financials.available || !last ? <Txt variant="small">No filing data loaded. {withoutSecOff(d.errors).filter((e) => /SEC|Demo/.test(e)).join(" ")}</Txt> : (
                <View>
                  <Txt variant="tiny">Fiscal year ended {last.end}. Facts from SEC filings; ratios calculated here.</Txt>
                  {([["Revenue", money(last.revenue)], ["Revenue growth", pc(last.revenue_growth_pct)], ["Operating margin", pc(last.operating_margin_pct)], ["Net margin", pc(last.net_margin_pct)], ["Free cash flow", money(last.free_cash_flow)], ["Net cash (cash − LT debt)", money(last.net_cash)], ["Debt / equity", last.debt_to_equity === null ? "n/a" : `${last.debt_to_equity.toFixed(2)}x`]] as const).map(([k, v], i) => (
                    <View key={k}>{i > 0 && <Divider />}<View style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: 7 }}><Txt variant="small">{k}</Txt><Txt variant="body">{v}</Txt></View></View>))}
                  {d.financials.revenue_cagr ? <Txt variant="tiny">Revenue growth per year, {d.financials.revenue_cagr.from.slice(0, 4)} to {d.financials.revenue_cagr.to.slice(0, 4)}: {pc(d.financials.revenue_cagr.value_pct)}.</Txt> : null}
                </View>)}
            </Block>
            <Block title={`Valuation${d.valuation?.status ? ` · ${d.valuation.status.toLowerCase()}` : ""}`}>
              {d.valuation ? d.valuation.rows.filter((r) => r.value !== null).slice(0, 5).map((r) => <View key={r.key} style={{ flexDirection: "row", justifyContent: "space-between" }}><Txt variant="small">{r.label}</Txt><Txt variant="body">{r.unit === "$" ? money(r.value) : `${r.value!.toFixed(2)}${r.unit}`}</Txt></View>) : <Txt variant="small">Valuation unavailable.</Txt>}
              <Txt variant="tiny">{d.valuation?.source ? `Source: ${d.valuation.source} (unofficial, delayed).` : ""}</Txt>
            </Block>
            <Block title="Earnings">
              <Txt variant="body">Next report: {d.earnings.next_date ?? "not available"}</Txt>
              <Txt variant="tiny">{d.earnings.guidance.reason} {d.earnings.consensus.reason}</Txt>
            </Block>
            {(["bull", "bear"] as const).map((side) => (
              <Block key={side} title={side === "bull" ? "Bull points" : "Bear points"}>
                <Tag label="Interpretation (rule-based)" tint={color.warn} />
                {d[side].length === 0 ? <Txt variant="small">No rule triggered.</Txt> : d[side].map((c) => <Txt key={c.id} variant="small">• {c.text}</Txt>)}
              </Block>))}
            <Txt variant="tiny">{d.case_note}</Txt>
            {d.catalysts.length > 0 && <Block title="Catalysts">{d.catalysts.map((c, i) => <Txt key={i} variant="small">{c.date} · {c.title}</Txt>)}</Block>}
            <Block title="Recent filings">
              {d.filings.length === 0 ? <Txt variant="small">None loaded.</Txt> : d.filings.slice(0, 5).map((f, i) => (
                <Pressable key={i} onPress={() => open(f.link)} disabled={!safeUrl(f.link)} accessibilityRole="link"><Txt variant="small">{f.filed} · {f.form} {f.items.map((x) => x.meaning).join("; ")}</Txt></Pressable>))}
            </Block>
            <Block title="News">
              {d.news.length === 0 ? <Txt variant="small">No recent headlines.</Txt> : d.news.slice(0, 5).map((n, i) => (
                <Pressable key={i} onPress={() => open(n.link)} disabled={!safeUrl(n.link)} accessibilityRole="link"><Txt variant="small">{n.title}</Txt><Txt variant="tiny">{n.feed}</Txt></Pressable>))}
            </Block>
            {withoutSecOff(d.errors).length > 0 && <Banner tone="warn" title="Some sources failed">{withoutSecOff(d.errors).join(" ")}</Banner>}
            <Txt variant="tiny">Not shown: {d.gaps.join(" ")}</Txt>
          </View>))}
    </GCard>
  );
}
