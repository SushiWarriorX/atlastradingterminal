import type { Tone } from "./lib/freshness";
import type { Stance } from "./api/types";

// Silver and graphite: near-black base, brushed-steel cards, bright silver accent. Green/red for direction, amber for "pay attention", sky blue for demo data.
export const color = {
  bg: "#08090B", surface: "#17191D", surface2: "#252930", border: "#3A3F48", text: "#FFFFFF", dim: "#A7ADB8", faint: "#9AA0AB",
  accent: "#D5D9E0", accent2: "#9AA1AD", accent3: "#EEF1F5", up: "#00C28C", down: "#FF5A66", warn: "#F5A524", demo: "#6DB3FF", live: "#00C28C",
  button: "#C4C9D1", onSilver: "#0B0C0E",
};
export const grad = {
  accent: ["#F6F8FB", "#C5CAD3", "#8C929D"] as const,       // buttons, active chips: polished silver, light to dark
  card: ["#2F333A", "#1E2126", "#14161A"] as const,         // cards: brushed steel fading to graphite
  hot: ["#303644", "#262A33", "#1D2025"] as const,          // highlight card: a cooler steel-blue sheen; dark enough that small grey captions stay readable (tested)
  good: ["#0F4A3E", "#1C2227", "#14161A"] as const, warn: ["#5A3F12", "#25221F", "#14161A"] as const, bad: ["#5A1B2B", "#251C20", "#14161A"] as const,
};
// Figtree: a free geometric typeface that is the closest match to Revolut's licensed Aeonik. Custom fonts need one family per weight.
export const fonts = { regular: "Figtree_400Regular", medium: "Figtree_500Medium", semibold: "Figtree_600SemiBold", bold: "Figtree_700Bold" };
export function famFor(w: unknown): string {
  const n = typeof w === "string" ? (w === "bold" ? 700 : w === "normal" ? 400 : parseInt(w, 10) || 400) : typeof w === "number" ? w : 400;
  return n >= 700 ? fonts.bold : n >= 600 ? fonts.semibold : n >= 500 ? fonts.medium : fonts.regular;
}
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
