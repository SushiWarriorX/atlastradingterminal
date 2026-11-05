import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { AgentName, Asset, ChartRange, JournalFilters, ResearchResponse, WatchlistResponse } from "../api/types";
import { keys } from "../lib/keys";
import { pushRecent } from "../lib/recents";
import { applyAdd, applyRemove, applyReorder } from "../lib/watchlist";
import { useConnection } from "./connection";
import { storage } from "./storage";

export function useNow(everyMs = 30_000): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), everyMs); return () => clearInterval(t); }, [everyMs]);
  return now;
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

const need = <T,>(x: T | null): T => { if (!x) throw new Error("not connected"); return x; };

export function useMeta() {
  const { api, baseUrl } = useConnection();
  return useQuery({ queryKey: keys(baseUrl).meta, queryFn: () => need(api).meta(), enabled: !!api, staleTime: 5 * 60_000 });
}

/** The saved watchlist with prices. The last good copy is kept on the device (per server) and shown, marked, when the server cannot be reached. */
export function useWatchlist() {
  const { api, baseUrl } = useConnection();
  const [cache, setCache] = useState<{ data: WatchlistResponse; savedAt: number } | null | undefined>(undefined);
  useEffect(() => { let live = true; setCache(undefined); storage.getWatchlistCache(baseUrl).then((c) => { if (live) setCache(c); }); return () => { live = false; }; }, [baseUrl]);
  const q = useQuery({ queryKey: keys(baseUrl).watchlist, queryFn: () => need(api).watchlist(), enabled: !!api, refetchInterval: 20_000, refetchIntervalInBackground: false, retry: 1 });
  const saved = useRef<WatchlistResponse | null>(null);
  useEffect(() => {
    if (baseUrl && q.data && q.data !== saved.current && q.isSuccess) { saved.current = q.data; storage.setWatchlistCache(q.data, baseUrl).then(() => undefined); }
  }, [q.data, q.isSuccess, baseUrl]);
  const fromCache = !q.data && !!cache;
  return { ...q, data: q.data ?? cache?.data, fromCache, cachedAt: fromCache ? cache?.savedAt ?? null : null, cacheLoaded: cache !== undefined, updatedAt: q.dataUpdatedAt || null };
}

export function useSearch(query: string) {
  const { api, baseUrl } = useConnection();
  const q = query.trim();
  return useQuery({ queryKey: keys(baseUrl).search(q), queryFn: () => need(api).search(q), enabled: !!api && q.length > 0, staleTime: 60_000, retry: 1 });
}

export function useAsset(id: string) {
  const { api, baseUrl } = useConnection();
  return useQuery({ queryKey: keys(baseUrl).asset(id), queryFn: () => need(api).asset(id), enabled: !!api && !!id, refetchInterval: 15_000, retry: 1 });
}

export function useChart(id: string, range: ChartRange) {
  const { api, baseUrl } = useConnection();
  return useQuery({ queryKey: keys(baseUrl).chart(id, range), queryFn: () => need(api).chart(id, range), enabled: !!api && !!id, staleTime: 30_000, refetchInterval: range === "1D" ? 30_000 : 120_000, retry: 1 });
}

export function useResearch(id: string) {
  const { api, baseUrl } = useConnection();
  return useQuery<ResearchResponse>({
    queryKey: keys(baseUrl).research(id), queryFn: () => need(api).research(id, 4), enabled: !!api && !!id, retry: 1,
    refetchInterval: (q) => (q.state.data && q.state.data.pending.length ? 2_500 : 60_000), staleTime: 15_000,
  });
}

export function useRefreshAgent(id: string) {
  const { api, baseUrl } = useConnection();
  const qc = useQueryClient();
  return useMutation({ mutationFn: (agent: AgentName) => need(api).refreshAgent(id, agent), onSuccess: (data) => qc.setQueryData(keys(baseUrl).research(id), data) });
}

type Ctx = { prev?: WatchlistResponse };
function optimistic<V>(edit: (w: WatchlistResponse, v: V) => WatchlistResponse, call: (api: NonNullable<ReturnType<typeof useConnection>["api"]>, v: V) => Promise<unknown>, assetId: (v: V) => string | null) {
  return function useIt() {
    const { api, baseUrl } = useConnection();
    const qc = useQueryClient();
    const k = keys(baseUrl);
    return useMutation<unknown, Error, V, Ctx>({
      mutationFn: (v) => call(need(api), v),
      onMutate: async (v) => {
        await qc.cancelQueries({ queryKey: k.watchlist });
        const prev = qc.getQueryData<WatchlistResponse>(k.watchlist);
        if (prev) qc.setQueryData(k.watchlist, edit(prev, v));
        return { prev };
      },
      onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(k.watchlist, ctx.prev); },          // the server said no: put the list back exactly as it was
      onSettled: (_d, _e, v) => {
        qc.invalidateQueries({ queryKey: k.watchlist });
        const id = assetId(v);
        if (id) qc.invalidateQueries({ queryKey: k.asset(id) });
      },
    });
  };
}
export const useAddToWatchlist = optimistic<Asset>(applyAdd, (api, a) => api.addToWatchlist(a.id), (a) => a.id);
export const useRemoveFromWatchlist = optimistic<string>(applyRemove, (api, id) => api.removeFromWatchlist(id), (id) => id);
export const useReorderWatchlist = optimistic<string[]>(applyReorder, (api, ids) => api.reorderWatchlist(ids), () => null);

export function useRecents() {
  const { baseUrl } = useConnection();
  const [list, setList] = useState<Asset[]>([]);
  useEffect(() => { let live = true; setList([]); storage.getRecents(baseUrl).then((l) => { if (live) setList(l); }); return () => { live = false; }; }, [baseUrl]);
  const add = (a: Asset) => setList((cur) => { const n = pushRecent(cur, a); storage.setRecents(n, baseUrl); return n; });
  const clear = () => { setList([]); storage.setRecents([], baseUrl); };
  return { list, add, clear };
}

export function useJournal(filters: JournalFilters) {
  const { api, baseUrl } = useConnection();
  return useQuery({ queryKey: keys(baseUrl).journal(filters), queryFn: () => need(api).journalLog(filters), enabled: !!api, refetchInterval: 30_000, retry: 1 });
}

export function useJournalSave() {
  const { api, baseUrl } = useConnection();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string | null; body: Record<string, string | null> }) => (id ? need(api).journalUpdate(id, body) : need(api).journalCreate(body)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["journal", baseUrl] }),
  });
}

export function useJournalDelete() {
  const { api, baseUrl } = useConnection();
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string) => need(api).journalDelete(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["journal", baseUrl] }) });
}

export function useMacroBrief() {
  const { api, baseUrl } = useConnection();
  return useQuery({ queryKey: keys(baseUrl).macro, queryFn: () => need(api).macroBrief(), enabled: !!api, staleTime: 5 * 60_000, refetchInterval: 10 * 60_000, retry: 1 });
}

export function useStockResearch(symbol: string, enabled: boolean) {
  const { api, baseUrl } = useConnection();
  return useQuery({ queryKey: keys(baseUrl).stock(symbol), queryFn: () => need(api).stockResearch(symbol), enabled: !!api && enabled, staleTime: 10 * 60_000, retry: 0 });
}

export function useEarnings(days: number, enabled: boolean) {
  const { api, baseUrl } = useConnection();
  return useQuery({ queryKey: keys(baseUrl).earnings(days), queryFn: () => need(api).earnings(days), enabled: !!api && enabled, staleTime: 10 * 60_000, retry: 0 });
}
