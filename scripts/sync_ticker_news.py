"""Fetch current CafeF tag-page news for one or more listed tickers."""

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
from fundamentals.coverage_store import record_attempt
from intelligence.news.pipeline import CafeFTickerNewsProvider, refresh_ticker_news
from intelligence.news.repository import SQLiteNewsRepository
from intelligence.news.sentiment import build_sentiment_model


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="+", help="ticker symbols, e.g. FPT SSI")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-age-days", type=int, default=30)
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 50 or args.max_age_days < 1:
        parser.error("--limit must be 1..50 and --max-age-days must be positive")

    load_dotenv()
    repository = SQLiteNewsRepository(
        os.getenv("NEWS_DATABASE_PATH", "news_sentiment.db")
    )
    coverage_connection = connect_database(
        os.getenv("DATABASE_URL", "sqlite:///stock_bot.db")
    )
    bootstrap_schema(coverage_connection)
    provider = CafeFTickerNewsProvider(
        timeout=float(os.getenv("NEWS_HTTP_TIMEOUT", "15"))
    )
    sentiment = build_sentiment_model()
    try:
        for raw_symbol in args.symbols:
            symbol = raw_symbol.strip().upper()
            count = refresh_ticker_news(
                symbol, repository=repository, sentiment_model=sentiment,
                provider=provider, limit=args.limit,
                max_age_days=args.max_age_days,
            )
            status = "READY" if count >= 3 else "PARTIAL" if count else "MISSING"
            record_attempt(
                coverage_connection, symbol, "NEWS", status,
                provider="CafeF", provider_source="ticker_tag",
                error_reason=(
                    f"{count} article(s) in last {args.max_age_days}d"
                    if count else f"no relevant news in last {args.max_age_days}d"
                ),
            )
            print(f"{symbol}: fetched={count}")
    finally:
        repository.connection.close()
        coverage_connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
