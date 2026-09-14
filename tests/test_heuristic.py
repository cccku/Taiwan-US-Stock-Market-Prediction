from backend.analysis.heuristic import HeuristicAnalyzer, score_text

NOW = 1_800_000_000


def art(i, title, summary=""):
    return {"id": f"a{i}", "title": title, "summary": summary, "published_at": NOW}


def test_scores_english_and_chinese():
    assert score_text("Quanta raises guidance on strong demand")[0] > 0
    assert score_text("廣達 下修 財測")[0] < 0


def test_word_boundaries_avoid_false_matches():
    # "delayed" should match, but "relay" must not trigger "delay"
    assert score_text("Accton relay product")[0] == 0


def test_critical_news_is_never_ignored(cfg):
    stock = cfg.stock("PLTR")
    result = HeuristicAnalyzer(cfg).analyze_stock(stock, [art(1, "Palantir faces SEC charges over accounting fraud")])
    row = result.rows[0]
    assert row["severity"] == "critical"
    assert row["impact_pct"] <= -25
    assert row["direction"] == "negative"


def test_industry_news_maps_to_segments(cfg):
    result = HeuristicAnalyzer(cfg).analyze_industry([art(1, "CoWoS capacity shortage worsens as AI demand surges")])
    tickers = {r["ticker"] for r in result.rows}
    assert "2330.TW" in tickers
    assert all(r["target"] == "INDUSTRY" for r in result.rows)


def test_industry_news_without_sentiment_is_skipped(cfg):
    result = HeuristicAnalyzer(cfg).analyze_industry([art(1, "TSMC holds annual technology symposium")])
    assert result.rows == []
    assert result.processed_ids == ["a1"]
