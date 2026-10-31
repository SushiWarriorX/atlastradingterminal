import logging
import os

import uvicorn

from .alerts.telegram import silence_http_logs
from .app import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
silence_http_logs()  # request URLs would leak the Telegram bot token
app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host=os.getenv("ATLAS_HOST", "127.0.0.1"), port=int(os.getenv("ATLAS_PORT", "8000")))
