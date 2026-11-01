// Plain constants shared by the store and the scope hook (kept free of imports so neither module has to load the other first).
export const BTC_ID = "CRYPTO:COINBASE:BTC-USD:SPOT";
export const DEFAULT_EQUITY = "EQUITY:NASDAQ:AAPL";
export const isEquityId = (id: string) => id.startsWith("EQUITY:") || id.startsWith("ETF:");
