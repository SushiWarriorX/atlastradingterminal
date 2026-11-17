import { Ionicons } from "@expo/vector-icons";
import React, { useState } from "react";
import { Pressable, RefreshControl, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import type { PaperAccount, PaperLab, PaperTrade } from "../api/types";
import { spoken } from "../lib/format";
import { chanceText, dayLabel, forwardLine, money, outcomeTone, paperLine, pctOf, periodLine, sample, split, whenLabel, type Tone } from "../lib/journey";
import { usePaperLab } from "../state/queries";
import { useIsWide } from "../state/layout";
import { color, dirColor, radius, space } from "../theme";
import { Avatar, logoColors } from "./Avatar";
import { CoinCard } from "./CoinCard";
import { CurveChart } from "./CurveChart";
import { ScreenHeader } from "./ScreenHeader";
import { Sparkline } from "./Sparkline";
import { Banner, Divider, EmptyState, ErrorState, GCard, LOGO_PAD, LogoSlot, Skeleton, TAP, Tag, TextButton, Txt } from "./ui";

const TONE: Record<Tone, string> = { up: color.up, down: color.down, warn: color.warn, dim: color.dim };
const CARD_TITLE: Record<string, string> = { portfolio: "Main portfolio", buy_hold: "Buy and hold", cash: "Cash only" };
const SHOWN_TRADES = 6;

function dirOf(r: number | null | undefined) { return r === null || r === undefined || r === 0 ? color.dim : dirColor(r > 0 ? "up" : "down"); }

/** A section heading in TradingView's style: large and bold, with a small chevron when the section can be opened up. */
function SectionTitle({ title, sub, onPress, open, label, testID }: { title: string; sub?: string; onPress?: () => void; open?: boolean; label?: string; testID?: string }) {
  const head = (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
      <Txt variant="title" style={{ fontSize: 22 }}>{title}</Txt>
      {onPress ? <Ionicons name={open ? "chevron-down" : "chevron-forward"} size={20} color={color.text} style={{ marginTop: 3 }} /> : null}
    </View>
  );
  return (
    <View style={{ paddingHorizontal: space.lg, gap: 2 }}>
      {onPress ? <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label ? `${title}. ${label}` : title} accessibilityState={{ expanded: !!open }} testID={testID} style={{ minHeight: TAP, justifyContent: "center" }}>{head}</Pressable> : head}
      {sub ? <Txt variant="small">{sub}</Txt> : null}
    </View>
  );
}

function Stat({ k, v, tint }: { k: string; v: string; tint?: string }) {
  return <View style={{ flexDirection: "row", justifyContent: "space-between", gap: space.md }}><Txt variant="small" style={{ flex: 1 }}>{k}</Txt><Txt variant="small" c={tint ?? color.text} style={{ fontWeight: "600", fontVariant: ["tabular-nums"] }}>{v}</Txt></View>;
}

