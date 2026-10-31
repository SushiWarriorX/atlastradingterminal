import json
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api.alerts.manager import AlertManager
from atlas_api.alerts.rules import parse_rule
from atlas_api.alerts.telegram import TelegramNotifier
from atlas_api.app import create_app
from atlas_api.models import Candle, OHLCV, Provenance, Quote
from atlas_api.service import MarketService

TOKEN = "123456789:AAH-secret-token_XYZ"
CHAT = "987654321"
BTC = "CRYPTO:COINBASE:BTC-USD:SPOT"


class Tg:
    """Mock Telegram Bot API. `script` is a list of (status, json) responses consumed in order; the last one repeats."""

    def __init__(self, *script):
        self.script, self.requests = list(script) or [(200, {"ok": True, "result": {"message_id": 1}})], []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        status, body = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        return httpx.Response(status, json=body)

    @property
    def sent(self):
        return [json.loads(r.content) for r in self.requests if r.url.path.endswith("/sendMessage")]


OK = (200, {"ok": True, "result": {"message_id": 1}})


def make(tg: Tg, settings=None, **kw):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    c = httpx.AsyncClient(transport=httpx.MockTransport(tg), base_url="https://api.telegram.org")
    n = TelegramNotifier(TOKEN, CHAT, settings or (lambda: {}), client=c, sleep=fake_sleep, **kw)
    n.sleeps = sleeps
    return n


def event(sev="warning", status="LIVE", msg="BTC-USD price above 70000: last 70,123.4"):
    return {"severity": sev, "message": msg, "ts": "2026-10-30T18:00:00+00:00", "rule_version": 3, "trigger": {"data": {"status": status, "provider": "coinbase"}}}


class Rule:
    telegram = True


async def test_message_shape_html_escaping_and_endpoint():
    tg = Tg(OK)
    n = make(tg)
    res = await n.deliver(event(msg="A <b>&</b> B > C"), Rule())
    assert res == "telegram:delivered"
    assert tg.requests[0].url.path == f"/bot{TOKEN}/sendMessage"
    body = tg.sent[0]
    assert body["chat_id"] == CHAT and body["parse_mode"] == "HTML" and body["disable_web_page_preview"] is True
    assert "A &lt;b&gt;&amp;&lt;/b&gt; B &gt; C" in body["text"] and "<b>ATLAS · WARNING</b>" in body["text"]   # user-derived text escaped, our markup kept
    assert "rule v3" in body["text"] and "data LIVE/coinbase" in body["text"] and "2026-10-30 18:00:00 UTC" in body["text"]


async def test_long_messages_are_truncated_under_telegram_limit():
    tg = Tg(OK)
    await make(tg).deliver(event(msg="x" * 10_000), Rule())
    assert len(tg.sent[0]["text"]) <= 4096


