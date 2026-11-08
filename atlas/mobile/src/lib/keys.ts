import type { ChartRange } from "../api/types";

/** Every cached answer is keyed by the server it came from, so an answer from one server (say a demo one) can never be shown while connected to another. */
export const keys = (base: string | null) => ({
  meta: ["meta", base] as const,
  watchlist: ["watchlist", base] as const,
  search: (q: string) => ["search", base, q] as const,
  asset: (id: string) => ["asset", base, id] as const,
  chart: (id: string, r: ChartRange) => ["chart", base, id, r] as const,
  research: (id: string) => ["research", base, id] as const,
  stock: (symbol: string) => ["stock", base, symbol] as const,
  whatif: (id: string, amount: number) => ["whatif", base, id, amount] as const,
  earnings: (days: number) => ["earnings", base, days] as const,
  calendar: (q: string) => ["calendar", base, q] as const,
  discover: ["discover", base] as const,
  macro: ["macro", base] as const,
  journal: (filters: object) => ["journal", base, filters] as const,
});
