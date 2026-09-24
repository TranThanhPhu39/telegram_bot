"""Normalized news and complete sentiment inference records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class SentimentLabel(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


@dataclass(frozen=True, slots=True)
class SentimentResult:
    label: SentimentLabel
    probability_positive: float
    probability_neutral: float
    probability_negative: float
    model_confidence: float
    backend: str
    model_name: str
    model_version: str
    analyzed_at: datetime
    calibration_version: str | None = None

    def __post_init__(self) -> None:
        probabilities = (
            self.probability_positive, self.probability_neutral,
            self.probability_negative,
        )
        if any(value < 0 or value > 1 for value in probabilities):
            raise ValueError("sentiment probabilities must be within [0, 1]")
        if abs(sum(probabilities) - 1.0) > 1e-5:
            raise ValueError("sentiment probabilities must sum to 1")
        if not 0 <= self.model_confidence <= 1:
            raise ValueError("model_confidence must be within [0, 1]")
        if self.analyzed_at.tzinfo is None:
            raise ValueError("analyzed_at must be timezone-aware")

    @property
    def score(self) -> float:
        return self.probability_positive - self.probability_negative


@dataclass(frozen=True, slots=True)
class NewsItem:
    id: str
    source: str
    url: str
    published_at: datetime
    title: str
    summary: str = ""
    content: str = ""
    tickers: tuple[str, ...] = ()
    primary_ticker: str | None = None
    ticker_relevance: dict[str, float] = field(default_factory=dict)
    event_type: str = "OTHER"
    event_importance: float = 0.3
    sentiment: SentimentResult | None = None
    retrieved_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.published_at.tzinfo is None:
            raise ValueError("published_at must be timezone-aware")
        if self.retrieved_at is not None and self.retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        normalized = tuple(dict.fromkeys(item.strip().upper() for item in self.tickers))
        object.__setattr__(self, "tickers", normalized)
        if self.primary_ticker and self.primary_ticker.upper() not in normalized:
            raise ValueError("primary_ticker must be in tickers")

    @property
    def model_text(self) -> str:
        parts = [self.title.strip(), self.summary.strip(), self.content.strip()]
        return "\n".join(part for part in parts if part)
