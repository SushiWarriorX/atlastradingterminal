import type { Tone } from "./lib/freshness";
import type { Stance } from "./api/types";

// One dark theme, restrained colour: green/red only for direction, amber only for "pay attention", violet only for demo data.
export const color = {
  bg: "#0B0B10", surface: "#14141B", surface2: "#1B1B25", border: "#262633", text: "#F4F4F7", dim: "#9B9BAB", faint: "#6A6A7A",
  accent: "#8B93FF", up: "#3DDC97", down: "#FF6B6B", warn: "#F5B14A", demo: "#B78CFF", live: "#3DDC97",
};
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };
export const radius = { sm: 8, md: 14, lg: 20, pill: 999 };
export const font = { xs: 11, sm: 13, md: 15, lg: 17, xl: 22, xxl: 30, hero: 38 };

export function toneColor(t: Tone): string {
  return { live: color.live, delayed: color.accent, historical: color.dim, stale: color.warn, demo: color.demo, unavailable: color.down }[t];
}
export function stanceColor(s: Stance | null): string {
  return s === "supportive" ? color.up : s === "cautious" ? color.warn : s === "mixed" ? color.accent : color.dim;
}
export function dirColor(d: "up" | "down" | "flat"): string {
  return d === "up" ? color.up : d === "down" ? color.down : color.dim;
}
