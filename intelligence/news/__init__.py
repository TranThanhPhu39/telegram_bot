"""News and sentiment domain boundaries."""

from intelligence.news.models import NewsItem, SentimentLabel, SentimentResult
from intelligence.news.sentiment import build_sentiment_model

__all__ = ["NewsItem", "SentimentLabel", "SentimentResult", "build_sentiment_model"]
