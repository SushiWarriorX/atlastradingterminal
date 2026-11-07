export interface Year { end: string; revenue: number | null; revenue_growth_pct: number | null; gross_margin_pct: number | null; operating_margin_pct: number | null; net_margin_pct: number | null; net_income: number | null; free_cash_flow: number | null; fcf_margin_pct: number | null; net_cash: number | null; debt_to_equity: number | null; eps_diluted: number | null }
export interface Case { id: string; text: string; based_on: string[]; kind: string }
export interface Filing { form: string; filed: string; report_date: string | null; link: string | null; items: { item: string; meaning: string }[] }
export interface StockResearch {
  symbol: string; as_of: string; demo: boolean;
  company: { name: string | null; sector: string | null; industry: string | null; sic_description: string | null; fiscal_year_end: string | null; source: string };
  financials: { available: boolean; years: Year[]; revenue_cagr: { value_pct: number; from: string; to: string; years: number; formula: string } | null; source: string; note: string; meta: { origin: string; fetched_at: string } | null };
  valuation: { rows: { key: string; label: string; value: number | null; unit: string; basis: string; note: string | null }[]; flags: string[]; source: string | null; fetched_at: string | null; status: string | null } | null;
  earnings: { next_date: string | null; source: string; guidance: { available: boolean; reason: string }; consensus: { available: boolean; reason: string } };
  bull: Case[]; bear: Case[]; case_note: string;
  catalysts: { kind: string; date: string; title: string; source: string; link: string | null }[];
  filings: Filing[]; news: { title: string; link: string | null; feed: string; published: string | null }[];
  errors: string[]; gaps: string[];
}
export interface EarningsCal { as_of: string; window_days: number; items: { symbol: string; name: string | null; instrument_id: string; date: string; days_away: number; sector: string | null; status: string | null; source: string }[]; checked: number; errors: string[]; note: string }
