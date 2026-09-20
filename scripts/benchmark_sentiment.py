"""Run the configured model against the checked-in Vietnamese benchmark."""

from pathlib import Path
from intelligence.news.benchmark import run_benchmark
from intelligence.news.sentiment import build_sentiment_model


if __name__ == "__main__":
    result = run_benchmark(
        build_sentiment_model(),
        Path(__file__).parents[1] / "tests" / "fixtures" / "sentiment_benchmark.csv",
    )
    print(result)
