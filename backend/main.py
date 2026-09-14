"""FastAPI app: JSON API under /api, static frontend at /."""
from __future__ import annotations

import csv
import io
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import DATA_DIR, FRONTEND_DIR, get_config, load_env_file, reload_config
from .db import Database, now_ts
from .evaluation import accuracy_report
from .providers import prices
from .refresh import RefreshManager
from .services import Snapshot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for noisy in ("yfinance", "urllib3", "peewee", "httpx", "httpx2"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_env_file()
    get_config()  # fail fast on invalid YAML
    app.state.db = Database(DATA_DIR / "radar.db")
    app.state.refresh = RefreshManager(app.state.db)
    app.state.refresh.trigger("startup", force=True)
    yield


app = FastAPI(title="AI Stock Radar", lifespan=lifespan)


def _snapshot(request: Request) -> Snapshot:
    return Snapshot(request.app.state.db, get_config(), now_ts())


def _prefs(request: Request) -> dict:
    db: Database = request.app.state.db
    return {
        "favorites": db.get_pref("favorites", []),
        "price_colors": db.get_pref("price_colors", "western"),
    }


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ── status & refresh ─────────────────────────────────────────────────────────
@app.get("/api/status")
def status(request: Request):
    return request.app.state.refresh.snapshot()


@app.post("/api/refresh")
def refresh(request: Request, reason: str = "manual"):
    started = request.app.state.refresh.trigger(reason)
    return {"started": started, "status": request.app.state.refresh.snapshot()}


# ── data ─────────────────────────────────────────────────────────────────────
@app.get("/api/dashboard")
def dashboard(request: Request):
    return {**_snapshot(request).dashboard(_prefs(request)), "prefs": _prefs(request)}


@app.get("/api/stocks/{ticker}")
def stock_detail(request: Request, ticker: str):
    cfg = get_config()
    stock = cfg.stock(ticker)
    if stock is None:
        raise HTTPException(404, f"{ticker} is not on the watchlist")
    detail = _snapshot(request).stock_detail(stock)
    detail["favorite"] = ticker in _prefs(request)["favorites"]
    return detail


@app.get("/api/stocks/{ticker}/history")
def stock_history(ticker: str, range: Literal["1W", "1M", "3M", "6M", "1Y", "5Y"] = "3M"):
    if get_config().stock(ticker) is None:
        raise HTTPException(404, f"{ticker} is not on the watchlist")
    try:
        points = prices.fetch_history(ticker, range)
    except Exception as e:
        raise HTTPException(502, f"Price history unavailable: {e}") from e
    return {"ticker": ticker, "range": range, "points": points}


@app.get("/api/news")
def news(request: Request, market: str | None = None, direction: str | None = None,
         scope: str | None = None, days: int | None = None):
    return _snapshot(request).news_hub(market=market or None, direction=direction or None,
                                       scope=scope or None, days=days)


@app.get("/api/supply-chain")
def supply_chain(request: Request):
    return _snapshot(request).supply_chain()


# ── preferences ──────────────────────────────────────────────────────────────
class PrefsUpdate(BaseModel):
    favorites: list[str] | None = None
    price_colors: Literal["western", "taiwan"] | None = None


@app.get("/api/prefs")
def get_prefs(request: Request):
    return _prefs(request)


@app.put("/api/prefs")
def put_prefs(request: Request, body: PrefsUpdate):
    db: Database = request.app.state.db
    if body.favorites is not None:
        known = {s.ticker for s in get_config().stocks}
        db.set_pref("favorites", list(dict.fromkeys(t for t in body.favorites if t in known)))
    if body.price_colors is not None:
        db.set_pref("price_colors", body.price_colors)
    return _prefs(request)


@app.post("/api/config/reload")
def config_reload(request: Request):
    try:
        cfg = reload_config()
    except Exception as e:
        raise HTTPException(400, f"Config invalid: {e}") from e
    request.app.state.refresh.trigger("config-reload", force=True)
    return {"stocks": len(cfg.stocks)}


@app.get("/api/settings")
def settings_view(request: Request):
    cfg = get_config()
    return {
        "settings": cfg.settings.model_dump(),
        "analysis": request.app.state.refresh.analysis_status(),
        "stock_count": {m: sum(s.market == m for s in cfg.stocks) for m in ("TW", "US")},
    }


# ── track record ─────────────────────────────────────────────────────────────
@app.get("/api/accuracy")
def accuracy(request: Request):
    return accuracy_report(request.app.state.db, get_config(), now_ts())


EXPORT_COLUMNS = [
    "ticker", "market", "day", "created_at_utc", "price", "predicted_price", "expected_return", "news_return",
    "valuation_return", "outlook", "engine", "algo_version", "article_ids", "horizon", "base_day", "base_close",
    "end_day", "end_close", "realized_return", "benchmark_return", "excess_return",
]


@app.get("/api/accuracy/export.csv")
def accuracy_export(request: Request):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for r in request.app.state.db.export_rows():
        r["created_at_utc"] = datetime.fromtimestamp(r["created_at"], tz=timezone.utc).isoformat()
        if r["realized_return"] is not None and r["benchmark_return"] is not None:
            r["excess_return"] = r["realized_return"] - r["benchmark_return"]
        writer.writerow(r)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="prediction-track-record.csv"'})


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
