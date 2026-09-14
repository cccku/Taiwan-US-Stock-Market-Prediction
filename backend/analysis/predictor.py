"""Turns analyzed news (+ an optional valuation anchor) into a predicted price.

expected_return = news_component + valuation_component

news_component: each analysis contributes
    impact% × confidence × (1 − priced_in) × 0.5^(age / half_life[duration])
Positive and negative contributions are summed separately and saturated with
cap·tanh(x/cap), so a pile of similar headlines cannot stack forever. The negative
cap is much larger than the positive one: bad news is allowed to be devastating.

valuation_component: valuation_weight × (analyst mean target / price − 1), capped.
It only moves when analyst consensus changes; set valuation_weight: 0 for news only.
"""
from __future__ import annotations

import math

from ..config import PredictionSettings

SEVERITY_WEIGHT = {"low": 1.0, "moderate": 1.2, "major": 1.5, "critical": 2.5}
MIN_ANALYSTS = 3


def age_days(published_at: int, now: int) -> float:
    return max(0.0, (now - published_at) / 86400)


def decay(analysis: dict, now: int, ps: PredictionSettings) -> float:
    half_life = getattr(ps.half_life_days, analysis["duration"], ps.half_life_days.medium)
    return 0.5 ** (age_days(analysis["published_at"], now) / half_life)


def contribution(analysis: dict, now: int, ps: PredictionSettings) -> float:
    """Fractional effect on expected return (0.01 == +1%)."""
    return (analysis["impact_pct"] / 100 * analysis["confidence"]
            * (1 - analysis["priced_in"]) * decay(analysis, now, ps))


def impact_score(analysis: dict, now: int, ps: PredictionSettings) -> float:
    """News Hub ranking: how much this item matters right now, in effective % points,
    boosted by severity so critical events always surface."""
    return (abs(analysis["impact_pct"]) * analysis["confidence"] * (1 - analysis["priced_in"])
            * decay(analysis, now, ps) * SEVERITY_WEIGHT.get(analysis["severity"], 1.0))


def _saturate(x: float, cap: float) -> float:
    return cap * math.tanh(x / cap) if cap > 0 else 0.0


def news_component(analyses: list[dict], now: int, ps: PredictionSettings) -> tuple[float, list[tuple[dict, float]]]:
    contribs = [(a, contribution(a, now, ps)) for a in analyses]
    pos = sum(c for _, c in contribs if c > 0)
    neg = -sum(c for _, c in contribs if c < 0)
    total = _saturate(pos, ps.positive_cap) - _saturate(neg, ps.negative_cap)
    contribs.sort(key=lambda ac: abs(ac[1]), reverse=True)
    return total, contribs


def valuation_component(price: float | None, fundamentals: dict, ps: PredictionSettings) -> tuple[float, dict | None]:
    target = (fundamentals or {}).get("targetMeanPrice")
    analysts = (fundamentals or {}).get("numberOfAnalystOpinions") or 0
    if not price or not target or analysts < MIN_ANALYSTS or ps.valuation_weight <= 0:
        return 0.0, None
    gap = target / price - 1
    value = max(-ps.valuation_cap, min(ps.valuation_cap, ps.valuation_weight * gap))
    return value, {"target": target, "analysts": analysts, "gap": gap, "weight": ps.valuation_weight}


def predict(price: float | None, analyses: list[dict], fundamentals: dict, now: int, ps: PredictionSettings) -> dict:
    news_r, contribs = news_component(analyses, now, ps)
    val_r, val_info = valuation_component(price, fundamentals, ps)
    total = max(-0.95, min(1.0, news_r + val_r))
    if total > ps.neutral_band:
        outlook = "up"
    elif total < -ps.neutral_band:
        outlook = "down"
    else:
        outlook = "neutral"
    return {
        "expected_return": total,
        "news_return": news_r,
        "valuation_return": val_r,
        "valuation": val_info,
        "predicted_price": price * (1 + total) if price else None,
        "outlook": outlook,
        "contributions": contribs,
    }
