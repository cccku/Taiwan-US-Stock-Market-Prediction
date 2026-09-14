"""Read models: combines quotes, fundamentals, analyses and config into API payloads."""
from __future__ import annotations

import json
from collections import defaultdict

from .analysis.predictor import age_days, contribution, impact_score, predict
from .analysis.scoring import pillar_scores
from .config import AppConfig, Stock
from .db import INDUSTRY, Database

CRITICAL_WINDOW_DAYS = 14
FUNDAMENTAL_FIELDS = [
    "marketCap", "trailingPE", "forwardPE", "priceToSalesTrailing12Months", "targetMeanPrice",
    "targetLowPrice", "targetHighPrice", "numberOfAnalystOpinions", "recommendationKey",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "revenueGrowth", "grossMargins", "operatingMargins",
]


class Snapshot:
    """Everything needed to render the app at one moment, loaded in a few queries."""

    def __init__(self, db: Database, cfg: AppConfig, now: int):
        self.db, self.cfg, self.now = db, cfg, now
        self.ps = cfg.settings.prediction
        self.since = now - cfg.settings.news.lookback_days * 86400
        self.quotes = db.quotes()
        self.fundamentals = db.fundamentals()
        self.outlooks = db.outlooks()
        self.analyses_by_ticker: dict[str, list[dict]] = defaultdict(list)
        for a in db.analyses(self.since):
            self.analyses_by_ticker[a["ticker"]].append(a)
        self._states: dict[str, dict] = {}

    # ── per-stock state ──────────────────────────────────────────────────────
    def state(self, stock: Stock) -> dict:
        if stock.ticker in self._states:
            return self._states[stock.ticker]
        q = self.quotes.get(stock.ticker) or {}
        f = self.fundamentals.get(stock.ticker) or {}
        analyses = self.analyses_by_ticker.get(stock.ticker, [])
        price = q.get("price")
        prev = q.get("prev_close")
        pred = predict(price, analyses, f, self.now, self.ps)
        st = {
            "quote": q, "fundamentals": f, "analyses": analyses, "prediction": pred,
            "pillars": pillar_scores(stock, analyses, f, price, self.now),
            "change": (price - prev) if price is not None and prev else None,
            "change_pct": (price / prev - 1) if price is not None and prev else None,
        }
        self._states[stock.ticker] = st
        return st

    def base_row(self, stock: Stock) -> dict:
        st = self.state(stock)
        q, pred = st["quote"], st["prediction"]
        seg = self.cfg.segment(stock)
        recent = [a for a in st["analyses"] if age_days(a["published_at"], self.now) <= 7]
        critical = [
            {"title": a["title"], "impact_pct": a["impact_pct"], "published_at": a["published_at"], "url": a["url"]}
            for a in st["analyses"]
            if a["severity"] == "critical" and a["impact_pct"] < 0
            and age_days(a["published_at"], self.now) <= CRITICAL_WINDOW_DAYS
        ]
        return {
            "ticker": stock.ticker, "name": stock.name, "name_local": stock.name_local,
            "market": stock.market, "segment": stock.segment, "segment_label": seg.label, "group": seg.group,
            "currency": q.get("currency") or stock.currency,
            "price": q.get("price"), "prev_close": q.get("prev_close"),
            "change": st["change"], "change_pct": st["change_pct"],
            "market_time": q.get("market_time"), "quote_updated_at": q.get("updated_at"),
            "predicted_price": pred["predicted_price"], "expected_return": pred["expected_return"],
            "news_return": pred["news_return"], "valuation_return": pred["valuation_return"],
            "outlook": pred["outlook"],
            "pillars": {k: v["score"] for k, v in st["pillars"].items()},
            "news_count_7d": len(recent),
            "last_news_at": max((a["published_at"] for a in st["analyses"]), default=None),
            "critical_events": critical,
        }

    def serialize_analysis(self, a: dict) -> dict:
        return {
            "article_id": a["article_id"], "ticker": a["ticker"],
            "scope": "industry" if a["target"] == INDUSTRY else "company",
            "title": a["title"], "summary": a["summary"], "url": a["url"], "source": a["source"],
            "published_at": a["published_at"], "lang": a["lang"],
            "direction": a["direction"], "impact_pct": a["impact_pct"], "confidence": a["confidence"],
            "priced_in": a["priced_in"], "duration": a["duration"], "severity": a["severity"],
            "category": a["category"], "pillar": a["pillar"], "pillar_delta": a["pillar_delta"],
            "company_decision": bool(a["company_decision"]), "market_alignment": a["market_alignment"],
            "alignment_note": a["alignment_note"], "reasoning": a["reasoning"], "engine": a["engine"],
            "contribution_pct": round(contribution(a, self.now, self.ps) * 100, 2),
            "impact_score": round(impact_score(a, self.now, self.ps), 3),
        }

    # ── payloads ─────────────────────────────────────────────────────────────
    def dashboard(self, prefs: dict) -> dict:
        favorites = prefs.get("favorites", [])
        rows = []
        for stock in self.cfg.stocks:
            row = self.base_row(stock)
            row["favorite"] = stock.ticker in favorites
            row["favorite_rank"] = favorites.index(stock.ticker) if row["favorite"] else None
            rows.append(row)
        alerts = sorted(
            ({**e, "ticker": r["ticker"], "name": r["name"]} for r in rows for e in r["critical_events"]),
            key=lambda e: e["published_at"], reverse=True,
        )
        return {
            "stocks": rows,
            "alerts": alerts,
            "markets": sorted({s.market for s in self.cfg.stocks}),
            "groups": sorted({self.cfg.segment(s).group for s in self.cfg.stocks}),
            "generated_at": self.now,
        }

    def stock_detail(self, stock: Stock) -> dict:
        st = self.state(stock)
        pred = st["prediction"]
        row = self.base_row(stock)
        f = st["fundamentals"]
        drivers = [
            {**self.serialize_analysis(a), "contribution_pct": round(c * 100, 2)}
            for a, c in pred["contributions"][:5] if abs(c) >= 0.0005
        ]
        links = self.cfg.industry.links
        chain = {
            "upstream": [self._node(l.source) | {"what": l.what} for l in links if l.target == stock.ticker],
            "downstream": [self._node(l.target) | {"what": l.what} for l in links if l.source == stock.ticker],
        }
        history = self.db.prediction_history(stock.ticker, since=self.now - 400 * 86400)
        outlook = self.outlooks.get(stock.ticker)
        return {
            **row,
            "thesis": stock.thesis.model_dump(),
            "fundamentals": {k: f.get(k) for k in FUNDAMENTAL_FIELDS},
            "fundamentals_updated_at": f.get("_updated_at"),
            "pillars_detail": st["pillars"],
            "valuation_anchor": pred["valuation"],
            "drivers": drivers,
            "outlook_summary": outlook,
            "supply_chain": chain,
            "news": [self.serialize_analysis(a) for a in st["analyses"]],
            "prediction_history": [
                {"t": h["created_at"], "predicted_price": h["predicted_price"], "base_price": h["base_price"],
                 "expected_return": h["expected_return"], "note": h["note"]}
                for h in history
            ],
            "horizon_days": self.ps.horizon_days,
        }

    def news_hub(self, market: str | None = None, direction: str | None = None,
                 scope: str | None = None, days: int | None = None, limit: int = 300) -> dict:
        stocks = {s.ticker: s for s in self.cfg.stocks}
        by_article: dict[str, list[dict]] = defaultdict(list)
        for ticker, analyses in self.analyses_by_ticker.items():
            if ticker in stocks:
                for a in analyses:
                    by_article[a["article_id"]].append(a)

        items = []
        for analyses in by_article.values():
            first = analyses[0]
            if days and age_days(first["published_at"], self.now) > days:
                continue
            impacts = sorted(
                (self.serialize_analysis(a) | {"name": stocks[a["ticker"]].name, "market": stocks[a["ticker"]].market}
                 for a in analyses),
                key=lambda x: x["impact_score"], reverse=True,
            )
            if market and not any(i["market"] == market for i in impacts):
                continue
            net = sum(i["contribution_pct"] for i in impacts)
            overall = "positive" if net > 0.05 else "negative" if net < -0.05 else "neutral"
            if direction and overall != direction:
                continue
            item_scope = "company" if any(i["scope"] == "company" for i in impacts) else "industry"
            if scope and item_scope != scope:
                continue
            scores = [i["impact_score"] for i in impacts]
            items.append({
                "article_id": first["article_id"], "title": first["title"], "summary": first["summary"],
                "url": first["url"], "source": first["source"], "published_at": first["published_at"],
                "lang": first["lang"], "scope": item_scope, "direction": overall,
                "severity": max((i["severity"] for i in impacts),
                                key=["low", "moderate", "major", "critical"].index),
                "impact_score": round(scores[0] + 0.25 * sum(scores[1:]), 3),
                "impacts": impacts,
            })
        items.sort(key=lambda x: x["impact_score"], reverse=True)
        return {"items": items[:limit], "total": len(items), "generated_at": self.now}

    def supply_chain(self) -> dict:
        nodes = [self._node(s.ticker) for s in self.cfg.stocks]
        nodes += [self._node(n.id) for n in self.cfg.industry.external_nodes]
        return {"nodes": nodes, "links": [l.model_dump() for l in self.cfg.industry.links]}

    def _node(self, node_id: str) -> dict:
        stock = self.cfg.stock(node_id)
        if stock is None:
            ext = next(n for n in self.cfg.industry.external_nodes if n.id == node_id)
            return {"id": ext.id, "label": ext.label, "detail": ext.detail, "kind": "external"}
        pred = self.state(stock)["prediction"]
        seg = self.cfg.segment(stock)
        return {
            "id": stock.ticker, "label": stock.name, "name_local": stock.name_local, "kind": "stock",
            "market": stock.market, "segment_label": seg.label, "group": seg.group,
            "outlook": pred["outlook"], "expected_return": pred["expected_return"],
            "detail": stock.thesis.niche,
        }


