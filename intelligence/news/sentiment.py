"""Pluggable Vietnamese financial sentiment backends with explicit fallback."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
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
            # No recognized evidence is uncertainty, not confident neutrality.
            probs = (1 / 3, 1 / 3, 1 / 3)
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


_FINANCIAL_METRIC = (
    r"(?:lợi nhuận(?: sau thuế)?|lnst|lãi ròng|lãi sau thuế|doanh thu|eps|"
    r"hợp đồng(?: mới)?|đơn hàng(?: mới)?|giá trị trúng thầu)"
)
_FINANCIAL_UP = r"(?:tăng(?: trưởng)?|vượt kế hoạch|cao hơn|lập kỷ lục|đạt kỷ lục|cải thiện)"
_FINANCIAL_DOWN = r"(?:giảm|sụt|lao dốc|thấp hơn|không đạt kế hoạch)"
_FINANCIAL_LOSS = r"(?:báo lỗ|lỗ ròng|lỗ sau thuế|thua lỗ)"
FINANCIAL_CALIBRATION_VERSION = "vn-financial-headline-v1"


def _financial_headline_direction(text: str) -> SentimentLabel | None:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    # Explicit negation makes these directional words non-evidence.
    normalized = re.sub(
        r"\b(?:không|chưa)\s+(?:tăng(?: trưởng)?|giảm|sụt|cao hơn)\b",
        " ", normalized,
    )

    def related(metric_action: str) -> bool:
        metric_then_action = re.search(
            rf"\b{_FINANCIAL_METRIC}\b.{{0,72}}\b{metric_action}\b", normalized
        )
        action_then_metric = re.search(
            rf"\b{metric_action}\b.{{0,72}}\b{_FINANCIAL_METRIC}\b", normalized
        )
        return metric_then_action is not None or action_then_metric is not None

    positive_direction = related(_FINANCIAL_UP)
    negative_direction = related(_FINANCIAL_DOWN) or re.search(
        rf"\b{_FINANCIAL_LOSS}\b", normalized
    ) is not None

    if positive_direction and negative_direction:
        return None
    if negative_direction:
        return SentimentLabel.NEGATIVE
    if positive_direction:
        return SentimentLabel.POSITIVE

    # A concrete statement of positive net profit is directional evidence;
    # a bare mention of revenue/profit without direction is not.
    if re.search(
        r"\blãi ròng\s+(?:gần\s+|đạt\s+|hơn\s+)?\d[\d.,]*\s*(?:tỷ|triệu)\b",
        normalized,
    ):
        return SentimentLabel.POSITIVE
    return None


class FinancialHeadlineCalibrationModel:
    """Apply only high-precision financial direction evidence to model output.

    Ambiguous, mixed, or merely topical headlines retain the underlying model
    result unchanged. Clear profit/loss direction is softly calibrated to a
    modest directional margin rather than promoted to a high-confidence call.
    """

    minimum_directional_score = 0.20
    minimum_label_margin = 0.05

    def __init__(self, model: SentimentModel):
        self.model = model

    def analyze(self, item: NewsItem) -> SentimentResult:
        result = self.model.analyze(item)
        direction = _financial_headline_direction(item.model_text)
        if direction is None:
            return replace(result, calibration_version=FINANCIAL_CALIBRATION_VERSION)

        positive = result.probability_positive
        neutral = result.probability_neutral
        negative = result.probability_negative
        target_score = self.minimum_directional_score

        if direction == SentimentLabel.POSITIVE:
            gap = max(0.0, target_score - (positive - negative))
            transfer = min(neutral, gap)
            positive += transfer
            neutral -= transfer
            gap -= transfer
            transfer = min(negative, gap / 2.0)
            positive += transfer
            negative -= transfer
            if positive <= neutral:
                transfer = min(neutral, (neutral - positive + self.minimum_label_margin) / 2.0)
                positive += transfer
                neutral -= transfer
        else:
            gap = max(0.0, target_score - (negative - positive))
            transfer = min(neutral, gap)
            negative += transfer
            neutral -= transfer
            gap -= transfer
            transfer = min(positive, gap / 2.0)
            negative += transfer
            positive -= transfer
            if negative <= neutral:
                transfer = min(neutral, (neutral - negative + self.minimum_label_margin) / 2.0)
                negative += transfer
                neutral -= transfer

        total = positive + neutral + negative
        positive, neutral, negative = (
            positive / total, neutral / total, negative / total
        )
        label = SentimentLabel(max(
            ((SentimentLabel.POSITIVE, positive),
             (SentimentLabel.NEUTRAL, neutral),
             (SentimentLabel.NEGATIVE, negative)),
            key=lambda pair: pair[1],
        )[0])
        return replace(
            result,
            label=label,
            probability_positive=positive,
            probability_neutral=neutral,
            probability_negative=negative,
            model_confidence=max(positive, neutral, negative),
            calibration_version=FINANCIAL_CALIBRATION_VERSION,
        )


def build_sentiment_model() -> SentimentModel:
    lexicon = LexiconSentimentModel(backend="lexicon_fallback")
    if os.getenv("SENTIMENT_MODEL_BACKEND", "phobert").lower() == "lexicon":
        return FinancialHeadlineCalibrationModel(LexiconSentimentModel())
    primary = PhoBERTSentimentModel(
        os.getenv("SENTIMENT_MODEL_NAME", "FiinGroup/phobert-finetuned"),
        device=os.getenv("SENTIMENT_DEVICE", "cpu"),
        cache_dir=os.getenv("SENTIMENT_MODEL_CACHE_DIR", ".model-cache/huggingface"),
    )
    base = FallbackSentimentModel(primary, lexicon) if os.getenv(
        "SENTIMENT_FALLBACK_ENABLED", "true").lower() == "true" else primary
    return FinancialHeadlineCalibrationModel(base)


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
