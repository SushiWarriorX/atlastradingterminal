export interface Metrics { bars: number; net_return_pct: number | null; cagr_pct: number | null; max_drawdown_pct: number | null; sharpe: number | null; win_rate_pct: number | null; profit_factor: number | null; trades: number; avg_trade_pct: number | null; exposure_pct: number | null; no_losing_trades?: boolean }
export interface LabStrategy { id: string; name: string; family: string; summary: string; entry: string; exit: string; stop: string; sizing: string; params: Record<string, number>; grid: Record<string, number[]>; stop_pct: number | null; symmetric: boolean; requires_funding: boolean; notes: string[] }
export interface LabStrategies { strategies: LabStrategy[]; defaults: string[]; max_leverage: number; demo: boolean; sources: { prices: string; funding: string }; data: Record<string, { bars: number; from: string | null; to: string | null; gap_count: number } & Record<string, unknown>> | null }
export interface LabResult {
  id: string; name: string; family: string; params: Record<string, number>; stop_pct: number | null;
  full: Metrics; in_sample: Metrics; out_of_sample: Metrics; walk_forward: Metrics & { folds: { from: string; to: string; chosen: Record<string, number>; train_sharpe: number | null; test_return_pct: number }[]; efficiency: number | null };
  buy_and_hold: { full: Metrics; out_of_sample: Metrics };
  robustness: { param: string; neighbours: Record<string, number>[]; share_positive: number; doubled_costs_oos_return_pct: number };
  evidence: { level: "none" | "weak" | "moderate"; reasons: string[]; min_trades: number };
  costs: { fees_paid_pct: number; funding_paid_pct: number; liquidated: boolean };
  now: { rule_position: string; conditions: { rule: string; met: boolean | null; value: string }[]; as_of: string; note: string };
  curve: { strategy: number[]; buy_and_hold: number[]; drawdown: number[]; oos_starts_at: number; from: string; to: string };
  trades: { total: number; recent: { entry: string; exit: string; side: string; entry_px: number; exit_px: number; reason: string; bars: number; ret_pct: number; open?: boolean }[] };
}
export interface LabRun {
  run_id: string; settings: { timeframe: string; market: string; leverage: number; long_short: boolean; fee_bps: number; slippage_bps: number }; period: { from: string; to: string; bars: number };
  results: LabResult[]; skipped: { id: string; reason: string }[]; buy_and_hold: { metrics: Metrics; note: string }; notes: string[]; caveats: string[];
  data: { demo: boolean; source: string; funding_source: string | null; bars: number; last_bar: string; gap_count: number; status: string; notes: string[] };
}
export interface LabReq { strategies: string[]; timeframe: string; market: string; leverage: number; long_short: boolean; fee_bps: number; slippage_bps: number }
