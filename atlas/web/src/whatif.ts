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
