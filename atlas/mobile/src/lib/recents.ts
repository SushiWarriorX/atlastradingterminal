import type { Asset } from "../api/types";

export const MAX_RECENTS = 8;

/** Most recent first, one entry per asset id (never per ticker), capped. */
export function pushRecent(list: Asset[], a: Asset, max = MAX_RECENTS): Asset[] {
  return [a, ...list.filter((x) => x.id !== a.id)].slice(0, max);
}

/** Defensive parse of whatever is in storage: anything malformed is dropped rather than crashing the app. */
export function parseRecents(raw: string | null | undefined): Asset[] {
  if (!raw) return [];
  try {
    const v = JSON.parse(raw);
    if (!Array.isArray(v)) return [];
    return v.filter((x): x is Asset => !!x && typeof x.id === "string" && typeof x.symbol === "string" && typeof x.name === "string" && ["crypto", "stock", "etf"].includes(x.type)).slice(0, MAX_RECENTS);
  } catch {
    return [];
  }
}
