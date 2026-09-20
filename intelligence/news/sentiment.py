"""Pluggable Vietnamese financial sentiment backends with explicit fallback."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import logging
import os
import re
from typing import Protocol

from intelligence.news.models import NewsItem, SentimentLabel, SentimentResult

logger = logging.getLogger(__name__)


class SentimentModel(Protocol):
    def analyze(self, item: NewsItem) -> SentimentResult: ...


class LexiconSentimentModel:
    POSITIVE = ("lợi nhuận tăng", "tăng trưởng", "vượt kế hoạch", "trúng thầu", "cổ tức")
    NEGATIVE = ("khởi tố", "gian lận", "thua lỗ", "lỗ ròng", "đình chỉ", "nợ xấu tăng")

    def __init__(self, *, backend: str = "lexicon", now: Callable[[], datetime] | None = None):
        self.backend = backend
        self.now = now or (lambda: datetime.now(timezone.utc))

    def analyze(self, item: NewsItem) -> SentimentResult:
        text = re.sub(r"\s+", " ", item.model_text.lower())
        positive = sum(phrase in text for phrase in self.POSITIVE)
        negative = sum(phrase in text for phrase in self.NEGATIVE)
        if positive == negative == 0:
            probs = (.15, .70, .15)
        else:
            total = positive + negative
            pos = .1 + .8 * positive / total
            neg = .1 + .8 * negative / total
            probs = (pos, 0.0, neg)
        label = (SentimentLabel.POSITIVE if probs[0] > probs[2] else
                 SentimentLabel.NEGATIVE if probs[2] > probs[0] else SentimentLabel.NEUTRAL)
        return SentimentResult(label, probs[0], probs[1], probs[2], max(probs),
                               self.backend, "financial-lexicon", "v1", self.now())


class PhoBERTSentimentModel:
    """Lazy, load-once wrapper for LABEL_0/1/2 = negative/neutral/positive."""

    def __init__(self, model_name: str, *, device: str = "cpu", cache_dir: str | None = None,
                 loader: Callable | None = None, now: Callable[[], datetime] | None = None):
        self.model_name, self.device, self.cache_dir = model_name, device, cache_dir
        self.loader = loader
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._pipeline = None

    def _load(self):
        if self._pipeline is None:
            if self.loader:
                self._pipeline = self.loader()
            else:
                from transformers import pipeline
                self._pipeline = pipeline("text-classification", model=self.model_name,
                    tokenizer=self.model_name, device=-1, model_kwargs={"cache_dir": self.cache_dir})
        return self._pipeline

    def analyze(self, item: NewsItem) -> SentimentResult:
        output = self._load()(item.model_text, truncation=True, max_length=256,
                              top_k=None)
        if output and isinstance(output[0], list):
            output = output[0]
        mapped = {"negative": 0.0, "neutral": 0.0, "positive": 0.0}
        labels = {"LABEL_0": "negative", "LABEL_1": "neutral", "LABEL_2": "positive"}
        for row in output:
            mapped[labels.get(row["label"], row["label"].lower())] = float(row["score"])
        label = SentimentLabel(max(mapped, key=mapped.get))
        return SentimentResult(label, mapped["positive"], mapped["neutral"], mapped["negative"],
            max(mapped.values()), "phobert", self.model_name, "hf", self.now())


class FallbackSentimentModel:
    def __init__(self, primary: SentimentModel, fallback: SentimentModel):
        self.primary, self.fallback = primary, fallback

    def analyze(self, item: NewsItem) -> SentimentResult:
        try:
            return self.primary.analyze(item)
        except Exception:
            logger.exception("Transformer sentiment failed; using lexicon fallback")
            return self.fallback.analyze(item)


def build_sentiment_model() -> SentimentModel:
    lexicon = LexiconSentimentModel(backend="lexicon_fallback")
    if os.getenv("SENTIMENT_MODEL_BACKEND", "phobert").lower() == "lexicon":
        return LexiconSentimentModel()
    primary = PhoBERTSentimentModel(
        os.getenv("SENTIMENT_MODEL_NAME", "FiinGroup/phobert-finetuned"),
        device=os.getenv("SENTIMENT_DEVICE", "cpu"),
        cache_dir=os.getenv("SENTIMENT_MODEL_CACHE_DIR", ".model-cache/huggingface"),
    )
    return FallbackSentimentModel(primary, lexicon) if os.getenv(
        "SENTIMENT_FALLBACK_ENABLED", "true").lower() == "true" else primary
