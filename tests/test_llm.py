"""Claude analyzer with a fake client — verifies request shape and result filtering, no network."""
from types import SimpleNamespace

import pytest

from backend.analysis.llm import AnalysisFailed, ClaudeAnalyzer
from backend.analysis.schemas import ArticleAssessment, IndustryAnalysis, IndustryArticleAssessment, StockAnalysis, TickerImpact

NOW = 1_800_000_000


def assessment(aid, impact, **overrides):
    base = dict(article_id=aid, relevant=True, duplicate_of_known_event=False, category="guidance",
                pillar="leadership", impact_percent=impact, confidence=0.8, already_priced_in=0.2,
                duration="medium", severity="moderate", pillar_delta=5.0, company_decision=True,
                market_alignment="against_market", alignment_assessment="Wins if demand holds.", reasoning="r")
    return ArticleAssessment(**{**base, **overrides})


class FakeMessages:
    def __init__(self, parsed, stop_reason="end_turn"):
        self.parsed, self.stop_reason, self.calls = parsed, stop_reason, []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        usage = SimpleNamespace(input_tokens=100, output_tokens=50, cache_read_input_tokens=0)
        return SimpleNamespace(parsed_output=self.parsed, stop_reason=self.stop_reason, usage=usage)


def fake_client(messages):
    return SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages))


@pytest.fixture
def analyzer(cfg, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    return ClaudeAnalyzer(cfg)


def articles():
    return [{"id": i, "title": f"t{i}", "summary": "", "published_at": NOW - 3600, "source": "S", "lang": "en"}
            for i in ("a", "b", "c")]


def test_stock_analysis_filters_and_normalizes(analyzer, cfg):
    parsed = StockAnalysis(outlook_summary="Solid.", assessments=[
        assessment("a", -150.0),                                   # clamped to -90
        assessment("b", 3.0, relevant=False),                      # dropped
        assessment("c", 2.0, duplicate_of_known_event=True),       # dropped
        assessment("zzz", 9.0),                                    # unknown id, dropped
    ])
    analyzer.client = fake_client(FakeMessages(parsed))
    res = analyzer.analyze_stock(cfg.stock("2317.TW"), articles(), quote={"price": 200, "prev_close": 198, "currency": "TWD"},
                                 fundamentals={}, returns={}, known_events=[], price_moves={"a": 0.01}, now=NOW)
    assert [r["article_id"] for r in res.rows] == ["a"]
    r = res.rows[0]
    assert r["impact_pct"] == -90 and r["direction"] == "negative"
    assert r["pillar_delta"] == 2.0  # clamped
    assert r["market_alignment"] == "against_market"
    assert sorted(res.processed_ids) == ["a", "b", "c"]
    assert res.outlook == "Solid."

    call = analyzer.client.messages.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["output_format"] is StockAnalysis
    assert call["thinking"] == {"type": "adaptive"}
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert "2317.TW" in call["messages"][0]["content"]


def test_refusal_raises(analyzer, cfg):
    analyzer.client = fake_client(FakeMessages(None, stop_reason="refusal"))
    with pytest.raises(AnalysisFailed):
        analyzer.analyze_stock(cfg.stock("PLTR"), articles(), quote=None, fundamentals={}, returns={},
                               known_events=[], price_moves={}, now=NOW)


def test_industry_analysis_ignores_unknown_tickers(analyzer):
    parsed = IndustryAnalysis(assessments=[IndustryArticleAssessment(
        article_id="a", relevant=True, duplicate_of_known_event=False, category="capacity_supply", severity="major",
        affected=[TickerImpact(ticker="2330.TW", impact_percent=4, confidence=0.7, already_priced_in=0.3, duration="medium", reasoning="x"),
                  TickerImpact(ticker="NVDA", impact_percent=4, confidence=0.7, already_priced_in=0.3, duration="medium", reasoning="x")])])
    analyzer.client = fake_client(FakeMessages(parsed))
    res = analyzer.analyze_industry(articles(), known_events=[], now=NOW)
    assert [(r["ticker"], r["target"]) for r in res.rows] == [("2330.TW", "INDUSTRY")]