async def test_429_honours_retry_after_then_succeeds():
    tg = Tg((429, {"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 7}}), OK)
    n = make(tg)
    assert await n.deliver(event(), Rule()) == "telegram:delivered"
    assert n.sleeps == [7.0] and len(tg.requests) == 2


async def test_5xx_is_retried_with_backoff_then_reported_failed():
    tg = Tg((502, {"ok": False, "description": "Bad Gateway"}))
    n = make(tg, retries=3)
    res = await n.deliver(event(), Rule())
    assert res == "telegram:failed:Telegram server error 502" and len(tg.requests) == 3 and n.sleeps == [0.5, 1.0]


@pytest.mark.parametrize("status,desc", [(403, "Forbidden: bot was blocked by the user"), (400, "Bad Request: chat not found"), (401, "Unauthorized")])
async def test_permanent_errors_are_not_retried(status, desc):
    tg = Tg((status, {"ok": False, "error_code": status, "description": desc}))
    n = make(tg)
    res = await n.deliver(event(), Rule())
    assert res == f"telegram:failed:{desc}" and len(tg.requests) == 1 and n.sleeps == []


async def test_network_error_message_never_contains_the_token():
    def boom(req):
        raise httpx.ConnectError(f"cannot reach {req.url}")   # httpx-style error that embeds the URL (and so the token)

    n = TelegramNotifier(TOKEN, CHAT, client=httpx.AsyncClient(transport=httpx.MockTransport(boom), base_url="https://api.telegram.org"),
                         sleep=lambda s: _noop(), retries=2)
    res = await n.deliver(event(), Rule())
    assert res.startswith("telegram:failed:ConnectError") and TOKEN not in res and "secret-token" not in res and "bot***" in res


async def _noop():
    return None


async def test_telegram_description_echoing_token_is_redacted():
    tg = Tg((404, {"ok": False, "description": f"Not Found: bot{TOKEN}"}))
    res = await make(tg).deliver(event(), Rule())
    assert TOKEN not in res and "***" in res


async def test_token_never_reaches_logs_even_with_info_logging(caplog):
    caplog.set_level(logging.DEBUG)
    tg = Tg(OK)
    n = TelegramNotifier(TOKEN, CHAT, client=httpx.AsyncClient(transport=httpx.MockTransport(tg), base_url="https://api.telegram.org"))
    await n.deliver(event(), Rule())
    await make(Tg((403, {"ok": False, "description": "Forbidden"}))).deliver(event(), Rule())
    assert TOKEN not in caplog.text and "secret-token" not in caplog.text
    assert logging.getLogger("httpx").level >= logging.WARNING            # request-URL logging is off


async def test_hazard_httpx_logs_the_token_when_not_silenced(caplog, monkeypatch):
    """Proves the silencing matters: with httpx's default logging the bot token lands in the log in clear text."""
    monkeypatch.setattr("atlas_api.alerts.telegram.silence_http_logs", lambda: None)
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.NOTSET)
    caplog.set_level(logging.INFO)
    n = TelegramNotifier(TOKEN, CHAT, client=httpx.AsyncClient(transport=httpx.MockTransport(Tg(OK)), base_url="https://api.telegram.org"))
    await n.deliver(event(), Rule())
    assert TOKEN in caplog.text          # this is the leak that silence_http_logs() prevents
    from atlas_api.alerts.telegram import silence_http_logs

    silence_http_logs()                  # restore for the rest of the session


async def test_delivery_filters():
    tg = Tg(OK)
    cfg = {"enabled": True, "min_severity": "warning"}
    n = make(tg, lambda: cfg)
    assert await n.deliver(event("info"), Rule()) == "telegram:skipped_severity"
    assert await n.deliver(event("warning"), Rule()) == "telegram:delivered"
    assert await n.deliver(event("critical"), Rule()) == "telegram:delivered"
    assert await n.deliver(event("critical", status="DEMO"), Rule()) == "telegram:skipped_demo"     # synthetic data never goes to a phone
    cfg["allow_demo"] = True
    assert await n.deliver(event("critical", status="DEMO"), Rule()) == "telegram:delivered"
    class NoTg: telegram = False
    assert await n.deliver(event("critical"), NoTg()) == "telegram:off"
    cfg["enabled"] = False
    assert await n.deliver(event("critical"), Rule()) == "telegram:off"
    assert len(tg.sent) == 3


async def test_rate_cap_per_minute_and_recovery():
    tg, now = Tg(OK), [1000.0]
    n = make(tg, max_per_minute=3, clock=lambda: now[0])
    assert [await n.deliver(event(), Rule()) for _ in range(4)] == ["telegram:delivered"] * 3 + ["telegram:rate_limited"]
    now[0] += 61
    assert await n.deliver(event(), Rule()) == "telegram:delivered"
    assert len(tg.sent) == 4


async def test_timeout_is_reported_not_raised():
    import asyncio

    async def slow(req):
        await asyncio.sleep(5)
        return httpx.Response(200, json={"ok": True})

    n = TelegramNotifier(TOKEN, CHAT, client=httpx.AsyncClient(transport=httpx.MockTransport(slow), base_url="https://api.telegram.org"), timeout=0.1)
    assert await n.deliver(event(), Rule()) == "telegram:failed:timeout"


async def test_status_masks_chat_and_caches_bot_info():
    tg = Tg((200, {"ok": True, "result": {"username": "atlas_bot", "id": 1}}))
    n = make(tg, lambda: {"enabled": True, "min_severity": "warning"})
    s = await n.status()
    assert s == {"configured": True, "enabled": True, "min_severity": "warning", "verified": True, "bot_username": "atlas_bot", "chat_hint": "…4321"}
    await n.status()
    assert len([r for r in tg.requests if r.url.path.endswith("/getMe")]) == 1      # cached
    bad = make(Tg((401, {"ok": False, "description": "Unauthorized"})))
    assert (await bad.status())["verified"] is False


# --- integration with the alert manager ---------------------------------------
class Script:
    name, entitlement, delay_seconds, native_intervals = "coinbase", "test", 0, {"1h"}

    def __init__(self):
        self.price = 100.0

    async def quote(self, inst):
        return Quote(instrument_id=inst.id, price=self.price, prev_close=100.0, prov=Provenance(
            provider="coinbase", venue="COINBASE", instrument_id=inst.id, event_time=datetime.now(timezone.utc),
            ingested_time=datetime.now(timezone.utc), entitlement="test", delay_seconds=0))


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    from atlas_api import service

    monkeypatch.setitem(service._TTL, "quote", 0.0)


async def test_manager_records_both_channels_and_survives_telegram_failure(db):
    prov, tg = Script(), Tg((403, {"ok": False, "description": "Forbidden: bot was blocked by the user"}))
    from atlas_api.alerts.manager import InAppNotifier

    mgr = AlertManager(db, MarketService({"coinbase": prov}), None, None, notifiers=[InAppNotifier(), make(tg)])
    mgr.create({"kind": "price", "instrument_id": BTC, "op": "above", "level": 100.5, "cooldown_seconds": 600})
    await mgr.evaluate_all()
    prov.price = 101
    ev = await mgr.evaluate_all()
    assert len(ev) == 1
    assert ev[0]["delivery"] == "in_app:delivered,telegram:failed:Forbidden: bot was blocked by the user"   # event kept; failure visible
    assert mgr.events()["unread"] == 1


async def test_suppressed_events_are_never_sent_to_telegram(db):
    prov, tg = Script(), Tg(OK)
    from atlas_api.alerts.manager import InAppNotifier

    mgr = AlertManager(db, MarketService({"coinbase": prov}), None, None, notifiers=[InAppNotifier(), make(tg)])
    mgr.create({"kind": "price", "instrument_id": BTC, "op": "above", "level": 100.5, "cooldown_seconds": 600})
    t = time.time()
    await mgr.evaluate_all(t)
    prov.price = 101
    await mgr.evaluate_all(t + 1)
    prov.price = 99
    await mgr.evaluate_all(t + 2)
    prov.price = 102
    sup = await mgr.evaluate_all(t + 3)
    assert sup[0]["delivery"] == "suppressed_cooldown" and len(tg.sent) == 1


def test_per_alert_telegram_flag_defaults_on_and_can_be_off():
    assert parse_rule({"kind": "price", "instrument_id": "BTC", "op": "above", "level": 1}).telegram is True
    assert parse_rule({"kind": "price", "instrument_id": "BTC", "op": "above", "level": 1, "telegram": False}).telegram is False


# --- API ------------------------------------------------------------------------
def client_with(tmp_path, tg):
    return TestClient(create_app(db_path=str(tmp_path / "t.db"), demo=False, providers={}, alert_loop=False, telegram=tg))


def test_api_status_when_not_configured_and_never_leaks_token(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with client_with(tmp_path, None) as c:
        s = c.get("/api/telegram/status").json()["data"]
        assert s["configured"] is False and "BotFather" in s["setup"]
        r = c.post("/api/telegram/test")
        assert r.status_code == 503 and r.json()["error"]["code"] == "TELEGRAM_NOT_CONFIGURED"
    tg = make(Tg((200, {"ok": True, "result": {"username": "atlas_bot"}})))
    with client_with(tmp_path, tg) as c:
        raw = c.get("/api/telegram/status").text + c.get("/api/prefs").text + c.get("/api/market/status").text
        assert TOKEN not in raw and "secret-token" not in raw and CHAT not in raw        # token and full chat id are never returned
        assert '"bot_username":"atlas_bot"' in raw.replace(" ", "")


def test_api_test_message_success_failure_and_rate_limit(tmp_path):
    tg_ok = Tg(OK)
    with client_with(tmp_path, make(tg_ok)) as c:
        assert c.post("/api/telegram/test").json() == {"ok": True, "data": {"sent": True}}
        assert "ATLAS test message" in tg_ok.sent[0]["text"]
        again = c.post("/api/telegram/test")
        assert again.status_code == 429 and again.json()["error"]["code"] == "RATE_LIMITED"
    with client_with(tmp_path, make(Tg((400, {"ok": False, "description": "Bad Request: chat not found"})))) as c:
        r = c.post("/api/telegram/test")
        assert r.status_code == 502 and r.json()["error"] == {"code": "TELEGRAM_FAILED", "message": "Bad Request: chat not found"}


def test_api_telegram_preferences_validate_and_drive_delivery(tmp_path):
    tg = Tg(OK)
    with client_with(tmp_path, make(tg)) as c:
        assert c.put("/api/prefs", json={"telegram_min_severity": "loud"}).status_code == 422
        assert c.put("/api/prefs", json={"telegram_enabled": "yes"}).status_code == 422
        p = c.put("/api/prefs", json={"telegram_enabled": False, "telegram_min_severity": "critical"}).json()["data"]
        assert p["telegram_enabled"] is False and p["telegram_min_severity"] == "critical"
        assert c.get("/api/telegram/status").json()["data"]["enabled"] is False