function Detail({ a, lab, hold }: { a: PaperAccount; lab: PaperLab; hold: PaperAccount | null }) {
  const b = a.backtest;
  const h = hold?.backtest?.run ?? null;
  return (
    <View style={{ gap: space.sm, paddingBottom: space.md }} testID={`journey-detail-${a.id}`}>
      {b?.curve && lab.backtest ? <CurveChart curve={b.curve} periods={lab.backtest.periods} tint={color.accent} label={`Backtest of ${a.name} from ${dayLabel(lab.backtest.from)} to ${dayLabel(lab.backtest.to)}, as a ratio of its $10,000 start.`} /> : null}
      {b?.run && lab.backtest ? (
        <View style={{ gap: 3 }}>
          <Stat k={`Backtest ${dayLabel(lab.backtest.from)} to ${dayLabel(lab.backtest.to)}`} v={pctOf(b.run.return)} tint={dirOf(b.run.return)} />
          {h ? <Stat k="Holding Bitcoin over the same days" v={pctOf(h.return)} tint={dirOf(h.return)} /> : null}
          <Stat k="Biggest fall from a peak" v={`${pctOf(b.run.max_drawdown, 1, false)}${h ? ` (holding: ${pctOf(h.max_drawdown, 1, false)})` : ""}`} />
          <Stat k="Trades in the replay" v={String(b.run.trades)} />
          {b.run.breaker_trips ? <Stat k="Circuit-breaker trips (15% fall)" v={String(b.run.breaker_trips)} /> : null}
        </View>
      ) : null}
      {b && (b.train || b.validation) ? (
        <View style={{ gap: 3 }}>
          {b.train ? <Txt variant="small">{periodLine("2020-2022 (settings chosen on this)", b.train)}</Txt> : null}
          {b.validation ? <Txt variant="small">{periodLine("2023-2024 (checked on this)", b.validation)}</Txt> : null}
        </View>
      ) : null}
      {b && b.outcome && b.outcome !== "admitted" ? (
        <View style={{ gap: 3 }} testID={`journey-why-${a.id}`}>
          <Txt variant="label" c={TONE[outcomeTone(b.outcome)]}>{b.outcome === "rejected" ? "Why it was not admitted" : "Why it could not be judged"}</Txt>
          {b.why.map((w, i) => <Txt key={i} variant="small">• {w.charAt(0).toUpperCase() + w.slice(1)}.</Txt>)}
          {b.timing_p !== null && b.why.some((w) => /random timing/.test(w)) ? <Txt variant="tiny">{chanceText(b.timing_p)}</Txt> : null}
        </View>
      ) : null}
      {forwardLine(a) ? (
        <View style={{ gap: 4 }} testID={`journey-forward-${a.id}`}>
          <Txt variant="label">Paper account since it opened</Txt>
          <Sparkline values={forwardLine(a)} tint={dirOf(a.return)} width={300} height={56} area dot />
        </View>
      ) : null}
      <Txt variant="small" testID={`journey-paper-${a.id}`}>{paperLine(a)}{a.pending ? `. Waiting: ${a.pending}.` : "."}{a.opened_after ? ` The paper record started after the ${dayLabel(a.opened_after.slice(0, 10))} close.` : ""}</Txt>
    </View>
  );
}

function StrategyRow({ a, lab, hold, open, onToggle }: { a: PaperAccount; lab: PaperLab; hold: PaperAccount | null; open: boolean; onToggle: () => void }) {
  const run = a.backtest?.run ?? null;
  const tone = outcomeTone(a.backtest?.outcome);
  const holding = hold?.backtest?.run ? `holding ${pctOf(hold.backtest.run.return, 0)}` : "backtest";
  // The words the row shows, in the order it shows them (the logo is drawn beside the button), then what the tap does.
  const label = `${spoken(a.name, a.backtest?.outcome ? a.backtest.outcome_text : null, a.params_text, run ? pctOf(run.return) : "n/a", holding)}. ${open ? "Hide details" : "Show details"}`;
  return (
    <View style={{ paddingHorizontal: space.lg }} testID={`journey-row-${a.id}`}>
      <View>
      <Pressable onPress={onToggle} accessibilityRole="button" accessibilityState={{ expanded: open }} accessibilityLabel={label}
        style={({ pressed }) => [{ flexDirection: "row", alignItems: "center", gap: space.md, paddingVertical: 12, paddingLeft: LOGO_PAD }, pressed && { opacity: 0.7 }]}>
        <View style={{ flex: 1, minWidth: 0 }}>
          <Txt variant="h2" numberOfLines={2} style={{ fontWeight: "700", fontSize: 16, lineHeight: 20 }}>{a.name}</Txt>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 2 }}>
            {a.backtest?.outcome ? <Tag label={a.backtest.outcome_text} tint={TONE[tone]} /> : null}
            <Txt variant="small" numberOfLines={1} style={{ flexShrink: 1 }}>{a.params_text}</Txt>
          </View>
        </View>
        <View style={{ alignItems: "flex-end", minWidth: 92 }}>
          <Txt variant="h2" c={dirOf(run?.return)} style={{ fontWeight: "700", fontVariant: ["tabular-nums"] }}>{run ? pctOf(run.return) : "n/a"}</Txt>
          <Txt variant="tiny" style={{ marginTop: 1 }}>{holding}</Txt>
        </View>
      </Pressable>
      <LogoSlot><Avatar id={a.family} symbol={a.short} /></LogoSlot>
      </View>
      {open ? <Detail a={a} lab={lab} hold={hold} /> : null}
    </View>
  );
}

