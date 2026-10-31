"""Market-data service: provider routing, caching, interval derivation, provenance classification, health."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from .instruments import Instrument
from .models import OHLCV, ProviderUnavailable, Quote
from .resample import MONDAY_OFFSET, SECONDS, resample
from .sessions import session_state
from .status import classify

# interval -> (finer interval to fetch, bucket seconds). Only used when the provider lacks the interval natively.
DERIVED = {"3m": "1m", "2h": "1h", "4h": "1h", "30m": "15m", "1w": "1d"}
WEEK = 7 * 86400
ALL_INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w", "1M"]
BAR_SECONDS = {**SECONDS, "1w": 7 * 86400, "1M": 30 * 86400}
_TTL = {"quote": 3.0, "ohlcv": 20.0}


class MarketService:
    def __init__(self, providers: dict, demo: bool = False):
        self.providers, self.demo = providers, demo
        self._cache: dict[tuple, tuple[float, object]] = {}
        self.health: dict[str, dict] = {n: {"ok": 0, "fail": 0, "last_ok": None, "last_error": None, "last_error_at": None,
                                             "consecutive_failures": 0} for n in providers}

    def provider_for(self, inst: Instrument):
        p = self.providers.get("demo") if self.demo else self.providers.get(inst.provider)
        if p is None:
            raise ProviderUnavailable(inst.provider, "provider not configured")
        return p

    def add_provider(self, p) -> None:
        self.providers[p.name] = p
        self.health.setdefault(p.name, {"ok": 0, "fail": 0, "last_ok": None, "last_error": None, "last_error_at": None, "consecutive_failures": 0})

    def _chain(self, inst: Instrument) -> list:
        """Providers to try, in order. IBKR is preferred for US stocks/ETFs only while it is connected; the default provider is always the last resort."""
        default = self.provider_for(inst)
        pref = None if self.demo else self.providers.get("ibkr")
        if pref is not None and pref is not default and pref.handles(inst) and pref.available:
            return [pref, default]
        return [default]

    @staticmethod
    def _supports(p, interval: str) -> bool:
        return interval in p.native_intervals or (interval in DERIVED and DERIVED[interval] in p.native_intervals)

    def supported_intervals(self, inst: Instrument) -> list[str]:
        p = self.provider_for(inst)
        return [i for i in ALL_INTERVALS if i in p.native_intervals or (i in DERIVED and DERIVED[i] in p.native_intervals)]

    def _note(self, p, ok: bool, err: str | None = None):
        h = self.health[p.name]
        now = datetime.now(timezone.utc).isoformat()
        if ok:
            h.update(ok=h["ok"] + 1, last_ok=now, consecutive_failures=0)
        else:
            h.update(fail=h["fail"] + 1, last_error=err, last_error_at=now, consecutive_failures=h["consecutive_failures"] + 1)

    def _finalize(self, inst: Instrument, obj):
        now = datetime.now(timezone.utc)
        sess = session_state(now)["state"] if inst.is_equity_like else None
        prov = obj.prov
        if isinstance(obj, OHLCV) and obj.candles and inst.asset_class != "macro" and obj.interval in BAR_SECONDS:
            # A bar's open time says nothing about freshness: a forming bar is current as of now, and a closed
            # last bar is as old as its close. Measure freshness from min(now, bar close).
            close = datetime.fromtimestamp(obj.candles[-1].time + BAR_SECONDS[obj.interval], timezone.utc)
            prov.event_time = min(now, close)
        prov.session = sess
        prov.status, notes = classify(provider=prov.provider, asset_class=inst.asset_class, event_time=prov.event_time,
                                      now=now, delay_seconds=prov.delay_seconds, session=sess)
        prov.quality = [*prov.quality, *(n for n in notes if n not in prov.quality)]      # keep what the provider and the fallback chain said, add the classification
        return obj

    async def _cached(self, key: tuple, kind: str, fetch):
        hit = self._cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        val = await fetch()
        self._cache[key] = (time.monotonic() + _TTL[kind], val)
        return val

    async def quote(self, inst: Instrument) -> Quote:
        chain = self._chain(inst)

        async def fetch():
            skipped: list[str] = []
            for i, p in enumerate(chain):
                try:
                    q = await p.quote(inst)
                except ProviderUnavailable as e:
                    self._note(p, False, e.message)
                    if i == len(chain) - 1:
                        raise
                    skipped.append(f"{p.name}: {e.message[:100]}")
                    continue
                self._note(p, True)
                if skipped:
                    q.prov.quality.append("preferred provider unavailable (" + "; ".join(skipped) + f"): using {p.name}")
                return q

        q = await self._cached(("q", inst.id, chain[0].name), "quote", fetch)
        return self._finalize(inst, q.model_copy(deep=True))

    async def ohlcv(self, inst: Instrument, interval: str, limit: int = 300) -> OHLCV:
        default = self.provider_for(inst)
        if interval not in self.supported_intervals(inst):
            raise ProviderUnavailable(default.name, f"interval {interval} not available for {inst.id} from {default.name}")
        chain = [p for p in self._chain(inst) if self._supports(p, interval)] or [default]

        async def fetch():
            skipped: list[str] = []
            for i, p in enumerate(chain):
                try:
                    if interval in p.native_intervals:
                        o = await p.ohlcv(inst, interval, limit)
                    else:
                        base = DERIVED[interval]
                        ratio = (WEEK if interval == "1w" else SECONDS[interval]) // SECONDS[base]
                        o = await p.ohlcv(inst, base, limit * ratio)
                        o.candles = resample(o.candles, WEEK if interval == "1w" else SECONDS[interval], MONDAY_OFFSET if interval == "1w" else 0)[-limit:]
                        o.interval, o.derived_from = interval, base
                except ProviderUnavailable as e:
                    self._note(p, False, e.message)
                    if i == len(chain) - 1:
                        raise
                    skipped.append(f"{p.name}: {e.message[:100]}")
                    continue
                self._note(p, True)
                if skipped:
                    o.prov.quality.append("preferred provider unavailable (" + "; ".join(skipped) + f"): using {p.name}")
                return o

        o = await self._cached(("o", inst.id, chain[0].name, interval, limit), "ohlcv", fetch)
        return self._finalize(inst, o.model_copy(deep=True))
