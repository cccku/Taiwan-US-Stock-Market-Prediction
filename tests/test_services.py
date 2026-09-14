import time

import pytest

from backend.analysis.schemas import make_row
from backend.db import INDUSTRY
from backend.services import Snapshot, record_predictions


def seed_article(db, aid, title, target, published):
    db.add_article({"id": aid, "title": title, "summary": "", "url": "https://example.com/" + aid,
                    "source": "Test", "published_at": published, "lang": "en", "provider": "test"}, target)


def row(aid, ticker, impact, target=None, severity="moderate"):
    return make_row(article_id=aid, ticker=ticker, target=target or ticker, impact_pct=impact, confidence=1.0,
                    priced_in=0.0, duration="structural", severity=severity, category="earnings",
                    pillar="demand_supply", reasoning="test", engine="test")


def test_prediction_moves_with_news_and_logs_only_on_input_change(db, cfg):
    now = int(time.time())
    db.upsert_quote("2330.TW", 1000.0, 990.0, "TWD", now)
    seed_article(db, "a1", "TSMC raises guidance", "2330.TW", now - 3600)
    db.save_analyses([row("a1", "2330.TW", 10.0)])

    snap = Snapshot(db, cfg, now)
    tsmc = next(r for r in snap.dashboard({"favorites": []})["stocks"] if r["ticker"] == "2330.TW")
    assert tsmc["predicted_price"] > tsmc["price"]
    assert tsmc["outlook"] == "up"
    assert tsmc["change_pct"] == pytest.approx(1000 / 990 - 1)

    assert record_predictions(db, cfg, now) == 1
    db.upsert_quote("2330.TW", 1100.0, 1000.0, "TWD", now)  # price moves, news doesn't
    assert record_predictions(db, cfg, now + 60) == 0

    seed_article(db, "a2", "TSMC hit by export ban", "2330.TW", now - 60)
    db.save_analyses([row("a2", "2330.TW", -40.0, severity="critical")])
    assert record_predictions(db, cfg, now + 120) == 1
    history = db.prediction_history("2330.TW")
    assert "1 new news item" in history[-1]["note"]
    assert history[-1]["expected_return"] < 0


def test_critical_news_surfaces_as_dashboard_alert(db, cfg):
    now = int(time.time())
    db.upsert_quote("TEM", 50.0, 52.0, "USD", now)
    seed_article(db, "c1", "Tempus AI restatement", "TEM", now - 3600)
    db.save_analyses([row("c1", "TEM", -45.0, severity="critical")])
    dash = Snapshot(db, cfg, now).dashboard({"favorites": ["TEM"]})
    assert dash["alerts"][0]["ticker"] == "TEM"
    tem = next(r for r in dash["stocks"] if r["ticker"] == "TEM")
    assert tem["favorite"] and tem["outlook"] == "down"


def test_industry_analysis_does_not_override_company_analysis(db, cfg):
    now = int(time.time())
    seed_article(db, "x1", "AI server orders jump", "2382.TW", now)
    db.save_analyses([row("x1", "2382.TW", 5.0)])
    db.save_analyses([row("x1", "2382.TW", -5.0, target=INDUSTRY)])
    [a] = db.analyses(now - 10, "2382.TW")
    assert a["impact_pct"] == 5.0


def test_news_hub_ranks_by_impact(db, cfg):
    now = int(time.time())
    for aid, impact in (("n1", 1.0), ("n2", -20.0), ("n3", 5.0)):
        seed_article(db, aid, f"headline {aid}", "PLTR", now - 3600)
        db.save_analyses([row(aid, "PLTR", impact)])
    items = Snapshot(db, cfg, now).news_hub()["items"]
    assert [i["article_id"] for i in items] == ["n2", "n3", "n1"]
    assert items[0]["direction"] == "negative"


def test_skip_backlog_closes_unselected_articles_only(db, cfg):
    now = int(time.time())
    for i in range(5):
        seed_article(db, f"b{i}", f"Cloudflare headline {i}", "NET", now - i * 3600)
    selected = db.pending_articles("NET", now - 86400, 2)
    assert [a["id"] for a in selected] == ["b0", "b1"]
    assert db.skip_backlog("NET", [a["id"] for a in selected]) == 3
    assert [a["id"] for a in db.pending_articles("NET", now - 86400, 10)] == ["b0", "b1"]


def test_pending_articles_upgrade_heuristic(db, cfg):
    now = int(time.time())
    seed_article(db, "h1", "Datadog headline", "DDOG", now)
    db.mark_processed(["h1"], "DDOG", "heuristic")
    assert db.pending_articles("DDOG", now - 10, 10) == []
    assert [a["id"] for a in db.pending_articles("DDOG", now - 10, 10, upgrade_from_engine="heuristic")] == ["h1"]
