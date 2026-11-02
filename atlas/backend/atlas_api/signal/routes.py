"""HTTP routes for Signal Mobile: /api/signal/*. Read-only research plus the saved watchlist. Nothing here can place an order."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .orchestrator import OrchestratorError
from .service import ERRORS, SignalError, SignalService


class AddIn(BaseModel):
    id: str = Field(min_length=3, max_length=80)


class OrderIn(BaseModel):
    ids: list[str] = Field(max_length=100)


class RefreshIn(BaseModel):
    agent: str = Field(max_length=20)


def register(app, signal: SignalService, ok) -> None:
    async def _err(_: Request, e):
        return JSONResponse({"ok": False, "error": {"code": e.code, "message": e.message}}, status_code=e.status)
    for exc in (*ERRORS, OrchestratorError):
        app.add_exception_handler(exc, _err)

    @app.get("/api/signal/meta")
    async def signal_meta():
        return ok(signal.meta())

    @app.get("/api/signal/search")
    async def signal_search(q: str = "", limit: int = 20):
        return ok(await signal.search(q[:60], limit))

    @app.get("/api/signal/watchlist")
    async def signal_watchlist():
        return ok(await signal.watchlist())

    @app.post("/api/signal/watchlist")
    async def signal_watchlist_add(b: AddIn):
        return ok(await signal.add(b.id))

    @app.put("/api/signal/watchlist/positions")
    async def signal_watchlist_positions(b: OrderIn):
        return ok(signal.reorder(b.ids))

    @app.delete("/api/signal/watchlist/{asset_id}")
    async def signal_watchlist_remove(asset_id: str):
        return ok(signal.remove(asset_id))

    @app.get("/api/signal/asset/{asset_id}")
    async def signal_asset(asset_id: str):
        return ok(await signal.asset_header(asset_id))

    @app.get("/api/signal/chart/{asset_id}")
    async def signal_chart(asset_id: str, range: str = "1M"):
        return ok(await signal.chart(asset_id, range))

    @app.get("/api/signal/research/{asset_id}")
    async def signal_research(asset_id: str, wait: float = 6.0):
        return ok(await signal.research(asset_id, wait))

    @app.post("/api/signal/research/{asset_id}/refresh")
    async def signal_refresh(asset_id: str, b: RefreshIn):
        return ok(await signal.refresh(asset_id, b.agent))
