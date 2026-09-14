"""Keyword heuristic used when Claude isn't configured. Deliberately low-confidence
and small-magnitude, except that survival-threatening terms are never ignored."""
from __future__ import annotations

import re

from ..config import AppConfig, Stock
from ..db import INDUSTRY
from .schemas import BatchResult, make_row

ENGINE = "heuristic"

POSITIVE = {
    "beats estimates": 2, "beat estimates": 2, "tops estimates": 2, "better than expected": 2,
    "record revenue": 2, "record high": 1.5, "record profit": 2, "raises guidance": 3, "raised guidance": 3,
    "raises outlook": 3, "raises forecast": 3, "upgrade": 1.5, "upgraded": 1.5, "outperform": 1,
    "wins contract": 2, "awarded": 1.5, "strong demand": 2, "surge": 1.5, "surges": 1.5, "soars": 1.5,
    "jumps": 1, "rallies": 1, "buyback": 1, "fda approval": 2, "fda clearance": 2, "profit rises": 2,
    "expands capacity": 1.5, "sold out": 1.5, "partnership": 0.7, "milestone": 0.7,
    "創新高": 1.5, "營收成長": 1.5, "年增": 1, "上修": 2.5, "調升": 1.5, "大單": 2, "擴產": 1,
    "獲利成長": 2, "買超": 1, "漲停": 1.5, "強勁": 1, "訂單滿載": 2, "優於預期": 2, "看好": 1,
}
NEGATIVE = {
    "misses estimates": -2, "missed estimates": -2, "below estimates": -2, "worse than expected": -2,
    "cuts guidance": -3, "lowers guidance": -3, "cut guidance": -3, "weak guidance": -2.5, "cuts forecast": -3,
    "downgrade": -1.5, "downgraded": -1.5, "underperform": -1, "lawsuit": -1.5, "sued": -1.5,
    "probe": -2, "investigation": -2, "export ban": -3, "export controls": -1.5, "tariff": -1,
    "recall": -2, "outage": -2, "breach": -2, "layoffs": -1, "resigns": -2, "steps down": -1.5,
    "plunge": -2, "plunges": -2, "tumbles": -1.5, "slumps": -1.5, "delay": -1.5, "delayed": -1.5,
    "shortage": -1, "loses contract": -2.5, "cancels": -1.5, "short seller": -2, "net loss": -1,
    "下修": -2.5, "衰退": -1.5, "調降": -1.5, "禁令": -2.5, "裁員": -1, "虧損": -1.5, "跌停": -2,
    "賣超": -1, "延遲": -1.5, "遞延": -1.5, "砍單": -2.5, "不如預期": -2, "調查": -1.5, "罰款": -1.5,
}
CRITICAL = [
    "fraud", "accounting irregularities", "restatement", "bankruptcy", "chapter 11", "delisting",
    "delisted", "going concern", "sec charges", "indicted", "掏空", "下市", "破產", "財報造假", "違約交割",
]
CATEGORIES = [
    ("legal_governance", ["fraud", "lawsuit", "sued", "probe", "investigation", "indicted", "調查", "掏空", "罰款"]),
    ("leadership_management", ["ceo", "cfo", "resigns", "steps down", "appoints", "chairman", "董事長", "總經理", "執行長"]),
    ("guidance", ["guidance", "outlook", "forecast", "財測", "展望"]),
    ("earnings", ["earnings", "revenue", "profit", "eps", "quarter", "營收", "財報", "獲利", "eps"]),
    ("analyst_rating", ["upgrade", "downgrade", "price target", "outperform", "underperform", "目標價"]),
    ("regulation_geopolitics", ["export", "tariff", "ban", "sanction", "關稅", "禁令", "出口管制"]),
    ("capacity_supply", ["capacity", "shortage", "supply", "產能", "擴產", "缺貨"]),
    ("customer_contract", ["contract", "order", "deal", "訂單", "大單"]),
    ("product", ["launch", "unveil", "release", "product", "推出", "新品"]),
]
PILLAR_BY_CATEGORY = {
    "leadership_management": "leadership", "legal_governance": "leadership", "product": "product",
    "analyst_rating": "price", "regulation_geopolitics": "macro",
}