def record_predictions(db: Database, cfg: AppConfig, now: int) -> int:
    """Append a prediction-history row whenever the *inputs* change (news set or analyst
    consensus) — never merely because the market price moved."""
    snap = Snapshot(db, cfg, now)
    written = 0
    for stock in cfg.stocks:
        st = snap.state(stock)
        price = st["quote"].get("price")
        if price is None:
            continue
        pred = st["prediction"]
        articles = sorted(a["article_id"] for a, c in pred["contributions"] if abs(c) >= 0.0005)
        target = round(pred["valuation"]["target"], 2) if pred["valuation"] else None
        signature = json.dumps({"articles": articles, "target": target})

        last = db.last_prediction(stock.ticker)
        if last and last["signature"] == signature:
            continue
        prev = json.loads(last["signature"]) if last else {"articles": [], "target": None}
        added = sorted(set(articles) - set(prev["articles"]))
        notes = []
        if not last:
            notes.append("Initial estimate")
        if added:
            notes.append(f"{len(added)} new news item{'s' if len(added) > 1 else ''}")
        if set(prev["articles"]) - set(articles):
            notes.append("older news faded out")
        if last and target != prev["target"]:
            notes.append("analyst consensus changed")
        db.add_prediction({
            "ticker": stock.ticker, "created_at": now, "base_price": price,
            "predicted_price": pred["predicted_price"], "expected_return": pred["expected_return"],
            "news_return": pred["news_return"], "valuation_return": pred["valuation_return"],
            "signature": signature, "note": ", ".join(notes) or "inputs updated",
            "trigger_articles": json.dumps(added),
        })
        written += 1
    return written