function FeedItem({ t, tint }: { t: PaperTrade; tint: string }) {
  return (
    <View style={{ paddingHorizontal: space.lg, paddingVertical: space.md, gap: 6 }} testID="journey-trade">
      <View style={{ flexDirection: "row", alignItems: "center", gap: space.sm }}>
        <View style={{ width: 18, height: 18, borderRadius: 9, backgroundColor: tint }} />
        <Txt variant="small" style={{ flex: 1 }}>{whenLabel(t.when)} · {t.label}</Txt>
      </View>
      <Txt variant="body" style={{ fontSize: 16, lineHeight: 22, fontWeight: "600" }}>{t.text}</Txt>
    </View>
  );
}

function Cards({ lab, list }: { lab: PaperLab; list: { portfolio: PaperAccount | null; benchmarks: PaperAccount[] } }) {
  const cards = [list.portfolio, ...list.benchmarks].filter((a): a is PaperAccount => !!a);
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: space.lg, gap: space.md }} testID="journey-cards" tabIndex={0}>      {/* tabIndex: with a keyboard the cards cannot be scrolled sideways unless the row can take focus */}
      {cards.map((a) => {
        const run = a.backtest?.run ?? null;
        const isMain = a.stage === "portfolio";
        const change = a.days === 0 ? "Paper day 0" : `${pctOf(a.return, 2)} since start`;
        return (
          <CoinCard key={a.id} id={a.id} symbol={a.short} name={CARD_TITLE[a.id] ?? a.label} value={money(a.equity)} change={change} tint={a.days === 0 ? color.dim : dirOf(a.return)} sparkTint={color.accent}
            spark={a.backtest?.curve ? sample(a.backtest.curve, 48) : null} testID={`journey-card-${a.id}`}
            caption={isMain ? (lab.counts.champions ? `${lab.counts.champions} champion(s) inside` : "In cash. No strategy has earned a place yet.") : run ? `Backtest since 2020: ${pctOf(run.return, 0)}` : undefined} />
        );
      })}
    </ScrollView>
  );
}

