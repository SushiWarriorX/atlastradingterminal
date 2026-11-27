import type { Tone } from "./lib/freshness";
import type { Stance } from "./api/types";

// A clean light look in the manner of TradingView's phone app: white screens, light-grey chips and avatars, hairline dividers, near-black text, TradingView-style blue for the one accent, and green/red for direction.
// Text colours are chosen so that grey captions (faint) and body-small text (dim) reach 4.5:1 on every card background (tested); amber is "pay attention", the second blue is demo data.
export const color = {
  bg: "#FFFFFF", surface: "#F5F7FA", surface2: "#EBEEF3", border: "#E1E4EB", text: "#0F1115", dim: "#565B68", faint: "#666B79",
  accent: "#2962FF", accent2: "#5B86FF", accent3: "#1A4BD6", up: "#07806A", down: "#D12F43", warn: "#A15C00", demo: "#1E5BD8", live: "#07806A",
  onAccent: "#FFFFFF",
};
export const grad = {
  accent: ["#3A76FF", "#2962FF", "#1D52E8"] as const,       // buttons and active chips: TradingView blue, light to dark
  card: ["#FFFFFF", "#FFFFFF", "#F7F9FC"] as const,         // cards: white, with the faintest cool shade at the far corner
  hot: ["#E8EFFF", "#F0F5FF", "#FFFFFF"] as const,          // highlight card: a pale blue wash
  good: ["#DFF4EC", "#F2FAF7", "#FFFFFF"] as const, warn: ["#FFEFD6", "#FFF8EB", "#FFFFFF"] as const, bad: ["#FFEBEE", "#FFF5F6", "#FFFFFF"] as const,
};
// Figtree: a free geometric typeface. Custom fonts need one family per weight.
export const fonts = { regular: "Figtree_400Regular", medium: "Figtree_500Medium", semibold: "Figtree_600SemiBold", bold: "Figtree_700Bold" };
export function famFor(w: unknown): string {
  const n = typeof w === "string" ? (w === "bold" ? 700 : w === "normal" ? 400 : parseInt(w, 10) || 400) : typeof w === "number" ? w : 400;
  return n >= 700 ? fonts.bold : n >= 600 ? fonts.semibold : n >= 500 ? fonts.medium : fonts.regular;
}
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };
export const radius = { sm: 8, md: 14, lg: 18, pill: 999 };
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
