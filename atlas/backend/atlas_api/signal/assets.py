"""Asset identity and search.

Every asset has a STABLE id that carries its type and venue, never just a ticker:
    CRYPTO:COINBASE:ETH-USD:SPOT     a crypto pair traded on Coinbase (USD)
    EQUITY:NASDAQ:AAPL               a US-listed stock
    ETF:ARCA:BTC                     a US-listed ETF (the Grayscale Bitcoin Mini Trust: NOT Bitcoin itself)
    EQUITY:US:XYZ                    an unverified ticker (exchange and type unknown)
so tokens, stocks and ETFs that share a ticker can never be confused, and an id can be turned back into an instrument without any lookup.

Coverage is honest and small: crypto = a hand-entered list of large tokens that trade against USD on Coinbase (checked against Coinbase's product list when it can
be reached); stocks/ETFs = the ATLAS catalog plus the Nasdaq Trader directory when it can be reached. Nothing else is claimed as supported.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from .. import instruments as I
from ..instruments import Instrument
from ..scanner.universe import CORE, NASDAQ_URLS

CRYPTO_ID = re.compile(r"^CRYPTO:COINBASE:([A-Z0-9]{2,12})-USD:SPOT$")
STOCK_ID = re.compile(r"^(EQUITY|ETF):([A-Z_]{2,14}):([A-Z0-9][A-Z0-9.\-]{0,11})$")
TICKERISH = re.compile(r"^[A-Za-z]{1,5}([.\-][A-Za-z])?$")
EXCHANGE_LABEL = {"NASDAQ": "Nasdaq", "NYSE": "NYSE", "ARCA": "NYSE Arca", "AMEX": "NYSE American", "BATS": "Cboe BZX", "IEX": "IEX", "US": "US (exchange unverified)"}
OTHER_LISTED_EXCHANGE = {"A": "AMEX", "N": "NYSE", "P": "ARCA", "Z": "BATS", "V": "IEX"}
COINBASE_PRODUCTS = "https://api.exchange.coinbase.com/products"
CRYPTO_VENUE = "Coinbase spot (USD)"
DIRECTORY_TTL = 24 * 3600
PRODUCTS_TTL = 6 * 3600
RETRY_AFTER_FAILURE = 600

# Hand-entered: symbol, name, CoinGecko id. Whether Coinbase actually lists each pair is checked at runtime when possible and at quote time always.
TOKENS: list[tuple[str, str, str]] = [
    ("BTC", "Bitcoin", "bitcoin"), ("ETH", "Ethereum", "ethereum"), ("SOL", "Solana", "solana"), ("XRP", "XRP", "ripple"), ("ADA", "Cardano", "cardano"),
    ("DOGE", "Dogecoin", "dogecoin"), ("AVAX", "Avalanche", "avalanche-2"), ("LINK", "Chainlink", "chainlink"), ("DOT", "Polkadot", "polkadot"),
    ("LTC", "Litecoin", "litecoin"), ("BCH", "Bitcoin Cash", "bitcoin-cash"), ("UNI", "Uniswap", "uniswap"), ("ATOM", "Cosmos", "cosmos"),
    ("XLM", "Stellar", "stellar"), ("NEAR", "NEAR Protocol", "near"), ("AAVE", "Aave", "aave"), ("ARB", "Arbitrum", "arbitrum"), ("OP", "Optimism", "optimism"),
    ("APT", "Aptos", "aptos"), ("SUI", "Sui", "sui"), ("HBAR", "Hedera", "hedera-hashgraph"), ("SHIB", "Shiba Inu", "shiba-inu"), ("PEPE", "Pepe", "pepe"),
    ("FIL", "Filecoin", "filecoin"), ("ETC", "Ethereum Classic", "ethereum-classic"), ("ALGO", "Algorand", "algorand"), ("ICP", "Internet Computer", "internet-computer"),
    ("INJ", "Injective", "injective-protocol"), ("RENDER", "Render", "render-token"), ("ONDO", "Ondo", "ondo-finance"), ("CRV", "Curve DAO", "curve-dao-token"),
    ("MKR", "Maker", "maker"), ("GRT", "The Graph", "the-graph"), ("LDO", "Lido DAO", "lido-dao"), ("SEI", "Sei", "sei-network"), ("TIA", "Celestia", "celestia"),
    ("WIF", "dogwifhat", "dogwifcoin"), ("BONK", "Bonk", "bonk"), ("POL", "Polygon", "polygon-ecosystem-token"),
]
TOKEN_BY_SYMBOL = {s: (n, cg) for s, n, cg in TOKENS}
TYPE_ORDER = {"crypto": 0, "stock": 1, "etf": 2}


@dataclass(frozen=True)
class Asset:
    id: str
    symbol: str
    name: str
    type: str                  # crypto | stock | etf
    venue: str                 # human label: "Nasdaq", "Coinbase spot (USD)"
    support: str               # supported | unverified
    inst: Instrument
    note: str | None = None
    coingecko_id: str | None = None
    sector: str | None = None

    def public(self) -> dict:
        return {"id": self.id, "symbol": self.symbol, "name": self.name, "type": self.type, "venue": self.venue, "support": self.support, "note": self.note}


def _crypto(sym: str) -> Asset:
    name, cg = TOKEN_BY_SYMBOL.get(sym, (sym, None))
    aid = f"CRYPTO:COINBASE:{sym}-USD:SPOT"
    inst = I.get(aid) or Instrument(aid, f"{sym}-USD", f"{name} / US Dollar (Coinbase spot)", "crypto", "COINBASE", "coinbase", f"{sym}-USD", venue="COINBASE", kind="spot",
                                    note="Single-venue price; not the global market price.")
    known = sym in TOKEN_BY_SYMBOL
    return Asset(aid, sym, name, "crypto", CRYPTO_VENUE, "supported" if known else "unverified", inst,
                 "Priced from Coinbase only. The same ticker can mean different tokens elsewhere; this id is Coinbase's " + sym + "-USD pair." if known
                 else "Not in Signal's token list: availability is unverified.", cg)


def _stock(cls: str, exch: str, sym: str, name: str | None, support: str, note: str | None = None) -> Asset:
    kind = "etf" if cls == "ETF" else "equity"
    aid = f"{cls}:{exch}:{sym}"
    cat = I.get(aid)
    inst = cat or Instrument(aid, sym, name or sym, kind, exch, "yahoo", sym.replace(".", "-"), sector=CORE.get(sym))
    return Asset(aid, sym, name or (cat.name if cat else sym), "etf" if cls == "ETF" else "stock", EXCHANGE_LABEL.get(exch, exch), support, inst, note, sector=inst.sector or CORE.get(sym))


def describe(asset_id: str) -> Asset | None:
    """Turn an id back into an asset with no lookup (so a saved watchlist still works when no directory can be loaded)."""
    m = CRYPTO_ID.match(asset_id)
    if m:
        return _crypto(m.group(1))
    m = STOCK_ID.match(asset_id)
    if m:
        cls, exch, sym = m.groups()
        if exch == "US":
            return _stock(cls, exch, sym, None, "unverified", "Not in Signal's list: exchange and asset type are unverified, so some research may not apply.")
        return _stock(cls, exch, sym, None, "unverified", "Not checked against a directory: availability is unverified.")
    return None


def parse_directory(nasdaq_txt: str, other_txt: str) -> list[tuple[str, str, str, bool]]:
    """(symbol, clean name, exchange key, is_etf) from the two Nasdaq Trader files. Test issues and odd symbols are dropped."""
    out: dict[tuple[str, str], tuple[str, str, str, bool]] = {}
    for txt, sym_col, exch_col in ((nasdaq_txt, "Symbol", None), (other_txt, "ACT Symbol", "Exchange")):
        lines = [l for l in txt.splitlines() if l and not l.startswith("File Creation Time")]
        if not lines:
            continue
        head = lines[0].split("|")
        try:
            i_sym, i_name, i_test, i_etf = head.index(sym_col), head.index("Security Name"), head.index("Test Issue"), head.index("ETF")
        except ValueError:
            continue
        i_ex = head.index(exch_col) if exch_col and exch_col in head else None
        for row in lines[1:]:
            f = row.split("|")
            if len(f) <= max(i_sym, i_name, i_test, i_etf) or f[i_test] == "Y":
                continue
            sym = f[i_sym].strip()
            if not sym or "$" in sym or not re.fullmatch(r"[A-Z]{1,5}([.\-][A-Z])?", sym):
                continue
            exch = "NASDAQ" if i_ex is None else OTHER_LISTED_EXCHANGE.get(f[i_ex].strip(), "")
            if not exch:
                continue
            name = re.sub(r"\s+-\s+(Common Stock|Class [A-Z] Common Stock|Ordinary Shares.*|American Depositary.*|Units?.*|Warrants?.*)$", "", f[i_name].strip()) or sym
            out[(exch, sym.replace("-", "."))] = (sym.replace("-", "."), name, exch, f[i_etf].strip() == "Y")
    return sorted(out.values())


class AssetRegistry:
    def __init__(self, *, demo: bool = False, cache_dir: str | None = None, client_factory=None, clock=time.time):
        self.demo, self._clock = demo, clock
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=6.0), follow_redirects=True))
        self._cache = Path(cache_dir or os.getenv("ATLAS_CACHE_DIR", ".")) / "signal_directory.json"
        self._by_id: dict[str, Asset] = {}
        self._dir_ok_at: float | None = None
        self._dir_retry_at = 0.0
        self.directory_error: str | None = None
        self._listed: set[str] | None = None
        self._listed_at = 0.0
        self._lock = asyncio.Lock()
        for sym, _, _ in TOKENS:
            a = _crypto(sym)
            self._by_id[a.id] = a
        for inst in I.CATALOG:
            if inst.asset_class in ("equity", "etf"):
                a = _stock("ETF" if inst.asset_class == "etf" else "EQUITY", inst.exchange, inst.symbol, inst.name, "supported")
                self._by_id[a.id] = a

    @property
    def directory_loaded(self) -> bool:
        return self._dir_ok_at is not None

    # --- optional network lookups (never in demo mode); each failure is remembered briefly and reported, never fatal ------------------------------
    async def ensure_directory(self) -> None:
        if self.demo:
            return
        async with self._lock:
            now = self._clock()
            if self._dir_ok_at is not None and now - self._dir_ok_at < DIRECTORY_TTL:
                return
            if now < self._dir_retry_at:
                return
            rows = self._read_disk(now)
            if rows is None:
                try:
                    async with self._client_factory() as c:
                        texts = [(await c.get(u)).raise_for_status().text for u in NASDAQ_URLS]
                    rows = parse_directory(*texts)
                    if len(rows) < 1000:
                        raise ValueError(f"directory parse looks wrong ({len(rows)} rows)")
                    self._write_disk(rows)
                except Exception as e:  # noqa: BLE001  a missing directory only narrows search
                    self.directory_error = f"US stock directory unavailable ({type(e).__name__})"
                    self._dir_retry_at = now + RETRY_AFTER_FAILURE
                    return
            for sym, name, exch, is_etf in rows:
                a = _stock("ETF" if is_etf else "EQUITY", exch, sym, name, "supported")
                self._by_id.setdefault(a.id, a)
            self._dir_ok_at, self.directory_error = now, None

    def _read_disk(self, now: float) -> list | None:
        try:
            if self._cache.exists() and now - self._cache.stat().st_mtime < DIRECTORY_TTL:
                return [tuple(r) for r in json.loads(self._cache.read_text())]
        except (OSError, ValueError):
            pass
        return None

    def _write_disk(self, rows: list) -> None:
        try:
            self._cache.write_text(json.dumps(rows))
        except OSError:
            pass

    async def ensure_products(self) -> None:
        """Which USD pairs Coinbase currently trades (so unlisted tokens are not offered). Unknown if unreachable."""
        if self.demo or (self._listed is not None and self._clock() - self._listed_at < PRODUCTS_TTL):
            return
        try:
            async with self._client_factory() as c:
                rows = (await c.get(COINBASE_PRODUCTS)).raise_for_status().json()
            listed = {r["id"] for r in rows if isinstance(r, dict) and r.get("quote_currency") == "USD" and r.get("status") == "online" and not r.get("trading_disabled")}
            if len(listed) >= 20:
                self._listed, self._listed_at = listed, self._clock()
        except Exception:  # noqa: BLE001  unknown stays unknown
            self._listed_at = self._clock() - PRODUCTS_TTL + RETRY_AFTER_FAILURE

    def same_symbol(self, a: Asset) -> list[Asset]:
        """Other assets of a different type that share this ticker (e.g. the BTC ETF and Bitcoin): the reason ids, not tickers, identify assets."""
        return [b for b in self._by_id.values() if b.symbol == a.symbol and b.type != a.type]

    def crypto_listed(self, a: Asset) -> bool:
        return self._listed is None or a.inst.provider_symbol in self._listed

    # --- lookup and search -------------------------------------------------------------------------------------------------------------------
    async def get(self, asset_id: str) -> Asset | None:
        a = self._by_id.get(asset_id) or describe(asset_id)
        if a is not None and asset_id not in self._by_id and a.type != "crypto":
            await self.ensure_directory()
            a = self._by_id.get(asset_id) or a
        return a

    async def search(self, query: str, limit: int = 20) -> dict:
        q = query.strip()
        if not q:
            return {"query": q, "results": [], "unsupported": None, "notes": []}
        await asyncio.gather(self.ensure_directory(), self.ensure_products())
        ql = q.lower()
        scored: list[tuple[int, int, str, Asset]] = []
        for a in self._by_id.values():
            if a.type == "crypto" and not self.crypto_listed(a):
                continue
            sym, name = a.symbol.lower(), a.name.lower()
            if sym == ql:
                s = 100
            elif name == ql:
                s = 95
            elif sym.startswith(ql):
                s = 80
            elif any(w.startswith(ql) for w in re.split(r"[\s/(),.&\-]+", name) if w):
                s = 60
            elif len(ql) >= 3 and ql in name:
                s = 40
            else:
                continue
            scored.append((-s, TYPE_ORDER[a.type], a.symbol, a))
        scored.sort(key=lambda x: x[:3])
        results = [a.public() for *_, a in scored[:limit]]
        notes = [self.directory_error] if self.directory_error and not self.demo else []
        unsupported = None
        if not results:
            reason = "Signal supports crypto that trades against USD on Coinbase, and US-listed stocks and ETFs."
            if TICKERISH.match(q) and not self.directory_loaded and not self.demo:
                u = describe(f"EQUITY:US:{q.upper()}")
                if u:
                    results.append(u.public())             # an explicit, labelled "unverified" candidate: the user decides
                    reason = "Not found in Signal's list, and the US stock directory could not be loaded to check it."
            unsupported = {"query": q, "message": f"No supported asset matches '{q[:40]}'. {reason}"} if not results else None
            if results:
                notes.append(reason)
        return {"query": q, "results": results, "unsupported": unsupported, "notes": notes}
