"""Fetch, classify, analyze and persist one bounded CafeF RSS batch."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from data.database import connect_database
from data.migrations import bootstrap_schema
from intelligence.news.pipeline import (
    CafeFCompanyCatalogProvider,
    CafeFRSSProvider,
    NewsIngestionService,
    build_ticker_linker,
)
from intelligence.news.repository import SQLiteNewsRepository
from intelligence.news.sentiment import build_sentiment_model


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")
    load_dotenv()
    timeout = float(os.getenv("NEWS_HTTP_TIMEOUT", "15"))
    connection = connect_database(os.getenv("DATABASE_URL", "sqlite:///stock_bot.db"))
    bootstrap_schema(connection)
    try:
        linker = build_ticker_linker(
            connection,
            CafeFCompanyCatalogProvider(
                url=os.getenv(
                    "NEWS_COMPANY_CATALOG_URL",
                    "https://cafefnew.mediacdn.vn/Search/company.json",
                ),
                timeout=timeout,
            ),
        )
    finally:
        connection.close()
    service = NewsIngestionService(
        CafeFRSSProvider(timeout=timeout),
        linker, build_sentiment_model(),
        SQLiteNewsRepository(os.getenv("NEWS_DATABASE_PATH", "news_sentiment.db")),
    )
    inserted, duplicates = service.run_once(args.limit)
    print(
        f"ticker_universe={linker.symbol_count} "
        f"inserted={inserted} duplicates={duplicates}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
