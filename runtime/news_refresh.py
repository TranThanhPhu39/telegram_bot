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
import threading
import time
from queue import Queue

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
    from intelligence.news.sentiment import get_shared_sentiment_model

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
        # Issue 5: shared, not build_sentiment_model directly -- a second
        # independently threaded runner (TargetedNewsRefreshWorker, below)
        # now also analyzes articles and must not load a second PhoBERT copy.
        sentiment_factory=get_shared_sentiment_model,
        window_days=window_days,
    )


# --------------------------------------------------------------------------
# Issue 5 -- targeted, on-demand per-ticker refresh
# --------------------------------------------------------------------------
#
# The run() path above is the *generic* half of the hybrid design: one
# scheduled sweep of CafeF's market-wide RSS feed, bounded to
# ``NEWS_INGEST_LIMIT`` (default 30) items, on the coverage worker's cadence.
# With a ~1,500-symbol universe that sweep only ever links a small fraction
# of tickers by chance, which is why most symbols showed NEWS MISSING even
# when CafeF had a relevant article somewhere on the site.
#
# TargetedNewsRefreshWorker is the *targeted* half: when /tin or /sentiment
# is asked about a ticker with no eligible coverage, the Telegram command
# path enqueues that symbol here (non-blocking) instead of waiting on a
# live fetch. A single background daemon thread then re-runs the existing
# CafeF RSS -> ticker link -> sentiment -> SQLite pipeline
# (``intelligence.news.pipeline.NewsIngestionService``) with a larger,
# bounded fetch limit than the periodic sweep uses, so an on-demand refresh
# samples more of CafeF's current front feed for a shot at catching that
# ticker's article, using the same ticker code / company name / alias
# linking as the generic path.
#
# This intentionally does not add a new provider or a new data source: CafeF
# does not expose a documented, stable per-ticker search or page endpoint
# that this environment could verify live, so a "CafeF ticker-page fallback"
# was not implemented -- adding an unverified scraper would risk silently
# returning wrong data or breaking on the next CafeF markup change, which is
# worse than the current honest MISSING. This mirrors how Issues 3 and 4
# treated an unavailable data source: report the gap, do not fabricate a
# provider for it.


@dataclass(frozen=True, slots=True)
class TargetedNewsRefreshResult:
    symbol: str
    inserted: int
    duplicates: int
    #: Most-recent linked articles for this ticker after the refresh
    #: (unfiltered by age; callers apply their own eligibility window).
    articles_found: int


