import asyncio
from typing import Literal
import json
import logging
import math
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import auth as authmod, commands, health_check, instruments as I
from .fedwatch import FedWatchService
from .signal import routes as signal_routes
from .signal.service import SignalService
from .macro import MacroService
from .brokers.ibkr import BrokerError, IBKRBroker, IBKRSettings
from .providers.ibkr_data import IBKRData
from .journal import hyperliquid as hl, importers as jimp, stats as jstats
from .journal.matching import Exec
from .journal.store import JournalError, JournalStore
from .news.service import NewsError, NewsService
from .derivatives.service import DerivativesService
from .jobs import Jobs
from .fundamentals.service import DemoFundamentals, FundamentalsService, YahooFundamentals
from .trading import analytics as tr_analytics
from .trading.engine import EngineError, TradingEngine, jsonable
from .trading.models import OrderIn
from .alerts.manager import AlertManager, InAppNotifier
from .alerts.telegram import TelegramNotifier, silence_http_logs
from .alerts.rules import INSTRUMENT_KINDS, parse_rule
from .ai.agents import AgentTeam, fundamental_snapshot, macro_snapshot, risk_snapshot
from .ai.desk import Desk
from .backtest import presets as bt_presets, run as bt_run
from .backtest.spec import BtSpec
from .scanner import engine as scan_engine, nl as scan_nl, presets as scan_presets, universe as scan_universe
from .scanner.bars import BarSource, DemoBars, YahooBars
from .scanner.features import FIELDS as SCAN_FIELDS
from .scanner.rules import ScanSpec
from pydantic import ValidationError
from .ai.llm import AnthropicLLM
from .ai.tools import Registry, ToolError
from .db import DB, now
from .models import ProviderUnavailable
from .providers.coinbase import CoinbaseProvider
from .providers.demo import DemoProvider
from .providers.fred import FredProvider
from .providers.yahoo import YahooProvider
from .service import MarketService
from .sessions import session_state
from . import compare as cmp, mtf, mtf_service, technical
from . import indicators as ind

log = logging.getLogger("atlas")
STRIP = ["BTC-USD", "SPX", "NDX", "VIX", "US10Y"]
DEFAULT_WATCHLIST = ["BTC-USD", "SPY", "QQQ", "AAPL", "NVDA", "MSFT"]
BROKER_ENV = "PAPER"  # paper trading only. There is no live broker adapter; POST /api/orders/live always refuses.


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status


def ok(data):
    return {"ok": True, "data": data}