/** The Journey tab: the paper-trading lab that runs the backtested Bitcoin strategies. At the top the verdict of the research run in plain words, then the paper accounts as cards, each strategy with its backtest and what it would do, and every order recorded the moment a rule signalled it. All simulated; nothing here can place an order. */
export function JourneyView() {
  const insets = useSafeAreaInsets();
  const wide = useIsWide();
  const q = usePaperLab();
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [all, setAll] = useState(false);
  const lab = q.data && q.data.available ? q.data : null;
  const list = lab ? split(lab.accounts) : null;
  const hold = list?.benchmarks.find((a) => a.id === "buy_hold") ?? null;

  let body: React.ReactNode;
  if (q.isLoading || (!q.data && !q.isError)) {
    body = <View style={{ paddingHorizontal: space.lg, gap: space.lg }} testID="journey-loading"><Skeleton h={120} r={radius.lg} /><View style={{ flexDirection: "row", gap: space.md }}><Skeleton w={184} h={170} r={radius.lg} /><Skeleton w={184} h={170} r={radius.lg} /></View>{[0, 1, 2].map((i) => <Skeleton key={i} h={44} />)}</View>;
  } else if (!q.data) {
    body = <ErrorState testID="journey-error" title="Can't load the paper lab" body={q.error instanceof Error ? q.error.message : "Something went wrong."} onRetry={() => q.refetch()} />;
  } else if (!lab || !list) {
    body = <EmptyState testID="journey-unavailable" icon="trail-sign-outline" title="The paper lab has not run yet" body={q.data.available ? "" : q.data.reason} />;
  } else {
    const trades = all ? lab.recent : lab.recent.slice(0, SHOWN_TRADES);
    const verdict = lab.counts.research_admitted === null ? "No research run yet" : `${lab.counts.research_admitted} of ${list.strategies.length} strategies passed`;
    body = (
      <View style={{ gap: space.xl }}>
        <View style={{ paddingHorizontal: space.lg, gap: space.sm }}>
          {lab.data.stale ? <Banner tone="warn" title="The price data is out of date" testID="journey-stale">The last daily candle is {dayLabel(lab.data.last_candle)}. Nothing below is current.</Banner> : null}
          {lab.problems.length ? <Banner tone="warn" title="A check on the frozen rules found a problem" testID="journey-problems">{lab.problems.join(" ")}</Banner> : null}
          <GCard style={{ padding: space.lg, gap: space.sm }} testID="journey-headline">
            <Txt variant="label">Admission bar, research run{lab.counts.research_ran_at ? ` of ${lab.counts.research_ran_at.slice(0, 10)}` : ""}</Txt>
            <Txt variant="title" style={{ fontSize: 26, lineHeight: 32 }} testID="journey-verdict">{verdict}</Txt>
            <Txt variant="small" c={color.text} style={{ fontSize: 14, lineHeight: 20 }}>{lab.headline}</Txt>
            <Txt variant="tiny">{lab.real_trading}. Price data to {dayLabel(lab.data.last_candle)}; the daily run is at 00:15 UTC.</Txt>
          </GCard>
        </View>

        <View style={{ gap: space.md }}>
          <SectionTitle title="Paper accounts" sub="Simulated money. Orders are filled at the next daily open." />
          <Cards lab={lab} list={list} />
        </View>

        <View>
          <View style={{ marginBottom: space.xs }}><SectionTitle title="Strategies" sub="Returns are replays on the same history the settings were chosen on, so they prove nothing. Tap one to see why it was or was not admitted." /></View>
          {list.strategies.map((a, i) => (
            <React.Fragment key={a.id}>
              {i > 0 ? <Divider /> : null}
              <StrategyRow a={a} lab={lab} hold={hold} open={!!open[a.id]} onToggle={() => setOpen((o) => ({ ...o, [a.id]: !o[a.id] }))} />
            </React.Fragment>
          ))}
        </View>

        <View testID="journey-feed">
          <SectionTitle title="Trades on signal" sub="Each order is recorded when a rule signals it, and again when it is filled." onPress={lab.recent.length > SHOWN_TRADES ? () => setAll((v) => !v) : undefined} open={all} label={all ? "Show fewer signals" : "Show all recorded signals"} testID="journey-feed-toggle" />
          {trades.length === 0 ? <Txt variant="small" style={{ paddingHorizontal: space.lg, paddingTop: space.md }}>Nothing yet. An order appears here the moment a rule signals one.</Txt>
            : trades.map((t, i) => <React.Fragment key={`${t.account}-${t.seq}`}>{i > 0 ? <Divider /> : null}<FeedItem t={t} tint={logoColors(t.account, (lab.accounts.find((a) => a.id === t.account)?.short ?? "?")).bg} /></React.Fragment>)}
          {lab.recent.length > SHOWN_TRADES ? <View style={{ alignItems: "center", paddingTop: space.sm }}><TextButton label={all ? "Show fewer" : `Show all ${lab.recent.length}`} onPress={() => setAll((v) => !v)} testID="journey-feed-more" /></View> : null}
        </View>

        <View style={{ paddingHorizontal: space.lg, gap: space.sm }} testID="journey-note">
          <Txt variant="tiny">{lab.note}</Txt>
          {lab.backtest ? <Txt variant="tiny">{lab.backtest.note}</Txt> : null}
          <Txt variant="tiny">Research only. Signal cannot place trades, and nothing here is financial advice.</Txt>
        </View>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: color.bg, paddingTop: wide ? 0 : insets.top }} testID="journey-screen">
      <ScreenHeader title="Journey" subtitle="Paper trading · simulated" />
      <ScrollView contentContainerStyle={{ paddingTop: space.sm, paddingBottom: space.xxl }} refreshControl={<RefreshControl refreshing={q.isRefetching && !q.isLoading} onRefresh={() => { void q.refetch(); }} tintColor={color.accent} />} testID="journey-scroll">
        {body}
      </ScrollView>
    </View>
  );
}
