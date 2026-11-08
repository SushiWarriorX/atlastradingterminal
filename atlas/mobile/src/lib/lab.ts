/** What to tell the user while a Strategy Lab comparison runs. On real data the first run downloads BTC history, which can take a minute, so a bare spinner looks frozen. */
export function busyText(market: string, timeframe: string): string {
  const parts = ["Running the comparison."];
  parts.push(timeframe === "1d" ? "The first run on real data downloads BTC price history; later runs are quick." : "The first run on real data downloads about three years of hourly prices; later runs are quick.");
  if (market === "perp") parts.push("Perpetual runs also download funding history (from 2023), which can take up to a minute the first time.");
  return parts.join(" ");
}
