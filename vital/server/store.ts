import fs from 'node:fs';
import path from 'node:path';
import { config } from './env';

/** Tiny JSON-file store under ./.data (gitignored). Holds tokens and caches. */
const DIR = config.dataDir;

export function readJson<T>(name: string, fallback: T): T {
  try {
    return JSON.parse(fs.readFileSync(path.join(DIR, name), 'utf8')) as T;
  } catch {
    return fallback;
  }
}

export function writeJson(name: string, value: unknown): void {
  fs.mkdirSync(DIR, { recursive: true, mode: 0o700 });
  fs.writeFileSync(path.join(DIR, name), JSON.stringify(value), { mode: 0o600 });
}

export function removeFile(name: string): void {
  fs.rmSync(path.join(DIR, name), { force: true });
}

/** In-memory TTL cache so refreshing the page doesn't hammer upstream rate limits. */
export class TtlCache<T> {
  private entry: { at: number; value: T } | null = null;
  constructor(private readonly ttlMs: number) {}
  get(): T | null {
    return this.entry && Date.now() - this.entry.at < this.ttlMs ? this.entry.value : null;
  }
  set(value: T): void {
    this.entry = { at: Date.now(), value };
  }
  clear(): void {
    this.entry = null;
  }
}
