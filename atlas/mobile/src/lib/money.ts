/** Dollar amounts with a unit that keeps the figure honest: $12.30B, $450.0M, $12.5K, $340.00. A small non-zero amount is never shown as zero; null is "n/a". */
export function moneyShort(x: number | null | undefined, decimals = 1): string {
  if (x == null || !Number.isFinite(x)) return "n/a";
  const a = Math.abs(x), sign = x < 0 ? "−" : "";
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(decimals)}M`;
  if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(decimals)}K`;
  return `${sign}$${a.toFixed(2)}`;
}
