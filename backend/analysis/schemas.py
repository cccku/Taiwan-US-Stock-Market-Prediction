"""Structured-output schemas for Claude, plus normalization into `analyses` rows.

Numeric bounds are enforced in `normalize_*` rather than in the JSON schema, so the
schemas stay within what structured outputs supports."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

Direction = Literal["positive", "negative", "neutral"]
Duration = Literal["transient", "medium", "structural"]
Severity = Literal["low", "moderate", "major", "critical"]
Pillar = Literal["leadership", "product", "price", "demand_supply", "macro"]
Alignment = Literal["not_applicable", "with_market", "against_market"]
Category = Literal[
    "earnings", "guidance", "product", "customer_contract", "capacity_supply", "demand_signal",
    "leadership_management", "capital_allocation", "regulation_geopolitics", "legal_governance",
    "competition", "analyst_rating", "macro", "other",
]

NEUTRAL_BAND_PCT = 0.5  # |impact| under 0.5% is shown as "≈ no change"


class ArticleAssessment(BaseModel):
    article_id: str
    relevant: bool
    duplicate_of_known_event: bool
    category: Category
    pillar: Pillar
    impact_percent: float
    confidence: float
    already_priced_in: float
    duration: Duration
    severity: Severity
    pillar_delta: float
    company_decision: bool
    market_alignment: Alignment
    alignment_assessment: str
    reasoning: str


class StockAnalysis(BaseModel):
    assessments: list[ArticleAssessment]
    outlook_summary: str


class TickerImpact(BaseModel):
    ticker: str
    impact_percent: float
    confidence: float
    already_priced_in: float
    duration: Duration
    reasoning: str


class IndustryArticleAssessment(BaseModel):
    article_id: str
    relevant: bool
    duplicate_of_known_event: bool
    category: Category
    severity: Severity
    affected: list[TickerImpact]


class IndustryAnalysis(BaseModel):
    assessments: list[IndustryArticleAssessment]


@dataclass
class BatchResult:
    rows: list[dict] = field(default_factory=list)
    processed_ids: list[str] = field(default_factory=list)
    outlook: str | None = None
    engine: str = ""


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def direction_for(impact_pct: float) -> Direction:
    if impact_pct >= NEUTRAL_BAND_PCT:
        return "positive"
    if impact_pct <= -NEUTRAL_BAND_PCT:
        return "negative"
    return "neutral"


def make_row(*, article_id: str, ticker: str, target: str, impact_pct: float, confidence: float,
             priced_in: float, duration: str, severity: str, category: str, pillar: str,
             reasoning: str, engine: str, pillar_delta: float = 0.0, company_decision: bool = False,
             market_alignment: str = "not_applicable", alignment_note: str = "") -> dict:
    impact_pct = clamp(float(impact_pct), -90.0, 60.0)
    return {
        "article_id": article_id, "ticker": ticker, "target": target,
        "direction": direction_for(impact_pct), "impact_pct": round(impact_pct, 2),
        "confidence": round(clamp(float(confidence), 0.0, 1.0), 3),
        "priced_in": round(clamp(float(priced_in), 0.0, 1.0), 3),
        "duration": duration, "severity": severity, "category": category, "pillar": pillar,
        "pillar_delta": round(clamp(float(pillar_delta), -2.0, 2.0), 2) if pillar in ("leadership", "product") else 0.0,
        "company_decision": int(bool(company_decision)),
        "market_alignment": market_alignment, "alignment_note": alignment_note or "",
        "reasoning": reasoning, "engine": engine,
    }
