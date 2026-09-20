"""Fetch, classify, analyze and persist one bounded CafeF RSS batch."""

from __future__ import annotations

import argparse
import os
from dotenv import load_dotenv

from intelligence.news.pipeline import CafeFRSSProvider, NewsIngestionService, TickerLinker
from intelligence.news.repository import SQLiteNewsRepository
from intelligence.news.sentiment import build_sentiment_model


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")
    load_dotenv()
    service = NewsIngestionService(
        CafeFRSSProvider(timeout=float(os.getenv("NEWS_HTTP_TIMEOUT", "15"))),
        TickerLinker(), build_sentiment_model(),
        SQLiteNewsRepository(os.getenv("NEWS_DATABASE_PATH", "news_sentiment.db")),
    )
    inserted, duplicates = service.run_once(args.limit)
    print(f"inserted={inserted} duplicates={duplicates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
