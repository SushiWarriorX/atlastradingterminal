export interface CalEvent {
  kind: "earnings" | "economy" | "rates" | "dividend" | "auction"; date: string; at_utc: string | null; time_label: string | null; title: string; symbol: string | null; name: string | null;
  importance: "high" | "medium" | "low"; market_cap: number | null; details: Record<string, string | number | boolean | null>; source: string; official: boolean; link: string | null; watch: boolean; instrument_id: string | null;
}
export interface CalSource { id: string; name: string; official: boolean; ok: boolean; count: number; error: string | null }
export interface CalData { as_of: string; from: string; to: string; demo: boolean; scope: string; kinds: string[]; items: CalEvent[]; counts: Record<string, number>; sources: CalSource[]; notes: string[]; importance_note: string; labels: Record<string, string> }
export const KIND_LABEL: Record<string, string> = { earnings: "Earnings", economy: "Economy", rates: "Rates (Fed)", dividend: "Dividends", auction: "Treasury auctions" };
