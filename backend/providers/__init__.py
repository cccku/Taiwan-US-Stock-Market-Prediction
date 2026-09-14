from .base import NewsProvider, RawArticle
from .google_news import GoogleNewsProvider
from .yahoo_news import YahooFinanceNewsProvider

# Register new news sources here (and list them under news.providers in settings.yaml).
NEWS_PROVIDERS: dict[str, type[NewsProvider]] = {
    GoogleNewsProvider.name: GoogleNewsProvider,
    YahooFinanceNewsProvider.name: YahooFinanceNewsProvider,
}

__all__ = ["NEWS_PROVIDERS", "NewsProvider", "RawArticle"]
