"""Background worker: runs the shared scheduler on its own, so jobs keep running when no browser or phone is connected.

    python -m atlas_api.worker

In the cloud this is a second container beside the web app (see docker-compose.yml). It shares the same database file; leases and atomic budget reservations in the database stop the
two processes from running the same job twice or overspending a budget. Stop it with Ctrl+C or SIGTERM; a run in progress is allowed to finish its current step.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal

from .app import create_app


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # The same services as the web app, but with the web app's own timer loops off: the scheduler is the only thing this process runs.
    app = create_app(alert_loop=False, news_loop=False, demo=os.getenv("ATLAS_DEMO") == "1")
    sched = app.state.scheduler
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, sched.stop)
        except NotImplementedError:      # Windows
            pass
    await sched.run_forever(poll_s=float(os.getenv("ATLAS_SCHEDULER_POLL_SECONDS", "10")))


if __name__ == "__main__":
    asyncio.run(main())
