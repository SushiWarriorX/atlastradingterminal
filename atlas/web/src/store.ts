import { create } from "zustand";
import { api, Prefs } from "./api";

import { BTC_ID as BTC, DEFAULT_EQUITY, isEquityId } from "./ids";
import { NAV } from "./workspaces";

const EQ_KEY = "atlas.selectedEquity";
const loadEquity = (): string => { try { const v = localStorage.getItem(EQ_KEY); return v && isEquityId(v) ? v : DEFAULT_EQUITY; } catch { return DEFAULT_EQUITY; } };
const saveEquity = (id: string) => { try { localStorage.setItem(EQ_KEY, id); } catch { /* per-viewer convenience only */ } };

interface State {
  theme: "dark" | "light"; updateSeconds: number; selected: string; selectedEquity: string; workspace: string; hydrated: boolean;
  pendingAsk: string | null; pendingScan: string | null; pendingBacktest: string | null; alertDraft: Record<string, unknown> | null; pendingCompare: string[] | null; ticketDraft: Record<string, string> | null; portfolioId: number | undefined; journalKey: string | null; helpOpen: boolean; notice: string | null;
  hydrate: () => Promise<void>;
  select: (id: string) => void;
  setWorkspace: (w: string) => void;
  setTheme: (t: "dark" | "light") => void;
  setUpdateSeconds: (s: number) => void;
  setPendingAsk: (a: string | null) => void;
  setPendingScan: (a: string | null) => void;
  setPendingBacktest: (a: string | null) => void;
  setAlertDraft: (d: Record<string, unknown> | null) => void;
  setPendingCompare: (c: string[] | null) => void;
  setTicketDraft: (d: Record<string, string> | null) => void;
  setPortfolioId: (id: number | undefined) => void;
  setJournalKey: (k: string | null) => void;
  takePendingCompare: () => string[] | null;
  setHelp: (o: boolean) => void;
  setNotice: (n: string | null) => void;
}

const persist = (p: Partial<Prefs>) => { api.setPrefs(p).catch(() => undefined); };

export const useStore = create<State>((set, get) => ({
  theme: "dark", updateSeconds: 5, selected: BTC, selectedEquity: loadEquity(), workspace: "overview", hydrated: false, pendingAsk: null, pendingScan: null, pendingBacktest: null, alertDraft: null, pendingCompare: null, ticketDraft: null, portfolioId: undefined, journalKey: null, helpOpen: false, notice: null,
  hydrate: async () => {
    try {
      const p = await api.prefs();
      document.documentElement.dataset.theme = p.theme;
      const eq = isEquityId(p.selected_instrument) ? p.selected_instrument : loadEquity();
      saveEquity(eq);
      // a workspace that no longer exists (Markets, Fundamentals) falls back to Overview instead of showing a dead page
      set({ theme: p.theme, updateSeconds: p.update_seconds, selected: p.selected_instrument, selectedEquity: eq, workspace: NAV.some((n) => n.view === p.workspace) ? p.workspace : "overview", hydrated: true });
    } catch {
      set({ hydrated: true });
    }
  },
  select: (id) => {
    if (isEquityId(id)) { saveEquity(id); set({ selected: id, selectedEquity: id }); } else set({ selected: id });
    persist({ selected_instrument: id });
  },
  setWorkspace: (w) => { set({ workspace: w }); persist({ workspace: w }); },
  setTheme: (t) => { document.documentElement.dataset.theme = t; set({ theme: t }); persist({ theme: t }); },
  setUpdateSeconds: (s) => { set({ updateSeconds: s }); persist({ update_seconds: s }); },
  setPendingAsk: (a) => set({ pendingAsk: a }),
  setPendingScan: (a) => set({ pendingScan: a }),
  setPendingBacktest: (a) => set({ pendingBacktest: a }),
  setAlertDraft: (d) => set({ alertDraft: d }),
  setPendingCompare: (c) => set({ pendingCompare: c }),
  setTicketDraft: (d) => set({ ticketDraft: d }),
  setPortfolioId: (id) => set({ portfolioId: id }),
  setJournalKey: (k) => set({ journalKey: k }),
  // atomic read-and-clear: several charts can mount in the same commit, and exactly one may take the request
  takePendingCompare: () => { const c = get().pendingCompare; if (c) set({ pendingCompare: null }); return c; },
  setHelp: (o) => set({ helpOpen: o }),
  setNotice: (n) => set({ notice: n }),
}));
