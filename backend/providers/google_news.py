"""Google News RSS search — free, no key, covers English and Traditional Chinese press."""
from __future__ import annotations

import calendar
import logging
import math
import time
from urllib.parse import quote

import feedparser
import requests

from ..config import NewsQuery, Stock
from .base import NewsProvider, RawArticle, strip_html

log = logging.getLogger(__name__)

EDITIONS = {
    "en": "hl=en-US&gl=US&ceid=US:en",
    "zh": "hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AIStockRadar/1.0"}


class GoogleNewsProvider(NewsProvider):
    name = "google_news"

    def _search(self, query: NewsQuery, since: int) -> list[RawArticle]:
        days = max(1, math.ceil((time.time() - since) / 86400))
        url = f"https://news.google.com/rss/search?q={quote(f'{query.q} when:{days}d')}&{EDITIONS[query.lang]}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=self.settings.request_timeout_seconds)
            resp.raise_for_status()
        except requests.RequestException as e:
            log.warning("Google News query %r failed: %s", query.q, e)
            return []

        out: list[RawArticle] = []
        for entry in feedparser.parse(resp.content).entries:
            parsed = entry.get("published_parsed")
            if not parsed:
                continue
            published = calendar.timegm(parsed)
            if published < since:
                continue
            source = (entry.get("source") or {}).get("title", "") or ""
            title = strip_html(entry.get("title"))
            if source and title.endswith(f" - {source}"):
                title = title[: -len(source) - 3]
            summary = strip_html(entry.get("summary"))
            # Google's RSS "summary" is usually just the headline + outlet again.
            if summary.startswith(title[:40]):
                summary = ""
            out.append(RawArticle(
                title=title, url=entry.get("link", ""), source=source, published_at=published,
                summary=summary, lang=query.lang, provider=self.name,
            ))
        return out

    def fetch_for_stock(self, stock: Stock, since: int) -> list[RawArticle]:
        results: list[RawArticle] = []
        for q in stock.news_queries:
            results += [a for a in self._search(q, since) if a.mentions(stock.keywords)]
        return results

    def fetch_industry(self, query: NewsQuery, since: int) -> list[RawArticle]:
        return self._search(query, since)
