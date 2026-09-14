"""Yahoo Finance per-ticker news via yfinance (often includes a short summary)."""
from __future__ import annotations

import logging
from datetime import datetime

import yfinance as yf

from ..config import Stock
from .base import NewsProvider, RawArticle, strip_html

log = logging.getLogger(__name__)


def _parse_time(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


class YahooFinanceNewsProvider(NewsProvider):
    name = "yahoo_finance"

    def fetch_for_stock(self, stock: Stock, since: int) -> list[RawArticle]:
        try:
            items = yf.Ticker(stock.ticker).news or []
        except Exception as e:  # yfinance raises a variety of errors on upstream changes
            log.warning("Yahoo news for %s failed: %s", stock.ticker, e)
            return []

        out: list[RawArticle] = []
        for item in items:
            c = item.get("content") or item  # newer yfinance nests fields under "content"
            title = strip_html(c.get("title"))
            published = _parse_time(c.get("pubDate") or c.get("providerPublishTime"))
            if not title or not published or published < since:
                continue
            url = ((c.get("canonicalUrl") or {}).get("url")
                   or (c.get("clickThroughUrl") or {}).get("url")
                   or c.get("link", ""))
            source = (c.get("provider") or {}).get("displayName") or c.get("publisher", "Yahoo Finance")
            article = RawArticle(
                title=title, url=url, source=source, published_at=published,
                summary=strip_html(c.get("summary") or c.get("description")), lang="en", provider=self.name,
            )
            # Yahoo's feed for a ticker sometimes includes general market pieces.
            if article.mentions(stock.keywords):
                out.append(article)
        return out
