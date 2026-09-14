"""Market data via yfinance: live quotes, price history, valuation fundamentals."""
from __future__ import annotations

import logging
import math
import threading
import time
from bisect import bisect_right
from datetime import datetime, timezone

import yfinance as yf

log = logging.getLogger(__name__)

RANGES = {
    "1W": ("5d", "30m"),
    "1M": ("1mo", "1d"),
    "3M": ("3mo", "1d"),
    "6M": ("6mo", "1d"),
    "1Y": ("1y", "1d"),
    "5Y": ("5y", "1wk"),
}

FUNDAMENTAL_KEYS = [
    "longName", "currency", "marketCap", "trailingPE", "forwardPE", "priceToSalesTrailing12Months",
    "trailingPegRatio", "pegRatio", "targetMeanPrice", "targetHighPrice", "targetLowPrice",
    "numberOfAnalystOpinions", "recommendationKey", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
    "revenueGrowth", "earningsGrowth", "grossMargins", "operatingMargins", "profitMargins",
    "dividendYield", "beta",
]

_cache: dict[tuple, tuple[float, object]] = {}
_cache_lock = threading.Lock()
HISTORY_TTL = 300


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _cached(key: tuple, ttl: float, fn):
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    value = fn()
    if value:
        with _cache_lock:
            _cache[key] = (time.time(), value)
    return value


def _epoch(value) -> int | None:
    """yfinance returns epoch ints or pandas Timestamps depending on version."""
    if value is None:
        return None
    return int(value.timestamp()) if hasattr(value, "timestamp") else int(value)


def fetch_quote(ticker: str) -> dict | None:
    """Latest regular-market price and previous close."""
    t = yf.Ticker(ticker)
    hist = t.history(period="5d", interval="1d", auto_adjust=False)
    if hist is None or hist.empty:
        return None
    closes = hist["Close"].dropna()
    if closes.empty:
        return None
    meta = getattr(t, "history_metadata", None) or {}
    price = _clean(meta.get("regularMarketPrice")) or float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else _clean(meta.get("chartPreviousClose"))
    return {
        "price": float(price),
        "prev_close": prev_close,
        "currency": meta.get("currency"),
        "market_time": _epoch(meta.get("regularMarketTime")) or _epoch(closes.index[-1]),
    }


def fetch_history(ticker: str, range_key: str = "3M") -> list[dict]:
    period, interval = RANGES.get(range_key, RANGES["3M"])

    def load():
        hist = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
        if hist is None or hist.empty:
            return []
        return [
            {"t": int(idx.timestamp()), "c": round(float(row["Close"]), 4)}
            for idx, row in hist.iterrows()
            if not math.isnan(row["Close"])
        ]

    return _cached(("hist", ticker, range_key), HISTORY_TTL, load) or []


MARKET_CLOSE_HOURS = {"TW": 13.5, "US": 16.0}  # local closing time


def fetch_daily_closes(ticker: str, start_ts: int, market: str) -> list[dict]:
    """Dividend/split-adjusted daily closes since start_ts. Each bar is stamped with its
    closing time (`t`), so callers can tell which close came after a given moment."""
    start = datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    offset = int(MARKET_CLOSE_HOURS.get(market, 16.0) * 3600)

    def load():
        hist = yf.Ticker(ticker).history(start=start, interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            return []
        return [
            {"day": idx.strftime("%Y-%m-%d"), "t": int(idx.normalize().timestamp()) + offset, "c": float(row["Close"])}
            for idx, row in hist.iterrows()
            if not math.isnan(row["Close"])
        ]

    return _cached(("daily", ticker, start), 1800, load) or []


def close_on_or_before(ticker: str, ts: int) -> float | None:
    """Daily close at or before a timestamp (used for 'price change since the article')."""
    points = fetch_history(ticker, "6M")
    if not points:
        return None
    idx = bisect_right([p["t"] for p in points], ts) - 1
    return points[max(idx, 0)]["c"]


def fetch_fundamentals(ticker: str) -> dict:
    try:
        info = yf.Ticker(ticker).get_info() or {}
    except Exception as e:
        log.warning("Fundamentals for %s failed: %s", ticker, e)
        return {}
    return {k: _clean(info.get(k)) for k in FUNDAMENTAL_KEYS if info.get(k) is not None}
