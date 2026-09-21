"""Scheduled news ingestion boundary for the coverage worker.

This wraps — it does not replace — the existing CafeF RSS → ticker link →
sentiment → SQLite pipeline (``intelligence.news.pipeline``). The worker only
sees :meth:`NewsRefreshRunner.run`.

Design constraints:

* PhoBERT is loaded at most once per process: the sentiment model object is
  built on first use and reused by every later run (the transformer pipeline
  inside it is itself lazy). Telegram command handlers never touch this class.
* The runner is constructed cheaply and creates its SQLite connections
  lazily, so it can be built on any thread and first *used* on the worker
  thread that owns them (``sqlite3`` connections are thread-affine).
* The ticker linker is rebuilt every run so the universe follows the current
  ``symbols`` table; if the CafeF catalog is down the existing linker falls
  back to the SQLite universe on its own.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
import sqlite3

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NewsRunResult:
    inserted: int
    duplicates: int
    #: Distinct articles per ticker inside the coverage window (read from SQLite).
    ticker_counts: Mapping[str, int]


class NewsRefreshRunner:
    def __init__(
        self,
        *,
        connection_factory: Callable[[], sqlite3.Connection],
        repository_factory: Callable[[], object],
        provider_factory: Callable[[], object],
        catalog_factory: Callable[[], object],
        sentiment_factory: Callable[[], object],
        window_days: int = 7,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if window_days < 1:
            raise ValueError("window_days must be positive")
        self._connection_factory = connection_factory
        self._repository_factory = repository_factory
        self._provider_factory = provider_factory
        self._catalog_factory = catalog_factory
        self._sentiment_factory = sentiment_factory
        self._window_days = window_days
        self._now = now
        self._repository = None
        self._provider = None
        self._catalog = None
        self._sentiment = None

    def run(self, limit: int) -> NewsRunResult:
        from intelligence.news.pipeline import NewsIngestionService, build_ticker_linker

        if self._repository is None:
            self._repository = self._repository_factory()
            self._provider = self._provider_factory()
            self._catalog = self._catalog_factory()
        if self._sentiment is None:
            self._sentiment = self._sentiment_factory()  # one model for the process
        connection = self._connection_factory()
        try:
            linker = build_ticker_linker(connection, self._catalog)
        finally:
            connection.close()
        service = NewsIngestionService(
            self._provider, linker, self._sentiment, self._repository
        )
        inserted, duplicates = service.run_once(limit)
        counts = self._repository.ticker_article_counts(
            self._now() - timedelta(days=self._window_days)
        )
        logger.info(
            "news ingestion finished inserted=%d duplicates=%d linked_tickers=%d",
            inserted, duplicates, len(counts),
        )
        return NewsRunResult(inserted, duplicates, counts)

    def close(self) -> None:
        repository = self._repository
        self._repository = None
        connection = getattr(repository, "connection", None)
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                logger.warning("news repository close failed")


def build_news_runner_from_env(
    connection_factory: Callable[[], sqlite3.Connection], *, window_days: int = 7,
) -> NewsRefreshRunner:
    """Build the production runner with the same env contract as run_news_once."""
    from dotenv import load_dotenv

    from intelligence.news.pipeline import CafeFCompanyCatalogProvider, CafeFRSSProvider
    from intelligence.news.repository import SQLiteNewsRepository
    from intelligence.news.sentiment import build_sentiment_model

    load_dotenv()
    timeout = float(os.getenv("NEWS_HTTP_TIMEOUT", "15"))
    return NewsRefreshRunner(
        connection_factory=connection_factory,
        repository_factory=lambda: SQLiteNewsRepository(
            os.getenv("NEWS_DATABASE_PATH", "news_sentiment.db")
        ),
        provider_factory=lambda: CafeFRSSProvider(timeout=timeout),
        catalog_factory=lambda: CafeFCompanyCatalogProvider(
            url=os.getenv(
                "NEWS_COMPANY_CATALOG_URL",
                "https://cafefnew.mediacdn.vn/Search/company.json",
            ),
            timeout=timeout,
        ),
        sentiment_factory=build_sentiment_model,
        window_days=window_days,
    )
