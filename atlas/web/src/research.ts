// Types for revenue-first fundamental research, newly listed companies and new-to-me candidates (shapes of /api/research/{symbol}, /api/discover/listings and /api/discover/candidates).
export interface Src { form: string; filed: string; link: string | null }
export interface RevRow { period_start: string; period_end: string; value: number; basis: string; yoy_pct?: number | null; yoy_note?: string | null; growth_pct?: number | null; growth_note?: string | null; source: Src }
export interface RevenueAnalysis {
  available: boolean; reason?: string; currency?: string; units?: string; annual?: RevRow[]; quarterly?: RevRow[];
  ttm?: { value: number; period_start: string; period_end: string; basis: string; quarters: string[] } | null; ttm_previous?: { value: number; period_end: string } | null;
  ttm_growth_pct?: number | null; ttm_growth_note?: string | null; cagr?: { from: string; to: string; years: number; value_pct: number; formula: string } | null;
  trend?: { label: string; latest_yoy_pct?: number; earlier_average_pct?: number; change_pp?: number; rule: string; reason?: string };
  per_share?: { period_end: string; revenue_per_diluted_share: number | null; diluted_shares: number | null }[]; share_count_change?: { from: string; to: string; change_pct: number; basis: string } | null;
  latest_period_end?: string | null; age_days?: number | null; stale?: boolean; missing?: string[]; not_in_structured_data?: string[];
}
export interface QualityRow { key: string; label: string; value: number | null; unit: string; note?: string | null }
export interface QualityData {
  available: boolean; reason?: string; basis?: string | null; rows?: QualityRow[]; ttm_period_end?: string; capitalised_software_ttm?: number | null;
  balance?: { cash: { value: number; end: string } | null; debt: { value: number; end: string } | null; equity: { value: number; end: string } | null; net_cash: number | null; note: string; as_of: string | null };
}
export interface R40Score {
  end: string; available: boolean; reason?: string; basis?: string; growth_pct?: number; margin_pct?: number; score?: number; reaches_40?: boolean; label?: string;
  ttm_revenue?: number; ttm_revenue_previous?: number; ttm_operating_cash_flow?: number; ttm_capital_expenditures?: number; ttm_free_cash_flow?: number; ttm_operating_income?: number; ttm_depreciation_amortisation?: number; ttm_ebitda?: number;
}
export interface Rule40 {
  definition: string; threshold: number; caveat: string; applicable: boolean; available?: boolean; label: string; reason?: string; sector?: string; current?: R40Score;
  history?: { end: string; score: number; growth_pct: number; margin_pct: number; reaches_40: boolean }[]; ebitda_variant?: R40Score; peers?: { available: boolean; reason: string };
  capitalised_software_ttm?: number; capitalised_software_note?: string;
}
export interface Scenario {
  name: "bear" | "base" | "bull"; fair_value_per_share: number; equity_value: number; enterprise_value: number; terminal_share_of_ev_pct: number | null; upside_pct: number;
  assumptions: { start_growth_pct: number; terminal_growth_pct: number; fcf_margin_start_pct: number; fcf_margin_end_pct: number; discount_rate_pct: number; years: number; annual_dilution_pct: number };
}
export interface Multiple { key: string; label: string; value: number | null; basis: string; note?: string | null }
export interface Valuation {
  label: string; label_key: "under" | "within" | "over" | "none"; reason?: string; caveat?: string; warnings?: string[]; price?: number | null; price_time?: string | null; price_source?: string | null;
  policy?: { discount_rate_pct: number; terminal_growth_pct: number; band_pct: number; years: number; min_evidence: string }; classification_rule?: string; sector?: string;
  evidence: { level: string; checks: { key: string; ok: boolean; essential: boolean; text: string }[]; limits: string[] };
  multiples?: Multiple[]; scenarios?: Scenario[]; fair_value_range?: { low: number; base: number; high: number };
  reverse_dcf?: { available: boolean; implied_growth_pct?: number; reported_ttm_growth_pct?: number; difference_pp?: number; reading?: string; reason?: string } | null;
  sensitivity?: { rows: string; cols: string; discount_rates: number[]; growths: number[]; values: (number | null)[][]; unit: string } | null;
  influence?: { input: string; low_value: number; high_value: number; swing: number }[]; invalidators?: string[];
  methods?: { dcf?: { available: boolean; reason?: string } | null; peers?: { available: boolean; reason: string }; own_history?: { available: boolean; reason: string } };
  inputs?: { shares_basis?: string | null; shares?: number | null; cash?: number | null; debt?: number | null; ttm_revenue?: number | null; ttm_fcf?: number | null; annual_dilution_pct?: number | null; financials_end?: string | null };
}
export interface Thesis { what_must_be_true: string[]; what_would_disprove_it: string[]; research_next: string[] }
export interface MyState {
  state: { symbol: string; first_seen_at: string | null; opened_at: string | null; saved_at: string | null; dismissed_at: string | null; researched_at: string | null; shown_count: number };
  notes: { id: number; body: string; created_at: string }[]; last_review: { reviewed_at: string; snapshot: Record<string, unknown> } | null;
}
export interface FundamentalResearch {
  available: boolean; reason?: string; demo?: boolean; symbol: string; as_of: string; errors: string[];
  company?: { name?: string | null; cik?: number | string | null; sic?: number | string | null; sector_kind?: string; special_sector_note?: string | null };
  revenue?: RevenueAnalysis; quality?: QualityData; rule_of_40?: Rule40; valuation?: Valuation; thesis?: Thesis; coverage?: { covered: string[]; not_covered: string[] };
  definitions?: Record<string, string>; sources?: { filings?: { origin: string; fetched_at: string; source: string }; submissions?: { sic_description?: string | null; exchanges?: string[] | null } | null }; my_state?: MyState;
}
export interface Brief { markdown: string; chars: number; detail: "concise" | "detailed"; symbol: string; filename: string; included: { notes: boolean; position: boolean }; redactions: number; explanation: string; default_question_used: boolean; sections: string[] }
export interface ChangeRow { key: string; label: string; unit: string; before: unknown; after: unknown }
export interface Changes { available: boolean; has_review: boolean; reason?: string; note?: string; reviewed_at?: string; changed?: ChangeRow[]; unchanged_count?: number }

