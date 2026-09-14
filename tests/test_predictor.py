import pytest

from backend.analysis.predictor import contribution, decay, impact_score, predict, valuation_component
from backend.config import PredictionSettings

NOW = 1_800_000_000
DAY = 86400
PS = PredictionSettings()


def item(impact, *, days=0, conf=1.0, priced=0.0, duration="medium", severity="moderate"):
    return {"impact_pct": impact, "confidence": conf, "priced_in": priced, "duration": duration,
            "severity": severity, "published_at": NOW - days * DAY}


def test_decay_halves_at_half_life():
    assert decay(item(5, days=21), NOW, PS) == pytest.approx(0.5)
    assert decay(item(5, days=90, duration="structural"), NOW, PS) == pytest.approx(0.5)


def test_contribution_accounts_for_confidence_and_priced_in():
    assert contribution(item(10, conf=0.5, priced=0.5), NOW, PS) == pytest.approx(0.025)


def test_no_news_means_no_change():
    p = predict(100.0, [], {}, NOW, PS)
    assert p["predicted_price"] == pytest.approx(100.0)
    assert p["outlook"] == "neutral"


def test_good_news_saturates_but_bad_news_can_be_devastating():
    many_good = [item(20) for _ in range(20)]
    catastrophe = [item(-90, duration="structural", severity="critical")]
    up = predict(100.0, many_good, {}, NOW, PS)
    down = predict(100.0, catastrophe, {}, NOW, PS)
    assert up["expected_return"] < PS.positive_cap
    assert down["expected_return"] < -0.6
    assert down["outlook"] == "down"


def test_valuation_anchor_is_off_by_default_and_requires_coverage():
    assert valuation_component(100.0, {"targetMeanPrice": 150, "numberOfAnalystOpinions": 20}, PS)[0] == 0
    ps = PredictionSettings(valuation_weight=0.25)
    assert valuation_component(100.0, {"targetMeanPrice": 150, "numberOfAnalystOpinions": 2}, ps)[0] == 0
    value, info = valuation_component(100.0, {"targetMeanPrice": 120, "numberOfAnalystOpinions": 10}, ps)
    assert value == pytest.approx(0.05)
    assert info["analysts"] == 10


def test_critical_news_ranks_above_similar_major_news():
    assert impact_score(item(-10, severity="critical"), NOW, PS) > impact_score(item(-10, severity="major"), NOW, PS)
