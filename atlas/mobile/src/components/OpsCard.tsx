import React from "react";
import { Alert, Platform, View } from "react-native";
import { useOps, useOpsAction } from "../state/queries";
import { color, space } from "../theme";
import { Banner, Divider, GCard, Skeleton, Tag, TextButton, Txt } from "./ui";

const mins = (s: number) => (s < 120 ? `${Math.round(s)}s` : s < 7200 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`);
const ago = (iso: string | null) => (iso ? `${mins((Date.now() - new Date(iso).getTime()) / 1000)} ago` : "never");
const clock = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }) : "n/a");

function confirm(message: string, then: () => void) {
  if (Platform.OS === "web") { if (typeof window !== "undefined" && window.confirm(message)) then(); return; }
  Alert.alert("Are you sure?", message, [{ text: "Cancel", style: "cancel" }, { text: "Yes", style: "destructive", onPress: then }]);
}

/** Operations on the phone: is the background scheduler alive, data freshness, next runs, why an interval differs, allowances, and pause / run now / emergency stop. */
export function OpsCard() {
  const q = useOps();
  const act = useOpsAction();
  const d = q.data;
  return (
    <GCard style={{ padding: space.lg, gap: space.md }} testID="ops-card">
      <View><Txt variant="h2">Operations</Txt><Txt variant="tiny">Background jobs, data freshness and budgets</Txt></View>
      {q.isLoading ? <Skeleton h={80} />
        : q.isError || !d ? <Banner tone="warn" title="Couldn't load operations" testID="ops-error">{q.error instanceof Error ? q.error.message : "Something went wrong."}</Banner>
        : (
          <View style={{ gap: space.md }} testID="ops-body">
            <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
              <Tag label={d.emergency_stop ? "EMERGENCY STOP" : d.paused ? "Paused" : d.scheduler_alive ? "Scheduler running" : "Scheduler not seen"} tint={d.emergency_stop || !d.scheduler_alive ? color.warn : undefined} />
              <Tag label={d.market_open ? "Market open" : "Market closed"} />
            </View>
            {!d.scheduler_alive ? <Banner tone="warn" title="Scheduler not seen recently">Jobs only run while the app's server or its worker is running.</Banner> : null}
            <View style={{ flexDirection: "row", gap: space.sm, flexWrap: "wrap" }}>
              {d.paused ? <TextButton label="Resume all" onPress={() => act.mutate({ path: "resume" })} testID="ops-resume" /> : <TextButton label="Pause all" onPress={() => act.mutate({ path: "pause" })} testID="ops-pause" />}
              {d.emergency_stop ? <TextButton solid label="Clear emergency stop" onPress={() => act.mutate({ path: "emergency-clear" })} testID="ops-clear-stop" />
                : <TextButton label="Emergency stop" tint={color.down} onPress={() => confirm("Stop every job now? Nothing will run until you clear the stop.", () => act.mutate({ path: "emergency-stop" }))} testID="ops-stop" />}
            </View>
            {act.isError ? <Txt variant="small" c={color.down}>{act.error instanceof Error ? act.error.message : "That did not work."}</Txt> : null}
            <Txt variant="label">Jobs</Txt>
            {d.jobs.map((j, i) => (
              <View key={j.id}>{i > 0 && <Divider />}
                <View style={{ paddingVertical: 4, gap: 2 }} testID={`ops-job-${j.id}`}>
                  <View style={{ flexDirection: "row", justifyContent: "space-between", gap: space.md }}>
                    <Txt variant="body" style={{ flex: 1 }}>{j.title}</Txt>
                    <Txt variant="small" c={j.last_status === "ok" ? color.up : j.last_status === "deferred" ? color.warn : j.last_status ? color.down : color.dim}>{j.running ? "running" : j.last_status ?? "not yet"}</Txt>
                  </View>
                  <Txt variant="tiny" c={j.stale && j.enabled && j.last_success_at ? color.warn : undefined}>Last success {ago(j.last_success_at)}{j.stale && j.enabled && j.last_success_at ? " · stale" : ""} · next {clock(j.next_run_at)}{!j.enabled ? " · off" : j.paused ? " · paused" : ""}</Txt>
                  <Txt variant="tiny">Every {mins(j.effective_interval_s)}{j.differs ? ` (you asked ${mins(j.preferred_now_s)}): ${j.why_effective[j.why_effective.length - 1]}` : ""}</Txt>
                  {j.deferred_reason ? <Txt variant="tiny" c={color.warn}>Deferred: {j.deferred_reason}</Txt> : null}
                  {j.last_error ? <Txt variant="tiny" c={color.down}>Error: {j.last_error}</Txt> : null}
                  <TextButton label="Run now" onPress={() => act.mutate({ path: `jobs/${j.id}/run` })} testID={`ops-run-${j.id}`} />
                </View>
              </View>))}
            <Txt variant="label">Allowances</Txt>
            <Txt variant="tiny" testID="ops-claude">Claude access: {d.claude.access === "unknown" ? "not set" : d.claude.access} · {d.claude.usage_note}{d.claude.dollar_cost_known ? "" : " Dollar cost is unknown until prices are entered."}</Txt>
            {d.budgets.map((b) => (
              <View key={b.bucket} style={{ flexDirection: "row", justifyContent: "space-between", gap: space.md }}>
                <Txt variant="small" style={{ flex: 1 }}>{b.bucket} (per {b.window})</Txt>
                <Txt variant="small" c={b.remaining_fraction !== null && b.remaining_fraction < 0.2 ? color.down : undefined}>{b.limit === null ? "no limit set" : `${Math.round((b.remaining_fraction ?? 0) * 100)}% left`}</Txt>
              </View>))}
            {d.dead_letters.length ? <><Txt variant="label" c={color.down}>Needs attention</Txt>{d.dead_letters.map((x) => <View key={x.id} style={{ gap: 2 }}><Txt variant="small" c={color.down}>{x.job_id}: {x.error} ({x.attempts} attempts)</Txt>
              <View style={{ flexDirection: "row", gap: space.sm }}><TextButton label="Retry" onPress={() => act.mutate({ path: `dead-letters/${x.id}/retry` })} /><TextButton label="Dismiss" onPress={() => act.mutate({ path: `dead-letters/${x.id}/dismiss` })} /></View></View>)}</> : null}
            {d.events.length ? <><Txt variant="label">Notices</Txt>{d.events.slice(0, 5).map((e, i) => <Txt key={i} variant="tiny" c={e.severity === "critical" ? color.down : e.severity === "warn" ? color.warn : undefined}>{clock(e.ts)} · {e.message}</Txt>)}</> : null}
          </View>)}
    </GCard>
  );
}