class TargetedNewsRefreshWorker:
    """Serialize on-demand per-ticker CafeF refreshes off Telegram's path.

    Mirrors ``runtime.sector_history_sync.SectorHistorySyncWorker``: one
    daemon thread, an in-process queue, and per-symbol in-flight/cooldown
    dedup so repeated /tin or /sentiment calls for the same under-covered
    ticker (including concurrent ones) do not pile up duplicate CafeF
    fetches. ``request()`` never blocks and never raises for a normal
    duplicate/cooldown call -- Telegram command handlers only ever see the
    non-blocking bool return.
    """

    _STOP = object()

    def __init__(
        self,
        *,
        connection_factory: Callable[[], sqlite3.Connection],
        repository_factory: Callable[[], object],
        provider_factory: Callable[[], object],
        catalog_factory: Callable[[], object],
        sentiment_factory: Callable[[], object],
        fetch_limit: int = 60,
        cooldown_seconds: float = 300.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if fetch_limit < 1:
            raise ValueError("fetch_limit must be positive")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds cannot be negative")
        self._connection_factory = connection_factory
        self._repository_factory = repository_factory
        self._provider_factory = provider_factory
        self._catalog_factory = catalog_factory
        self._sentiment_factory = sentiment_factory
        self._fetch_limit = fetch_limit
        self._cooldown_seconds = cooldown_seconds
        self._monotonic = monotonic
        self._repository = None
        self._provider = None
        self._catalog = None
        self._sentiment = None
        self._queue: Queue[str | object] = Queue()
        self._lock = threading.Lock()
        self._pending: set[str] = set()
        self._last_attempt: dict[str, float] = {}
        self._listeners: list[Callable[[TargetedNewsRefreshResult], None]] = []
        self._thread: threading.Thread | None = None
        self._stopped = False

    def start(self) -> threading.Thread:
        with self._lock:
            if self._stopped:
                raise RuntimeError("targeted news refresh worker has been stopped")
            if self._thread is not None:
                return self._thread
            self._thread = threading.Thread(
                target=self._run, name="targeted-news-refresh", daemon=True
            )
            self._thread.start()
            return self._thread

    def request(self, symbol: str) -> bool:
        """Queue ``symbol`` once; False for a duplicate in-flight/cooldown call."""
        normalized = symbol.strip().upper()
        if not normalized:
            return False
        with self._lock:
            if self._stopped:
                return False
            if normalized in self._pending:
                return False
            last_attempt = self._last_attempt.get(normalized)
            if (
                last_attempt is not None
                and self._monotonic() - last_attempt < self._cooldown_seconds
            ):
                return False
            self._pending.add(normalized)
            self._queue.put(normalized)
            return True

    def add_listener(
        self, listener: Callable[[TargetedNewsRefreshResult], None]
    ) -> None:
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def stop(self, timeout: float | None = None) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            thread = self._thread
            self._queue.put(self._STOP)
        if thread is not None:
            thread.join(timeout)

    def close(self) -> None:
        repository = self._repository
        self._repository = None
        connection = getattr(repository, "connection", None)
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                logger.warning("targeted news repository close failed")

    def _run(self) -> None:
        from intelligence.news.pipeline import NewsIngestionService, build_ticker_linker

        while True:
            item = self._queue.get()
            if item is self._STOP:
                self._queue.task_done()
                return
            symbol = str(item)
            try:
                result = self._refresh_one(symbol, NewsIngestionService, build_ticker_linker)
                self._publish(result)
            except Exception:
                logger.exception(
                    "targeted news refresh failed", extra={"symbol": symbol}
                )
            finally:
                with self._lock:
                    self._pending.discard(symbol)
                    self._last_attempt[symbol] = self._monotonic()
                self._queue.task_done()

    def _refresh_one(
        self, symbol: str, news_ingestion_service_cls, build_linker
    ) -> TargetedNewsRefreshResult:
        if self._repository is None:
            self._repository = self._repository_factory()
            self._provider = self._provider_factory()
            self._catalog = self._catalog_factory()
        if self._sentiment is None:
            self._sentiment = self._sentiment_factory()  # shared across runners
        connection = self._connection_factory()
        try:
            linker = build_linker(connection, self._catalog)
        finally:
            connection.close()
        service = news_ingestion_service_cls(
            self._provider, linker, self._sentiment, self._repository
        )
        inserted, duplicates = service.run_once(self._fetch_limit)
        articles = len(self._repository.latest_for_ticker(symbol, 5))
        logger.info(
            "targeted news refresh finished symbol=%s inserted=%d duplicates=%d "
            "articles_now=%d",
            symbol, inserted, duplicates, articles,
        )
        return TargetedNewsRefreshResult(symbol, inserted, duplicates, articles)

    def _publish(self, result: TargetedNewsRefreshResult) -> None:
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(result)
            except Exception:
                logger.exception(
                    "targeted news refresh listener failed",
                    extra={"symbol": result.symbol},
                )


def build_targeted_news_refresh_worker_from_env(
    connection_factory: Callable[[], sqlite3.Connection],
) -> TargetedNewsRefreshWorker:
    """Build the production on-demand worker with the same env contract as
    ``build_news_runner_from_env``, plus its own fetch-limit/cooldown knobs.
    """
    from dotenv import load_dotenv

    from intelligence.news.pipeline import CafeFCompanyCatalogProvider, CafeFRSSProvider
    from intelligence.news.repository import SQLiteNewsRepository
    from intelligence.news.sentiment import get_shared_sentiment_model

    load_dotenv()
    timeout = float(os.getenv("NEWS_HTTP_TIMEOUT", "15"))
    return TargetedNewsRefreshWorker(
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
        sentiment_factory=get_shared_sentiment_model,
        fetch_limit=int(os.getenv("NEWS_TARGETED_FETCH_LIMIT", "60")),
        cooldown_seconds=float(os.getenv("NEWS_TARGETED_COOLDOWN_SECONDS", "300")),
    )
