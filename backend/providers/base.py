from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field

from ..config import NewsQuery, NewsSettings, Stock

_TAG_RE = re.compile(r"<[^>]+>")
_KEY_RE = re.compile(r"[\W_]+", re.UNICODE)


def strip_html(text: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", text or ""))).strip()


def title_key(title: str) -> str:
    return _KEY_RE.sub("", title.lower())


@dataclass
class RawArticle:
    title: str
    url: str
    source: str
    published_at: int
    summary: str = ""
    lang: str = "en"
    provider: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        # Same headline from different providers collapses to one article.
        return hashlib.sha1(title_key(self.title).encode()).hexdigest()[:16]

    def as_row(self) -> dict:
        return {
            "id": self.id, "title": self.title, "summary": self.summary, "url": self.url,
            "source": self.source, "published_at": self.published_at, "lang": self.lang,
            "provider": self.provider,
        }

    def mentions(self, keywords: list[str]) -> bool:
        text = f"{self.title} {self.summary}".lower()
        return any(k.lower() in text for k in keywords)


class NewsProvider:
    name = "base"

    def __init__(self, settings: NewsSettings):
        self.settings = settings

    def fetch_for_stock(self, stock: Stock, since: int) -> list[RawArticle]:
        return []

    def fetch_industry(self, query: NewsQuery, since: int) -> list[RawArticle]:
        return []
