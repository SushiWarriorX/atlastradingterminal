from __future__ import annotations

import asyncio
import logging
import time

import httpx

log = logging.getLogger("atlas.http")


class Http:
    """httpx wrapper: min-interval rate limit, retries with exponential backoff on 429/5xx/network errors."""

    def __init__(self, base_url: str, provider: str, min_interval: float = 0.15, retries: int = 3,
                 client: httpx.AsyncClient | None = None):
        self.provider, self.min_interval, self.retries = provider, min_interval, retries
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=10, headers={"User-Agent": "atlas-terminal/0.1"})
        self._lock, self._last = asyncio.Lock(), 0.0

    async def get(self, path: str, params: dict | None = None) -> httpx.Response:
        from ..models import ProviderUnavailable

        last: Exception | None = None
        for attempt in range(self.retries):
            async with self._lock:
                wait = self._last + self.min_interval - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last = time.monotonic()
            try:
                r = await self._client.get(path, params=params)
                if r.status_code == 429 or r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                r.raise_for_status()
                return r
            except (httpx.HTTPError, OSError) as e:
                last = e
                retryable = not (isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 429)
                log.warning("%s GET %s failed (attempt %d): %s", self.provider, path, attempt + 1, e)
                if not retryable:
                    break
                await asyncio.sleep(0.4 * 2 ** attempt)
        raise ProviderUnavailable(self.provider, str(last) or type(last).__name__)
