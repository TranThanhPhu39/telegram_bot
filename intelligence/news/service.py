"""Read-only sentiment query boundary for runtime consumers."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from intelligence.news.models import NewsItem, SentimentLabel
from intelligence.news.repository import SQLiteNewsRepository

@dataclass(frozen=True, slots=True)
class SentimentAggregate:
    ticker: str; hours: int; score: float; article_count: int
    positive_count: int; neutral_count: int; negative_count: int
    model_confidence: float; top_events: tuple[str, ...]
    latest_at: datetime | None; backends: tuple[str, ...]

class SentimentQueryService:
    def __init__(self, repository: SQLiteNewsRepository, half_life_hours: float = 24):
        self.repository, self.half_life_hours = repository, max(1.0, half_life_hours)

    def latest_news(self, ticker: str, limit: int = 5):
        return self.repository.latest_for_ticker(ticker, limit)

    def ticker_sentiment(self, ticker: str, hours: int = 24, *, now: datetime | None = None):
        end = now or datetime.now(timezone.utc); start = end - timedelta(hours=hours)
        items = tuple(x for x in self.repository.latest_for_ticker(ticker, 200)
                      if start <= x.published_at <= end and x.sentiment)
        if not items: return None
        weights = [x.event_importance * x.sentiment.model_confidence *
                   math.pow(2, -(end-x.published_at).total_seconds()/3600/self.half_life_hours) for x in items]
        total = sum(weights); score = sum(x.sentiment.score*w for x,w in zip(items,weights))/total
        labels = [x.sentiment.label for x in items]
        return SentimentAggregate(ticker.upper(), hours, score, len(items),
            labels.count(SentimentLabel.POSITIVE), labels.count(SentimentLabel.NEUTRAL),
            labels.count(SentimentLabel.NEGATIVE),
            sum(x.sentiment.model_confidence for x in items)/len(items),
            tuple(dict.fromkeys(x.event_type for x in items))[:3], max(x.published_at for x in items),
            tuple(dict.fromkeys(x.sentiment.backend for x in items)))

    def severe_negative(self, ticker: str, *, now: datetime | None = None,
                        events=("LEGAL",), negative_threshold=.75,
                        confidence_threshold=.70, max_age_hours=48) -> NewsItem | None:
        end = now or datetime.now(timezone.utc)
        for item in self.repository.latest_for_ticker(ticker, 20):
            sentiment = item.sentiment
            age = end - item.published_at
            if (item.primary_ticker == ticker.upper() and item.event_type in events and sentiment
                and sentiment.probability_negative >= negative_threshold
                and sentiment.model_confidence >= confidence_threshold
                and timedelta(0) <= age <= timedelta(hours=max_age_hours)):
                return item
        return None
