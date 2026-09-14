"""Prediction track record.

1. record_snapshots — every refresh stores each stock's prediction, one row per market day
   (later refreshes that day overwrite it; past days are never touched).
2. evaluate — once enough trading days have passed, measures the real dividend-adjusted return
   from the first close *after* the prediction was made (no credit for moves you couldn't trade),
   next to the market index over the same window. Individual news items are scored the same way
   at short horizons, which gives feedback on the analysis engine within days.
3. accuracy_report — hit rates against a naive baseline with honest confidence ranges, rank
   correlation, calibration buckets, and breakdowns by market / engine / algorithm version.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import statistics
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from .analysis.prompts import PROMPT_VERSION
from .config import AppConfig
from .db import Database
from .providers import prices
from .services import Snapshot

log = logging.getLogger(__name__)

MARKET_TZ = {"TW": "Asia/Taipei", "US": "America/New_York"}
HORIZON_LABELS = {1: "1 day", 5: "1 week", 21: "1 month", 63: "3 months"}
MIN_DIRECTIONAL = 20          # fewer scored directional calls than this → "not enough data"
CONTRIBUTION_EPS = 0.0005
BAR_SETTLE_SECONDS = 900      # a daily bar counts as final 15 minutes after the close
SNAPSHOT_SCOPE_DAYS = 400
NEWS_SCOPE_DAYS = 180
BUCKETS = [
    (-math.inf, -0.05, "≤ −5%"),
    (-0.05, -0.01, "−5% to −1%"),
    (-0.01, 0.01, "≈ 0 (within ±1%)"),
    (0.01, 0.05, "+1% to +5%"),
    (0.05, math.inf, "≥ +5%"),
]


def market_day(ts: int, market: str) -> str:
    return datetime.fromtimestamp(ts, ZoneInfo(MARKET_TZ.get(market, "UTC"))).strftime("%Y-%m-%d")


def horizon_label(h: int) -> str:
    return HORIZON_LABELS.get(h, f"{h} trading days")


def trading_horizon(cfg: AppConfig) -> int:
    return max(1, round(cfg.settings.prediction.horizon_days * 252 / 365))


def algo_version(cfg: AppConfig) -> str:
    a = cfg.settings.analysis
    payload = {"prediction": cfg.settings.prediction.model_dump(), "engine": a.engine, "model": a.model,
               "effort": a.effort, "prompt": PROMPT_VERSION}
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:8]


def engine_group(engine: str | None) -> str:
    if not engine:
        return "no-news"
    return "heuristic" if engine.startswith("heuristic") else "claude"


# ── 1. snapshots ─────────────────────────────────────────────────────────────
def record_snapshots(db: Database, cfg: AppConfig, now: int) -> int:
    snap = Snapshot(db, cfg, now)
    version = algo_version(cfg)
    written = 0
    for stock in cfg.stocks:
        st = snap.state(stock)
        price = st["quote"].get("price")
        if price is None:
            continue
        pred = st["prediction"]
        active = [a for a, c in pred["contributions"] if abs(c) >= CONTRIBUTION_EPS]
        groups = {engine_group(a["engine"]) for a in active}
        db.upsert_snapshot({
            "ticker": stock.ticker, "day": market_day(now, stock.market), "market": stock.market,
            "created_at": now, "price": price, "predicted_price": pred["predicted_price"],
            "expected_return": pred["expected_return"], "news_return": pred["news_return"],
            "valuation_return": pred["valuation_return"], "outlook": pred["outlook"],
            "horizon_days": cfg.settings.prediction.horizon_days,
            "engine": "claude" if "claude" in groups else "heuristic" if groups else "no-news",
            "article_ids": json.dumps(sorted(a["article_id"] for a in active)),
            "algo_version": version,
        })
        written += 1
    return written


# ── 2. scoring matured predictions ───────────────────────────────────────────
def _window(points: list[dict], times: list[int], ts: int, h: int) -> tuple[dict, dict] | None:
    """Base = first settled close at/after ts; end = h trading days later."""
    i0 = bisect_left(times, ts)
    if i0 + h >= len(points):
        return None
    return points[i0], points[i0 + h]


def _benchmark_return(closes_by_day: dict[str, float], base_day: str, end_day: str) -> float | None:
    b0, b1 = closes_by_day.get(base_day), closes_by_day.get(end_day)
    return b1 / b0 - 1 if b0 and b1 else None


def _load_closes(ticker: str, start: int, market: str, now: int) -> list[dict]:
    try:
        points = prices.fetch_daily_closes(ticker, start - 7 * 86400, market)
    except Exception as e:
        log.warning("Daily closes for %s unavailable: %s", ticker, e)
        return []
    return [p for p in points if p["t"] + BAR_SETTLE_SECONDS <= now]


def evaluate(db: Database, cfg: AppConfig, now: int) -> dict:
    ev = cfg.settings.evaluation
    horizons = sorted(set(ev.horizons_trading_days))
    news_horizons = sorted(set(ev.news_horizons_trading_days))
    stocks = {s.ticker: s for s in cfg.stocks}

    snaps = [s for s in db.snapshots_missing_outcome(horizons[-1], now - SNAPSHOT_SCOPE_DAYS * 86400)
             if s["ticker"] in stocks]
    news = [a for a in db.analyses_missing_news_outcome(news_horizons[-1], ev.news_min_abs_impact_pct,
                                                        now - NEWS_SCOPE_DAYS * 86400)
            if a["ticker"] in stocks]
    if not snaps and not news:
        return {"outcomes": 0, "news_outcomes": 0}

    starts: dict[str, int] = {}
    for ticker, ts in [(s["ticker"], s["created_at"]) for s in snaps] + [(a["ticker"], a["published_at"]) for a in news]:
        starts[ticker] = min(starts.get(ticker, ts), ts)
    series = {t: _load_closes(t, start, stocks[t].market, now) for t, start in starts.items()}
    times = {t: [p["t"] for p in pts] for t, pts in series.items()}

    bench: dict[str, dict[str, float]] = {}
    for market in {stocks[t].market for t in starts}:
        symbol = ev.benchmarks.get(market)
        if symbol:
            start = min(s for t, s in starts.items() if stocks[t].market == market)
            bench[market] = {p["day"]: p["c"] for p in _load_closes(symbol, start, market, now)}

    outcome_rows = []
    have = db.outcome_keys()
    for s in snaps:
        for h in horizons:
            if (s["ticker"], s["day"], h) in have:
                continue
            w = _window(series[s["ticker"]], times[s["ticker"]], s["created_at"], h)
            if not w:
                continue
            base, end = w
            outcome_rows.append({
                "ticker": s["ticker"], "day": s["day"], "horizon": h,
                "base_day": base["day"], "base_close": base["c"], "end_day": end["day"], "end_close": end["c"],
                "realized_return": end["c"] / base["c"] - 1,
                "benchmark_return": _benchmark_return(bench.get(s["market"], {}), base["day"], end["day"]),
                "evaluated_at": now,
            })
    db.add_outcomes(outcome_rows)

    news_rows = []
    have_news = db.news_outcome_keys()
    for a in news:
        market = stocks[a["ticker"]].market
        for h in news_horizons:
            if (a["article_id"], a["ticker"], a["engine"], h) in have_news:
                continue
            w = _window(series[a["ticker"]], times[a["ticker"]], a["published_at"], h)
            if not w:
                continue
            base, end = w
            news_rows.append({
                **{k: a[k] for k in ("article_id", "ticker", "engine", "impact_pct", "confidence",
                                     "severity", "category", "published_at")},
                "horizon": h, "realized_return": end["c"] / base["c"] - 1,
                "benchmark_return": _benchmark_return(bench.get(market, {}), base["day"], end["day"]),
                "evaluated_at": now,
            })
    db.add_news_outcomes(news_rows)
    return {"outcomes": len(outcome_rows), "news_outcomes": len(news_rows)}


# ── 3. metrics ───────────────────────────────────────────────────────────────
def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def wilson(hits: float, n: float, z: float = 1.96) -> tuple[float, float]:
    """95% interval for a hit rate; n may be an effective (fractional) sample size."""
    if n <= 0:
        return 0.0, 1.0
    p = hits / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    return cov / math.sqrt(vx * vy) if vx and vy else None


def direction_stats(pairs: list[tuple[float, float]], overlap: float = 1.0) -> dict:
    """pairs = (predicted move, realized move vs market) for non-neutral predictions.

    Baseline = always guessing whichever direction was more common, so a model can't look good
    just because most stocks happened to rise. `overlap` shrinks the effective sample size
    (daily snapshots scored over h days overlap heavily)."""
    n = len(pairs)
    if not n:
        return {"directional": 0, "hit_rate": None, "baseline": None, "ci": None, "verdict": "not_enough",
                "spread": None, "avg_excess_up": None, "avg_excess_down": None}
    hits = sum(1 for p, o in pairs if o != 0 and (p > 0) == (o > 0))
    rate = hits / n
    share_up = sum(1 for _, o in pairs if o > 0) / n
    baseline = max(share_up, 1 - share_up)
    n_eff = max(1.0, n / overlap)
    lo, hi = wilson(rate * n_eff, n_eff)
    if n < MIN_DIRECTIONAL:
        verdict = "not_enough"
    elif lo > baseline:
        verdict = "beating"
    elif hi < baseline:
        verdict = "worse"
    else:
        verdict = "unclear"
    avg_up = _mean(o for p, o in pairs if p > 0)
    avg_down = _mean(o for p, o in pairs if p < 0)
    return {
        "directional": n, "hit_rate": rate, "baseline": baseline, "ci": [lo, hi], "verdict": verdict,
        "spread": avg_up - avg_down if avg_up is not None and avg_down is not None else None,
        "avg_excess_up": avg_up, "avg_excess_down": avg_down,
    }


def summarize(rows: list[dict], h: int, band: float, horizon_td: int) -> dict:
    scored = [r for r in rows if r["excess"] is not None]
    directional = [r for r in scored if abs(r["expected_return"]) > band]
    out = {"n": len(rows), **direction_stats([(r["expected_return"], r["excess"]) for r in directional], overlap=h)}

    raw = [r for r in rows if abs(r["expected_return"]) > band]
    out["hit_rate_raw"] = (sum(1 for r in raw if r["realized_return"] != 0
                               and (r["expected_return"] > 0) == (r["realized_return"] > 0)) / len(raw)) if raw else None

    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in scored:
        by_day[r["day"]].append(r)
    ics = [c for c in (spearman([r["expected_return"] for r in rs], [r["excess"] for r in rs])
                       for rs in by_day.values() if len(rs) >= 5) if c is not None]
    out["ic"], out["ic_days"] = _mean(ics), len(ics)

    # Predictions are ~horizon fair-value moves; scale linearly for shorter checkpoints.
    scale = min(1.0, h / horizon_td)
    naive = _mean(abs(r["realized_return"]) for r in rows)
    model = _mean(abs(r["expected_return"] * scale - r["realized_return"]) for r in rows)
    out["error_skill"] = 1 - model / naive if naive else None
    out["avg_expected"] = _mean(r["expected_return"] * scale for r in rows)
    out["avg_realized"] = _mean(r["realized_return"] for r in rows)
    out["avg_excess"] = _mean(r["excess"] for r in scored)
    return out


SMALL_KEYS = ("n", "directional", "hit_rate", "baseline", "ci", "verdict", "spread", "avg_excess_up", "avg_excess_down")


def _small(summary: dict) -> dict:
    return {k: summary.get(k) for k in SMALL_KEYS}


def _calibrate(rows: list[dict], h: int, horizon_td: int) -> list[dict]:
    scale = min(1.0, h / horizon_td)
    out = []
    for lo, hi, label in BUCKETS:
        rs = [r for r in rows if lo <= r["expected_return"] < hi]
        out.append({
            "label": label, "n": len(rs),
            "avg_expected": _mean(r["expected_return"] * scale for r in rs),
            "avg_realized": _mean(r["realized_return"] for r in rs),
            "avg_excess": _mean(r["excess"] for r in rs),
        })
    return out


def _grouped(rows: list[dict], key: str) -> list[tuple[str, list[dict]]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[str(r.get(key))].append(r)
    return sorted(groups.items())


def _recent(r: dict, names: dict, band: float) -> dict:
    exp = r["expected_return"]
    hit = None
    if abs(exp) > band and r["excess"] is not None:
        hit = r["excess"] != 0 and (exp > 0) == (r["excess"] > 0)
    return {
        "ticker": r["ticker"], "name": names.get(r["ticker"], r["ticker"]), "day": r["day"], "end_day": r["end_day"],
        "price": r["price"], "expected_return": exp, "realized_return": r["realized_return"],
        "benchmark_return": r["benchmark_return"], "excess": r["excess"], "hit": hit, "engine": r["engine"],
    }


def _news_report(rows: list[dict], ev) -> dict:
    valid = []
    for r in rows:
        if r["benchmark_return"] is not None:
            valid.append({**r, "excess": r["realized_return"] - r["benchmark_return"]})
    by_engine: dict[tuple, list[dict]] = defaultdict(list)
    for r in valid:
        by_engine[(engine_group(r["engine"]), r["horizon"])].append(r)
    top_h = max(ev.news_horizons_trading_days)
    by_category: dict[str, list[dict]] = defaultdict(list)
    for r in valid:
        if r["horizon"] == top_h:
            by_category[r["category"] or "other"].append(r)
    pairs = lambda rs: [(r["impact_pct"], r["excess"]) for r in rs]  # noqa: E731
    return {
        "total": len(valid),
        "by_engine": [{"engine": e, "h": h, "label": horizon_label(h), **direction_stats(pairs(rs))}
                      for (e, h), rs in sorted(by_engine.items())],
        "category_horizon": top_h,
        "by_category": sorted(({"category": c, **direction_stats(pairs(rs))} for c, rs in by_category.items()),
                              key=lambda x: -x["directional"]),
    }


def accuracy_report(db: Database, cfg: AppConfig, now: int) -> dict:
    ev = cfg.settings.evaluation
    band = cfg.settings.prediction.neutral_band
    horizon_td = trading_horizon(cfg)
    names = {s.ticker: s.name for s in cfg.stocks}
    stats = db.snapshot_stats()

    rows = db.snapshot_outcome_rows()
    for r in rows:
        r["excess"] = r["realized_return"] - r["benchmark_return"] if r["benchmark_return"] is not None else None
    by_h: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_h[r["horizon"]].append(r)

    horizons, calibration, groups, per_stock, recent = [], {}, {}, {}, {}
    for h in sorted(set(ev.horizons_trading_days)):
        hr = by_h.get(h, [])
        first = stats["first_created_at"]
        horizons.append({
            "h": h, "label": horizon_label(h), **summarize(hr, h, band, horizon_td),
            "pending": max(0, stats["snapshots"] - len(hr)),
            # rough: trading days → calendar days, plus a day for the first close
            "first_result_eta": first + (math.ceil(h * 7 / 5) + 1) * 86400 if first else None,
        })
        calibration[h] = _calibrate(hr, h, horizon_td)
        groups[h] = {key: [{"key": k, **_small(summarize(rs, h, band, horizon_td))} for k, rs in _grouped(hr, key)]
                     for key in ("market", "engine", "algo_version")}
        per_stock[h] = [{"ticker": t, "name": names.get(t, t), **_small(summarize(rs, h, band, horizon_td))}
                        for t, rs in _grouped(hr, "ticker")]
        recent[h] = [_recent(r, names, band)
                     for r in sorted(hr, key=lambda r: (r["end_day"], r["ticker"]), reverse=True)[:30]]

    return {
        "generated_at": now,
        "tracking": {
            "since": stats["first_day"], "snapshots": stats["snapshots"], "stocks": stats["stocks"],
            "last_snapshot_at": stats["last_created_at"], "last_evaluated_at": db.get_pref("last_evaluation_at"),
            "versions": stats["versions"], "current_version": algo_version(cfg),
        },
        "settings": {"benchmarks": ev.benchmarks, "neutral_band": band, "trading_horizon": horizon_td,
                     "news_min_abs_impact_pct": ev.news_min_abs_impact_pct},
        "horizons": horizons,
        "calibration": calibration,
        "groups": groups,
        "stocks": per_stock,
        "recent": recent,
        "news": _news_report(db.news_outcome_rows(), ev),
    }
