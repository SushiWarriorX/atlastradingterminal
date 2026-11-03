import type { Asset, WatchlistResponse, WatchRow } from "../api/types";

export type Move = "up" | "down";

/** Move one id up or down by one place. Returns the same array if it cannot move. */
export function moveId(ids: string[], id: string, dir: Move): string[] {
  const i = ids.indexOf(id);
  const j = dir === "up" ? i - 1 : i + 1;
  if (i < 0 || j < 0 || j >= ids.length) return ids;
  const out = ids.slice();
  [out[i], out[j]] = [out[j], out[i]];
  return out;
}

export const idsOf = (w: WatchlistResponse | undefined | null): string[] => (w?.items ?? []).map((r) => r.asset.id);

/** Optimistic edits applied to the cached list while the server call is in flight; rolled back by restoring the previous cache on error. */
export function applyRemove(w: WatchlistResponse, id: string): WatchlistResponse {
  const items = w.items.filter((r) => r.asset.id !== id);
  return { ...w, items, count: items.length };
}
export function applyReorder(w: WatchlistResponse, ids: string[]): WatchlistResponse {
  const by = new Map(w.items.map((r) => [r.asset.id, r] as const));
  const items = ids.map((i) => by.get(i)).filter((r): r is WatchRow => !!r);
  return { ...w, items: items.length === w.items.length ? items : w.items };
}
export function placeholderRow(a: Asset): WatchRow {
  return { asset: a, quote: null, spark: null, takeaway: null, error: null, loading: true };
}
/** Rows the server has answered for. Placeholders are left out of every "how many prices are stale or missing" count. */
export const settledRows = (items: WatchRow[]): WatchRow[] => items.filter((r) => !r.loading);
export function applyAdd(w: WatchlistResponse, a: Asset): WatchlistResponse {
  if (w.items.some((r) => r.asset.id === a.id)) return w;
  return { ...w, items: [...w.items, placeholderRow(a)], count: w.count + 1 };
}
export function emptyWatchlist(demo = false): WatchlistResponse {
  return { items: [], count: 0, demo, as_of: new Date(0).toISOString() };
}
