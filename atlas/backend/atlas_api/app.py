import asyncio
from typing import Literal
import json
import logging
import math
import os
import time
from dataclasses import asdict
from datetime import date, datetime, timezone

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
from .macro_brief import MacroBriefService
from .discover.service import DiscoverService
from .eventcal.service import EventCalendar
from .btclab.data import BtcData
from .sentiment import FearGreed
from .nyfed import NyFedSofr
from .treasury import Treasury
from .cftc import CftcBitcoin
from .stablecoins import Stablecoins
from .onchain import OnChain
from .ecb import EcbFx
from .worldbank import WorldBank
from .fedops import FedOps
from .tga import Tga
from .auctions import Auctions
from .mts import Mts
from .intexp import InterestExpense
from .buybacks import Buybacks
from .billauctions import BillAuctions
from .borrowing import Borrowing
from .cftc_futures import CftcAgriculture, CftcCommodities, CftcCurrencies, CftcFutures
from .customs import Customs
from .dealers import Dealers
from .outlays import Outlays
from .realyields import RealYields
from .fincond import FinConditions
from .claims import JoblessClaims
from .oil import OilPrices
from .gasoline import GasolinePrices
from .naturalgas import NaturalGas
from .moneysupply import MoneySupply
from .retailsales import RetailSales
from .housingstarts import HousingStarts
from .industrialproduction import IndustrialProduction
from .euromoney import EuroMoneySupply
from .eurohicp import EuroInflation
from .eurounemployment import EuroUnemployment
from .eurostress import EuroStress
from .euroyields import EuroYields
from .eurogdp import EuroGdp
from .eurobankrates import EuroBankRates
from .eurostockrates import EuroStockRates
from .euroemployment import EuroEmployment
from .jolts import Jolts
from .joltsindustries import JoltsIndustries
from .joltsflows import JoltsFlows
from .usinventories import UsInventories
from .usconsumercredit import UsConsumerCredit
from .usbankloans import UsBankLoans
from .usbankbalance import UsBankBalance
from .usbuildingpermits import UsBuildingPermits
from .usconstruction import UsConstruction
from .usnewhomes import UsNewHomes
from .usjobs import UsJobs
from .usgdp import UsGdp
from .ushousehold import UsHousehold
from .usrealspending import UsRealSpending
from .ustrade import UsTrade
from .eurolending import EuroLending
from .reserves import BankReserves
from .ecbrates import EcbRates
from .receipts import Receipts
from .avgrates import AvgRates
from .mspd import Mspd
from .soma import Soma
from .fedrates import FedRates
from .cgglobal import CoinGeckoGlobal
from .sched.engine import Scheduler
from .sched.jobs import register_default_jobs
from .sched import settings as sched_settings
from .discover.narratives import NarrativeService
from .btclab.evaluate import LabError
from .btclab.service import AgentIn as LabAgentIn, LabService, RunIn as LabRunIn
from .stocks.edgar import EdgarClient
from .stocks.research import StockResearch
from .research.live import FundamentalResearch
from .research.brief import build_brief
from .discover.store import DiscoveryStore, STATES as DISC_STATES
from .discover.listings import NasdaqIpoFeed
from .discover.listings_service import ListingsService
from .discover.newtome import NewToMe
from .brokers.ibkr import BrokerError, IBKRBroker, IBKRSettings
from .providers.ibkr_data import IBKRData
from .journal import entries as jent, hyperliquid as hl, importers as jimp, stats as jstats
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


