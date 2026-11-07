export interface MacroChange { label: string; ref_date: string; value: number | null; unit: string }
export interface MacroFact {
  id: string; label: string; unit?: string; status?: string; series?: string; value?: number; lower?: number; upper?: number; obs_date?: string; error?: string; note?: string;
  changes?: MacroChange[]; inverted?: boolean; unchanged_since?: string; unchanged_since_is_lower_bound?: boolean; index_level?: number;
  freshness?: { state: "CURRENT" | "OVERDUE"; age_days: number; limit_days: number; rule: string };
}
export interface MacroNote { id: string; based_on: string[]; text: string; caveat: string }
export interface MacroOverview { demo: boolean; as_of?: string; source: string; notice?: string; facts: MacroFact[]; interpretations: MacroNote[]; interpretation_note?: string }

export const fmtChange = (c: MacroChange): string => {
  if (c.value === null || c.value === undefined) return "n/a";
  const sign = c.value >= 0 ? "+" : "−";
  const a = Math.abs(c.value);
  return c.unit === "bps" ? `${sign}${a.toFixed(0)} bps` : c.unit === "%" ? `${sign}${a.toFixed(2)}%` : `${sign}${a.toFixed(2)} pp`;
};

export const fmtValue = (f: MacroFact): string => {
  if (f.id === "fed") return f.lower !== undefined && f.upper !== undefined ? `${f.lower.toFixed(2)}–${f.upper.toFixed(2)}%` : "n/a";
  if (f.value === undefined) return "n/a";
  return f.id === "curve" ? `${f.value >= 0 ? "+" : "−"}${Math.abs(f.value).toFixed(0)} bps` : f.unit === "%" || f.unit === "% year-over-year" ? `${f.value.toFixed(2)}%` : f.value.toFixed(2);
};

// --- Fed Watch ---------------------------------------------------------------------------------------------------------------------------
export interface FedEvent { id: string; type: string; title: string; meeting: string; at_utc: string; projections: boolean; source: string; link: string }
export interface FedDecision {
  meeting_end: string; announced_date?: string; announced_utc: string; effective_obs_date?: string | null; date_note?: string; outcome: "raised" | "cut" | "held" | null; change_bps?: number; note?: string;
  previous?: { lower: number; upper: number; obs_date: string }; new?: { lower: number; upper: number; obs_date: string };
}
export interface FedComm { type: string; type_label: string; title: string; link: string | null; summary: string; published_utc: string | null; feed: string; significant: boolean; why_it_matters: string }
export interface FedRelease extends MacroFact { relevance?: string; consensus_note?: string; level?: number }
export interface FedWatch {
  as_of: string; demo: boolean; notice?: string; links: Record<string, string>; scenarios: Record<"raised" | "cut" | "held", Record<"equities" | "bonds" | "dollar" | "crypto", string>>; scenario_note: string;
  calendar?: { needs_update: boolean; last_meeting: string; link: string; message: string | null };
  upcoming: FedEvent[]; decisions: FedDecision[]; decisions_error?: string | null; communications: FedComm[]; feed_status: { feed: string; ok: boolean; items: number; error: string | null }[];
  releases: FedRelease[]; release_schedule: { series: string; label: string; name: string; date: string; at_utc: string | null }[]; schedule_note: string;
  balance_sheet: (MacroFact & { trend?: string; trend_rule?: string; why_it_matters?: string }) | null; errors: string[]; interpretation_note: string;
}

/** "in 5d 3h" / "in 2h 15m" / "in 12m" / "now". Pure: the caller passes the current time. */
export const countdown = (iso: string, nowMs: number): string => {
  const s = Math.floor((Date.parse(iso) - nowMs) / 1000);
  if (!Number.isFinite(s)) return "";
  if (s <= 0) return "now or past";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d > 0 ? `in ${d}d ${h}h` : h > 0 ? `in ${h}h ${m}m` : `in ${Math.max(1, m)}m`;
};

/** A UTC timestamp shown in the viewer's timezone (or the one given), with the zone abbreviation. */
export const localTime = (iso: string | null, tz?: string): string => {
  if (!iso) return "n/a";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "n/a" : d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short", ...(tz ? { timeZone: tz } : {}) });
};

export const OUTCOME_TEXT: Record<"raised" | "cut" | "held", string> = { raised: "Raised rates", cut: "Cut rates", held: "Held rates" };

export interface BriefItem { kind: "fact" | "interpretation"; title: string; detail: string; source: string; link?: string | null; based_on?: string[] }
export interface BriefIndicator { id: string; label: string; available: boolean; reason?: string; value?: number | string | null; unit?: string | null; obs_date?: string | null; change?: { label: string; value: number; unit: string } | null; freshness?: string | null; source?: string; note?: string | null }
export interface BriefEvent { kind: "scheduled"; date: string; at_utc: string | null; title: string; source: string; link?: string | null }
export interface BriefHeadline { kind: "headline"; feed: string; title: string; link: string | null; published: string | null; topic: string; topic_label: string; implication: string; implication_kind: string }
export interface MacroBrief { as_of: string; demo: boolean; today: BriefItem[]; indicators: BriefIndicator[]; indicators_note: string | null; upcoming: BriefEvent[]; headlines: BriefHeadline[]; topics: Record<string, string>; calendar_warning: string | null; errors: string[]; gaps: string[]; notice: string | null; labels: Record<string, string> }
