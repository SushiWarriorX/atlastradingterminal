import { createContext, useContext } from "react";
import { BTC_ID } from "./ids";
import { useStore } from "./store";

/** Which desk a widget sits on. "btc" is locked to Bitcoin, "equity" to stocks and ETFs; null follows the global selection (Charts, Overview, ...). */
export type Scope = "btc" | "equity" | null;
export const ScopeContext = createContext<Scope>(null);

/** The instrument a widget should show: fixed to BTC on the BTC desk, the last selected stock/ETF on the Equities desk, else the global selection. */
export function useSelectedId(): string {
  const scope = useContext(ScopeContext);
  const selected = useStore((s) => s.selected);
  const equity = useStore((s) => s.selectedEquity);
  return scope === "btc" ? BTC_ID : scope === "equity" ? equity : selected;
}
export const useScope = () => useContext(ScopeContext);
