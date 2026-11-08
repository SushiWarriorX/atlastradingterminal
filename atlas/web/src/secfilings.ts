// Mirrors GET /api/stocks/filings. Form types, dates and links come from SEC EDGAR; the plain-English meaning is generic.
export interface SecFiling {
  symbol: string; name: string | null; instrument_id: string; form: string; meaning: string; importance: "high" | "medium" | "low"; filed: string; report_date: string | null;
  accepted_at: string | null; items: { item: string; meaning: string }[]; link: string | null; origin: string; fetched_at: string;
}
export interface SecFilings { as_of: string; forms: string[]; checked: number; demo: boolean; source: string; note: string; items: SecFiling[]; errors: string[]; needs_contact?: boolean }

/** Groups the filter chips use; each is a list of SEC form types. */
export const FILING_GROUPS: [string, string, string[]][] = [
  ["all", "All", []],
  ["reports", "Reports", ["10-K", "10-K/A", "10-Q", "20-F"]],
  ["events", "Events (8-K)", ["8-K", "8-K/A", "6-K"]],
  ["insiders", "Insiders", ["4", "144"]],
  ["holders", "Big holders", ["SC 13D", "SC 13D/A", "SC 13G"]],
  ["offerings", "Offerings", ["S-1", "S-3", "424B5"]],
  ["warnings", "Late notices", ["NT 10-K", "NT 10-Q"]],
];
