import type { Tone } from "./lib/freshness";
import type { Stance } from "./api/types";

// Deep midnight with a violet-to-teal accent. Green/red for direction, amber for "pay attention", sky blue for demo data.
export const color = {
  bg: "#07070F", surface: "#12121F", surface2: "#1C1C33", border: "#2A2A4A", text: "#FFFFFF", dim: "#A0A0BC", faint: "#6C6C8C",
  accent: "#8B7BFF", accent2: "#3B82F6", accent3: "#14D9C5", up: "#22D3A0", down: "#FF5D7A", warn: "#FFB547", demo: "#4DA3FF", live: "#22D3A0",
};
export const grad = {
  accent: ["#7C5CFF", "#3B82F6", "#14D9C5"] as const,       // buttons, active tabs, highlights
  card: ["#1E1B3A", "#14142A", "#101022"] as const,         // cards: a faint violet-to-navy slope
  good: ["#0F3D36", "#12121F"] as const, warn: ["#3D2E10", "#12121F"] as const, bad: ["#3D1220", "#12121F"] as const,
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
