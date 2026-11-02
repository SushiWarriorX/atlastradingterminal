import logging
import os
import sys

import uvicorn

from .alerts.telegram import silence_http_logs
from . import auth
from .app import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
silence_http_logs()  # request URLs would leak the Telegram bot token
app = create_app()

if __name__ == "__main__":
    host = os.getenv("ATLAS_HOST", "127.0.0.1")
    why = auth.refuse_open_server(host, os.getenv("ATLAS_AUTH_PASSWORD"))
    if why:
        sys.exit(why)
    # behind the HTTPS proxy (cloud), trust its forwarded scheme/client address; the container port is never published, only the proxy is
    uvicorn.run(app, host=host, port=int(os.getenv("ATLAS_PORT", "8000")), proxy_headers=True, forwarded_allow_ips=os.getenv("ATLAS_FORWARDED_ALLOW_IPS", "127.0.0.1"))
