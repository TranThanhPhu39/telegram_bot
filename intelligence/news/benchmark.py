"""Small reproducible benchmark primitives; no benchmark result is hard-coded."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
from collections.abc import Sequence

from intelligence.news.models import NewsItem, SentimentLabel
from intelligence.news.sentiment import SentimentModel
from intelligence.news.service import time_decay_weight


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    total: int
    correct: int
    accuracy: float
    macro_f1: float
    confusion: dict[str, dict[str, int]]


def run_benchmark(model: SentimentModel, fixture: str | Path) -> BenchmarkResult:
    rows = tuple(csv.DictReader(Path(fixture).open(encoding="utf-8-sig", newline="")))
    labels = tuple(label.value for label in SentimentLabel)
    confusion = {actual: {predicted: 0 for predicted in labels} for actual in labels}
    for index, row in enumerate(rows):
        actual = SentimentLabel(row["label"]).value
        item = NewsItem(str(index), "benchmark", f"benchmark://{index}",
                        datetime.now(timezone.utc), row["text"])
        predicted = model.analyze(item).label.value
        confusion[actual][predicted] += 1
    correct = sum(confusion[label][label] for label in labels)
    f1_values = []
    for label in labels:
        tp = confusion[label][label]
        fp = sum(confusion[actual][label] for actual in labels if actual != label)
        fn = sum(confusion[label][predicted] for predicted in labels if predicted != label)
        f1_values.append(0.0 if 2 * tp + fp + fn == 0 else 2 * tp / (2 * tp + fp + fn))
    total = len(rows)
    return BenchmarkResult(total, correct, correct / total if total else 0.0,
                           sum(f1_values) / len(f1_values), confusion)


@dataclass(frozen=True, slots=True)
class DecayProfile:
    name: str
    normalized_weights: tuple[float, ...]
    newest_share: float
    oldest_share: float


def benchmark_decay_profiles(
    age_hours: Sequence[float] = (0, 24, 72, 168, 720),
    half_lives_hours: Sequence[float] = (24, 72, 168),
) -> tuple[DecayProfile, ...]:
    """Compare equal weighting with exponential half-life choices, no news I/O."""
    ages = tuple(float(age) for age in age_hours)
    if not ages or any(not math.isfinite(age) or age < 0 for age in ages):
        raise ValueError("age_hours must contain finite non-negative values")
    profiles: list[DecayProfile] = []
    raw_equal = tuple(1.0 for _ in ages)
    equal_total = sum(raw_equal)
    equal = tuple(weight / equal_total for weight in raw_equal)
    profiles.append(DecayProfile("equal", equal, equal[0], equal[-1]))
    for half_life in half_lives_hours:
        if not math.isfinite(half_life) or half_life <= 0:
            raise ValueError("half_lives_hours must contain finite positive values")
        raw = tuple(time_decay_weight(age, half_life) for age in ages)
        total = sum(raw)
        normalized = tuple(weight / total for weight in raw)
        profiles.append(DecayProfile(
            f"half-life-{half_life:g}h", normalized, normalized[0], normalized[-1]
        ))
    return tuple(profiles)
