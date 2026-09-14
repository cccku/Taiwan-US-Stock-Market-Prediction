import random
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.analysis.schemas import make_row
from backend.evaluation import (
    accuracy_report, direction_stats, evaluate, record_snapshots, spearman, summarize, wilson,
)
from backend.providers import prices

DAY = 86400
NY = ZoneInfo("America/New_York")


def series(first_close_ts, closes):
    return [{"day": time.strftime("%Y-%m-%d", time.gmtime(first_close_ts + i * DAY)),
             "t": first_close_ts + i * DAY, "c": c} for i, c in enumerate(closes)]


def seed_news(db, aid, ticker, impact, published):
    db.add_article({"id": aid, "title": f"headline {aid}", "summary": "", "url": "https://example.com",
                    "source": "Test", "published_at": published, "lang": "en", "provider": "test"}, ticker)
    db.save_analyses([make_row(article_id=aid, ticker=ticker, target=ticker, impact_pct=impact, confidence=1.0,
                               priced_in=0.0, duration="structural", severity="moderate", category="guidance",
                               pillar="demand_supply", reasoning="r", engine="claude-opus-5")])


def test_statistics_helpers():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 1, 1], [1, 2, 3]) is None
    lo, hi = wilson(55, 100)
    assert lo < 0.55 < hi and hi - lo == pytest.approx(0.19, abs=0.01)


def test_one_snapshot_per_market_day(db, cfg):
    noon = int(datetime(2026, 9, 14, 12, tzinfo=NY).timestamp())
    db.upsert_quote("PLTR", 100.0, 99.0, "USD", noon)
    assert record_snapshots(db, cfg, noon) == 1
    db.upsert_quote("PLTR", 101.0, 99.0, "USD", noon)
    record_snapshots(db, cfg, noon + 3600)
    assert db.snapshot_stats()["snapshots"] == 1
    [row] = db.export_rows()
    assert row["price"] == 101.0 and row["day"] == "2026-09-14" and row["engine"] == "no-news"


def test_evaluate_scores_from_first_close_after_prediction(db, cfg, monkeypatch):
    noon = int(datetime(2026, 6, 1, 12, tzinfo=NY).timestamp())
    first_close = noon + 4 * 3600
    db.upsert_quote("PLTR", 100.0, 99.0, "USD", noon)
    seed_news(db, "n1", "PLTR", 10.0, noon - 3600)
    record_snapshots(db, cfg, noon)

    stock = series(first_close, [100, 101, 102, 103, 104, 110, 111])
    bench = series(first_close, [1000, 1000, 1000, 1000, 1000, 1020, 1020])
    monkeypatch.setattr(prices, "fetch_daily_closes",
                        lambda ticker, start, market: bench if ticker.startswith("^") else stock)
    now = first_close + 30 * DAY
    assert evaluate(db, cfg, now) == {"outcomes": 1, "news_outcomes": 2}

    [o] = db.snapshot_outcome_rows()
    assert o["horizon"] == 5  # 21 and 63 trading days haven't happened yet
    assert o["realized_return"] == pytest.approx(0.10)
    assert o["benchmark_return"] == pytest.approx(0.02)
    assert evaluate(db, cfg, now) == {"outcomes": 0, "news_outcomes": 0}  # idempotent

    report = accuracy_report(db, cfg, now)
    week = next(h for h in report["horizons"] if h["h"] == 5)
    assert week["n"] == 1 and week["hit_rate"] == 1.0 and week["verdict"] == "not_enough"
    assert next(h for h in report["horizons"] if h["h"] == 21)["n"] == 0
    assert report["recent"][5][0]["hit"] is True
    assert {(e["engine"], e["h"]) for e in report["news"]["by_engine"]} == {("claude", 1), ("claude", 5)}


def test_bars_that_have_not_closed_are_ignored(db, cfg, monkeypatch):
    noon = int(datetime(2026, 6, 1, 12, tzinfo=NY).timestamp())
    db.upsert_quote("PLTR", 100.0, 99.0, "USD", noon)
    record_snapshots(db, cfg, noon)
    first_close = noon + 4 * 3600
    stock = series(first_close, [100, 101, 102, 103, 104, 110])
    monkeypatch.setattr(prices, "fetch_daily_closes", lambda *a: stock)
    # "now" is just before the 6th bar settles → no 5-day outcome yet
    assert evaluate(db, cfg, first_close + 5 * DAY + 60)["outcomes"] == 0


def _rows(sign_right: bool, days=30, stocks=10, seed=1):
    rng = random.Random(seed)
    rows = []
    for d in range(days):
        for s in range(stocks):
            exp = rng.choice([-0.05, 0.05]) * (1 + s / 10)
            excess = abs(rng.gauss(0.03, 0.01)) * (1 if (exp > 0) == sign_right else -1)
            rows.append({"day": f"d{d}", "expected_return": exp, "realized_return": excess + 0.01,
                         "benchmark_return": 0.01, "excess": excess})
    return rows


def test_skillful_predictions_beat_baseline_and_bad_ones_do_not():
    good = summarize(_rows(True), 5, 0.01, 62)
    assert good["verdict"] == "beating" and good["spread"] > 0 and good["ic"] > 0.5
    bad = summarize(_rows(False), 5, 0.01, 62)
    assert bad["verdict"] == "worse" and bad["spread"] < 0


def test_overlap_widens_confidence_interval():
    pairs = [(0.05, 0.01)] * 60 + [(0.05, -0.01)] * 40
    narrow, wide = direction_stats(pairs, overlap=1), direction_stats(pairs, overlap=21)
    assert (wide["ci"][1] - wide["ci"][0]) > (narrow["ci"][1] - narrow["ci"][0])
