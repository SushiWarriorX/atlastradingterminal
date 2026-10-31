// Shared helpers for the e2e scripts.

// The DEMO BTC quote oscillates +/-1% around a fixed centre with a ~25 s period. Setting a level relative to the CURRENT price
// is flaky (near the top of the cycle it can sit above the maximum and never be crossed). Sample one full period to find the
// centre and amplitude, then return a level that the oscillation is guaranteed to cross upward every period.
async function demoCrossLevel(base = 'http://127.0.0.1:8000', seconds = 27) {
  const px = [];
  const end = Date.now() + seconds * 1000;
  while (Date.now() < end) {
    const r = await fetch(`${base}/api/quotes?ids=BTC-USD`).then(r => r.json());
    px.push(r.data[0].price);
    await new Promise(r => setTimeout(r, 1000));
  }
  const lo = Math.min(...px), hi = Math.max(...px), centre = (lo + hi) / 2, amp = (hi - lo) / 2;
  if (amp / centre < 0.004) throw new Error(`demo oscillation not observed (amplitude ${(100 * amp / centre).toFixed(3)}%)`);
  return Math.round((centre + 0.5 * amp) * 100) / 100;
}
module.exports = { demoCrossLevel };
