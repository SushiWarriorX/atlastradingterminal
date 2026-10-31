export const clamp = (x: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, x));

export const mean = (xs: number[]): number => xs.reduce((a, b) => a + b, 0) / xs.length;

/** Sample standard deviation. */
export function sd(xs: number[]): number {
  if (xs.length < 2) return 0;
  const m = mean(xs);
  return Math.sqrt(xs.reduce((a, x) => a + (x - m) ** 2, 0) / (xs.length - 1));
}

export const sigmoid = (x: number): number => 1 / (1 + Math.exp(-x));

export function round(x: number, digits = 0): number {
  const f = 10 ** digits;
  return Math.round(x * f) / f;
}
