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
from queue import Empty, Full, Queue
import sqlite3
import threading
import time

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NewsRunResult:
    inserted: int
    duplicates: int
    #: Distinct articles per ticker inside the coverage window (read from SQLite).
    ticker_counts: Mapping[str, int]
    known_tickers: frozenset[str] = frozenset()


class NewsRefreshRunner:
    def __init__(
        self,
        *,
        connection_factory: Callable[[], sqlite3.Connection],
        repository_factory: Callable[[], object],
        provider_factory: Callable[[], object],
        catalog_factory: Callable[[], object],
        sentiment_factory: Callable[[], object],
        window_days: int = 30,
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
        known = getattr(self._repository, "all_tickers_with_articles", None)
        known_tickers = (
            frozenset(known()) if callable(known) else frozenset(counts.keys())
        )
        logger.info(
            "news ingestion finished inserted=%d duplicates=%d linked_tickers=%d",
            inserted, duplicates, len(counts),
        )
        return NewsRunResult(inserted, duplicates, counts, known_tickers=known_tickers)

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
    connection_factory: Callable[[], sqlite3.Connection], *, window_days: int = 30,
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


class TargetedNewsWorker:
    """Bounded, non-blocking daemon worker for targeted ticker news refresh."""

    _STOP = object()

    def __init__(
        self,
        *,
        repository_factory: Callable[[], object],
        sentiment_factory: Callable[[], object],
        provider_factory: Callable[[], object] | None = None,
        connection_factory: Callable[[], sqlite3.Connection] | None = None,
        request_cooldown_seconds: float = 300.0,
        request_delay_seconds: float = 0.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if request_cooldown_seconds < 0 or request_delay_seconds < 0:
            raise ValueError("news request intervals cannot be negative")
        self.repository_factory = repository_factory
        self.sentiment_factory = sentiment_factory
        self.provider_factory = provider_factory
        self.connection_factory = connection_factory
        self.request_cooldown_seconds = request_cooldown_seconds
        self.request_delay_seconds = request_delay_seconds
        self.monotonic = monotonic

        self._queue: Queue[str | object] = Queue(maxsize=100)
        self._lock = threading.Lock()
        self._pending: set[str] = set()
        self._last_attempt: dict[str, float] = {}
        self._thread: threading.Thread | None = None
        self._stopped = False
        self._worker_failed = False
        self._repository = None

    def start(self) -> threading.Thread:
        with self._lock:
            if self._stopped:
                raise RuntimeError("targeted news worker has been stopped")
            if self._thread is not None:
                return self._thread
            self._thread = threading.Thread(
                target=self._run, name="targeted-news-worker", daemon=True
            )
            self._thread.start()
            return self._thread

    def request(self, symbol: str) -> bool:
        normalized = symbol.strip().upper()
        if not normalized or not normalized.isalnum():
            return False
        with self._lock:
            if self._stopped:
                return False
            if self._worker_failed:
                return False
            if self._thread is None or not self._thread.is_alive():
                return False
            if normalized in self._pending:
                return False
            last_attempt = self._last_attempt.get(normalized)
            if (
                last_attempt is not None
                and self.monotonic() - last_attempt < self.request_cooldown_seconds
            ):
                return False
            self._pending.add(normalized)

        # Claim the symbol before enqueueing it. Otherwise subsequent coverage
        # cycles can select the same first batch while it is still waiting in
        # the queue and starve later symbols in the universe.
        try:
            self._record_in_progress(normalized)
        except Exception:
            with self._lock:
                self._pending.discard(normalized)
            logger.exception("could not mark ticker news refresh in progress for %s", normalized)
            return False

        rejected_reason: str | None = None
        with self._lock:
            if self._stopped:
                rejected_reason = "ticker news worker stopped before enqueue"
            elif self._worker_failed:
                rejected_reason = "ticker news worker initialization failed"
            elif self._thread is None or not self._thread.is_alive():
                rejected_reason = "ticker news worker is not running"
            else:
                try:
                    self._queue.put_nowait(normalized)
                    return True
                except Full:
                    rejected_reason = "ticker news worker queue is full"
            self._pending.discard(normalized)

        try:
            self._record_coverage(normalized, "ERROR", rejected_reason or "ticker news enqueue failed")
        except Exception:
            logger.exception("could not persist ticker news enqueue failure for %s", normalized)
        return False

    def stop(self, timeout: float | None = None) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            thread = self._thread
            if thread is None:
                return
            try:
                self._queue.put_nowait(self._STOP)
            except Full:
                # The worker checks _stopped after draining the bounded queue.
                pass
        if thread is not threading.current_thread():
            thread.join(timeout)

    def close(self) -> None:
        thread = self._thread
        if thread is not None and thread.is_alive():
            logger.warning("targeted news worker still running; repository left open")
            return
        self._close_repository()

    def _close_repository(self) -> None:
        repository = self._repository
        self._repository = None
        connection = getattr(repository, "connection", None)
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                logger.warning("targeted news repository close failed")

    def _record_in_progress(self, symbol: str) -> None:
        if self.connection_factory is None:
            return
        connection = self.connection_factory()
        try:
            from fundamentals.coverage_store import mark_in_progress

            mark_in_progress(connection, symbol, "NEWS")
        finally:
            connection.close()

    def _record_coverage(self, symbol: str, status: str, reason: str) -> None:
        if self.connection_factory is None:
            return
        connection = self.connection_factory()
        try:
            from fundamentals.coverage_store import record_attempt

            record_attempt(
                connection,
                symbol,
                "NEWS",
                status,
                provider="CafeF",
                provider_source="ticker_page",
                error_reason=reason,
            )
        finally:
            connection.close()

    def _run(self) -> None:
        try:
            from intelligence.news.pipeline import CafeFTickerNewsProvider, refresh_ticker_news

            repository = self.repository_factory()
            self._repository = repository
            sentiment_model = self.sentiment_factory()
            provider = (
                self.provider_factory()
                if self.provider_factory is not None
                else CafeFTickerNewsProvider()
            )
        except Exception as error:
            logger.exception("targeted news worker initialization failed")
            with self._lock:
                self._worker_failed = True
            self._fail_queued_requests(error)
            return
        while True:
            try:
                item = self._queue.get(timeout=0.5)
            except Empty:
                with self._lock:
                    if self._stopped:
                        self._close_repository()
                        return
                continue
            if item is self._STOP:
                self._queue.task_done()
                self._close_repository()
                return
            symbol = str(item)
            try:
                count = refresh_ticker_news(
                    symbol,
                    repository=repository,
                    sentiment_model=sentiment_model,
                    provider=provider,
                    limit=5,
                    max_age_days=30,
                )
                current = datetime.now(timezone.utc)
                cutoff = current - timedelta(days=30)
                recent = tuple(
                    article for article in repository.latest_for_ticker(symbol, 20)
                    if cutoff <= article.published_at <= current and article.sentiment is not None
                )
                if len(recent) >= 3:
                    status, reason = "READY", f"{len(recent)} linked article(s) in last 30d"
                elif recent:
                    status, reason = "PARTIAL", f"{len(recent)} linked article(s) in last 30d"
                elif repository.latest_for_ticker(symbol, 1):
                    status, reason = "STALE", "newest linked article is older than 30d"
                else:
                    status, reason = "MISSING", "no relevant news in last 30d"
                self._record_coverage(symbol, status, reason)
            except Exception as error:
                logger.exception("targeted news refresh failed for %s", symbol)
                try:
                    status_code = getattr(error, "status_code", None)
                    reason = (
                        f"HTTP {status_code}: ticker-page refresh failed"
                        if status_code is not None
                        else f"{type(error).__name__}: ticker-page refresh failed"
                    )
                    self._record_coverage(
                        symbol,
                        "ERROR",
                        reason,
                    )
                except Exception:
                    logger.exception("failed to persist ticker-page error for %s", symbol)
            finally:
                with self._lock:
                    self._pending.discard(symbol)
                    self._last_attempt[symbol] = self.monotonic()
                self._queue.task_done()
                if self.request_delay_seconds:
                    time.sleep(self.request_delay_seconds)

    def _fail_queued_requests(self, error: Exception) -> None:
        reason = f"{type(error).__name__}: ticker news worker initialization failed"
        while True:
            try:
                item = self._queue.get_nowait()
            except Empty:
                return
            try:
                if item is not self._STOP:
                    symbol = str(item)
                    try:
                        self._record_coverage(symbol, "ERROR", reason)
                    except Exception:
                        logger.exception("could not persist initialization failure for %s", symbol)
                    with self._lock:
                        self._pending.discard(symbol)
                        self._last_attempt[symbol] = self.monotonic()
            finally:
                self._queue.task_done()


def start_targeted_news_worker_from_env(
    connection_factory: Callable[[], sqlite3.Connection] | None = None,
) -> TargetedNewsWorker:
    """Build and start the targeted ticker news refresh worker from env config."""
    from dotenv import load_dotenv

    from intelligence.news.pipeline import CafeFTickerNewsProvider
    from intelligence.news.repository import SQLiteNewsRepository
    from intelligence.news.sentiment import get_shared_sentiment_model

    load_dotenv()
    timeout = float(os.getenv("NEWS_HTTP_TIMEOUT", "15"))
    worker = TargetedNewsWorker(
        repository_factory=lambda: SQLiteNewsRepository(
            os.getenv("NEWS_DATABASE_PATH", "news_sentiment.db")
        ),
        sentiment_factory=get_shared_sentiment_model,
        provider_factory=lambda: CafeFTickerNewsProvider(timeout=timeout),
        connection_factory=connection_factory,
        request_cooldown_seconds=float(os.getenv("NEWS_ON_DEMAND_COOLDOWN_SECONDS", "300")),
        request_delay_seconds=float(os.getenv("NEWS_TICKER_FETCH_DELAY_SECONDS", "0.5")),
    )
    worker.start()
    return worker
