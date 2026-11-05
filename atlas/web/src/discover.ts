export interface Pick {
  symbol: string; name: string | null; sector: string | null; asset_id: string; score: number; coverage: number; of: number; rank?: number;
  factors: Record<string, { score: number; inputs: Record<string, number | boolean | null> } | null>;
  reasons: string[]; risks: string[]; evidence: { label: string; value: number | null; unit: string; source: string; as_of: string }[];
  price: number; pe: number | null; revenue_growth_pct: number | null; as_of: { prices: string; fiscal_year_end: string };
}
export interface DiscoverRun {
  asof: string; created_at: string; demo: boolean; shortlist: Pick[]; ranked: Pick[]; stale_notice?: string; notes: string[]; excluded: Record<string, number>;
  universe: { name: string; size: number; priced: number; liquid: number; scored: number };
  data: { prices: string; prices_status: string; prices_as_of: string | null; fundamentals: string };
  method: { weights: Record<string, number>; scales: Record<string, string>; steps: string[]; min_factors: number; max_per_sector: number; note: string };
  gaps: string[]; disclaimer: string;
}
export interface DiscoverRanked { items: Pick[]; total: number; asof: string | null; sectors?: string[] }
