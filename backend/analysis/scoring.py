"""Three pillars: leadership, product (baseline + news adjustments) and price (live valuation)."""
from __future__ import annotations

from ..config import Stock
from .predictor import age_days

PILLAR_HALF_LIFE_DAYS = 180


def _clamp(x: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, x))


def valuation_score(price: float | None, f: dict) -> dict:
    parts: list[tuple[float, float, str]] = []  # (weight, score, explanation)
    f = f or {}

    target, analysts = f.get("targetMeanPrice"), f.get("numberOfAnalystOpinions") or 0
    if price and target and analysts >= 3:
        upside = target / price - 1
        parts.append((0.5, _clamp(5 + 12.5 * upside), f"{upside:+.0%} to analyst mean target ({analysts} analysts)"))

    fpe, growth = f.get("forwardPE"), f.get("revenueGrowth")
    if fpe is not None and fpe <= 0:
        parts.append((0.35, 2.0, "unprofitable on forward earnings"))
    elif fpe and growth and growth > 0:
        peg = fpe / (growth * 100)
        parts.append((0.35, _clamp(10 - 4 * (peg - 0.5)), f"forward P/E {fpe:.0f} vs revenue growth {growth:.0%}"))
    elif fpe:
        parts.append((0.35, _clamp(10 - (fpe - 10) / 5), f"forward P/E {fpe:.0f}"))

    hi, lo = f.get("fiftyTwoWeekHigh"), f.get("fiftyTwoWeekLow")
    if price and hi and lo and hi > lo:
        pos = _clamp((price - lo) / (hi - lo), 0, 1)
        parts.append((0.15, 10 - 5 * pos, f"at {pos:.0%} of its 52-week range"))

    if not parts:
        return {"score": None, "basis": "Not enough valuation data yet."}
    total_w = sum(w for w, _, _ in parts)
    return {
        "score": round(sum(w * s for w, s, _ in parts) / total_w, 1),
        "basis": "; ".join(text for _, _, text in parts).capitalize() + ".",
    }


def pillar_scores(stock: Stock, analyses: list[dict], fundamentals: dict, price: float | None, now: int) -> dict:
    out: dict[str, dict] = {}
    for pillar in ("leadership", "product"):
        baseline = getattr(stock.pillars, pillar)
        items = [a for a in analyses if a.get("pillar") == pillar and a.get("pillar_delta")]
        delta = sum(
            a["pillar_delta"] * a["confidence"] * 0.5 ** (age_days(a["published_at"], now) / PILLAR_HALF_LIFE_DAYS)
            for a in items
        )
        out[pillar] = {
            "score": round(_clamp(baseline + delta), 1),
            "baseline": baseline,
            "news_adjustment": round(delta, 2),
            "news_events": len(items),
            "basis": getattr(stock.thesis, pillar),
        }
    out["price"] = valuation_score(price, fundamentals)
    return out
