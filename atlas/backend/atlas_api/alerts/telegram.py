"""Telegram delivery for alerts (Bot API, sendMessage).

Secrets: the bot token and chat id come from the backend environment only. The token is part of the Bot API URL, so
this module (a) silences httpx/httpcore request logging, which prints full URLs, and (b) redacts the token from every
error string it returns. Nothing here ever returns or logs the token.
"""
from __future__ import annotations

import asyncio
import html
import logging
import time
from collections import deque
from typing import Callable

import httpx

log = logging.getLogger("atlas.telegram")
API = "https://api.telegram.org"
SEV = {"info": 0, "warning": 1, "critical": 2}
ICON = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
MAX_TEXT = 3900  # Telegram's limit is 4096 characters


def silence_http_logs() -> None:
    """httpx logs 'HTTP Request: POST https://api.telegram.org/bot<TOKEN>/sendMessage' at INFO. Never allow that."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


class TelegramNotifier:
    name = "telegram"

    def __init__(self, token: str, chat_id: str, settings: Callable[[], dict] | None = None, client: httpx.AsyncClient | None = None,
                 max_per_minute: int = 20, retries: int = 3, sleep=asyncio.sleep, clock=time.monotonic, timeout: float = 15.0):
        silence_http_logs()
        self._token, self._chat = token, str(chat_id)
        self.settings = settings or (lambda: {})
        self.client = client or httpx.AsyncClient(base_url=API, timeout=10)
        self.max_per_minute, self.retries, self._sleep, self._clock, self.timeout = max_per_minute, retries, sleep, clock, timeout
        self._sent: deque[float] = deque()
        self._lock = asyncio.Lock()
        self._me: tuple[float, dict] | None = None

    # --- safety ------------------------------------------------------------
    def redact(self, s: str) -> str:
        return s.replace(self._token, "***").replace(f"bot{self._token}", "bot***")

    @property
    def chat_hint(self) -> str:
        c = self._chat
        return "…" + c[-4:] if len(c) > 4 else "****"

    # --- Bot API -----------------------------------------------------------
    async def _call(self, method: str, payload: dict | None = None) -> tuple[bool, dict | str]:
        """POST/GET with retries. Returns (ok, json_result | redacted error). Retries 429 (honouring retry_after), 5xx, network errors."""
        last = "unknown error"
        for attempt in range(self.retries):
            try:
                r = await self.client.post(f"/bot{self._token}/{method}", json=payload or {})
            except (httpx.HTTPError, OSError) as e:
                last = self.redact(f"{type(e).__name__}: {e}")[:160]
            else:
                try:
                    j = r.json()
                except ValueError:
                    j = {}
                if r.status_code == 200 and j.get("ok"):
                    return True, j.get("result", {})
                desc = self.redact(str(j.get("description", f"HTTP {r.status_code}")))[:160]
                if r.status_code == 429:
                    wait = float((j.get("parameters") or {}).get("retry_after", 1))
                    last = f"rate limited by Telegram (retry_after {wait:g}s)"
                    if attempt < self.retries - 1:
                        await self._sleep(min(wait, 30))
                        continue
                elif r.status_code >= 500:
                    last = f"Telegram server error {r.status_code}"
                else:
                    return False, desc      # 400/401/403/404: bad token, wrong chat, blocked bot... retrying cannot help
            if attempt < self.retries - 1:
                await self._sleep(0.5 * 2 ** attempt)
        return False, last

    async def send_text(self, text: str) -> tuple[bool, str]:
        ok, res = await self._call("sendMessage", {"chat_id": self._chat, "text": text[:MAX_TEXT], "parse_mode": "HTML", "disable_web_page_preview": True})
        return ok, ("sent" if ok else str(res))

    async def bot_info(self) -> dict | None:
        if self._me and self._clock() - self._me[0] < 60:
            return self._me[1]
        ok, res = await self._call("getMe")
        if ok and isinstance(res, dict):
            self._me = (self._clock(), res)
            return res
        return None

    async def status(self) -> dict:
        cfg = self.settings()
        me = await self.bot_info()
        return {"configured": True, "enabled": cfg.get("enabled", True), "min_severity": cfg.get("min_severity", "info"),
                "verified": me is not None, "bot_username": (me or {}).get("username"), "chat_hint": self.chat_hint}

    # --- alert delivery ----------------------------------------------------
    @staticmethod
    def format(event: dict) -> str:
        sev = event.get("severity", "info")
        data = (event.get("trigger") or {}).get("data") or {}
        bits = [b for b in (data.get("status"), data.get("provider")) if b]
        foot = f"{event.get('ts', '')[:19].replace('T', ' ')} UTC · rule v{event.get('rule_version', 1)}" + (f" · data {'/'.join(bits)}" if bits else "")
        return f"{ICON.get(sev, '')} <b>ATLAS · {html.escape(sev.upper())}</b>\n{html.escape(event.get('message', ''))}\n<i>{html.escape(foot)}</i>"

    async def deliver(self, event: dict, rule) -> str:
        cfg = self.settings()
        if not cfg.get("enabled", True) or not getattr(rule, "telegram", True):
            return "telegram:off"
        status = (((event.get("trigger") or {}).get("data")) or {}).get("status")
        if status == "DEMO" and not cfg.get("allow_demo", False):
            return "telegram:skipped_demo"             # never push synthetic data to a phone as if it were an alert
        if SEV.get(event.get("severity", "info"), 0) < SEV.get(cfg.get("min_severity", "info"), 0):
            return "telegram:skipped_severity"
        async with self._lock:
            now = self._clock()
            while self._sent and now - self._sent[0] > 60:
                self._sent.popleft()
            if len(self._sent) >= self.max_per_minute:
                return "telegram:rate_limited"
            self._sent.append(now)
            try:
                ok, detail = await asyncio.wait_for(self.send_text(self.format(event)), self.timeout)
            except asyncio.TimeoutError:
                ok, detail = False, "timeout"
        if not ok:
            log.warning("telegram delivery failed: %s", detail)
        return "telegram:delivered" if ok else f"telegram:failed:{detail}"