def _has(text: str, term: str) -> bool:
    if re.search(r"[一-鿿]", term):
        return term in text
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def score_text(text: str) -> tuple[float, list[str], bool]:
    text = text.lower()
    hits, score = [], 0.0
    for term, weight in (*POSITIVE.items(), *NEGATIVE.items()):
        if _has(text, term):
            score += weight
            hits.append(f"{term} ({'+' if weight > 0 else '−'})")
    critical = [t for t in CRITICAL if _has(text, t)]
    hits += [f"{t} (critical)" for t in critical]
    return score, hits, bool(critical)


def categorize(text: str) -> str:
    text = text.lower()
    return next((cat for cat, terms in CATEGORIES if any(_has(text, t) for t in terms)), "other")


def _assess(text: str) -> dict | None:
    score, hits, critical = score_text(text)
    category = categorize(text)
    if critical:
        return dict(impact_pct=-30.0, confidence=0.35, duration="structural", severity="critical",
                    category="legal_governance", hits=hits, score=score)
    impact = max(-6.0, min(6.0, score * 0.8))
    return dict(
        impact_pct=impact, confidence=min(0.2 + 0.05 * len(hits), 0.4),
        duration="medium" if category in ("guidance", "customer_contract", "regulation_geopolitics") else "transient",
        severity="moderate" if abs(impact) >= 3 else "low", category=category, hits=hits, score=score,
    )


def _reason(hits: list[str], scale_note: str = "") -> str:
    matched = ", ".join(hits[:5]) if hits else "no sentiment keywords"
    return (f"Keyword heuristic matched: {matched}.{scale_note} Low confidence; "
            "configure Claude for reasoned analysis.")


class HeuristicAnalyzer:
    engine = ENGINE

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg

    def analyze_stock(self, stock: Stock, articles: list[dict], **_) -> BatchResult:
        result = BatchResult(processed_ids=[a["id"] for a in articles], engine=ENGINE)
        pos = neg = 0
        for a in articles:
            text = f"{a['title']} {a.get('summary') or ''}"
            r = _assess(text)
            pillar = PILLAR_BY_CATEGORY.get(r["category"], "demand_supply")
            result.rows.append(make_row(
                article_id=a["id"], ticker=stock.ticker, target=stock.ticker,
                impact_pct=r["impact_pct"], confidence=r["confidence"], priced_in=0.4,
                duration=r["duration"], severity=r["severity"], category=r["category"], pillar=pillar,
                pillar_delta=(0.5 if r["score"] > 0 else -0.5 if r["score"] < 0 else 0) if pillar in ("leadership", "product") else 0,
                reasoning=_reason(r["hits"]), engine=ENGINE,
            ))
            pos += r["impact_pct"] > 0
            neg += r["impact_pct"] < 0
        if articles:
            result.outlook = (f"Keyword scan of {len(articles)} new articles: {pos} lean positive, {neg} lean negative. "
                              "This is not a reasoned outlook — configure Claude to get one.")
        return result

    def analyze_industry(self, articles: list[dict], **_) -> BatchResult:
        result = BatchResult(processed_ids=[a["id"] for a in articles], engine=ENGINE)
        general = self.cfg.industry.general_ai_infra_keywords
        for a in articles:
            text = f"{a['title']} {a.get('summary') or ''}"
            r = _assess(text)
            if r["score"] == 0 and r["severity"] != "critical":
                continue  # no sentiment signal: don't guess
            lowered = text.lower()
            is_general = any(_has(lowered, k.lower()) for k in general)
            for stock in self.cfg.stocks:
                if any(_has(lowered, k.lower()) for k in stock.keywords):
                    scale, note = 1.0, ""
                elif any(_has(lowered, k.lower()) for k in self.cfg.segment(stock).keywords):
                    scale, note = 0.6, " Scaled to 60% (segment-level news)."
                elif is_general and stock.market == "TW":
                    scale, note = 0.3, " Scaled to 30% (broad AI-infrastructure news)."
                else:
                    continue
                result.rows.append(make_row(
                    article_id=a["id"], ticker=stock.ticker, target=INDUSTRY,
                    impact_pct=r["impact_pct"] * scale, confidence=r["confidence"] * 0.8, priced_in=0.4,
                    duration=r["duration"], severity=r["severity"], category=r["category"],
                    pillar="demand_supply", reasoning=_reason(r["hits"], note), engine=ENGINE,
                ))
        return result
