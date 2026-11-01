"""In-memory background jobs with progress, shared by the scanner and the backtester."""
from __future__ import annotations

import asyncio
import uuid
from typing import Awaitable, Callable

from pydantic import BaseModel


class Jobs:
    """`runner(spec, source, symbols, progress)` does the work. `on_done(result)` (optional) runs in a worker thread after it finishes and may return extra
    fields to merge into the job (for example the id of a saved copy), so saving never blocks the event loop and happens exactly once per job."""

    def __init__(self, runner: Callable[..., Awaitable[dict]], keep: int = 20, on_done: Callable[[dict], dict | None] | None = None):
        self.runner, self.keep, self.on_done = runner, keep, on_done
        self.jobs: dict[str, dict] = {}

    def start(self, spec: BaseModel, source, symbols: list[str] | None = None) -> str:
        jid = str(uuid.uuid4())
        job = {"id": jid, "status": "running", "done": 0, "total": 0, "result": None, "error": None, "spec": spec.model_dump(mode="json")}
        self.jobs[jid] = job
        for old in list(self.jobs)[: -self.keep]:
            del self.jobs[old]

        def prog(d, t):
            job["done"], job["total"] = d, t

        async def go():
            try:
                res = await self.runner(spec, source, symbols, prog)
                if self.on_done:
                    job.update(await asyncio.to_thread(self.on_done, res) or {})
                job["result"] = res
                job["status"] = "done"
            except Exception as e:  # noqa: BLE001
                job["status"], job["error"] = "failed", f"{type(e).__name__}: {e}"
            finally:
                job.pop("task", None)        # a finished job keeps its result, not its task

        job["task"] = asyncio.create_task(go())
        return jid

    def view(self, jid: str) -> dict | None:
        j = self.jobs.get(jid)
        return None if j is None else {k: v for k, v in j.items() if k != "task"}
