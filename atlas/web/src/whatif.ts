// Mirrors GET /api/signal/whatif/{asset}. Every figure is calculated by the server from the asset's own daily closes.
export interface WhatIf {
  asset: { id: string; symbol: string; name: string };
  amount: number; from: string; to: string; years: number; bars: number; bars_per_year: number; last_price: number;
  prov: { provider: string; status: string }; adjustment: string;
  lump_sum: { label: string; buy_date: string; buy_price: number; invested: number; value_now: number; gain: number; return_pct: number; per_year_pct: number | null; lowest_vs_cost_pct: number; max_drawdown_pct: number; days_below_cost: number; days: number }[];
  monthly: { label: string; from: string; buys: number; invested: number; value_now: number; gain: number; return_pct: number; average_price: number; same_money_lump_sum_return_pct: number }[];
  every_start: { label: string; worst_pct: number; median_pct: number; best_pct: number; share_positive: number; share_lost_20: number; worst_buy_date: string; best_buy_date: string; note: string }[];
  exit_rules: { label: string; rules: { rule: string; label: string; result_pct: number; sold: boolean; sold_on: string | null; why: string }[] }[];
  bootstrap: { paths: number; p5_pct: number; median_pct: number; p95_pct: number; share_positive: number; share_lost_20: number; typical_worst_dip_pct: number; note: string } | null;
  notes: string[]; caveats: string[];
}

export interface Sentiment {
  available: boolean; reason?: string; demo: boolean; source: string; url: string; note: string; as_of: string;
  value?: number; label?: string; date?: string; age_days?: number; freshness?: "CURRENT" | "OVERDUE";
  yesterday?: number | null; a_week_ago?: number | null; a_month_ago?: number | null; history?: { date: string; value: number }[];
}

export interface NarrativeBasketRow { symbol: string; available: boolean; price?: number; change_1d_pct?: number | null; return_5d_pct?: number | null; return_1m_pct?: number | null; above_50d?: boolean | null; volume_vs_normal?: number | null; last_bar?: string }
export interface NarrativeData {
  asof: string; created_at: string; demo: boolean; theme: string | null; notes: string[]; disclaimer: string; gaps: string[];
  method: { weights: Record<string, number>; scales: Record<string, string>; steps: string[]; note: string };
  data: { prices: string; prices_status: string; prices_as_of: string | null };
  name: string; score: number; parts: Record<string, number | null>; context: string; context_note: string; why_now: string[]; basket: NarrativeBasketRow[];
  headlines: { title: string; link: string | null; feed: string | null; published: string | null }[]; risks: string[]; volatility_note: string; recent_excluded: string[];
  facts: { median_return_1m_pct: number; spy_return_1m_pct: number | null; relative_1m_pct: number; share_above_50d: number | null; median_volume_vs_normal: number | null; headlines_48h: number | null; median_daily_range_pct: number };
  runners_up: { theme: string; name: string; score: number; relative_1m_pct: number }[]; all_themes: { theme: string; name: string; score: number; recently_featured: boolean }[];
}