def create_app(*, db_path: str | None = None, demo: bool | None = None, llm=None, providers: dict | None = None, bar_source: BarSource | None = None, backtest_source: BarSource | None = None, alert_loop: bool | None = None, telegram: TelegramNotifier | None = None, broker: IBKRBroker | None = None, hyperliquid: hl.HyperliquidClient | None = None, news_client: httpx.AsyncClient | None = None, news_loop: bool | None = None, fundamentals_provider=None, deriv_client=None, auth_password: str | None = None) -> FastAPI:
    demo = os.getenv("ATLAS_DEMO") == "1" if demo is None else demo
    db = DB(db_path or os.getenv("ATLAS_DB", "atlas.db"))
    provs = providers if providers is not None else {"coinbase": CoinbaseProvider(), "yahoo": YahooProvider(), "fred": FredProvider()}
    if demo:
        provs = {**provs, "demo": DemoProvider()}
    svc = MarketService(provs, demo=demo)
    if llm is None and os.getenv("ANTHROPIC_API_KEY"):
        llm = AnthropicLLM(os.environ["ANTHROPIC_API_KEY"], os.getenv("ATLAS_MODEL", "claude-sonnet-5-5"))
    journal = JournalStore(db)
    news = NewsService(db, news_client, allow_local=os.getenv("ATLAS_NEWS_ALLOW_LOCAL") == "1", user_agent=os.getenv("ATLAS_NEWS_USER_AGENT", "ATLAS-Terminal/0.1 (personal research)"),
                       symbol_url=os.getenv("ATLAS_NEWS_SYMBOL_URL") or None)
    derivs = DerivativesService(db, deriv_client, demo)
    fundamentals = FundamentalsService(db, fundamentals_provider or (DemoFundamentals() if demo else YahooFundamentals()), demo)
    hl_client = hyperliquid or hl.HyperliquidClient(os.getenv("HYPERLIQUID_API_BASE", "https://api.hyperliquid.xyz"))
    desk = Desk(llm, Registry(svc, journal, fundamentals), db)
    bars: BarSource = bar_source or (DemoBars() if demo else YahooBars())
    jobs = Jobs(scan_engine.run)
    bt_source: BarSource = backtest_source or bar_source or (DemoBars(days=1100) if demo else YahooBars(period="5y", ttl=3600.0))
    bt_jobs = Jobs(bt_run.run, keep=10, on_done=lambda r: bt_persist(r))      # saves each finished run once, in a worker thread
    app_symbols_override: dict = {}  # test hook: universe name -> symbols

    if not db.q("SELECT 1 FROM watchlists LIMIT 1"):
        wid = db.x("INSERT INTO watchlists(name,created_at) VALUES('Core',?)", (now(),))
        for n, s in enumerate(DEFAULT_WATCHLIST):
            db.x("INSERT INTO watchlist_items VALUES(?,?,?)", (wid, I.by_symbol(s).id, n))

    async def load_universe(name: str) -> list[str]:
        return app_symbols_override.get(name) or await scan_universe.load(name)

    def telegram_settings() -> dict:
        return {"enabled": db.pref_get("telegram_enabled", True), "min_severity": db.pref_get("telegram_min_severity", "info"),
                "allow_demo": os.getenv("ATLAS_TELEGRAM_ALLOW_DEMO") == "1"}

    silence_http_logs()   # httpx would otherwise log request URLs, and Telegram's URL contains the bot token
    tg = telegram
    if tg is None and os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        # TELEGRAM_API_BASE is for self-hosted Bot API servers or local test doubles; default is Telegram's public API
        tg = TelegramNotifier(os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"], telegram_settings,
                              client=httpx.AsyncClient(base_url=os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org"), timeout=10))
    elif tg is not None:
        tg.settings = telegram_settings
    alerts = AlertManager(db, svc, bars, load_universe, notifiers=[InAppNotifier(), *([tg] if tg else [])])
    last_tg_test = {"t": 0.0}
    run_loop = (os.getenv("ATLAS_ALERT_LOOP", "1") == "1") if alert_loop is None else alert_loop
    alert_seconds = float(os.getenv("ATLAS_ALERT_SECONDS", "30"))
    if broker is None and os.getenv("IBKR_ENABLED") == "1":
        # IBKR_MODE: readonly (default; any account, positions/executions only) or paper_trading (orders, paper accounts only). There is no live mode.
        broker = IBKRBroker(IBKRSettings(host=os.getenv("IBKR_HOST", "127.0.0.1"), port=int(os.getenv("IBKR_PORT", "7497")), client_id=int(os.getenv("IBKR_CLIENT_ID", "21")),
                                         mode=os.getenv("IBKR_MODE", "readonly"), account=os.getenv("IBKR_ACCOUNT") or None))
    ibkr_md = None
    if broker is not None and os.getenv("ATLAS_IBKR_DATA") == "1" and not demo:
        ibkr_md = IBKRData(broker)       # US stocks/ETFs prefer IBKR while connected; Yahoo stays the labelled fallback
        svc.add_provider(ibkr_md)

    def ibkr_status_dict() -> dict:
        if broker is None:
            return {"configured": False}
        return {**broker.status(), "market_data": {"enabled": ibkr_md is not None, "active": bool(ibkr_md and ibkr_md.available),
                "note": "US stocks/ETFs use IBKR quotes and bars while connected (live only with a market-data subscription, else delayed); Yahoo is the labelled fallback."
                        if ibkr_md else "off: set ATLAS_IBKR_DATA=1 to prefer IBKR market data for US stocks/ETFs"}}
    trading = TradingEngine(db, svc, broker=broker)
    team = AgentTeam(desk.llm, db, svc, fundamentals, trading, desk)
    paper_loop = (os.getenv("ATLAS_PAPER_LOOP", "1") == "1") if alert_loop is None else alert_loop
    paper_seconds = float(os.getenv("ATLAS_PAPER_SECONDS", "5"))
    # RSS polling: on by default for real data, off in demo mode (there is no network and no fabricated headlines); ATLAS_NEWS_LOOP=1/0 overrides
    run_news = (os.getenv("ATLAS_NEWS_LOOP", "0" if demo else "1") == "1") if news_loop is None and alert_loop is not False else bool(news_loop)
    news_seconds = float(os.getenv("ATLAS_NEWS_SECONDS", "900"))
    # derivatives polling records history for percentiles: on for real data, off in demo (nothing real to record); ATLAS_DERIV_LOOP=1/0 overrides
    run_derivs = (os.getenv("ATLAS_DERIV_LOOP", "0" if demo else "1") == "1") if alert_loop is not False else False
    deriv_seconds = float(os.getenv("ATLAS_DERIV_SECONDS", "300"))

    async def ibkr_keepalive(every: float) -> None:
        """Opt-in (IBKR_AUTOCONNECT=1): connect to a running TWS/Gateway and reconnect after its daily logout. Uses the same read-only/paper rules as the
        Connect button; a refusal is recorded as the last error and retried later, never raised."""
        while True:
            if not broker.connected:
                try:
                    await broker.connect()
                    db.audit("system", "ibkr_autoconnect", {"mode": broker.s.mode, "port": broker.s.port})
                except Exception:  # noqa: BLE001  BrokerError already stored last_error; Gateway may simply not be running yet
                    pass
            await asyncio.sleep(every)

    @asynccontextmanager
    async def lifespan(_app):
        tasks = []
        if run_loop:
            tasks.append(asyncio.create_task(alerts.run_loop(alert_seconds)))
        if paper_loop:
            tasks.append(asyncio.create_task(trading.run_loop(paper_seconds)))
        if run_news:
            tasks.append(asyncio.create_task(news.run_loop(news_seconds)))
        if run_derivs:
            tasks.append(asyncio.create_task(derivs.run_loop(deriv_seconds)))
        if broker is not None and os.getenv("IBKR_AUTOCONNECT") == "1":
            tasks.append(asyncio.create_task(ibkr_keepalive(float(os.getenv("IBKR_RECONNECT_SECONDS", "30")))))
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="ATLAS TERMINAL API", version="0.1.0", lifespan=lifespan)
    app.state.db, app.state.svc, app.state.desk = db, svc, desk
    app.state.scan_universes = app_symbols_override
    app.state.alerts = alerts
    app.state.trading = trading
    app.state.journal = journal
    app.state.news = news
    app.state.fundamentals = fundamentals
    app.state.derivs = derivs
    app.state.broker = broker
    extra_origins = [o.strip() for o in (os.getenv("ATLAS_CORS_ORIGINS") or "").split(",") if o.strip().startswith(("http://", "https://"))]       # opt-in, e.g. the Signal Mobile web build
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", *extra_origins],
                       allow_methods=["*"], allow_headers=["*"])
    # Cloud hosting (optional): password login, plus the public hostname allowed in the Host/Origin checks. Both are off for the local setup.
    auth = authmod.Auth(auth_password if auth_password is not None else os.getenv("ATLAS_AUTH_PASSWORD"))
    public_name = (os.getenv("ATLAS_ALLOWED_HOST") or "").strip().lower()                  # "atlas.example.com" (a port may be added for testing: "localhost:8000")
    public_host = public_name.rsplit(":", 1)[0] if public_name.count(":") == 1 else public_name
    public_origins = {f"https://{public_name}", f"http://{public_name}"} if public_name else set()
    app.add_middleware(authmod.AuthMiddleware, auth=auth, allowed_origins={"http://localhost:5173", "http://127.0.0.1:5173", *public_origins, *extra_origins})

    class LoginBody(BaseModel):
        password: str = Field(max_length=200)
        client: Literal["web", "mobile"] = "web"      # a native app gets a bearer token to keep in secure storage; the web app gets an HttpOnly cookie

    @app.get("/api/auth/status")
    async def auth_status(request: Request):
        return ok({"required": auth.enabled, "authenticated": (not auth.enabled) or auth.valid_token(request.cookies.get(authmod.COOKIE)) or auth.valid_token(authmod.bearer(request.headers.get("authorization")))})

    @app.post("/api/auth/login")
    async def auth_login(b: LoginBody, request: Request, response: Response):
        if not auth.enabled:
            return ok({"required": False, "authenticated": True})
        ip = request.client.host if request.client else "unknown"
        wait = auth.retry_after(ip)
        if wait:
            raise ApiError("TOO_MANY_ATTEMPTS", f"Too many failed attempts. Try again in {wait}s.", 429)
        if not auth.check_password(b.password):
            auth.record_failure(ip)
            await asyncio.sleep(0.5)
            raise ApiError("BAD_PASSWORD", "Wrong password.", 401)
        auth.clear_failures(ip)
        if b.client == "mobile":
            return ok({"required": True, "authenticated": True, "token": auth.make_token(ttl=authmod.MOBILE_MAX_AGE), "expires_in": authmod.MOBILE_MAX_AGE})
        response.set_cookie(authmod.COOKIE, auth.make_token(), max_age=authmod.MAX_AGE, httponly=True, samesite="strict", secure=request.url.scheme == "https", path="/")
        return ok({"required": True, "authenticated": True})

    @app.post("/api/auth/logout")
    async def auth_logout(response: Response):
        response.delete_cookie(authmod.COOKIE, path="/")
        return ok({"required": auth.enabled, "authenticated": False})

    @app.exception_handler(ApiError)
    async def _api_err(_, e: ApiError):
        return JSONResponse({"ok": False, "error": {"code": e.code, "message": e.message}}, status_code=e.status)

    @app.exception_handler(EngineError)
    async def _engine_err(_, e: EngineError):
        return JSONResponse({"ok": False, "error": {"code": e.code, "message": e.message, **e.extra}}, status_code=e.status)

    @app.exception_handler(JournalError)
    async def _journal_err(_, e: JournalError):
        return JSONResponse({"ok": False, "error": {"code": e.code, "message": e.message}}, status_code=e.status)

    @app.exception_handler(BrokerError)
    async def _broker_err(_, e: BrokerError):
        status = 403 if e.code.startswith("LIVE_") else 409 if e.code in ("NOT_CONNECTED", "BROKER_READONLY") else 502 if e.code == "IBKR_UNREACHABLE" else 400
        return JSONResponse({"ok": False, "error": {"code": e.code, "message": e.message}}, status_code=status)

    @app.exception_handler(ProviderUnavailable)
    async def _unavail(_, e: ProviderUnavailable):
        return JSONResponse({"ok": False, "error": {"code": "DATA_UNAVAILABLE", "message": str(e), "status": "UNAVAILABLE"}}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def _val(_, e: RequestValidationError):
        return JSONResponse({"ok": False, "error": {"code": "INVALID_REQUEST", "message": str(e.errors()[:3])}}, status_code=422)

    def inst_or_404(x: str) -> I.Instrument:
        inst = I.resolve(x)
        if inst is None:
            raise ApiError("UNKNOWN_INSTRUMENT", f"Unknown instrument '{x}'", 404)
        return inst

    # --- meta / status ------------------------------------------------------
    @app.get("/api/health")
    async def health():
        return ok({"status": "up", "time_utc": now()})

    # --- provider health check (on demand, read-only, localhost-only) ----------------------------------------------
    hc_state: dict = {"last": None, "started": None}
    hc_lock = asyncio.Lock()
    local_hosts = {"localhost", "127.0.0.1", "::1", *([public_host] if public_host else [])}
    local_origins = {f"http://{h}:{p}" for h in ("localhost", "127.0.0.1") for p in (5173, int(os.getenv("ATLAS_PORT", "8000")))} | public_origins

    def local_only(request: Request, *, mutating: bool) -> None:
        """Refuse anything that is not the local web app: wrong Host (DNS rebinding), foreign Origin / cross-site fetch (CSRF), or missing marker header."""
        host = (request.url.hostname or "").lower()
        if host not in local_hosts:
            raise ApiError("FORBIDDEN_HOST", "This request was not addressed to localhost, so it was refused.", 403)
        origin = request.headers.get("origin")
        if origin is not None and origin not in local_origins:
            raise ApiError("FORBIDDEN_ORIGIN", "Requests from other websites are refused.", 403)
        if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "same-site", "none"):
            raise ApiError("FORBIDDEN_ORIGIN", "Cross-site requests are refused.", 403)
        if mutating and request.headers.get("x-atlas-request") != "health-check":
            raise ApiError("FORBIDDEN_ORIGIN", "Missing local-app marker header.", 403)

    def hc_cooldown_left() -> int:
        t = hc_state["started"]
        return 0 if t is None else max(0, int(math.ceil(health_check.COOLDOWN - (time.monotonic() - t))))

    @app.get("/api/health/check")
    async def health_check_last(request: Request):
        local_only(request, mutating=False)
        return ok({"last": hc_state["last"], "cooldown_left": hc_cooldown_left(), "running": hc_lock.locked()})

    @app.post("/api/health/check")
    async def health_check_run(request: Request):
        local_only(request, mutating=True)
        if hc_lock.locked():
            raise ApiError("BUSY", "A provider check is already running.", 409)
        left = hc_cooldown_left()
        if left:
            raise ApiError("COOLDOWN", f"Please wait {left}s before running the check again.", 429)
        async with hc_lock:
            hc_state["started"] = time.monotonic()
            hc_state["last"] = await health_check.run_checks(svc=svc, provs=provs, ibkr_md=ibkr_md, broker=broker, derivs=derivs, news=news, demo=demo)
        return ok({"last": hc_state["last"], "cooldown_left": hc_cooldown_left(), "running": False})

    macro = MacroService(provs.get("fred"), demo) if (demo or provs.get("fred")) else None

    @app.get("/api/macro/overview")
    async def macro_overview():
        if macro is None:
            raise ApiError("NOT_CONFIGURED", "The FRED provider is not set up.", 503)
        return ok(await macro.overview())

    fedwatch = FedWatchService(provs.get("fred"), news, demo)
    signal = SignalService(db=db, svc=svc, news=news, fundamentals=fundamentals, macro=macro, fedwatch=fedwatch, demo=demo, llm=llm)       # Signal Mobile research API (read-only)
    signal_routes.register(app, signal, ok)

    @app.get("/api/macro/fed")
    async def macro_fed():
        if not demo and provs.get("fred") is None:
            raise ApiError("NOT_CONFIGURED", "The FRED provider is not set up.", 503)
        return ok(await fedwatch.overview())

    @app.get("/api/market/status")
    async def market_status():
        return ok({
            "server_time_utc": now(), "ny": session_state(), "broker_env": BROKER_ENV, "live_trading_enabled": False, "trading_halted": trading.halted(),
            "demo_mode": demo,
            "providers": {n: {"entitlement": p.entitlement, "delay_seconds": p.delay_seconds, **svc.health[n]} for n, p in provs.items()},
            "ai": {"configured": desk.configured, "model": desk.llm.model if desk.llm else None},
            "ibkr": ibkr_status_dict(),
            "update_seconds": db.pref_get("update_seconds", 5),
        })

    @app.get("/api/meta/views")
    async def views():
        return ok({k: {"implemented": v[0], "phase": v[1], "description": v[2]} for k, v in commands.VIEWS.items()})

    # --- instruments / market data -----------------------------------------
    @app.get("/api/instruments/search")
    async def search(q: str, limit: int = 10):
        return ok([asdict(i) for i in I.search(q, limit)])

    @app.get("/api/instruments/{instrument_id:path}")
    async def instrument(instrument_id: str):
        i = inst_or_404(instrument_id)
        return ok({**asdict(i), "supported_intervals": svc.supported_intervals(i)})

    @app.get("/api/quotes")
    async def quotes(ids: str):
        insts = [inst_or_404(i) for i in ids.split(",")]  # validate all ids before any provider call
        res = await asyncio.gather(*(svc.quote(i) for i in insts), return_exceptions=True)
        return ok([{"instrument_id": i.id, "error": str(r), "status": "UNAVAILABLE"} if isinstance(r, Exception) else r.model_dump(mode="json")
                   for i, r in zip(insts, res)])

    @app.get("/api/market/strip")
    async def strip():
        insts = [I.by_symbol(s) for s in STRIP]
        res = await asyncio.gather(*(svc.quote(i) for i in insts), return_exceptions=True)
        return ok([{"instrument_id": i.id, "symbol": i.symbol, "name": i.name, **(
            {"error": str(r), "status": "UNAVAILABLE"} if isinstance(r, Exception) else {"quote": r.model_dump(mode="json")})}
            for i, r in zip(insts, res)])

    @app.get("/api/ohlcv/{instrument_id:path}")
    async def ohlcv(instrument_id: str, interval: str = "1d", limit: int = 300):
        i = inst_or_404(instrument_id)
        if not 1 <= limit <= 1500:
            raise ApiError("INVALID_REQUEST", "limit must be 1..1500", 422)
        return ok((await svc.ohlcv(i, interval, limit)).model_dump(mode="json"))

    @app.get("/api/technical/indicators")
    async def indicators(instrument_id: str, interval: str = "1d", ind_specs: str = "sma:20,ema:21", limit: int = 300):
        i = inst_or_404(instrument_id)
        o = await svc.ohlcv(i, interval, limit)
        try:
            series = ind.compute(o.candles, [s for s in ind_specs.split(",") if s])
        except (ValueError, IndexError) as e:
            raise ApiError("INVALID_INDICATOR", str(e), 422)
        return ok({"instrument_id": i.id, "interval": interval, "times": [c.time for c in o.candles], "series": series,
                   "prov": o.prov.model_dump(mode="json")})

    @app.get("/api/technical/levels")
    async def levels(instrument_id: str, interval: str = "1h"):
        i = inst_or_404(instrument_id)
        o = await svc.ohlcv(i, interval, 300)
        return ok({"levels": [asdict(l) for l in technical.key_levels(o.candles, interval, equity_tz=i.is_equity_like)],
                   "trend": technical.trend(o.candles), "prov": o.prov.model_dump(mode="json")})

    # --- portfolio, paper trading, risk ----------------------------------------
    class PortfolioIn(BaseModel):
        name: str = Field(min_length=1, max_length=40)
        kind: str = "paper"
        starting_cash: str | float = 100000

    class PaperOrderIn(BaseModel):
        order: OrderIn
        preview_id: str | None = None
        client_key: str | None = None

    class ManualPositionIn(BaseModel):
        instrument_id: str
        qty: str | float
        avg_cost: str | float

    class CashIn(BaseModel):
        cash: str | float

    class HaltIn(BaseModel):
        halted: bool
        cancel_open: bool = False

    class ScenarioIn(BaseModel):
        portfolio_id: int | None = None
        shocks: dict[str, float] = Field(default_factory=dict)
        benchmark: str | None = None
        benchmark_shock: float | None = None

    from .trading.money import D as _D

    def dec(x, what: str):
        try:
            return _D(x)
        except Exception:  # noqa: BLE001
            raise ApiError("INVALID_REQUEST", f"{what} must be a number", 422)

    @app.get("/api/portfolios")
    async def portfolios_list():
        return ok(trading.portfolios())

    @app.post("/api/portfolios")
    async def portfolios_create(b: PortfolioIn):
        return ok(trading.create_portfolio(b.name, b.kind, dec(b.starting_cash, "starting_cash")))

    @app.get("/api/portfolio")
    async def portfolio_summary(pid: int | None = None):
        v = await trading.valuation(trading.portfolio(pid)["id"])
        trading.snapshot_equity_value(v["portfolio"]["id"], v["equity"], v["cash"]) if not v["unpriced_positions"] else None
        return ok(jsonable({**v, "halted": trading.halted(), "day_start_equity": trading.day_start_equity(v["portfolio"]["id"])}))

    @app.put("/api/portfolios/{pid}/manual/position")
    async def manual_position(pid: int, b: ManualPositionIn):
        trading.set_manual_position(pid, b.instrument_id, dec(b.qty, "qty"), dec(b.avg_cost, "avg_cost"))
        return ok({"saved": True})

    @app.put("/api/portfolios/{pid}/manual/cash")
    async def manual_cash(pid: int, b: CashIn):
        trading.set_manual_cash(pid, dec(b.cash, "cash"))
        return ok({"saved": True})

    @app.post("/api/portfolios/{pid}/reset")
    async def paper_reset(pid: int, body: dict):
        if body.get("confirm") is not True:
            raise ApiError("CONFIRMATION_REQUIRED", "send {\"confirm\": true} to reset the paper account (deletes its orders, fills and history)", 409)
        return ok(trading.reset_paper(pid))

    @app.post("/api/orders/preview")
    async def orders_preview(o: OrderIn):
        return ok(await trading.preview(o))

    @app.post("/api/orders/paper")
    async def orders_paper(b: PaperOrderIn):
        return ok(await trading.submit(b.order, b.preview_id, b.client_key))

    @app.post("/api/orders/live")
    async def orders_live(body: dict):
        db.audit("user", "live_order_refused", {"symbol": str(body.get("instrument_id"))[:40]})
        raise ApiError("LIVE_TRADING_DISABLED", "Live trading is not available. This build has no live broker adapter; only paper orders are possible.", 403)

    @app.get("/api/orders")
    async def orders_list(pid: int | None = None, state: str | None = None, limit: int = 100):
        return ok(trading.orders(pid, state, min(max(limit, 1), 500)))

    @app.post("/api/orders/{oid}/cancel")
    async def orders_cancel(oid: int):
        return ok(await trading.cancel(oid))

    @app.get("/api/fills")
    async def fills_list(pid: int | None = None, limit: int = 100):
        return ok(trading.fills(pid, min(max(limit, 1), 500)))

    @app.get("/api/portfolio/reconcile")
    async def portfolio_reconcile(pid: int | None = None):
        return ok(trading.reconcile(trading.portfolio(pid)["id"]))

    @app.get("/api/portfolio/performance")
    async def portfolio_performance(pid: int | None = None):
        return ok(tr_analytics.performance(trading, trading.portfolio(pid)["id"]))

    @app.get("/api/portfolio/risk")
    async def portfolio_risk(pid: int | None = None, benchmark: str = "SPY"):
        return ok(await tr_analytics.portfolio_risk(trading, trading.portfolio(pid)["id"], benchmark))

    @app.post("/api/portfolio/scenario")
    async def portfolio_scenario(b: ScenarioIn):
        try:
            return ok(await tr_analytics.scenario(trading, trading.portfolio(b.portfolio_id)["id"], b.shocks, b.benchmark, b.benchmark_shock))
        except ValueError as e:
            raise ApiError("INVALID_REQUEST", str(e), 422)

    @app.get("/api/risk/limits")
    async def risk_limits_get():
        return ok(trading.limits().model_dump())

    @app.put("/api/risk/limits")
    async def risk_limits_put(body: dict):
        try:
            return ok(trading.set_limits(body).model_dump())
        except (ValidationError, TypeError) as e:
            raise ApiError("INVALID_LIMITS", "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:3]) if isinstance(e, ValidationError) else str(e), 422)

    @app.get("/api/risk/size")
    async def risk_size(instrument_id: str, entry: str, stop: str, pid: int | None = None, risk_pct: float | None = None):
        return ok(await trading.size(pid, instrument_id, dec(entry, "entry"), dec(stop, "stop"), risk_pct))

    @app.get("/api/trading/status")
    async def trading_status():
        return ok({"environment": BROKER_ENV, "live_trading_enabled": False, "halted": trading.halted(), "sim": trading.sim_params().model_dump()})

    @app.put("/api/trading/sim")
    async def trading_sim(body: dict):
        try:
            return ok(trading.set_sim_params(body).model_dump())
        except (ValidationError, TypeError) as e:
            raise ApiError("INVALID_SIM_PARAMS", "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:3]) if isinstance(e, ValidationError) else str(e), 422)

    @app.post("/api/trading/halt")
    async def trading_halt(b: HaltIn):
        return ok(await trading.set_halted(b.halted, b.cancel_open))

    # --- IBKR ----------------------------------------------------------------
    IBKR_HELP = ("Run TWS or IB Gateway locally with the API enabled, then start the backend with IBKR_ENABLED=1 (and IBKR_PORT: paper 7497/4002). "
                 "IBKR_MODE=readonly (default) reads positions and executions from ANY account; IBKR_MODE=paper_trading routes orders to a PAPER account only.")

    def need_broker() -> IBKRBroker:
        if broker is None:
            raise ApiError("IBKR_NOT_CONFIGURED", IBKR_HELP, 503)
        return broker

    @app.get("/api/ibkr/status")
    async def ibkr_status():
        return ok(ibkr_status_dict() if broker else {"configured": False, "help": IBKR_HELP})

    @app.post("/api/ibkr/connect")
    async def ibkr_connect():
        b = need_broker()
        db.audit("user", "ibkr_connect", {"mode": b.s.mode, "port": b.s.port})
        return ok(await b.connect())

    @app.post("/api/ibkr/disconnect")
    async def ibkr_disconnect():
        b = need_broker()
        await b.disconnect()
        return ok(b.status())

    class LinkIn(BaseModel):
        name: str = Field(min_length=1, max_length=40)

    @app.post("/api/ibkr/portfolio")
    async def ibkr_portfolio(b: LinkIn):
        need_broker()
        return ok(await trading.link_ibkr_portfolio(b.name))

    @app.post("/api/ibkr/sync")
    async def ibkr_sync():
        b = need_broker()
        out = {"portfolios": [], "journal": None}
        for pf in trading.portfolios():
            if pf["venue"] == "ibkr" and pf["broker_account"] == b.account:
                out["portfolios"].append(await trading.sync_broker_portfolio(pf["id"]))
        ex = await b.executions()
        ins, dup = journal.insert_executions(ex)
        out["journal"] = {"executions_seen": len(ex), "inserted": ins, "duplicates": dup,
                          "note": "TWS only returns recent executions; for older history import an IBKR Flex Query (Journal > Import)."}
        return ok(out)

    # --- journal ---------------------------------------------------------------
    def trade_json(t: dict) -> dict:
        out = {k: v for k, v in t.items() if k not in ("net_pnl",)}
        out["net_pnl"] = str(t["net_pnl"])
        out["net_pnl_num"] = float(t["net_pnl"])
        for k in ("opened_at", "closed_at"):
            out[k] = t[k].isoformat() if t[k] else None
        return out

    class ImportIn(BaseModel):
        source: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_.:\- ]+$")
        kind: str = "trades"
        text: str = Field(min_length=1, max_length=5_000_000)
        preset: str | None = None
        mapping: dict | None = None
        options: dict | None = None
        filename: str | None = Field(default=None, max_length=200)
        confirm: bool = False

    def run_parse(b: ImportIn):
        if b.kind not in ("trades", "flows"):
            raise ApiError("INVALID_REQUEST", "kind must be trades or flows", 422)
        if b.preset and b.preset not in jimp.PRESETS:
            raise ApiError("INVALID_REQUEST", f"unknown preset '{b.preset}'", 422)
        mapping = b.mapping if b.mapping is not None else None
        try:
            return jimp.parse(b.text, b.source, b.kind, mapping, b.preset, b.options)
        except ValueError as e:
            raise ApiError("INVALID_FILE", str(e), 422)

    @app.get("/api/journal/presets")
    async def journal_presets():
        return ok({"presets": {k: {"label": v["label"], "verified": v["verified"], "note": v["note"]} for k, v in jimp.PRESETS.items()},
                   "roles": {"trades": jimp.ROLES_TRADES, "flows": jimp.ROLES_FLOWS}})

    @app.post("/api/journal/import/preview")
    async def journal_preview(b: ImportIn):
        r = run_parse(b)
        existing = 0
        keys = [e.ext_id for e in r.executions] if r.kind == "trades" else [f.ext_id for f in r.flows]
        table = "executions" if r.kind == "trades" else "cashflows"
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            existing += db.q(f"SELECT COUNT(*) FROM {table} WHERE source=? AND ext_id IN ({','.join('?' * len(chunk))})", (b.source, *chunk))[0][0]
        rows = r.executions if r.kind == "trades" else r.flows
        sample = [{"ts": x.ts.isoformat(), "symbol": x.symbol, **({"side": x.side, "qty": str(x.qty), "price": str(x.price), "fee": str(x.fee), "kind": x.kind} if r.kind == "trades" else {"kind": x.kind, "amount": str(x.amount)})} for x in rows[:8]]
        return ok({"headers": r.headers, "mapping": r.mapping, "options": r.options, "rows_total": r.rows_total, "parsed": len(rows), "already_imported": existing,
                   "errors": r.errors[:20], "errors_total": len(r.errors), "skipped": dict(r.skipped), "kinds": dict(r.kinds), "warnings": r.warnings, "sample": sample,
                   "time_range": [rows[0].ts.isoformat(), rows[-1].ts.isoformat()] if rows else None,
                   "preset": {"label": jimp.PRESETS[b.preset]["label"], "verified": jimp.PRESETS[b.preset]["verified"], "note": jimp.PRESETS[b.preset]["note"]} if b.preset else None,
                   "will_insert": len(rows) - existing})

    @app.post("/api/journal/import")
    async def journal_import(b: ImportIn):
        if not b.confirm:
            raise ApiError("CONFIRMATION_REQUIRED", "preview the import, check the mapping and timestamps, then send confirm: true", 409)
        r = run_parse(b)
        if r.errors and not (r.executions or r.flows):
            raise ApiError("IMPORT_FAILED", "nothing could be parsed: " + "; ".join(e["error"] for e in r.errors[:3]), 422)
        batch = journal.batch(b.source, b.kind, b.filename, r, 0, 0)
        ins, dup = journal.insert_executions(r.executions, batch) if r.kind == "trades" else journal.insert_flows(r.flows, batch)
        db.x("UPDATE import_batches SET inserted=?, duplicates=? WHERE id=?", (ins, dup, batch))
        journal.save_mapping(b.source, {"mapping": r.mapping, "options": r.options, "preset": b.preset})
        db.audit("user", "journal_import", {"source": b.source, "kind": b.kind, "inserted": ins, "duplicates": dup})
        return ok({"batch_id": batch, "inserted": ins, "duplicates": dup, "skipped": dict(r.skipped), "errors": len(r.errors), "warnings": r.warnings})

    class ManualExecIn(BaseModel):
        symbol: str = Field(min_length=1, max_length=20)
        side: str
        qty: str | float
        price: str | float
        fee: str | float = 0
        ts: str
        asset_class: str = "crypto"
        source: str = Field(default="manual", pattern=r"^[A-Za-z0-9_.:\- ]+$", max_length=60)

    @app.post("/api/journal/executions")
    async def journal_manual(b: ManualExecIn):
        import uuid as _uuid
        if b.side not in ("buy", "sell"):
            raise ApiError("INVALID_REQUEST", "side must be buy or sell", 422)
        try:
            qty, price, fee = dec(b.qty, "qty"), dec(b.price, "price"), dec(b.fee, "fee")
            ts = jimp.parse_ts(b.ts)
        except ValueError as e:
            raise ApiError("INVALID_REQUEST", str(e), 422)
        if qty <= 0 or price <= 0 or fee < 0:
            raise ApiError("INVALID_REQUEST", "qty and price must be positive and fee cannot be negative", 422)
        ins, _ = journal.insert_executions([Exec(source=b.source, ext_id=f"manual-{_uuid.uuid4().hex[:12]}", ts=ts, symbol=b.symbol.strip().upper(), asset_class=b.asset_class,
                                                 side=b.side, qty=qty, price=price, fee=fee)])
        db.audit("user", "journal_manual_execution", {"symbol": b.symbol.upper()})
        return ok({"inserted": ins})

    @app.get("/api/journal/sources")
    async def journal_sources():
        return ok({"sources": journal.sources(), "batches": journal.batches()})

    @app.delete("/api/journal/source")
    async def journal_delete_source(source: str, confirm: bool = False):
        if not confirm:
            raise ApiError("CONFIRMATION_REQUIRED", "deleting a source removes its executions, cash flows and the notes on its trades: pass confirm=true", 409)
        return ok(journal.delete_source(source))

    class HLSyncIn(BaseModel):
        model_config = ConfigDict(extra="forbid")
        address: str = Field(min_length=1, max_length=100)

    @app.post("/api/journal/hyperliquid/sync")
    async def journal_hyperliquid(b: HLSyncIn):
        """Read-only: pulls fills and funding for a PUBLIC wallet address. Idempotent (re-syncing adds only new rows)."""
        try:
            addr = hl.valid_address(b.address)
        except ValueError as e:
            raise ApiError("INVALID_ADDRESS", str(e), 422)
        try:
            fills = await hl_client.fills(addr)
            funding = await hl_client.funding(addr)
        except hl.HyperliquidError as e:
            raise ApiError("HYPERLIQUID_UNAVAILABLE", f"{e}. Nothing was imported.", 502)
        res = hl.parse_fills(fills, addr)
        flows = hl.parse_funding(funding, addr)
        batch = journal.batch(hl.source_name(addr), "trades", None, res, 0, 0)
        ins, dup = journal.insert_executions(res.executions, batch)
        f_ins, f_dup = journal.insert_flows(flows, batch)
        db.audit("user", "journal_hyperliquid_sync", {"source": hl.source_name(addr), "inserted": ins, "duplicates": dup, "funding": f_ins})
        return ok({"source": hl.source_name(addr), "fills_seen": len(fills), "executions": {"inserted": ins, "duplicates": dup},
                   "funding": {"seen": len(funding), "inserted": f_ins, "duplicates": f_dup}, "skipped": dict(res.skipped), "warnings": res.warnings,
                   "reported": {"closed_pnl": res.options["reported_closed_pnl"], "note": "Hyperliquid's own realized P&L (excludes fees). The journal uses FIFO lot matching, so totals can differ slightly; large gaps mean missing history."},
                   "history_limit_note": "The API serves only the most recent ~10,000 fills." if len(fills) >= 10_000 else None})

    @app.post("/api/journal/sync")
    async def journal_sync():
        out = journal.sync_paper()
        if broker is not None and broker.connected:
            ins, dup = journal.insert_executions(await broker.executions())
            out["ibkr"] = {"inserted": ins, "duplicates": dup}
        else:
            out["ibkr"] = "not connected: nothing synced"
        return ok(out)

    @app.get("/api/journal/trades")
    async def journal_trades(source: str | None = None, status: str | None = None, symbol: str | None = None, limit: int = 500):
        journal.sync_paper()
        res = journal.trades(source, status, symbol)
        return ok({"trades": [trade_json(t) for t in res["trades"][: min(max(limit, 1), 2000)]], "total": len(res["trades"]), "unattributed_cashflows": res["unattributed_cashflows"]})

    @app.get("/api/journal/trade")
    async def journal_trade(key: str):
        res = journal.trades()
        t = next((x for x in res["trades"] if x["key"] == key), None)
        if t is None:
            raise ApiError("NOT_FOUND", "trade not found (it may have been re-derived after an import or deletion)", 404)
        ex, _ = journal.load(t["source"])
        ids = set(t["exec_ids"])
        return ok({"trade": trade_json(t), "note": journal.get_note(key), "executions": [
            {"ext_id": e.ext_id, "ts": e.ts.isoformat(), "side": e.side, "qty": str(e.qty), "price": str(e.price), "fee": str(e.fee), "kind": e.kind} for e in ex
            if e.symbol == t["symbol"] and e.ext_id in ids]})

    @app.put("/api/journal/notes")
    async def journal_note(key: str, body: dict):
        if not any(x["key"] == key for x in journal.trades()["trades"]):
            raise ApiError("NOT_FOUND", "trade not found", 404)
        return ok(journal.upsert_note(key, body))

    @app.get("/api/journal/stats")
    async def journal_stats(source: str | None = None, symbol: str | None = None, since: str | None = None, until: str | None = None, groups: str | None = None):
        journal.sync_paper()
        closed = journal.trades(source, "closed", symbol)["trades"]
        try:
            if since:
                lo = datetime.fromisoformat(since).replace(tzinfo=timezone.utc) if "T" not in since else datetime.fromisoformat(since)
                closed = [t for t in closed if t["closed_at"] >= lo]
            if until:
                hi = datetime.fromisoformat(until).replace(tzinfo=timezone.utc) if "T" not in until else datetime.fromisoformat(until)
                closed = [t for t in closed if t["closed_at"] <= hi]
            return ok(jstats.analyze(closed, [g for g in groups.split(",") if g] if groups else None) | {"filters": {"source": source, "symbol": symbol, "since": since, "until": until}})
        except ValueError as e:
            raise ApiError("INVALID_REQUEST", str(e), 422)

    @app.get("/api/journal/export.csv")
    async def journal_export(source: str | None = None):
        import csv as _csv
        import io as _io
        from fastapi.responses import Response
        buf = _io.StringIO()
        w = _csv.writer(buf)
        cols = ["key", "source", "symbol", "side", "status", "opened_at", "closed_at", "qty_max", "entry_avg", "exit_avg", "gross_pnl", "fees", "funding", "net_pnl", "r_multiple", "setup", "tags", "planned_stop"]
        w.writerow(cols)
        for t in journal.trades(source)["trades"]:
            j = trade_json(t)
            w.writerow([("; ".join(j[c]) if c == "tags" else j.get(c)) if j.get(c) is not None else "" for c in cols])
        return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=journal-trades.csv"})

    # --- compare + multi-timeframe -------------------------------------------
    @app.get("/api/compare")
    async def compare(ids: str, interval: str = "1d", limit: int = 300):
        """Overlay 2-4 instruments rebased to 100 on calendar-aligned bars, with return correlation/beta versus the first id."""
        insts = [inst_or_404(i) for i in ids.split(",") if i]
        if not 2 <= len(insts) <= 4 or len({i.id for i in insts}) != len(insts):
            raise ApiError("INVALID_REQUEST", "provide 2 to 4 distinct instruments", 422)
        if not 10 <= limit <= 1500:
            raise ApiError("INVALID_REQUEST", "limit must be 10..1500", 422)
        res = await asyncio.gather(*(svc.ohlcv(i, interval, limit) for i in insts), return_exceptions=True)
        failed = [f"{i.symbol}: {r}" for i, r in zip(insts, res) if isinstance(r, Exception)]
        if failed:
            raise ApiError("DATA_UNAVAILABLE", "; ".join(failed), 503)
        try:
            times, aligned = cmp.align({i.id: r.candles for i, r in zip(insts, res)}, interval)
        except cmp.NoOverlap as e:
            raise ApiError("NO_OVERLAP", str(e), 422)
        base = insts[0].id
        closes = {k: [c.close for c in v] for k, v in aligned.items()}
        return ok({
            "interval": interval, "base": base, "aligned_bars": len(times), "times": times,
            "range": [times[0], times[-1]],
            "series": {i.id: {"symbol": i.symbol, "name": i.name, "closes": closes[i.id], "rebased": cmp.rebase(closes[i.id]),
                              "bars_before_alignment": len(r.candles), "prov": r.prov.model_dump(mode="json")} for i, r in zip(insts, res)},
            "stats": {i.id: cmp.pair_stats(closes[base], closes[i.id]) for i in insts[1:]},
            "notes": [f"Aligned to the {len(times)} bars all series share (calendar-aligned): bars present in only some series are dropped.",
                      "Returns are measured between consecutive shared bars, so every series has the same horizon.",
                      "Correlation and beta are historical and unstable; see rolling_60 min/max."],
        })

    @app.get("/api/technical/mtf")
    async def technical_mtf(instrument_id: str, swing_k: int = 3, benchmark: str | None = None):
        inst = inst_or_404(instrument_id)
        if not 1 <= swing_k <= 10:
            raise ApiError("INVALID_REQUEST", "swing_k must be 1..10", 422)
        bench = benchmark if benchmark is not None else ("SPY" if inst.is_equity_like and inst.symbol != "SPY" else None)
        bench_inst = inst_or_404(bench) if bench and bench.lower() != "none" else None
        return ok(await mtf_service.run_mtf(svc, inst, swing_k, bench_inst))

    # --- commands -----------------------------------------------------------
    class CommandIn(BaseModel):
        text: str = Field(max_length=500)

    @app.post("/api/command")
    async def command(body: CommandIn):
        c = commands.resolve(body.text)
        db.audit("user", "command", {"text": body.text, "ok": c.ok})
        if c.ok:
            hist = db.pref_get("recent_commands", [])
            db.pref_set("recent_commands", ([body.text.strip().upper()] + [h for h in hist if h != body.text.strip().upper()])[:20])
        return ok(asdict(c))

    @app.get("/api/command/suggest")
    async def suggest(q: str):
        return ok({"suggestions": commands.suggest(q), "recent": db.pref_get("recent_commands", [])[:8]})

    # --- watchlists / prefs / layouts --------------------------------------
    class WatchlistIn(BaseModel):
        name: str = Field(min_length=1, max_length=40)

    class ItemIn(BaseModel):
        instrument_id: str

    def wl_dict(r):
        items = [x["instrument_id"] for x in db.q("SELECT instrument_id FROM watchlist_items WHERE watchlist_id=? ORDER BY position", (r["id"],))]
        return {"id": r["id"], "name": r["name"], "items": items}

    @app.get("/api/watchlists")
    async def wls():
        return ok([wl_dict(r) for r in db.q("SELECT * FROM watchlists ORDER BY id")])

    @app.post("/api/watchlists")
    async def wl_create(b: WatchlistIn):
        if db.q("SELECT 1 FROM watchlists WHERE name=?", (b.name,)):
            raise ApiError("DUPLICATE", "A watchlist with that name exists", 409)
        wid = db.x("INSERT INTO watchlists(name,created_at) VALUES(?,?)", (b.name, now()))
        return ok(wl_dict(db.q("SELECT * FROM watchlists WHERE id=?", (wid,))[0]))

    @app.delete("/api/watchlists/{wid}")
    async def wl_delete(wid: int):
        db.x("DELETE FROM watchlists WHERE id=?", (wid,))
        return ok({"deleted": wid})

    @app.post("/api/watchlists/{wid}/items")
    async def wl_add(wid: int, b: ItemIn):
        i = inst_or_404(b.instrument_id)
        if not db.q("SELECT 1 FROM watchlists WHERE id=?", (wid,)):
            raise ApiError("NOT_FOUND", "watchlist not found", 404)
        pos = db.q("SELECT COALESCE(MAX(position),-1)+1 FROM watchlist_items WHERE watchlist_id=?", (wid,))[0][0]
        db.x("INSERT OR IGNORE INTO watchlist_items VALUES(?,?,?)", (wid, i.id, pos))
        return ok(wl_dict(db.q("SELECT * FROM watchlists WHERE id=?", (wid,))[0]))

    @app.delete("/api/watchlists/{wid}/items/{instrument_id:path}")
    async def wl_remove(wid: int, instrument_id: str):
        db.x("DELETE FROM watchlist_items WHERE watchlist_id=? AND instrument_id=?", (wid, instrument_id))
        return ok(wl_dict(db.q("SELECT * FROM watchlists WHERE id=?", (wid,))[0]))

    PREF_KEYS = {"theme": ("dark", "light"), "update_seconds": None, "selected_instrument": None, "workspace": None,
                 "telegram_enabled": None, "telegram_min_severity": None}

    @app.get("/api/prefs")
    async def prefs():
        return ok({"theme": db.pref_get("theme", "dark"), "update_seconds": db.pref_get("update_seconds", 5),
                   "selected_instrument": db.pref_get("selected_instrument", "CRYPTO:COINBASE:BTC-USD:SPOT"),
                   "workspace": db.pref_get("workspace", "overview"),
                   "telegram_enabled": db.pref_get("telegram_enabled", True), "telegram_min_severity": db.pref_get("telegram_min_severity", "info")})

    @app.put("/api/prefs")
    async def prefs_put(body: dict):
        for k, v in body.items():
            if k not in PREF_KEYS:
                raise ApiError("INVALID_PREF", f"unknown preference '{k}'", 422)
            if k == "theme" and v not in ("dark", "light"):
                raise ApiError("INVALID_PREF", "theme must be dark or light", 422)
            if k == "update_seconds" and not (isinstance(v, (int, float)) and 1 <= v <= 300):
                raise ApiError("INVALID_PREF", "update_seconds must be 1..300", 422)
            if k == "telegram_enabled" and not isinstance(v, bool):
                raise ApiError("INVALID_PREF", "telegram_enabled must be true or false", 422)
            if k == "telegram_min_severity" and v not in ("info", "warning", "critical"):
                raise ApiError("INVALID_PREF", "telegram_min_severity must be info, warning or critical", 422)
            db.pref_set(k, v)
        return await prefs()

    @app.get("/api/layouts/{workspace}")
    async def layout_get(workspace: str):
        r = db.q("SELECT layout FROM layouts WHERE workspace=?", (workspace,))
        return ok(json.loads(r[0][0]) if r else None)

    @app.put("/api/layouts/{workspace}")
    async def layout_put(workspace: str, body: dict):
        db.x("INSERT INTO layouts VALUES(?,?,?) ON CONFLICT(workspace) DO UPDATE SET layout=excluded.layout, updated_at=excluded.updated_at",
             (workspace, json.dumps(body), now()))
        return ok(body)

    @app.delete("/api/layouts/{workspace}")
    async def layout_reset(workspace: str):
        db.x("DELETE FROM layouts WHERE workspace=?", (workspace,))
        return ok({"reset": workspace})

    # --- AI -----------------------------------------------------------------
    class ChatIn(BaseModel):
        message: str = Field(min_length=1, max_length=4000)
        instrument_id: str | None = None

    class AnalyzeIn(BaseModel):
        instrument_id: str
        agent: str = "technical"

    def need_ai():
        if not desk.configured:
            raise ApiError("AI_NOT_CONFIGURED", "Set ANTHROPIC_API_KEY on the backend to enable the AI desk.", 503)

    @app.get("/api/ai/status")
    async def ai_status():
        return ok({"configured": desk.configured, "model": desk.llm.model if desk.llm else None,
                   "tools": [t.name for t in desk.reg.tools.values()], "order_tools": []})

    @app.post("/api/ai/chat")
    async def ai_chat(b: ChatIn):
        need_ai()
        out = await desk.chat(b.message, b.instrument_id)
        db.audit("ai", "chat", {"analysis_id": out["analysis_id"], "tools": [c["name"] for c in out["tool_calls"]]})
        return ok(out)

    @app.post("/api/ai/analyze")
    async def ai_analyze(b: AnalyzeIn):
        need_ai()
        if b.agent not in ("technical", "fundamental", "macro", "risk", "chief"):
            raise ApiError("AGENT_NOT_AVAILABLE", f"unknown agent '{b.agent}'. Built: technical, fundamental, macro, risk, chief. Not built: news (headlines are untrusted text), "
                                                  "scanner, strategy (a strategy agent would drift into trade recommendations)", 501)
        try:
            if b.agent == "technical":
                return ok(await desk.technical(b.instrument_id))
            inst = I.resolve(b.instrument_id) if b.instrument_id else None
            if b.agent in ("fundamental", "chief") and inst is None:
                raise ToolError(f"unknown instrument {b.instrument_id}")
            if b.agent == "chief":
                out = await team.chief(inst.id)
                db.audit("ai", "chief", {"analysis_id": out["analysis_id"], "status": out["status"]})
                return ok(out)
            if b.agent == "fundamental":
                if inst.asset_class not in ("equity", "etf"):
                    raise ApiError("NOT_APPLICABLE", f"fundamentals do not apply to {inst.asset_class} instruments", 422)
                return ok(await team.specialist("fundamental", await fundamental_snapshot(inst, fundamentals)))
            return ok(await team.specialist(b.agent, await (macro_snapshot(svc) if b.agent == "macro" else risk_snapshot(trading))))
        except ToolError as e:
            raise ApiError("UNKNOWN_INSTRUMENT", str(e), 404)

    @app.get("/api/ai/analysis/{aid}")
    async def ai_get(aid: str):
        r = db.q("SELECT * FROM analyses WHERE analysis_id=?", (aid,))
        if not r:
            raise ApiError("NOT_FOUND", "analysis not found", 404)
        return ok(dict(r[0]))


    def inst_id(sym: str) -> str:
        i = I.by_symbol(sym) or I.adhoc(sym)
        return i.id if i else f"EQUITY:US:{sym}"

    # --- BTC derivatives -------------------------------------------------------
    @app.get("/api/derivatives/btc")
    async def derivatives_btc(fresh: bool = False):
        return ok(await derivs.snapshot(fresh))

    @app.get("/api/derivatives/btc/history")
    async def derivatives_btc_history(hours: float = 48):
        return ok(derivs.history(max(1.0, min(hours, 24 * 30))))

    # --- fundamentals ---------------------------------------------------------
    @app.get("/api/fundamentals/{token:path}")
    async def fundamentals_get(token: str, refresh: bool = False):
        inst = I.resolve(token)
        if inst is None:
            raise ApiError("UNKNOWN_INSTRUMENT", f"unknown instrument '{token[:40]}'", 404)
        return ok(await fundamentals.get(inst, force=refresh))

    # --- news -----------------------------------------------------------------
    @app.exception_handler(NewsError)
    async def _news_err(_, e: NewsError):
        return JSONResponse({"ok": False, "error": {"code": e.code, "message": e.message}}, status_code=e.status)

    class FeedIn(BaseModel):
        model_config = ConfigDict(extra="forbid")
        name: str = Field(min_length=1, max_length=80)
        url: str = Field(min_length=8, max_length=500)

    class FeedPatch(BaseModel):
        model_config = ConfigDict(extra="forbid")
        enabled: bool

    class RefreshIn(BaseModel):
        model_config = ConfigDict(extra="forbid")
        feed_id: int | None = None

    def yahoo_symbol(instrument_id: str | None, symbol: str) -> str | None:
        inst = I.resolve(instrument_id or symbol)
        if inst is None:
            return None
        if inst.asset_class == "crypto":
            return f"{inst.symbol.split('-')[0]}-USD"
        return inst.symbol if inst.asset_class in ("equity", "etf") else None

    @app.get("/api/news")
    async def news_list(symbol: str | None = None, q: str | None = None, hours: float = 72, limit: int = 60, fetch: bool = True):
        sym = symbol.strip().upper() if symbol else None
        symbol_fetch = None
        if sym and fetch:
            ys = yahoo_symbol(None, sym)
            if ys:
                symbol_fetch = await news.refresh_symbol(ys, sym.split("-")[0] if ys.endswith("-USD") else sym)
        out = await asyncio.to_thread(news.items, sym.split("-")[0] if sym and sym.endswith("-USD") else sym, q, max(1, min(hours, 24 * 14)), max(1, min(limit, 200)))
        out["meta"]["symbol_fetch"] = symbol_fetch
        return ok(out)

    @app.post("/api/news/refresh")
    async def news_refresh(b: RefreshIn):
        return ok({"results": await news.refresh(b.feed_id)})

    @app.get("/api/news/feeds")
    async def news_feeds():
        return ok({"feeds": news.feeds(), "note": "Default feed URLs were written from memory and have not been fetched by the build; each feed reports its own health."})

    @app.post("/api/news/feeds")
    async def news_feed_add(b: FeedIn):
        f = news.add_feed(b.name, b.url)
        db.audit("user", "news_feed_add", {"name": f["name"]})
        return ok(f)

    @app.patch("/api/news/feeds/{fid}")
    async def news_feed_patch(fid: int, b: FeedPatch):
        news.set_enabled(fid, b.enabled)
        return ok({"id": fid, "enabled": b.enabled})

    @app.delete("/api/news/feeds/{fid}")
    async def news_feed_del(fid: int):
        news.delete_feed(fid)
        db.audit("user", "news_feed_delete", {"id": fid})
        return ok({"deleted": fid})

    # --- backtester ---------------------------------------------------------
    class BtRunIn(BaseModel):
        preset: str | None = None
        overrides: dict | None = None
        spec: dict | None = None

    @app.get("/api/backtest/presets")
    async def bt_list():
        return ok({"presets": bt_presets.listing(), "universes": scan_universe.UNIVERSES, "demo": demo, "caveats": bt_run.CAVEATS,
                   "unavailable": scan_presets.UNAVAILABLE_PRESETS})

    @app.post("/api/backtest/run")
    async def bt_start(b: BtRunIn):
        try:
            if b.preset:
                pid = scan_presets.ALIASES.get(b.preset.upper(), b.preset)
                if pid in scan_presets.UNAVAILABLE_PRESETS:
                    raise ApiError("PRESET_NOT_AVAILABLE", scan_presets.UNAVAILABLE_PRESETS[pid], 501)
                if pid not in scan_presets.PRESETS:
                    raise ApiError("UNKNOWN_PRESET", f"unknown preset '{b.preset}'", 404)
                spec = bt_presets.preset_spec(pid, b.overrides)
            elif b.spec:
                spec = BtSpec.model_validate(b.spec)
            else:
                raise ApiError("INVALID_REQUEST", "provide preset or spec", 422)
        except ValidationError as e:
            raise ApiError("INVALID_SPEC", "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:4]), 422)
        if spec.universe not in scan_universe.UNIVERSES:
            raise ApiError("UNKNOWN_UNIVERSE", f"unknown universe '{spec.universe}'", 422)
        if demo and spec.universe != "core":
            raise ApiError("DEMO_UNIVERSE", "Demo mode only supports the core universe (no network for the full directory).", 422)
        syms = app_symbols_override.get(spec.universe)
        if syms is None:
            try:
                syms = await scan_universe.load(spec.universe)
            except scan_universe.UniverseUnavailable as e:
                raise ApiError("UNIVERSE_UNAVAILABLE", str(e), 503)
        db.audit("user", "backtest_run", {"name": spec.name, "universe": spec.universe, "side": spec.side})
        return ok({"job_id": bt_jobs.start(spec, bt_source, syms)})

    def bt_decorate(r: dict) -> dict:
        """Attach the catalog instrument id to every trade/open position/signal so a click charts the right instrument (not an UNVERIFIED ad-hoc one)."""
        ids = {x["symbol"]: inst_id(x["symbol"]) for k in ("trades", "open_at_end", "pending_signals") for x in r.get(k, [])}
        for k in ("trades", "open_at_end", "pending_signals"):
            for x in r.get(k, []):
                x["instrument_id"] = ids[x["symbol"]]
        return r

    def bt_persist(r: dict) -> dict:
        """Runs once per finished backtest, in a worker thread: tag trades with catalog ids, then save the full result."""
        bt_decorate(r)
        rid = db.x("INSERT INTO backtest_runs(name,spec,result,trades,ran_at) VALUES(?,?,?,?,?)",
                   (r["meta"]["spec"]["name"], json.dumps(r["meta"]["spec"]), json.dumps(r), r["summary"]["n"], r["meta"]["ran_at"]))
        return {"run_id": rid}

    @app.get("/api/backtest/jobs/{jid}")
    async def bt_job(jid: str):
        j = bt_jobs.view(jid)
        if j is None:
            raise ApiError("NOT_FOUND", "backtest job not found (jobs are kept in memory)", 404)
        return ok(j)

    @app.get("/api/backtest/runs")
    async def bt_runs():
        return ok([{"id": r["id"], "name": r["name"], "trades": r["trades"], "ran_at": r["ran_at"]} for r in db.q("SELECT id,name,trades,ran_at FROM backtest_runs ORDER BY id DESC LIMIT 50")])

    @app.get("/api/backtest/runs/{rid}")
    async def bt_run_get(rid: int):
        rows = db.q("SELECT * FROM backtest_runs WHERE id=?", (rid,))
        if not rows:
            raise ApiError("NOT_FOUND", "no such saved backtest", 404)
        return ok({"id": rid, "result": await asyncio.to_thread(lambda: bt_decorate(json.loads(rows[0]["result"])))})

    @app.delete("/api/backtest/runs/{rid}")
    async def bt_run_del(rid: int):
        db.x("DELETE FROM backtest_runs WHERE id=?", (rid,))
        return ok({"deleted": rid})

    # --- scanner ------------------------------------------------------------
    @app.get("/api/scanner/presets")
    async def scan_list():
        return ok({"presets": [{"id": k, "name": v["name"], "description": v["description"], "spec": v["spec"].model_dump()} for k, v in scan_presets.PRESETS.items()],
                   "unavailable": scan_presets.UNAVAILABLE_PRESETS, "universes": scan_universe.UNIVERSES, "demo": demo,
                   "data_source": "demo (synthetic)" if demo else "Yahoo daily bars (unofficial, delayed)"})

    @app.get("/api/scanner/fields")
    async def scan_fields():
        return ok({k: {"type": t, "label": lbl, "unit": u} for k, (t, lbl, u) in SCAN_FIELDS.items()})

    class NLIn(BaseModel):
        text: str = Field(min_length=3, max_length=500)

    @app.post("/api/scanner/nl")
    async def scan_nl_route(b: NLIn):
        return ok(scan_nl.translate(b.text))

    class RunIn(BaseModel):
        preset: str | None = None
        spec: dict | None = None

    @app.post("/api/scanner/run")
    async def scan_run(b: RunIn):
        if b.preset:
            pid = scan_presets.ALIASES.get(b.preset.upper(), b.preset)
            if pid in scan_presets.UNAVAILABLE_PRESETS:
                raise ApiError("PRESET_NOT_AVAILABLE", scan_presets.UNAVAILABLE_PRESETS[pid], 501)
            if pid not in scan_presets.PRESETS:
                raise ApiError("UNKNOWN_PRESET", f"unknown preset '{b.preset}'", 404)
            spec = scan_presets.PRESETS[pid]["spec"].model_copy(deep=True)
        elif b.spec:
            try:
                spec = ScanSpec.model_validate(b.spec)
            except ValidationError as e:
                raise ApiError("INVALID_SPEC", "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:4]), 422)
        else:
            raise ApiError("INVALID_REQUEST", "provide preset or spec", 422)
        if spec.universe not in scan_universe.UNIVERSES:
            raise ApiError("UNKNOWN_UNIVERSE", f"unknown universe '{spec.universe}'", 422)
        if demo and spec.universe != "core":
            raise ApiError("DEMO_UNIVERSE", "Demo mode only supports the core universe (no network for the full directory).", 422)
        syms = app_symbols_override.get(spec.universe)
        if syms is None:
            try:
                syms = await scan_universe.load(spec.universe)
            except scan_universe.UniverseUnavailable as e:
                raise ApiError("UNIVERSE_UNAVAILABLE", str(e), 503)
        db.audit("user", "scan_run", {"name": spec.name, "universe": spec.universe, "filters": len(spec.filters)})
        return ok({"job_id": jobs.start(spec, bars, syms)})

    @app.get("/api/scanner/jobs/{jid}")
    async def scan_job(jid: str):
        j = jobs.view(jid)
        if j is None:
            raise ApiError("NOT_FOUND", "scan job not found (jobs are kept in memory)", 404)
        if j["status"] == "done":
            for r in j["result"]["results"]:
                r["instrument_id"] = inst_id(r["symbol"])
            m = j["result"]["meta"]
            if not j.get("logged"):
                db.x("INSERT INTO scan_runs(name,spec,matched,universe_size,data_as_of,provider,ran_at) VALUES(?,?,?,?,?,?,?)",
                     (m["spec"]["name"], json.dumps(m["spec"]), m["matched"], m["universe_size"], m["data_as_of"], m["provider"], m["ran_at"]))
                jobs.jobs[jid]["logged"] = True
        return ok(j)

    class SaveIn(BaseModel):
        name: str = Field(min_length=1, max_length=60)
        spec: dict

    @app.post("/api/scanner/save")
    async def scan_save(b: SaveIn):
        try:
            spec = ScanSpec.model_validate({**b.spec, "name": b.name})
        except ValidationError as e:
            raise ApiError("INVALID_SPEC", str(e.errors()[0]["msg"]), 422)
        db.x("INSERT INTO saved_scans(name,spec,created_at) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET spec=excluded.spec",
             (b.name, spec.model_dump_json(), now()))
        return ok({"saved": b.name})

    @app.get("/api/scanner/saved")
    async def scan_saved():
        return ok([{"id": r["id"], "name": r["name"], "spec": json.loads(r["spec"]), "created_at": r["created_at"]} for r in db.q("SELECT * FROM saved_scans ORDER BY name")])

    @app.delete("/api/scanner/saved/{sid}")
    async def scan_saved_del(sid: int):
        db.x("DELETE FROM saved_scans WHERE id=?", (sid,))
        return ok({"deleted": sid})

    @app.get("/api/scanner/runs")
    async def scan_runs():
        return ok([dict(r) for r in db.q("SELECT * FROM scan_runs ORDER BY id DESC LIMIT 25")])

    # --- alerts -------------------------------------------------------------
    def clean_rule(data: dict) -> dict:
        """Validate and canonicalise: symbols become canonical instrument ids; scan specs are validated by the scanner."""
        d = dict(data)
        if d.get("kind") in INSTRUMENT_KINDS:
            i = I.resolve(str(d.get("instrument_id", "")))
            if i is None:
                raise ApiError("UNKNOWN_INSTRUMENT", f"Unknown instrument '{d.get('instrument_id')}'", 404)
            d["instrument_id"] = i.id
        try:
            rule = parse_rule(d)
            if rule.kind == "scan":
                if rule.preset and scan_presets.ALIASES.get(rule.preset.upper(), rule.preset) not in scan_presets.PRESETS:
                    raise ValueError(f"unknown preset '{rule.preset}'")
                if rule.spec:
                    ScanSpec.model_validate(rule.spec)
        except (ValidationError, ValueError) as e:
            msg = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:3]) if isinstance(e, ValidationError) else str(e)
            raise ApiError("INVALID_ALERT", msg, 422)
        return rule.model_dump()

    @app.get("/api/alerts")
    async def alerts_list():
        return ok(alerts.list())

    @app.post("/api/alerts")
    async def alerts_create(body: dict):
        return ok(alerts.create(clean_rule(body)))

    @app.put("/api/alerts/{aid}")
    async def alerts_update(aid: int, body: dict):
        a = alerts.update(aid, clean_rule(body))
        if a is None:
            raise ApiError("NOT_FOUND", "alert not found", 404)
        return ok(a)

    class EnableIn(BaseModel):
        enabled: bool

    @app.post("/api/alerts/{aid}/enabled")
    async def alerts_enable(aid: int, b: EnableIn):
        a = alerts.set_enabled(aid, b.enabled)
        if a is None:
            raise ApiError("NOT_FOUND", "alert not found", 404)
        return ok(a)

    @app.delete("/api/alerts/{aid}")
    async def alerts_delete(aid: int):
        alerts.delete(aid)
        return ok({"deleted": aid})

    @app.get("/api/alerts/events")
    async def alerts_events(limit: int = 100, unread_only: bool = False):
        return ok(alerts.events(min(max(limit, 1), 500), unread_only))

    class ReadIn(BaseModel):
        ids: list[int] | None = None   # null = mark all read

    @app.post("/api/alerts/events/read")
    async def alerts_read(b: ReadIn):
        return ok({"marked": alerts.mark_read(b.ids)})

    @app.post("/api/alerts/evaluate")
    async def alerts_eval():
        """Run one evaluation pass now (the background loop does this on a timer)."""
        ev = await alerts.evaluate_all()
        return ok({"events": ev, "evaluated": len([a for a in alerts.list() if a["enabled"]])})

    # --- telegram -----------------------------------------------------------
    SETUP = ("Create a bot with @BotFather and copy its token, message your bot once, then find your chat id "
             "(e.g. via @userinfobot). Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the backend environment and restart.")

    @app.get("/api/telegram/status")
    async def telegram_status():
        if tg is None:
            return ok({"configured": False, "setup": SETUP})
        return ok(await tg.status())     # never contains the token; chat id is masked

    @app.post("/api/telegram/test")
    async def telegram_test():
        if tg is None:
            raise ApiError("TELEGRAM_NOT_CONFIGURED", SETUP, 503)
        t = time.monotonic()
        if t - last_tg_test["t"] < 5:
            raise ApiError("RATE_LIMITED", "Wait a few seconds between test messages.", 429)
        last_tg_test["t"] = t
        sent, detail = await tg.send_text("<b>ATLAS test message</b>\nIf you can read this, Telegram alert delivery is working. "
                                          "Alerts based on DEMO data are not sent to Telegram.")
        db.audit("user", "telegram_test", {"ok": sent})
        if not sent:
            raise ApiError("TELEGRAM_FAILED", detail, 502)
        return ok({"sent": True})

    # --- websocket fan-out --------------------------------------------------
    @app.websocket("/ws/market-data")
    async def ws_market(ws: WebSocket):
        await ws.accept()
        ids: list[str] = []

        async def reader():
            nonlocal ids
            while True:
                msg = await ws.receive_json()
                if isinstance(msg.get("subscribe"), list):
                    ids = [i for i in msg["subscribe"][:50] if isinstance(i, str)]

        task = asyncio.create_task(reader())
        try:
            while True:
                insts = [I.resolve(i) for i in ids]
                res = await asyncio.gather(*(svc.quote(i) for i in insts if i), return_exceptions=True)
                data = [{"instrument_id": i.id, "error": str(r), "status": "UNAVAILABLE"} if isinstance(r, Exception) else r.model_dump(mode="json")
                        for i, r in zip([i for i in insts if i], res)]
                await ws.send_json({"type": "quotes", "data": data, "sent_at": now()})
                await asyncio.sleep(max(1.0, float(db.pref_get("update_seconds", 5))))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            task.cancel()

    dist = os.getenv("ATLAS_WEB_DIST")
    if dist and os.path.isdir(dist):                       # cloud: one server serves both the API and the built web app (same origin, no CORS)
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")

    return app