def create_app(*, db_path: str | None = None, demo: bool | None = None, llm=None, providers: dict | None = None, bar_source: BarSource | None = None, backtest_source: BarSource | None = None, alert_loop: bool | None = None, telegram: TelegramNotifier | None = None, broker: IBKRBroker | None = None, hyperliquid: hl.HyperliquidClient | None = None, news_client: httpx.AsyncClient | None = None, news_loop: bool | None = None, fundamentals_provider=None, deriv_client=None, auth_password: str | None = None, signal_registry=None, signal_parts: dict | None = None, calendar_client: httpx.AsyncClient | None = None) -> FastAPI:
    demo = os.getenv("ATLAS_DEMO") == "1" if demo is None else demo
    db = DB(db_path or os.getenv("ATLAS_DB", "atlas.db"))
    provs = providers if providers is not None else {"coinbase": CoinbaseProvider(), "yahoo": YahooProvider(), "fred": FredProvider()}
    if demo:
        provs = {**provs, "demo": DemoProvider()}
    svc = MarketService(provs, demo=demo)
    if llm is None and os.getenv("ANTHROPIC_API_KEY"):
        llm = AnthropicLLM(os.environ["ANTHROPIC_API_KEY"], os.getenv("ATLAS_MODEL", "claude-sonnet-5-5"))
    journal = JournalStore(db)
    journal_entries = jent.EntryStore(db)
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

    # The background scheduler runs inside this process by default (local use). In the cloud a separate worker process runs it (ATLAS_SCHEDULER=off here, `python -m atlas_api.worker` there).
    run_sched = os.getenv("ATLAS_SCHEDULER", "inprocess") == "inprocess" and alert_loop is not False and not demo

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
        sched = getattr(_app.state, "scheduler", None)
        if sched is not None and run_sched:
            tasks.append(asyncio.create_task(sched.run_forever()))
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
    signal = SignalService(db=db, svc=svc, news=news, fundamentals=fundamentals, macro=macro, fedwatch=fedwatch, demo=demo, llm=llm, registry=signal_registry, **(signal_parts or {}))       # Signal Mobile research API (read-only); the last two are test hooks
    signal_routes.register(app, signal, ok)
    jent.register(app, ok, journal, journal_entries)           # simple journal entries: write a trade down like a note

    @app.get("/api/macro/fed")
    async def macro_fed():
        if not demo and provs.get("fred") is None:
            raise ApiError("NOT_CONFIGURED", "The FRED provider is not set up.", 503)
        return ok(await fedwatch.overview())

    treasury = Treasury(demo=demo)
    ecb_fx = EcbFx(demo=demo)
    world_bank = WorldBank(demo=demo)
    fed_ops = FedOps(demo=demo)
    tga = Tga(demo=demo)
    auctions = Auctions(demo=demo)
    budget = Mts(demo=demo)
    interest = InterestExpense(demo=demo)
    buybacks = Buybacks(demo=demo)
    bill_auctions = BillAuctions(demo=demo)
    borrowing = Borrowing(demo=demo)
    dealers = Dealers(demo=demo)
    futures_positioning = CftcFutures(demo=demo)
    customs = Customs(demo=demo)
    receipts = Receipts(demo=demo)
    outlays = Outlays(demo=demo)
    real_yields = RealYields(demo=demo)
    fin_conditions = FinConditions(demo=demo)
    jobless_claims = JoblessClaims(demo=demo)
    oil_prices = OilPrices(demo=demo)
    gasoline_prices = GasolinePrices(demo=demo)
    natural_gas = NaturalGas(demo=demo)
    money_supply = MoneySupply(demo=demo)
    retail_sales = RetailSales(demo=demo)
    housing_starts = HousingStarts(demo=demo)
    industrial_production = IndustrialProduction(demo=demo)
    euro_money_supply = EuroMoneySupply(demo=demo)
    euro_inflation = EuroInflation(demo=demo)
    euro_unemployment = EuroUnemployment(demo=demo)
    euro_stress = EuroStress(demo=demo)
    euro_yields = EuroYields(demo=demo)
    euro_gdp = EuroGdp(demo=demo)
    euro_lending = EuroLending(demo=demo)
    euro_bank_rates = EuroBankRates(demo=demo)
    euro_stock_rates = EuroStockRates(demo=demo)
    euro_employment = EuroEmployment(demo=demo)
    jolts = Jolts(demo=demo)
    jolts_industries = JoltsIndustries(demo=demo)
    jolts_flows = JoltsFlows(demo=demo)
    us_inventories = UsInventories(demo=demo)
    us_consumer_credit = UsConsumerCredit(demo=demo)
    us_bank_loans = UsBankLoans(demo=demo)
    us_bank_balance = UsBankBalance(demo=demo)
    us_building_permits = UsBuildingPermits(demo=demo)
    us_construction = UsConstruction(demo=demo)
    us_new_homes = UsNewHomes(demo=demo)
    us_jobs = UsJobs(demo=demo)
    us_gdp = UsGdp(demo=demo)
    us_household = UsHousehold(demo=demo)
    us_real_spending = UsRealSpending(demo=demo)
    us_trade = UsTrade(demo=demo)
    bank_reserves = BankReserves(demo=demo)
    ecb_rates = EcbRates(demo=demo)
    commodity_positioning = CftcCommodities(demo=demo)
    currency_positioning = CftcCurrencies(demo=demo)
    agri_positioning = CftcAgriculture(demo=demo)
    debt_rates = AvgRates(demo=demo)
    debt_mix = Mspd(demo=demo)
    fed_holdings = Soma(demo=demo)
    fed_rates = FedRates(demo=demo)

    @app.get("/api/macro/fedrates")
    async def macro_fedrates():
        """The Fed's policy rate (EFFR), its target range and the overnight reference rates (New York Fed). Describes where overnight money costs; not a signal."""
        return ok(await fed_rates.overview())

    @app.get("/api/macro/fedholdings")
    async def macro_fedholdings():
        """What the Federal Reserve holds (SOMA, weekly, New York Fed): size, mix and changes. Describes the Fed's portfolio; not a signal."""
        return ok(await fed_holdings.overview())

    @app.get("/api/macro/debtmix")
    async def macro_debtmix():
        """What the US national debt is made of (Monthly Statement of the Public Debt): size, share and monthly change by security type. A month-end record; not a signal."""
        return ok(await debt_mix.overview())

    @app.get("/api/macro/debtrates")
    async def macro_debtrates():
        """Average interest rate the US government pays on its debt, by security type. Describes what it pays on what it owes; not a signal."""
        return ok(await debt_rates.overview())

    @app.get("/api/macro/interest")
    async def macro_interest():
        """Interest the US government owes on debt held by the public, by month and security type. Describes what already happened; not a signal."""
        return ok(await interest.overview())

    @app.get("/api/macro/buybacks")
    async def macro_buybacks():
        """US Treasury buyback operations: what dealers offered and what the Treasury bought. Describes what already happened; not a signal."""
        return ok(await buybacks.overview())

    @app.get("/api/macro/bills")
    async def macro_bills():
        """US Treasury bill auction results by term: rate, bid-to-cover, size and who bought. Describes auctions that already happened; not a signal."""
        return ok(await bill_auctions.overview())

    @app.get("/api/macro/borrowing")
    async def macro_borrowing():
        """US Treasury marketable borrowing from the Daily Treasury Statement: issues, redemptions and net, month and fiscal year so far. Describes what already happened; not a signal."""
        return ok(await borrowing.overview())

    @app.get("/api/macro/futures-positioning")
    async def macro_futures_positioning():
        """Who holds S&P 500, Nasdaq-100, 2-year and 10-year Treasury and dollar index futures (CFTC Commitments of Traders), weekly. Checked against the report's own totals; describes what already happened, not a signal."""
        return ok(await futures_positioning.overview())

    @app.get("/api/macro/agriculture-positioning")
    async def macro_agriculture_positioning():
        """Who holds silver, corn, soybean, wheat, coffee and sugar futures (CFTC Commitments of Traders, Disaggregated report), weekly. Checked against the report's own totals; describes what already happened, not a signal."""
        return ok(await agri_positioning.overview())

    @app.get("/api/macro/currency-positioning")
    async def macro_currency_positioning():
        """Who holds euro, yen, pound and VIX futures (CFTC Commitments of Traders), weekly. Checked against the report's own totals; describes what already happened, not a signal."""
        return ok(await currency_positioning.overview())

    @app.get("/api/macro/commodity-positioning")
    async def macro_commodity_positioning():
        """Who holds gold, crude oil, copper and natural gas futures (CFTC Commitments of Traders, Disaggregated report), weekly. Checked against the report's own totals; describes what already happened, not a signal."""
        return ok(await commodity_positioning.overview())

    @app.get("/api/macro/financial-conditions")
    async def macro_financial_conditions():
        """Chicago Fed National Financial Conditions Index (weekly, via FRED): zero is the average since 1971, positive tighter, negative looser. Describes what already happened; not a signal or a forecast."""
        return ok(await fin_conditions.overview())

    @app.get("/api/macro/oil-prices")
    async def macro_oil_prices():
        """WTI and Brent crude, spot, daily (US Energy Information Administration via FRED): checked for range, spacing, one-day moves and the Brent minus WTI spread. Describes what already happened; not a signal or a forecast."""
        return ok(await oil_prices.overview())

    @app.get("/api/macro/gasoline-prices")
    async def macro_gasoline_prices():
        """US regular gasoline, weekly national average (US Energy Information Administration via FRED): checked for spacing, range, weekly moves and consistency with WTI crude. Describes what already happened; not a signal or a forecast."""
        return ok(await gasoline_prices.overview())

    @app.get("/api/macro/natural-gas")
    async def macro_natural_gas():
        """Henry Hub natural gas spot price, daily (US Energy Information Administration via FRED): checked for range, spacing, one-day moves (a real cold-snap spike is allowed) and against EIA's own monthly average. Describes what already happened; not a signal or a forecast."""
        return ok(await natural_gas.overview())

    @app.get("/api/macro/money-supply")
    async def macro_money_supply():
        """M2 money supply, monthly seasonally adjusted level and its growth (Federal Reserve Board H.6 via FRED): checked for range, months in a row, one-month and one-year moves (real shocks like 2020 are allowed), adjusted against unadjusted, and the weekly figures against the monthly one. Describes what already happened; not a signal or a forecast."""
        return ok(await money_supply.overview())

    @app.get("/api/macro/retail-sales")
    async def macro_retail_sales():
        """US retail and food services sales, monthly seasonally adjusted (Census Bureau Advance Monthly Retail Trade Survey via FRED): checked for range, months in a row, one-month and one-year moves (real shocks like 2020 are allowed), retail trade plus food services against the total, and food services' share; the newest month is an advance estimate that is revised later. A failing check or request shows nothing."""
        return ok(await retail_sales.overview())

    @app.get("/api/macro/housing-starts")
    async def macro_housing_starts():
        """US housing starts, monthly seasonally adjusted annual rate in thousands (Census Bureau and HUD via FRED): the total, single-family and five-or-more-unit homes, checked for range, months in a row, one-month and one-year moves (real shocks like 2009 are allowed), the parts never exceeding the total and the single-family share; there is no exact parts-add-up check (the two-to-four-unit series is calculated from the other two). No key. A failure says so and shows nothing."""
        return ok(await housing_starts.overview())

    @app.get("/api/macro/industrial-production")
    async def macro_industrial_production():
        """US industrial production, monthly seasonally adjusted index with 2017 = 100 (Board of Governors of the Federal Reserve System, release G.17, via FRED): the total, manufacturing, mining and electric and gas utilities, and capacity utilization, checked for range, months in a row, one-month and one-year moves (real shocks like 2020 are allowed), the total's change lying between those of its three groups, and the capacity implied by output and utilization moving slowly. The newest month is an estimate that is revised later. Describes what already happened: not a signal or a forecast."""
        return ok(await industrial_production.overview())

    @app.get("/api/macro/euro-money-supply")
    async def macro_euro_money_supply():
        """Euro-area money supply, monthly, adjusted for working days and the season (ECB Data Portal, the monetary aggregates from the balance sheets of euro-area monetary financial institutions): M3, M2 and M1 in euro at the end of the month, the ECB's own annual growth rates, and what M3 is made of, checked for units, months in a row, range, one-month moves (real shocks like 2020 are allowed), four sums that hold to the million euro in the ECB's own arithmetic, and the published growth staying near the growth of the amounts. The newest month is provisional and revised later. Describes what already happened: not a signal or a forecast."""
        return ok(await euro_money_supply.overview())

    @app.get("/api/macro/euro-inflation")
    async def macro_euro_inflation():
        """Euro-area consumer prices (HICP, compiled by Eurostat and published on the ECB Data Portal), monthly: the headline annual rate, core, the five parts of the basket with their shares and annual rates, and about how many points of the headline each contributes, checked for units, months in a row, range, one-month moves, the basket weights, the headline lying between its parts and core between goods and services, and two checks that are Eurostat's own arithmetic (the all-items index follows from its parts and weights; each published rate matches its index). The newest month is an early (flash) estimate until the final figure replaces it. Describes what already happened: not a signal or a forecast."""
        return ok(await euro_inflation.overview())

    @app.get("/api/macro/euro-unemployment")
    async def macro_euro_unemployment():
        """Euro-area unemployment (the European Labour Force Survey, compiled by Eurostat and published on the ECB Data Portal; euro area of 20 countries, fixed composition, seasonally adjusted), monthly: the rate for everybody aged 15 to 74 with its change over a month, three months and a year, women, men, the under 25 and the 25 to 74, the number of unemployed persons, checked for units, months in a row, ranges, one-month moves, the rate for everybody lying between its parts, and three checks that are Eurostat's own arithmetic (the persons add up, the labour force implied by the parts agrees). Describes what already happened: not a signal or a forecast."""
        return ok(await euro_unemployment.overview())

    @app.get("/api/macro/euro-stress")
    async def macro_euro_stress():
        """Euro-area financial stress (the ECB's New Composite Indicator of Systemic Stress, published on the ECB Data Portal; euro area of changing composition), daily: the index between 0 and 1 with its change over a week and a month, how it compares with the past ten years, the contribution of each of its five market segments and of the correlation between them, checked for units, holes, range, one-day moves, the signs of the contributions (properties) and one check that is the ECB's own arithmetic (the contributions add up to the index). Describes stress that already happened: not a signal or a forecast."""
        return ok(await euro_stress.overview())

    @app.get("/api/macro/euro-yields")
    async def macro_euro_yields():
        """Euro-area government bond yields (the ECB's yield curve for AAA-rated euro-area government bonds, a Svensson curve fitted every business day and published on the ECB Data Portal), daily: the 3-month, 1-, 2-, 5-, 10- and 30-year spot rates with their change over a week and a month, the ECB's spreads of the 10-year rate over the shorter ones, where the 10-year rate sits among the past ten years, checked for units, holes, ranges, one-day moves and the model parameters (plain checks) and for two pieces of the ECB's own arithmetic (the spreads are differences of the rates, and the rates follow from the published curve parameters). Describes yields that already happened: not a signal or a forecast."""
        return ok(await euro_yields.overview())

    @app.get("/api/macro/euro-gdp")
    async def macro_euro_gdp():
        """Euro-area GDP (Eurostat's quarterly national accounts for the euro area of 21 countries, seasonally adjusted, published on the ECB Data Portal): real growth on the previous quarter and on a year earlier for the newest quarter with where it sits among the past ten years and the last six quarters, and, for the newest quarter with a breakdown, nominal GDP, domestic demand, exports and imports with their contributions to growth. Calculated figures are labelled as the ECB's own arithmetic; a failed check shows nothing. Demo mode shows nothing."""
        return ok(await euro_gdp.overview())

    @app.get("/api/macro/euro-lending")
    async def macro_euro_lending():
        """Euro-area bank lending (the ECB's loans of euro-area banks to firms and households, adjusted for loan sales and securitisation, seasonally adjusted, monthly, from the ECB Data Portal): annual growth, amounts outstanding and the month's net lending, households by purpose and firms by maturity, with the source's own arithmetic checked. Describes what already happened; not a signal or a forecast."""
        return ok(await euro_lending.overview())

    @app.get("/api/macro/euro-bank-rates")
    async def macro_euro_bank_rates():
        """Euro-area bank interest rates (what euro-area banks charge on new loans to firms and households and pay on new deposits, monthly, with the ECB's composite cost of borrowing, from the ECB Data Portal): the rates, their changes, the new business volumes and a ten-year comparison, with the source's own arithmetic checked. Describes what already happened; not a signal or a forecast."""
        return ok(await euro_bank_rates.overview())

    @app.get("/api/macro/euro-stock-rates")
    async def macro_euro_stock_rates():
        """Euro-area bank interest rates on EXISTING loans and deposits (ECB Data Portal, MIR dataflow, outstanding amounts): the average rate on loans to firms and households (all, for house purchase, for consumption and other purposes, by original maturity) and on deposits with an agreed maturity, with the ECB's split of each month's change into a rate part and a weight part. Official, dated, with its checks; describes what already happened, not a signal."""
        return ok(await euro_stock_rates.overview())

    @app.get("/api/macro/euro-employment")
    async def macro_euro_employment():
        """Euro-area employment and productivity (Eurostat's quarterly national accounts for the euro area of 21 countries, seasonally adjusted, published on the ECB Data Portal): people in work and hours worked, by activity and by employees and self-employed, and labour productivity per person and per hour. Checked against Eurostat's own sums and the ECB's own arithmetic; a failing check shows nothing."""
        return ok(await euro_employment.overview())

    @app.get("/api/macro/jolts")
    async def macro_jolts():
        """US job openings and labour turnover (Bureau of Labor Statistics JOLTS, with payroll employment and unemployed persons, via FRED): openings, hires and separations with their rates, openings per unemployed person and the range of the last ten years, checked for months in a row, ranges, the sum of separations and each rate against its level; shows nothing if a check fails. Describes what already happened: not a signal or a forecast."""
        return ok(await jolts.overview())

    @app.get("/api/macro/jolts-industries")
    async def macro_jolts_industries():
        """US job openings by industry (Bureau of Labor Statistics JOLTS via FRED): total nonfarm, private and government openings and the openings of seven groups of industries with their parts (health care, retail, state and local government, durable and nondurable manufacturing, accommodation and food, arts), each with its share of all openings, its change on a year ago and where it stands among the last ten years, four remainders worked out by subtraction and marked as such, checked for months in a row, ranges, three sums and the parts inside their wholes; nothing is shown when a check fails."""
        return ok(await jolts_industries.overview())

    @app.get("/api/macro/jolts-flows")
    async def macro_jolts_flows():
        """US hires, quits and layoffs by industry (Bureau of Labor Statistics JOLTS via FRED, 33 monthly series): total nonfarm hires, quits, layoffs, other separations and total separations with the net of the month (hires minus separations), the same for the private sector and government, and hires, quits and total separations of six private industries with the rest of the private sector worked out by subtraction and marked as such, each with its change on a year ago; checked for months in a row, ranges, the eight sums of the survey's own arithmetic, quits inside separations and the six industries inside private; nothing is shown when a check fails."""
        return ok(await jolts_flows.overview())

    @app.get("/api/macro/us-inventories")
    async def macro_us_inventories():
        """US business inventories and sales (US Census Bureau, Manufacturing and Trade Inventories and Sales via FRED, 12 monthly series): total inventories, sales and the inventories-to-sales ratio, and the same for manufacturers, merchant wholesalers and retailers; the totals are checked against the three kinds and every ratio against its inventories over its sales."""
        return ok(await us_inventories.overview())

    @app.get("/api/macro/us-consumer-credit")
    async def macro_us_consumer_credit():
        """US consumer credit (Board of Governors of the Federal Reserve System, G.19 Consumer Credit via FRED, 3 monthly series): total consumer credit owed at the end of the month, split into revolving credit (mostly credit cards) and nonrevolving credit (mostly car and student loans), with the change on the month and on a year ago and the last six months; checked for months in a row, ranges and that the total equals the two kinds to the rounding of the figures; nothing is shown when a check fails."""
        return ok(await us_consumer_credit.overview())

    @app.get("/api/macro/us-bank-loans")
    async def macro_us_bank_loans():
        """US bank loans and leases (Board of Governors of the Federal Reserve System, H.8 Assets and Liabilities of Commercial Banks via FRED, 14 weekly series): the loans and leases of all US commercial banks on a Wednesday in all and by kind (business, real estate, consumer, all other), real estate split into residential and commercial, loans to nondepository financial institutions, the change on the week and on a year ago and the last six weeks; checked for weeks in a row, ranges, four sums to the rounding of the figures and that the loans to nondepository institutions are within the other loans; nothing is shown when a check fails."""
        return ok(await us_bank_loans.overview())

    @app.get("/api/macro/us-bank-balance-sheet")
    async def macro_us_bank_balance_sheet():
        """US bank balance sheet (Board of Governors of the Federal Reserve System, H.8 Assets and Liabilities of Commercial Banks via FRED, 10 weekly series): what all US commercial banks held (total assets: loans and leases, securities, cash assets, everything else) and owed (deposits, everything else) on a Wednesday, the residual, the changes on a week and on a year, where the growth of total assets stands against its last ten years, the last six weeks and what was checked (three sums, two orders). Describes what already happened: not a signal or a forecast."""
        return ok(await us_bank_balance.overview())

    @app.get("/api/macro/us-building-permits")
    async def macro_us_building_permits():
        """US building permits (U.S. Census Bureau and U.S. Department of Housing and Urban Development, New Residential Construction via FRED, 8 monthly series): how many new homes local governments gave permission to build in a month, as a seasonally adjusted annual rate in thousands of homes, split by type (single-family, 2-4 units, 5 or more) and by Census region, the changes on a month and on a year, where the growth of the total on a year earlier stands among the last ten years and the last six months, with the checks it passed (the months in a row, the ranges, and two sums that hold exactly). Research only: a plain record of permission already given, no forecast."""
        return ok(await us_building_permits.overview())

    @app.get("/api/macro/us-construction")
    async def macro_us_construction():
        """US construction spending (U.S. Census Bureau, Construction Spending, the value of construction put in place, via FRED, 9 monthly series): how much construction work was done in a month, as a seasonally adjusted annual rate in millions of dollars, split by who pays (private, public), by use (residential, nonresidential) and into the four parts of that table, the changes on a month and on a year, where the growth of the total on a year earlier stands among the last ten years and the last six months, with the checks it passed (the months in a row, the ranges, and six sums that hold to within the rounding). Research only: a plain record of work already done, no forecast."""
        return ok(await us_construction.overview())

    @app.get("/api/macro/us-new-home-sales")
    async def macro_us_new_home_sales():
        """US new home sales (U.S. Census Bureau and U.S. Department of Housing and Urban Development, New Residential Sales via FRED, 9 monthly series): sales of new one-family houses in thousands at a seasonally adjusted annual rate, in total and for the four regions, the homes for sale at the month end, the months' supply and the median and average prices, with three checks (the four regions add up to the total, the months' supply is 12 times the homes for sale over the sales, the average price is not below the median). Research only: it describes houses already sold."""
        return ok(await us_new_homes.overview())

    @app.get("/api/macro/us-jobs")
    async def macro_us_jobs():
        """The US jobs report (Bureau of Labor Statistics Employment Situation via FRED): payrolls and their monthly change, private and government, the unemployment rate, participation and the employment-population ratio with the ten-year range of the unemployment rate, checked for months in a row, ranges, the sums of payrolls and of the labour force and each rate against its levels; shows nothing if a check fails. Describes what already happened: not a signal or a forecast."""
        return ok(await us_jobs.overview())

    @app.get("/api/macro/us-gdp")
    async def macro_us_gdp():
        """US gross domestic product by component (Bureau of Economic Analysis National Income and Product Accounts via FRED): GDP in billions of dollars at an annual rate with consumer spending, private investment, government spending and net exports, real growth and each part's contribution to it, checked for quarters in a row, ranges, the four parts against GDP, exports minus imports against net exports and the contributions against growth; shows nothing if a check fails. Describes what already happened: not a signal or a forecast."""
        return ok(await us_gdp.overview())

    @app.get("/api/macro/us-household")
    async def macro_us_household():
        """US household income, spending and saving (Bureau of Economic Analysis Personal Income and Outlays and the GDP release via FRED): personal income, taxes, disposable income, outlays (consumer spending, interest, the rest), saving and the saving rate, monthly, with the quarterly split of consumer spending into durable goods, nondurable goods and services; the whole record since 1959 is checked for months in a row, ranges, the accounting sums and the quarter against the average of its months. Describes what already happened; not a signal or a forecast. Unavailable (never a guess) if any series fails a check."""
        return ok(await us_household.overview())

    @app.get("/api/macro/us-real-spending")
    async def macro_us_real_spending():
        """US real consumer spending (Bureau of Economic Analysis Personal Income and Outlays via FRED): spending with the effect of price changes taken out (chained 2017 dollars), spending in the dollars of the day and the PCE price index with and without food and energy, with the year's change split into more goods and services bought and higher prices, the last six months, and the checks the figures passed (ranges, monthly moves, real spending times prices against spending in dollars). Free, no key; research only."""
        return ok(await us_real_spending.overview())

    @app.get("/api/macro/us-trade")
    async def macro_us_trade():
        """US international trade in goods and services (Census Bureau and Bureau of Economic Analysis via FRED): exports, imports and the balance for the total, for goods and for services, the change in the balance over a month and a year, the last six months and the checks the figures passed (six sums, each within 1.5 million dollars). Read-only research data, never a trading signal."""
        return ok(await us_trade.overview())

    @app.get("/api/macro/bank-reserves")
    async def macro_bank_reserves():
        """Bank reserves, currency and the monetary base (Federal Reserve Board H.4.1 weekly and H.6 monthly via FRED): checked for dates, ranges, one-week and one-month moves (real shocks like 2020 are allowed), the identity base = currency + reserves, and the weekly figures against the monthly base. Describes what already happened; not a signal or a forecast."""
        return ok(await bank_reserves.overview())

    @app.get("/api/macro/ecb-rates")
    async def macro_ecb_rates():
        """The European Central Bank's three key interest rates (deposit, main refinancing, marginal lending) and the euro short-term rate (ECB Data Portal): checked for days in a row, steps of 0.05, range, one-day moves, the order of the three rates and that the market rate sits near the deposit rate. Describes what the rates are and were; not a signal or a forecast."""
        return ok(await ecb_rates.overview())

    @app.get("/api/macro/jobless-claims")
    async def macro_jobless_claims():
        """US weekly jobless claims (initial and continuing, seasonally adjusted, Thursdays, via FRED): checked against the Labor Department's own four-week average. Describes what already happened; not a signal or a forecast."""
        return ok(await jobless_claims.overview())

    @app.get("/api/macro/real-yields")
    async def macro_real_yields():
        """US Treasury real (TIPS) yields and breakeven inflation at 5 to 30 years, from the Treasury's own daily curves. Describes what already happened; not a forecast of inflation or prices."""
        return ok(await real_yields.overview())

    @app.get("/api/macro/outlays")
    async def macro_outlays():
        """Where US federal money goes: net outlays by purpose, receipts and the deficit, latest month and fiscal year so far versus last year (Monthly Treasury Statement). Checked against the source's own totals; describes what already happened, not a signal."""
        return ok(await outlays.overview())

    @app.get("/api/macro/receipts")
    async def macro_receipts():
        """Where US federal revenue comes from: the seven receipt categories, latest month and fiscal year so far versus last year (Monthly Treasury Statement). Checked against the source's own total; describes what already happened, not a signal."""
        return ok(await receipts.overview())

    @app.get("/api/macro/customs")
    async def macro_customs():
        """US customs duties (tariff revenue): collected, refunded and net, by month and fiscal year so far (Monthly Treasury Statement). Checked against the source's own arithmetic; describes what already happened, not a signal."""
        return ok(await customs.overview())

    @app.get("/api/macro/dealers")
    async def macro_dealers():
        """Primary dealers' net position in US Treasuries (New York Fed), weekly. Describes what already happened; not a signal."""
        return ok(await dealers.overview())

    @app.get("/api/macro/budget")
    async def macro_budget():
        """US federal receipts, outlays and deficit from the Monthly Treasury Statement. Describes what already happened; not a signal."""
        return ok(await budget.overview())

    @app.get("/api/macro/auctions")
    async def macro_auctions():
        """US Treasury note and bond auction results (yield and bid-to-cover by term). Describes finished auctions; not a signal."""
        return ok(await auctions.overview())

    @app.get("/api/macro/tga")
    async def macro_tga():
        """US Treasury General Account (the government's cash balance at the Fed), from the Daily Treasury Statement. Describes where cash sits; not a signal."""
        return ok(await tga.overview())

    @app.get("/api/macro/fedops")
    async def macro_fedops():
        """Fed repo and reverse repo operations (New York Fed): cash parked at the Fed and cash the Fed lent. Describes money-market plumbing; not a signal."""
        return ok(await fed_ops.overview())

    @app.get("/api/macro/world")
    async def macro_world():
        """Yearly growth, inflation and unemployment for the US and five other big economies (World Bank). Context, not a forecast; figures arrive months late and are revised."""
        return ok(await world_bank.overview())

    @app.get("/api/macro/fx")
    async def macro_fx():
        """How the US dollar is doing against the major currencies (ECB euro reference rates, daily, official). For information, not tradable quotes."""
        return ok(await ecb_fx.overview())

    @app.get("/api/macro/treasury")
    async def macro_treasury():
        """Full US Treasury yield curve (1 month to 30 years) with 2s10s / 3m10y spreads, plus total public debt. Official free data, with dates."""
        return ok(await treasury.overview())

    macro_brief = MacroBriefService(macro, fedwatch, news, demo, sofr=NyFedSofr(demo=demo))

    @app.get("/api/macro/brief")
    async def macro_brief_route():
        return ok(await macro_brief.overview())      # works without a FRED key: it then says the indicators are unavailable instead of failing

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

    stock_research = StockResearch(EdgarClient(db), fundamentals, news, demo)

    discover = DiscoverService(db, bars, stock_research.edgar, demo)
    fundamental_research = FundamentalResearch(stock_research.edgar, fundamentals, demo)
    discovery_store = DiscoveryStore(db)
    listings_service = ListingsService(db, NasdaqIpoFeed(db), bars, stock_research.edgar, demo)

    async def _study(symbol, price, price_time, price_source, now):
        return await fundamental_research.filing_research(symbol, price, price_time, price_source, now)
    new_to_me = NewToMe(db, discovery_store, _study, None, demo, watchlist=lambda: [r["symbol"] for r in db.q("SELECT symbol FROM signal_watchlist WHERE asset_type='stock'")])
    narratives = NarrativeService(db, bars, news, demo)

    @app.get("/api/discover/narrative")
    async def discover_narrative(refresh: bool = False):
        """Today's market narrative (Quantum, Nuclear, Robotics ...), found by fixed rules from price strength, breadth, volume and headlines. Saved per UTC day."""
        return ok(await narratives.today(refresh))

    @app.get("/api/discover/narrative/history")
    async def discover_narrative_history(limit: int = 30):
        return ok({"items": narratives.history(max(1, min(limit, 100))), "method": narratives.method()})


    @app.get("/api/discover/shortlist")
    async def discover_shortlist(refresh: bool = False):
        return ok(await discover.shortlist(refresh))

    @app.get("/api/discover/ranked")
    async def discover_ranked(sector: str | None = None, min_score: float = 0, max_pe: float | None = None, min_growth: float | None = None, limit: int = 25):
        return ok(discover.ranked(sector, min_score, max_pe, min_growth, limit))

    @app.get("/api/discover/method")
    async def discover_method():
        return ok(discover.method())

    event_calendar = EventCalendar(db, demo, client=calendar_client)

    @app.get("/api/calendar")
    async def calendar_route(days: int = 14, start: str | None = None, kinds: str = "", scope: str = "major", symbols: str = ""):
        """Earnings, economic data, rate decisions, dividends and Treasury auctions in one list."""
        try:
            st = date.fromisoformat(start) if start else None
        except ValueError:
            raise ApiError("INVALID_DATE", "start must look like 2026-11-10", 422)
        names = [x.strip().upper() for x in symbols.split(",") if x.strip()][:40]
        return ok(await event_calendar.overview(st, days, [k.strip() for k in kinds.split(",") if k.strip()] or None, scope, names))

    lab = LabService(BtcData(db), demo)
    fear_greed = FearGreed(demo=demo)
    cftc_btc = CftcBitcoin(demo=demo)
    stablecoins = Stablecoins(demo=demo)
    onchain = OnChain(demo=demo)
    cg_global = CoinGeckoGlobal(demo=demo)

    @app.get("/api/btc/market")
    async def btc_market():
        """Whole crypto market (CoinGecko): total value, 24h change and volume, Bitcoin and Ether share, stablecoin share. Descriptive, not a signal."""
        return ok(await cg_global.overview())

    @app.get("/api/btc/network")
    async def btc_network():
        """Bitcoin network health (mempool.space): fees, mempool size, difficulty cycle and hashrate. Each section fails on its own; not a price signal."""
        return ok(await onchain.overview())

    @app.get("/api/btc/stablecoins")
    async def btc_stablecoins():
        """US-dollar stablecoin supply (DefiLlama): the cash inside crypto, with changes and the biggest issuers. A liquidity gauge, not a price signal."""
        return ok(await stablecoins.overview())

    @app.get("/api/btc/positioning")
    async def btc_positioning():
        """Who holds CME Bitcoin futures (CFTC Commitments of Traders): leveraged funds, asset managers, dealers. Weekly, official, dated; not a signal."""
        return ok(await cftc_btc.overview())

    @app.get("/api/btc/sentiment")
    async def btc_sentiment():
        """Crypto Fear & Greed index (alternative.me), labelled with its source and date. A mood gauge, not a signal."""
        return ok(await fear_greed.overview())


    @app.get("/api/btclab/strategies")
    async def btclab_strategies():
        return ok({"strategies": lab.listing(), **lab.status()})

    @app.post("/api/btclab/data/refresh")
    async def btclab_refresh():
        try:
            return ok(await lab.refresh(["1d", "1h"]))
        except LabError as e:
            raise ApiError("DATA_UNAVAILABLE", str(e), 503)

    @app.get("/api/btclab/tracker")
    async def btclab_tracker():
        """Strategies added by the research loop: frozen backtest plus the forward record since each was added. Research only."""
        try:
            return ok(await lab.tracker())
        except LabError as e:
            raise ApiError("LAB_UNAVAILABLE", str(e), 503)

    @app.get("/api/btclab/experiments")
    async def btclab_experiments():
        """The pre-registered strategy experiments and how each ended (a frozen ledger, never recomputed). Research only: nothing here is advice and nothing places a trade."""
        import json as _json
        from pathlib import Path as _P
        entries = _json.loads((_P(__file__).parent / "btclab" / "experiments_ledger.json").read_text())["entries"]
        passed = sum(1 for e in entries if e["verdict"] == "passed")
        return ok({"entries": entries, "tested": len(entries), "passed": passed,
                   "note": "Each rule and pass bar was written down before it was run, then run once and never adjusted. A pass would only mean a candidate to follow on new data for 60 days, never 'profitable'. None has passed yet."})

    @app.get("/api/btcquant/paper")
    async def btcquant_paper():
        """The paper-trading lab: the latest daily dashboard in plain words and the last trades as the ledger recorded them on signal. Simulated accounts only; nothing here can place an order."""
        from .btcquant import view as _view
        return ok(_view.paper_view())

    @app.post("/api/btclab/run")
    async def btclab_run(b: LabRunIn):
        try:
            res = await lab.run(b)
        except LabError as e:
            raise ApiError("LAB_UNAVAILABLE", str(e), 503)
        db.audit("user", "btclab_run", {"strategies": b.strategies, "timeframe": b.timeframe, "market": b.market, "leverage": b.leverage})
        return ok(res)

    @app.post("/api/btclab/agent")
    async def btclab_agent(b: LabAgentIn):
        """Five-year stress test, find where the rule loses money, apply a fix from a fixed menu, rerun. Research only."""
        try:
            res = await lab.agent(b, db)
        except LabError as e:
            raise ApiError("LAB_UNAVAILABLE", str(e), 503)
        db.audit("user", "btclab_agent", {"strategies": b.strategies, "rounds": b.rounds})
        return ok(res)

    @app.get("/api/btclab/agent/history")
    async def btclab_agent_history(strategy: str = "", limit: int = 20):
        return ok({"items": lab.agent_history(db, strategy or None, max(1, min(limit, 100)))})

    @app.get("/api/stocks/earnings")
    async def stocks_earnings(symbols: str = "", days: int = 30):
        """Next earnings dates for the symbols asked about (default: the equities on the watchlist)."""
        names = [x.strip().upper() for x in symbols.split(",") if x.strip()][:40]
        insts = []
        for n in names:
            inst = I.resolve(n)
            if inst is not None and inst.asset_class == "equity":
                insts.append(inst)
        if not names:
            insts = [i for i in (I.resolve(r["symbol"]) for r in db.q("SELECT symbol FROM signal_watchlist WHERE asset_type='stock' ORDER BY position")) if i is not None and i.asset_class == "equity"][:40]
        return ok(await stock_research.earnings_calendar(insts, max(1, min(days, 120))))

    @app.get("/api/stocks/filings")
    async def stocks_filings(symbols: str = "", forms: str = "", limit: int = 40, days: int = 365):
        """Latest SEC filings (10-K, 10-Q, 8-K, insider Form 4, 5% holders, offerings...) for the symbols asked about, default the watchlist's stocks."""
        names = [x.strip().upper() for x in symbols.split(",") if x.strip()][:25]
        insts = [i for i in (I.resolve(n) for n in names) if i is not None and i.asset_class == "equity"]
        if not names:
            insts = [i for i in (I.resolve(r["symbol"]) for r in db.q("SELECT symbol FROM signal_watchlist WHERE asset_type='stock' ORDER BY position")) if i is not None and i.asset_class == "equity"][:25]
        want = [f.strip().upper() if f.strip().upper() != "SC13D" else "SC 13D" for f in forms.split(",") if f.strip()] or None
        return ok(await stock_research.filings_feed(insts, want, max(1, min(limit, 200)), max(1, min(days, 1500))))

    # --- fundamental discovery: newly listed companies, new-to-me candidates, my own states and notes ---
    @app.get("/api/discover/listings")
    async def discover_listings(days: int = 30):
        """Newly listed companies on NYSE and Nasdaq: upcoming deals and recent pricings, with confirmation and SEC verification where they could be checked."""
        return ok(listings_service.read(days))

    def _csv(v: str | None):
        items = [x.strip() for x in (v or "").split(",") if x.strip()]
        return items[:20] or None

    @app.get("/api/discover/candidates")
    async def discover_candidates(target: int = 5, sectors: str | None = None, countries: str | None = None, exchanges: str | None = None, min_market_cap: float | None = None,
                                  max_market_cap: float | None = None, min_dollar_volume: float | None = None, max_listing_age_years: int | None = None, min_listing_age_years: int | None = None):
        """New-to-me research candidates from the latest daily study, narrowed by my filters and by what I have already seen, saved or dismissed. Fewer are shown when evidence is weak."""
        f = {"sectors": _csv(sectors), "countries": _csv(countries), "exchanges": _csv(exchanges), "min_market_cap": 0 if min_market_cap is None else max(0.0, min_market_cap),
             "max_market_cap": float("inf") if max_market_cap is None else max_market_cap, "min_dollar_volume": 0 if min_dollar_volume is None else max(0.0, min_dollar_volume),
             "max_listing_age_years": max_listing_age_years, "min_listing_age_years": min_listing_age_years}
        return ok(new_to_me.read(f, max(1, min(target, 20))))

    class StateIn(BaseModel):
        model_config = ConfigDict(extra="forbid")
        symbol: str = Field(min_length=1, max_length=10, pattern=r"^[A-Za-z]{1,5}([-/][A-Za-z])?$")
        state: str
        on: bool = True

    @app.post("/api/discover/state")
    async def discover_state(body: StateIn):
        if body.state not in DISC_STATES:
            raise ApiError("BAD_STATE", f"state must be one of {', '.join(DISC_STATES)}", 422)
        return ok(discovery_store.set_state(body.symbol, body.state, body.on))

    @app.get("/api/discover/state/{symbol}")
    async def discover_state_get(symbol: str):
        return ok({"state": discovery_store.get(symbol), "notes": discovery_store.notes(symbol), "last_review": discovery_store.last_review(symbol)})

    class NoteIn(BaseModel):
        model_config = ConfigDict(extra="forbid")
        body: str = Field(min_length=1, max_length=4000)

    @app.post("/api/research/{token}/notes")
    async def research_note_add(token: str, body: NoteIn):
        inst = I.resolve(token)
        if inst is None or inst.asset_class != "equity":
            raise ApiError("UNKNOWN_INSTRUMENT", f"unknown stock '{token[:40]}'", 404)
        try:
            return ok(discovery_store.add_note(inst.symbol, body.body))
        except ValueError as e:
            raise ApiError("BAD_NOTE", str(e), 422)

    @app.delete("/api/research/notes/{note_id}")
    async def research_note_delete(note_id: int):
        if not discovery_store.delete_note(note_id):
            raise ApiError("NOT_FOUND", "no such note", 404)
        return ok({"deleted": note_id})

    class BriefIn(BaseModel):
        model_config = ConfigDict(extra="forbid")
        detail: str = Field("concise", pattern=r"^(concise|detailed)$")
        question: str | None = Field(None, max_length=2000)
        include_notes: bool = False
        include_position: bool = False
        shares: float | None = Field(None, gt=0, le=1e10)
        buy_price: float | None = Field(None, gt=0, le=1e8)

    @app.post("/api/research/{token}/brief")
    async def research_brief(token: str, body: BriefIn):
        """A paste-ready research brief for ChatGPT, built locally from research the app already holds: no AI call, no key. My notes and position are included only when switched on."""
        inst = I.resolve(token)
        if inst is None or inst.asset_class != "equity":
            raise ApiError("UNKNOWN_INSTRUMENT", f"unknown stock '{token[:40]}'", 404)
        r = await fundamental_research.research(inst)
        if not r.get("available"):
            raise ApiError("NOT_AVAILABLE", r.get("reason") or "there is no research to export for this company right now", 409)
        run = new_to_me.latest_run()
        disc = next((p for p in (run or {}).get("pool", []) if p["symbol"] == inst.symbol), None)
        try:
            stories = [{"title": s["title"], "link": s.get("link"), "feed": s["feed"], "published": s.get("published")} for s in news.items(symbol=inst.symbol, hours=24 * 14, limit=8)["items"]]
        except Exception:  # noqa: BLE001  headlines are optional
            stories = []
        notes = discovery_store.notes(inst.symbol) if body.include_notes else None
        pos = {"shares": body.shares, "buy_price": body.buy_price} if body.include_position else None
        return ok(build_brief(r, detail=body.detail, question=body.question, discovery=disc, filings=r.get("filings"), news=stories, exchange=inst.exchange, notes=notes, position=pos))

    @app.post("/api/research/{token}/review")
    async def research_review(token: str):
        """Mark a company as reviewed now: saves the figures I looked at so the next visit can show what changed. Needs the filing analysis to be available."""
        inst = I.resolve(token)
        if inst is None or inst.asset_class != "equity":
            raise ApiError("UNKNOWN_INSTRUMENT", f"unknown stock '{token[:40]}'", 404)
        r = await fundamental_research.research(inst)
        if not r.get("available"):
            raise ApiError("NOT_AVAILABLE", r.get("reason") or "the research is not available right now, so there is nothing to record", 409)
        return ok({"snapshot": discovery_store.record_review(inst.symbol, r)})

    @app.get("/api/research/{token}/changes")
    async def research_changes(token: str):
        inst = I.resolve(token)
        if inst is None or inst.asset_class != "equity":
            raise ApiError("UNKNOWN_INSTRUMENT", f"unknown stock '{token[:40]}'", 404)
        r = await fundamental_research.research(inst)
        if not r.get("available"):
            return ok({"has_review": discovery_store.last_review(inst.symbol) is not None, "available": False, "reason": r.get("reason")})
        return ok({**discovery_store.changes_since_review(inst.symbol, r), "available": True})

    @app.get("/api/research/{token}")
    async def fundamental_research_route(token: str, discount_rate_pct: float | None = None, terminal_growth_pct: float | None = None, band_pct: float | None = None):
        """Revenue-first fundamental research from SEC filings: revenue, quality, Rule of 40, valuation under stated assumptions. Policy values outside their limits are ignored."""
        inst = I.resolve(token)
        if inst is None:
            raise ApiError("UNKNOWN_INSTRUMENT", f"unknown instrument '{token[:40]}'", 404)
        if inst.asset_class != "equity":
            raise ApiError("NOT_APPLICABLE", f"fundamental research applies to US stocks, not {inst.asset_class} instruments", 422)
        discovery_store.set_state(inst.symbol, "opened")
        out = await fundamental_research.research(inst, {"discount_rate_pct": discount_rate_pct, "terminal_growth_pct": terminal_growth_pct, "band_pct": band_pct})
        out["my_state"] = {"state": discovery_store.get(inst.symbol), "notes": discovery_store.notes(inst.symbol), "last_review": discovery_store.last_review(inst.symbol)}
        return ok(out)

    @app.get("/api/stocks/{token}/research")
    async def stocks_research(token: str):
        inst = I.resolve(token)
        if inst is None:
            raise ApiError("UNKNOWN_INSTRUMENT", f"unknown instrument '{token[:40]}'", 404)
        if inst.asset_class != "equity":
            raise ApiError("NOT_APPLICABLE", f"stock research applies to US stocks, not {inst.asset_class} instruments", 422)
        return ok(await stock_research.research(inst))

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

    # --- operations: the shared scheduler -----------------------------------------------------------------------------------------------
    def sched_notify(severity: str, message: str) -> None:
        if tg is None:
            return
        try:
            asyncio.get_running_loop().create_task(tg.send_text(f"ATLAS {severity.upper()}: {message}"))
        except RuntimeError:
            pass                                                         # no running loop (a synchronous caller): the event is still stored and shown on the dashboard

    scheduler = Scheduler(db, notify=sched_notify)
    register_default_jobs(scheduler, {"db": db, "news": news, "stock_research": stock_research, "resolve": I.resolve, "btc_data": lab.data, "demo": demo,
                                      "listings": listings_service, "new_to_me": new_to_me,
                                      "extras": {"fed_rates": fed_rates, "fed_holdings": fed_holdings, "debt_mix": debt_mix, "debt_rates": debt_rates, "budget": budget, "interest": interest, "buybacks": buybacks, "bill_auctions": bill_auctions, "borrowing": borrowing, "dealers": dealers, "futures_positioning": futures_positioning, "customs": customs, "receipts": receipts, "outlays": outlays, "real_yields": real_yields, "fin_conditions": fin_conditions, "jobless_claims": jobless_claims, "oil_prices": oil_prices, "gasoline_prices": gasoline_prices, "natural_gas": natural_gas, "money_supply": money_supply, "retail_sales": retail_sales, "housing_starts": housing_starts, "industrial_production": industrial_production, "euro_money_supply": euro_money_supply, "euro_inflation": euro_inflation, "euro_unemployment": euro_unemployment, "euro_stress": euro_stress, "euro_yields": euro_yields, "euro_gdp": euro_gdp, "euro_lending": euro_lending, "euro_bank_rates": euro_bank_rates, "euro_stock_rates": euro_stock_rates, "euro_employment": euro_employment, "jolts": jolts, "jolts_industries": jolts_industries, "jolts_flows": jolts_flows, "us_inventories": us_inventories, "us_consumer_credit": us_consumer_credit, "us_bank_loans": us_bank_loans, "us_bank_balance": us_bank_balance, "us_building_permits": us_building_permits, "us_construction": us_construction, "us_new_homes": us_new_homes, "us_jobs": us_jobs, "us_gdp": us_gdp, "us_household": us_household, "us_real_spending": us_real_spending, "us_trade": us_trade, "bank_reserves": bank_reserves, "ecb_rates": ecb_rates, "commodity_positioning": commodity_positioning, "currency_positioning": currency_positioning, "agri_positioning": agri_positioning, "auctions": auctions, "tga": tga, "fed_ops": fed_ops, "macro_brief": macro_brief, "treasury": treasury, "ecb_fx": ecb_fx, "world_bank": world_bank, "fear_greed": fear_greed,
                                                 "stablecoins": stablecoins, "onchain": onchain, "cg_global": cg_global, "cftc_btc": cftc_btc}})
    app.state.scheduler = scheduler

    class JobPatch(BaseModel):
        model_config = ConfigDict(extra="forbid")
        enabled: bool | None = None
        paused: bool | None = None
        priority: int | None = Field(None, ge=1, le=5)
        interval_market_s: int | None = Field(None, ge=30, le=7 * 86400)
        interval_off_s: int | None = Field(None, ge=30, le=7 * 86400)
        max_tokens: int | None = Field(None, ge=0, le=2_000_000)
        max_runtime_s: int | None = Field(None, ge=5, le=6 * 3600)
        max_experiments: int | None = Field(None, ge=0, le=10_000)

    class ClaudePatch(BaseModel):
        model_config = ConfigDict(extra="forbid")
        access: Literal["unknown", "api", "subscription", "claude_code"] | None = None
        model: str | None = Field(None, max_length=60)
        usage_telemetry: Literal["unknown", "per_request", "none"] | None = None
        price_in_per_mtok: float | None = Field(None, ge=0, le=1000)
        price_out_per_mtok: float | None = Field(None, ge=0, le=1000)
        daily_token_limit: int | None = Field(None, ge=0, le=100_000_000)
        daily_usd_limit: float | None = Field(None, ge=0, le=100_000)
        monthly_usd_limit: float | None = Field(None, ge=0, le=1_000_000)

    class SchedPatch(BaseModel):
        model_config = ConfigDict(extra="forbid")
        reserve_pct: float | None = Field(None, ge=0, le=90)
        max_concurrent: int | None = Field(None, ge=1, le=8)
        claude: ClaudePatch | None = None

    @app.get("/api/ops/overview")
    async def ops_overview():
        return ok(scheduler.overview())

    @app.post("/api/ops/jobs/{job_id}")
    async def ops_job_update(job_id: str, b: JobPatch):
        if scheduler.job(job_id) is None:
            raise ApiError("UNKNOWN_JOB", "no such job", 404)
        patch = {k: (int(v) if isinstance(v, bool) else v) for k, v in b.model_dump(exclude_none=True).items()}
        scheduler.update_job(job_id, **patch)
        return ok(scheduler.overview())

    @app.post("/api/ops/jobs/{job_id}/run")
    async def ops_job_run(job_id: str):
        if scheduler.job(job_id) is None:
            raise ApiError("UNKNOWN_JOB", "no such job", 404)
        if not scheduler.request_run(job_id):
            raise ApiError("STOPPED", "The emergency stop is on, so nothing can be run. Clear it first.", 409)
        if not run_sched:
            await scheduler.tick()                                         # no background scheduler in this process (demo or cloud web): run it now
        return ok(scheduler.overview())

    @app.post("/api/ops/pause")
    async def ops_pause():
        scheduler.set_global(paused=True)
        return ok(scheduler.overview())

    @app.post("/api/ops/resume")
    async def ops_resume():
        scheduler.set_global(paused=False)
        return ok(scheduler.overview())

    @app.post("/api/ops/emergency-stop")
    async def ops_stop():
        scheduler.emergency_stop(True)
        return ok(scheduler.overview())

    @app.post("/api/ops/emergency-clear")
    async def ops_clear():
        scheduler.emergency_stop(False)
        return ok(scheduler.overview())

    @app.post("/api/ops/settings")
    async def ops_settings(b: SchedPatch):
        patch = b.model_dump(exclude_none=True)
        scheduler.set_global(**patch)
        return ok(scheduler.overview())

    @app.post("/api/ops/dead-letters/{dl_id}/{action}")
    async def ops_dead_letter(dl_id: int, action: Literal["retry", "dismiss"]):
        if not scheduler.resolve_dead_letter(dl_id, retry=action == "retry"):
            raise ApiError("NOT_FOUND", "no such open dead letter", 404)
        return ok(scheduler.overview())


    return app
