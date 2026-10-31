import type { Snapshot } from '../../shared/types';

export interface ProviderStatus {
  configured: boolean;
  connected: boolean;
  /** Can we try to fetch from it right now? */
  ready: boolean;
}

export interface Status {
  strava: ProviderStatus & { athlete: string | null };
  garmin: ProviderStatus;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const body = (await res.json().catch(() => null)) as { error?: string } | null;
  if (!res.ok) throw new Error(body?.error ?? `Request failed (${res.status})`);
  return body as T;
}

export const getStatus = () => request<Status>('/api/status');

export const getStrava = (days: number) =>
  request<{ snapshot: Snapshot; meta: { limited: boolean; activities: number } }>(`/api/strava/data?days=${days}`);

export const getGarmin = (days: number) =>
  request<{ snapshot: Snapshot; meta: { days: number; activities: number; failures: number } }>(
    `/api/garmin/data?days=${days}`,
  );

export const disconnect = (provider: 'strava' | 'garmin') =>
  request<{ ok: true }>(`/api/${provider}/disconnect`, { method: 'POST', headers: { 'X-Requested-With': 'vital' } });
