import type { Prov } from "../api/types";
import { localClock, relativeTime } from "./format";

export type Tone = "live" | "delayed" | "historical" | "stale" | "demo" | "unavailable";
export interface Fresh {
  tone: Tone;
  label: string;        // short: "Live", "Delayed ~15 min", "Stale"
  detail: string;       // "updated 12:54 PM" / "last update 3h ago"
  warn: boolean;        // draw attention (stale / unavailable)
}

/** The honest freshness label for a price. The server decides the status (LIVE/DELAYED/HISTORICAL/STALE/DEMO/UNAVAILABLE); the device only words it. */
export function describeFreshness(prov: Prov | null | undefined, nowMs: number, tz?: string): Fresh {
  if (!prov) return { tone: "unavailable", label: "No data", detail: "", warn: true };
  const when = prov.event_time;
  const at = when ? `updated ${localClock(when, tz)}` : "update time unknown";
  switch (prov.status) {
    case "LIVE": return { tone: "live", label: "Live", detail: at, warn: false };
    case "DELAYED": return { tone: "delayed", label: prov.delay_seconds ? `Delayed ~${Math.max(1, Math.round(prov.delay_seconds / 60))} min` : "Delayed", detail: at, warn: false };
    case "HISTORICAL": return { tone: "historical", label: prov.session === "CLOSED" || prov.session === "HOLIDAY" ? "Market closed" : "Last known", detail: when ? `as of ${localClock(when, tz)}` : "", warn: false };
    case "STALE": return { tone: "stale", label: "Stale", detail: when ? `last update ${relativeTime(when, nowMs)}` : "last update unknown", warn: true };
    case "DEMO": return { tone: "demo", label: "Demo data", detail: "synthetic, not real", warn: false };
    default: return { tone: "unavailable", label: "Unavailable", detail: "", warn: true };
  }
}

/** True when WE are holding data older than `maxAgeMs` (the app was backgrounded, or refreshes are failing): show it as possibly outdated. */
export function isOutdated(fetchedAtMs: number | null | undefined, nowMs: number, maxAgeMs = 120_000): boolean {
  return fetchedAtMs === null || fetchedAtMs === undefined || nowMs - fetchedAtMs > maxAgeMs;
}

export function worstTone(tones: Tone[]): Tone | null {
  const rank: Tone[] = ["unavailable", "stale", "delayed", "historical", "demo", "live"];
  const found = rank.find((t) => tones.includes(t));
  return found ?? null;
}

/** What deserves a banner: only prices that are stale or missing. "Delayed" and "market closed" are normal and get just the small dot beside the price. */
export function summarizeTones(tones: Tone[]): string {
  const n = (t: Tone) => tones.filter((x) => x === t).length;
  return [n("stale") && `${n("stale")} stale`, n("unavailable") && `${n("unavailable")} unavailable`].filter(Boolean).join(" · ");
}
