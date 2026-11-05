import type { Tone } from "./lib/freshness";
import type { Stance } from "./api/types";

// Revolut-style: true black, charcoal cards, one blue-violet accent. Green/red for direction, amber for "pay attention", sky blue for demo data.
export const color = {
  bg: "#05050D", surface: "#161A2E", surface2: "#222747", border: "#2F3566", text: "#FFFFFF", dim: "#8D969E", faint: "#6B7279",
  accent: "#6F75F5", accent2: "#0666EB", accent3: "#4DA3FF", up: "#00C28C", down: "#FF5A66", warn: "#F5A524", demo: "#4DA3FF", live: "#00C28C",
  button: "#5B5FF0",
};
export const grad = {
  accent: ["#7A5CFF", "#3D7BFF", "#16D9C6"] as const,       // buttons, active chips and tabs: violet to blue to teal
  card: ["#2B2478", "#1A1F4F", "#12162E"] as const,         // cards: indigo fading to navy
  hot: ["#8A2A6B", "#41268F", "#1B2F7A"] as const,          // highlight card: deep magenta to violet to navy, dark enough for white text
  good: ["#0C5A49", "#123246", "#12162E"] as const, warn: ["#6A4310", "#2A2030", "#12162E"] as const, bad: ["#6A1830", "#2A1A38", "#12162E"] as const,
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
