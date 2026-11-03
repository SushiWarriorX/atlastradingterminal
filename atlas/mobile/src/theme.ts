import type { Tone } from "./lib/freshness";
import type { Stance } from "./api/types";

// Black and white with one blue for actions. Green/red only for direction, amber only for "pay attention", light blue only for demo data.
export const color = {
  bg: "#000000", surface: "#141414", surface2: "#1F1F1F", border: "#262626", text: "#FFFFFF", dim: "#8E8E93", faint: "#5F5F64",
  accent: "#2E7BFF", up: "#20C27B", down: "#F25C54", warn: "#F2A93B", demo: "#4DA3FF", live: "#20C27B",
};
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };
export const radius = { sm: 8, md: 14, lg: 22, pill: 999 };
export const font = { xs: 11, sm: 13, md: 15, lg: 17, xl: 22, xxl: 32, hero: 46 };

export function toneColor(t: Tone): string {
  return { live: color.live, delayed: color.dim, historical: color.faint, stale: color.warn, demo: color.demo, unavailable: color.down }[t];
}
export function stanceColor(s: Stance | null): string {
  return s === "supportive" ? color.up : s === "cautious" ? color.warn : color.dim;
}
export function dirColor(d: "up" | "down" | "flat"): string {
  return d === "up" ? color.up : d === "down" ? color.down : color.dim;
}
