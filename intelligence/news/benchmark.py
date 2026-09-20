"""Small reproducible benchmark primitives; no benchmark result is hard-coded."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from intelligence.news.models import NewsItem, SentimentLabel
from intelligence.news.sentiment import SentimentModel


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
