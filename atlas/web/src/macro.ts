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
