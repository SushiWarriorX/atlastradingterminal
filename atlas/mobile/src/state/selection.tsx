import { router } from "expo-router";
import React, { createContext, useCallback, useContext, useMemo, useState } from "react";
import { useIsWide } from "./layout";

export type Pane = "watchlist" | "search";
export type Dest = "btc" | "stocks" | "macro" | "discover" | "journal";
export const DESTS: { key: Dest; label: string }[] = [{ key: "btc", label: "BTC" }, { key: "stocks", label: "Stocks" }, { key: "macro", label: "Macro" }, { key: "discover", label: "Discover" }, { key: "journal", label: "Journal" }];
export const BTC_ID = "CRYPTO:COINBASE:BTC-USD:SPOT";
interface Sel { selectedId: string | null; select: (id: string) => void; pane: Pane; setPane: (p: Pane) => void; dest: Dest; setDest: (d: Dest) => void }
const Ctx = createContext<Sel | null>(null);

/** On wide screens the asset being read lives in the centre pane; this remembers which one and which left pane is showing. */
export function SelectionProvider({ children }: { children: React.ReactNode }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pane, setPane] = useState<Pane>("watchlist");
  const [dest, setDest] = useState<Dest>("btc");
  const select = useCallback((id: string) => setSelectedId(id), []);
  const value = useMemo(() => ({ selectedId, select, pane, setPane, dest, setDest }), [selectedId, select, pane, dest]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
export function useSelection(): Sel {
  const c = useContext(Ctx);
  if (!c) throw new Error("useSelection must be used inside SelectionProvider");
  return c;
}

/** One way to open an asset from any list: select it in the centre pane on wide screens, push its screen on a phone. */
export function useOpenAsset(): (id: string) => void {
  const wide = useIsWide();
  const { select, setDest } = useSelection();
  return useCallback((id: string) => { if (wide) { select(id); setDest("stocks"); } else router.push({ pathname: "/asset/[id]", params: { id } }); }, [wide, select, setDest]);
}
export function useGoToSearch(): () => void {
  const wide = useIsWide();
  const { setPane, setDest } = useSelection();
  return useCallback(() => { if (wide) { setDest("stocks"); setPane("search"); } else router.push("/search"); }, [wide, setPane, setDest]);
}
