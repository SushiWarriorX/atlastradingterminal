"""A small async TTL cache that shares in-flight work: many callers asking for the same key at once cause one computation, and a computation
that outlives a caller's patience keeps running (bounded by its own timeout) so the next request finds the result."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass
class Entry(Generic[T]):
    value: T
    expires: float              # monotonic
    stored_at: datetime         # wall clock, for "last updated"


class SharedCache(Generic[T]):
    def __init__(self, max_entries: int = 512, clock: Callable[[], float] = time.monotonic):
        self._clock, self._max = clock, max_entries
        self._data: dict[tuple, Entry[T]] = {}
        self._inflight: dict[tuple, asyncio.Task] = {}

    def peek(self, key: tuple) -> Entry[T] | None:
        e = self._data.get(key)
        return e if e and e.expires > self._clock() else None

    def invalidate(self, key: tuple) -> None:
        self._data.pop(key, None)

    def running(self, key: tuple) -> bool:
        return key in self._inflight

    def _evict(self) -> None:
        if len(self._data) > self._max:
            now = self._clock()
            self._data = {k: v for k, v in self._data.items() if v.expires > now}

    async def get(self, key: tuple, fetch: Callable[[], Awaitable[T]], ttl_for: Callable[[T], float], wait: float | None = None) -> Entry[T] | None:
        """The cached entry, or the result of one shared `fetch()`. With `wait`, returns None if the work is not done in time (it keeps running)."""
        hit = self.peek(key)
        if hit is not None:
            return hit
        task = self._inflight.get(key)
        if task is None:
            async def run() -> Entry[T]:
                val = await fetch()
                e = Entry(val, self._clock() + max(0.0, ttl_for(val)), datetime.now(timezone.utc))
                self._data[key] = e
                self._evict()
                return e
            task = asyncio.ensure_future(run())
            self._inflight[key] = task
            task.add_done_callback(lambda t, k=key: (self._inflight.pop(k, None), t.exception() if not t.cancelled() else None))
        try:
            return await asyncio.wait_for(asyncio.shield(task), wait) if wait is not None else await asyncio.shield(task)
        except asyncio.TimeoutError:
            return None