export interface ListingItem {
  deal_id: string; symbol: string | null; name: string; exchange: string | null; exchange_text: string | null; stage: string; status: string; status_text: string; listing_type: string; listing_type_note: string;
  price: string | null; shares_offered: number | null; offer_amount: number | null; priced_date: string | null; expected_date: string | null; expected_first_trade?: string; first_trade_date?: string;
  verification?: { verified: boolean; note: string; evidence: { form: string; filed: string; link: string | null } | null }; newness?: { new: boolean | null; reason: string };
}
export interface ListingsFeed {
  available: boolean; reason?: string; as_of?: string; fetched_at?: string; age_hours?: number; stale?: boolean; window_days?: number; today?: { priced: number; expected_first_trade: number; text: string };
  upcoming: ListingItem[]; recent: ListingItem[]; counts?: { upcoming: number; recent: number; confirmed_trading: number; verified_by_sec: number }; source?: string; url?: string; coverage: string; errors?: string[];
}
export interface Candidate {
  symbol: string; name: string; exchange: string; sector: string | null; industry: string | null; country: string | null; market_cap: number | null; size_bucket: string | null; ipo_year: number | null;
  dollar_volume: number | null; price: number | null; price_time: string; price_source: string; score: number; factors: Record<string, number | null>; why_selected: string[]; risks: string[];
  main_opportunity: string; main_risk: string; why_shown_again: string | null; description: { classification?: number | string | null; industry: string | null; sector: string | null; note: string };
  revenue: { ttm: number | null; ttm_period_end: string | null; growth_pct: number | null; trend: string | null; fcf_margin_pct: number | null; age_days: number | null; latest_period_end: string | null };
  rule_of_40: { applicable: boolean; label: string; score: number | null }; valuation: { label: string; label_key: string; evidence: string | null; base_fair_value: number | null };
  state: { seen: boolean; opened: boolean; saved: boolean; shown_count: number };
}
export interface CandidatesFeed {
  available: boolean; reason?: string; asof?: string; age_days?: number; stale?: boolean; target?: number; shown?: number; items: Candidate[]; pool_size?: number; evidence_note?: string; gaps: string[];
  excluded_by_my_filters?: Record<string, number>; hidden_because_seen?: { symbol: string; reason: string }[]; kept_varied?: { symbol: string; reason: string }[];
  study?: { universe: number; after_filters: number; studied: number; passed: number; left_out_reasons: Record<string, number>; could_not_study: Record<string, number> };
  method?: { weights: Record<string, number>; min_total: number; min_factors: number; max_per_sector: number; cooldown_days: number }; source?: { universe: string; filings: string };
}

/** Dollar amounts with a unit that keeps the figure honest: $12.30B, $450.0M, $12.5K, $340.00. A small non-zero amount is never shown as zero; null is "n/a". */
export function moneyShort(x: number | null | undefined, decimals = 1): string {
  if (x == null || !Number.isFinite(x)) return "n/a";
  const a = Math.abs(x), sign = x < 0 ? "-" : "";
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(decimals)}M`;
  if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(decimals)}K`;
  return `${sign}$${a.toFixed(2)}`;
}
