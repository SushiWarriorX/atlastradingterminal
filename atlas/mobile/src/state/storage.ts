import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";
import type { Asset, WatchlistResponse } from "../api/types";
import { parseRecents } from "../lib/recents";

const K = { baseUrl: "signal.baseUrl.v1", token: "signal.token.v1", watchlist: "signal.watchlist.cache.v2", recents: "signal.recents.v1" };
const native = Platform.OS !== "web";

async function safe<T>(fn: () => Promise<T>, fallback: T): Promise<T> {
  try { return await fn(); } catch { return fallback; }          // private mode, full disk, or a platform without the module: the app still works, it just forgets
}

export const storage = {
  getBaseUrl: () => safe(() => AsyncStorage.getItem(K.baseUrl), null),
  setBaseUrl: (v: string) => safe(() => AsyncStorage.setItem(K.baseUrl, v), undefined),
  // The login token lives in the platform's secure store (Keychain / Keystore). The web build has none, so it falls back to local storage: use the web build for development only.
  getToken: () => safe(() => (native ? SecureStore.getItemAsync(K.token) : AsyncStorage.getItem(K.token)), null),
  setToken: (v: string) => safe(() => (native ? SecureStore.setItemAsync(K.token, v) : AsyncStorage.setItem(K.token, v)), undefined),
  clearToken: () => safe(() => (native ? SecureStore.deleteItemAsync(K.token) : AsyncStorage.removeItem(K.token)), undefined),
  /** The saved copy is only ever returned for the server it came from, so a demo server's list can never appear under a live one. */
  async getWatchlistCache(baseUrl: string | null): Promise<{ data: WatchlistResponse; savedAt: number } | null> {
    const raw = await safe(() => AsyncStorage.getItem(K.watchlist), null);
    if (!raw) return null;
    try {
      const v = JSON.parse(raw);
      return v && baseUrl && v.baseUrl === baseUrl && Array.isArray(v.data?.items) && typeof v.savedAt === "number" ? v : null;
    } catch { return null; }
  },
  setWatchlistCache: (data: WatchlistResponse, baseUrl: string) => safe(() => AsyncStorage.setItem(K.watchlist, JSON.stringify({ data, savedAt: Date.now(), baseUrl })), undefined),
  clearWatchlistCache: () => safe(() => AsyncStorage.removeItem(K.watchlist), undefined),
  /** Recent searches are kept per server, like the saved copy of the watchlist: a demo server's assets never show up under a live one. */
  getRecents: async (baseUrl: string | null): Promise<Asset[]> => (baseUrl ? parseRecents(await safe(() => AsyncStorage.getItem(`${K.recents}:${baseUrl}`), null)) : []),
  setRecents: (list: Asset[], baseUrl: string | null) => (baseUrl ? safe(() => AsyncStorage.setItem(`${K.recents}:${baseUrl}`, JSON.stringify(list)), undefined) : Promise.resolve(undefined)),
};
