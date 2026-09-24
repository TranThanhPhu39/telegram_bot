"""Pluggable Vietnamese financial sentiment backends with explicit fallback."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import logging
import os
import re
import threading
from typing import Protocol

from intelligence.news.models import NewsItem, SentimentLabel, SentimentResult

logger = logging.getLogger(__name__)


class SentimentModel(Protocol):
    def analyze(self, item: NewsItem) -> SentimentResult: ...


class LexiconSentimentModel:
    """Conservative, auditable Vietnamese financial-news classifier.

    Unknown language is neutral instead of being forced into a directional
    bucket.  This is intentional: a false negative can block ASMF, while a
    neutral result is only context.  Directional accounting phrases are scored
    before generic phrases so mixed results such as revenue down/profit up stay
    mixed rather than inheriting one keyword's label.
    """

    POSITIVE = (
        "lãi kỷ lục", "lợi nhuận kỷ lục", "vượt kế hoạch", "vượt kỳ vọng",
        "trúng thầu", "ký hợp đồng", "hợp đồng mới", "mua ròng",
        "tăng trưởng", "tăng vốn", "nâng hạng", "cổ tức tiền mặt",
        "hoàn tất mua", "lãi ròng", "có lãi",
    )
    NEGATIVE = (
        "khởi tố", "gian lận", "thua lỗ", "lỗ ròng", "đình chỉ",
        "nợ xấu tăng", "bán tháo", "hủy niêm yết", "phá sản", "vỡ nợ",
        "xử phạt", "truy thu", "giảm sâu", "lao dốc", "sụt giảm",
        "xả mạnh", "bán ròng", "mất gần", "mất hơn",
    )
    POSITIVE_PATTERNS = (
        re.compile(
            r"(?:lợi nhuận|lãi ròng|doanh thu|doanh số|eps).{0,40}"
            r"(?:tăng|tăng trưởng|vượt|cao hơn)",
            re.I,
        ),
    )
    NEGATIVE_PATTERNS = (
        re.compile(
            r"(?:lợi nhuận|lãi ròng|doanh thu|doanh số|eps).{0,40}"
            r"(?:giảm|sụt|lao dốc|âm)",
            re.I,
        ),
    )

    def __init__(self, *, backend: str = "lexicon", now: Callable[[], datetime] | None = None):
        self.backend = backend
        self.now = now or (lambda: datetime.now(timezone.utc))

    def analyze(self, item: NewsItem) -> SentimentResult:
        text = re.sub(r"\s+", " ", item.model_text.lower())
        positive = sum(phrase in text for phrase in self.POSITIVE)
        negative = sum(phrase in text for phrase in self.NEGATIVE)
        positive += 2 * sum(pattern.search(text) is not None for pattern in self.POSITIVE_PATTERNS)
        negative += 2 * sum(pattern.search(text) is not None for pattern in self.NEGATIVE_PATTERNS)
        if positive == negative == 0:
            probs = (.10, .80, .10)
        elif positive and negative:
            total = positive + negative
            # Mixed evidence should not be presented with false certainty.
            probs = (.45 * positive / total, .55, .45 * negative / total)
        else:
            total = positive + negative
            pos = .10 + .80 * positive / total
            neg = .10 + .80 * negative / total
            probs = (pos, 0.0, neg)
        label = (
            SentimentLabel.POSITIVE,
            SentimentLabel.NEUTRAL,
            SentimentLabel.NEGATIVE,
        )[max(range(3), key=probs.__getitem__)]
        return SentimentResult(label, probs[0], probs[1], probs[2], max(probs),
                               self.backend, "financial-rules", "v2", self.now(),
                               calibration_version="rules-v2")


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
    backend = os.getenv("SENTIMENT_MODEL_BACKEND", "financial_rules").lower()
    rules = LexiconSentimentModel(backend="financial_rules")
    if backend in {"lexicon", "financial_rules", "rules"}:
        return rules
    if os.getenv("SENTIMENT_ALLOW_UNVALIDATED_TRANSFORMER", "false").lower() != "true":
        logger.warning(
            "Transformer sentiment is disabled because its generic LABEL_0/1/2 "
            "semantics and local benchmark are not production-validated; using "
            "conservative financial rules"
        )
        return rules
    lexicon = LexiconSentimentModel(backend="financial_rules_fallback")
    primary = PhoBERTSentimentModel(
        os.getenv("SENTIMENT_MODEL_NAME", "FiinGroup/phobert-finetuned"),
        device=os.getenv("SENTIMENT_DEVICE", "cpu"),
        cache_dir=os.getenv("SENTIMENT_MODEL_CACHE_DIR", ".model-cache/huggingface"),
    )
    return FallbackSentimentModel(primary, lexicon) if os.getenv(
        "SENTIMENT_FALLBACK_ENABLED", "true").lower() == "true" else primary


_shared_model: SentimentModel | None = None
_shared_model_lock = threading.Lock()


def get_shared_sentiment_model() -> SentimentModel:
    """Process-wide singleton over ``build_sentiment_model()``.

    PhoBERT (via :class:`PhoBERTSentimentModel`) is expensive to load and is
    meant to be loaded at most once per process (see
    ``runtime/news_refresh.py``'s module docstring). Before Issue 5's
    on-demand targeted refresh worker, only one caller (the periodic
    coverage-worker ``NewsRefreshRunner``) ever built a sentiment model, so a
    plain per-runner instance was enough. With a second, independently
    threaded runner now also analyzing articles, both must share this one
    instance instead of each loading their own copy of the model.
    """
    global _shared_model
    if _shared_model is None:
        with _shared_model_lock:
            if _shared_model is None:
                _shared_model = build_sentiment_model()
    return _shared_model
