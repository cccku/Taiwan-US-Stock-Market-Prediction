"""Loads and validates config/*.yaml. Adding a stock only requires editing watchlist.yaml."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = Path(os.environ.get("AISTOCK_CONFIG_DIR", ROOT / "config"))
DATA_DIR = Path(os.environ.get("AISTOCK_DATA_DIR", ROOT / "data"))
FRONTEND_DIR = ROOT / "frontend"

Lang = Literal["en", "zh"]


# ── settings.yaml ────────────────────────────────────────────────────────────
class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765


class RefreshSettings(BaseModel):
    interval_seconds: int = 300
    min_gap_seconds: int = 45
    fundamentals_ttl_hours: float = 6


class NewsSettings(BaseModel):
    lookback_days: int = 30
    max_new_articles_per_stock: int = 12
    max_new_industry_articles: int = 20
    providers: list[str] = ["google_news", "yahoo_finance"]
    request_timeout_seconds: float = 15
    max_workers: int = 4


class AnalysisSettings(BaseModel):
    engine: Literal["auto", "llm", "heuristic"] = "auto"
    model: str = "claude-opus-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    use_fallbacks: bool = True
    batch_size: int = 10
    max_workers: int = 4
    request_timeout_seconds: float = 300


class HalfLife(BaseModel):
    transient: float = 5
    medium: float = 21
    structural: float = 90


class PredictionSettings(BaseModel):
    horizon_days: int = 90
    half_life_days: HalfLife = HalfLife()
    positive_cap: float = 0.40
    negative_cap: float = 0.85
    valuation_weight: float = 0.0
    valuation_cap: float = 0.15
    neutral_band: float = 0.01


class Settings(BaseModel):
    server: ServerSettings = ServerSettings()
    refresh: RefreshSettings = RefreshSettings()
    news: NewsSettings = NewsSettings()
    analysis: AnalysisSettings = AnalysisSettings()
    prediction: PredictionSettings = PredictionSettings()


# ── watchlist.yaml ───────────────────────────────────────────────────────────
class NewsQuery(BaseModel):
    q: str
    lang: Lang = "en"


class Thesis(BaseModel):
    niche: str
    demand: str
    supply: str
    leadership: str
    product: str


class PillarBaseline(BaseModel):
    leadership: float = Field(ge=0, le=10)
    product: float = Field(ge=0, le=10)


class Stock(BaseModel):
    ticker: str
    name: str
    name_local: str | None = None
    market: Literal["TW", "US"]
    segment: str
    thesis: Thesis
    pillars: PillarBaseline
    keywords: list[str]
    news_queries: list[NewsQuery]

    @property
    def currency(self) -> str:
        return "TWD" if self.market == "TW" else "USD"


# ── industry.yaml ────────────────────────────────────────────────────────────
class Segment(BaseModel):
    label: str
    group: str
    keywords: list[str] = []


class ExternalNode(BaseModel):
    id: str
    label: str
    detail: str = ""


class Link(BaseModel):
    source: str
    target: str
    what: str


class Industry(BaseModel):
    segments: dict[str, Segment]
    external_nodes: list[ExternalNode] = []
    general_ai_infra_keywords: list[str] = []
    links: list[Link] = []
    queries: list[NewsQuery] = []


class AppConfig(BaseModel):
    settings: Settings
    stocks: list[Stock]
    industry: Industry

    @model_validator(mode="after")
    def _check_references(self) -> "AppConfig":
        tickers = [s.ticker for s in self.stocks]
        dupes = {t for t in tickers if tickers.count(t) > 1}
        if dupes:
            raise ValueError(f"watchlist.yaml: duplicate tickers {sorted(dupes)}")
        for s in self.stocks:
            if s.segment not in self.industry.segments:
                raise ValueError(f"watchlist.yaml: {s.ticker} uses unknown segment '{s.segment}'")
        node_ids = set(tickers) | {n.id for n in self.industry.external_nodes}
        for link in self.industry.links:
            for end in (link.source, link.target):
                if end not in node_ids:
                    raise ValueError(f"industry.yaml: link references unknown node '{end}'")
        return self

    def stock(self, ticker: str) -> Stock | None:
        return next((s for s in self.stocks if s.ticker == ticker), None)

    def segment(self, stock: Stock) -> Segment:
        return self.industry.segments[stock.segment]

    def node_label(self, node_id: str) -> str:
        if (s := self.stock(node_id)) is not None:
            return s.name
        return next((n.label for n in self.industry.external_nodes if n.id == node_id), node_id)


def _read_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_env_file() -> None:
    """Load KEY=VALUE pairs from config/.env without overriding the real environment."""
    path = CONFIG_DIR / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return AppConfig(
        settings=Settings.model_validate(_read_yaml("settings.yaml")),
        stocks=_read_yaml("watchlist.yaml").get("stocks", []),
        industry=Industry.model_validate(_read_yaml("industry.yaml")),
    )


def reload_config() -> AppConfig:
    get_config.cache_clear()
    return get_config()
