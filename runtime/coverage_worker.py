"""Phase 25 market-wide coverage orchestration.

This module is *orchestration only*. It decides **which** symbol/dataset to
refresh, **when**, and **how carefully**; it contains no provider parsing and no
SQL about statements or flows. Every dataset is delegated to the component that
already owns it:

==================  =========================================================
FINANCIALS          ``fundamentals.refresh_service.refresh_financials``
INSTITUTIONAL       ``fundamentals.refresh_service.refresh_institutional_flow``
MARKET_HISTORY      ``SectorHistorySynchronizer.refresh_symbol_history``
SECTOR_HISTORY      the existing ``SectorHistorySyncWorker`` (requested, not run)
NEWS                ``runtime.news_refresh.NewsRefreshRunner`` (CafeF/PhoBERT)
==================  =========================================================

Two layers:

* :class:`MarketCoverageEngine` — one synchronous, bounded ``run_cycle()``.
  Deterministic, single-threaded, and directly usable by CLI scripts and tests.
* :class:`MarketCoverageWorker` — a single daemon thread that calls the engine
  on an interval and stops cooperatively.

Safety properties (each covered by tests):

* **Bounded** — at most ``batch_size`` symbols and one call per (symbol, dataset)
  per cycle, plus ``sector_requests_per_cycle`` sector hand-offs. No concurrency.
* **Failure-isolated** — a raised exception for one dataset/symbol is recorded
  as ERROR and the loop continues; every write commits on its own.
* **Restart-safe / idempotent** — all state lives in ``symbol_data_coverage``;
  an abandoned IN_PROGRESS marker expires after a lease; upserts never duplicate.
* **Rate-limit aware** — a pause between provider calls, exponential in-cycle
  backoff on ERROR, a per-dataset circuit breaker for a dead provider, and
  cross-cycle cooldowns: MISSING waits min(interval, missing_cooldown), ERROR waits
  ``error_cooldown_seconds``. Permanent-missing symbols are therefore not
  retried every few seconds.
* **Never blocks Telegram** — nothing here is imported by a command handler;
  handlers only read what this worker persisted.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import re
import sqlite3
import threading
import time

from asmf_data.store import active_sector, sector_members
from fundamentals.coverage_store import (
    DEFAULT_IN_PROGRESS_LEASE_SECONDS,
    SUCCESS_STATES,
    CoverageStatus,
    effective_status,
    load_all_coverage,
    mark_in_progress,
    mark_in_progress_bulk,
    mark_stale,
    record_attempt,
    record_attempts_bulk,
)
from fundamentals.providers.provider_chain import ProviderChain
from fundamentals.refresh_service import (
    RefreshResult,
    refresh_financials,
    refresh_institutional_flow,
)
from runtime.bot_service import MINIMUM_SECTOR_HISTORY, VIETNAM_TIMEZONE
from runtime.coverage_config import BATCH_DATASETS, CoverageConfig
from runtime.market_universe import MarketSymbol, load_market_universe
from runtime.redaction import safe_reason
from runtime.sector_history_sync import HistoryFetch, SectorSyncResult

logger = logging.getLogger(__name__)

MINIMUM_STRATEGY_HISTORY = 200

#: Mirrors ``RuntimeBotDataService.sector_history_needs_sync``: ASMF needs five
#: usable peer histories before the sector layer can be scored.
MINIMUM_USABLE_PEERS = 5

#: After this many consecutive FAILED results for one dataset inside a cycle the
#: provider is presumed down and the rest of the cycle skips it.
CIRCUIT_BREAKER_FAILURES = 3

_RATE_LIMIT_PATTERN = re.compile(r"429|rate.?limit|too many requests", re.IGNORECASE)


class HistoryClient:
    """Structural type for the market-history source (a SectorHistorySynchronizer)."""

    minimum_bars: int
    strategy_minimum_bars: int = MINIMUM_STRATEGY_HISTORY

    def refresh_symbol_history(self, symbol: str) -> HistoryFetch:  # pragma: no cover
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class DatasetOutcome:
    symbol: str
    dataset: str
    #: SUCCESS / PARTIAL / MISSING / FAILED / SKIPPED_FRESH
    result: str
    provider: str | None = None
    attempts: int = 1
    elapsed_seconds: float = 0.0
    detail: str | None = None


@dataclass(slots=True)
class CycleReport:
    started_at: datetime
    universe_size: int = 0
    due_symbols: int = 0
    selected: tuple[str, ...] = ()
    outcomes: list[DatasetOutcome] = field(default_factory=list)
    sector_requested: list[str] = field(default_factory=list)
    sector_recorded: int = 0
    sector_deferred: int = 0
    news: str | None = None
    stopped_early: bool = False
    tripped_datasets: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, dict[str, int]]:
        table: dict[str, Counter] = {}
        for outcome in self.outcomes:
            table.setdefault(outcome.dataset, Counter())[outcome.result] += 1
        return {dataset: dict(counter) for dataset, counter in sorted(table.items())}

    def summary(self) -> str:
        parts = [
            f"universe={self.universe_size}", f"due={self.due_symbols}",
            f"selected={len(self.selected)}",
        ]
        for dataset, counter in self.counts().items():
            parts.append(
                f"{dataset}[" + ",".join(f"{k}={v}" for k, v in sorted(counter.items())) + "]"
            )
        if self.sector_requested or self.sector_recorded or self.sector_deferred:
            parts.append(
                f"SECTOR[requested={len(self.sector_requested)},"
                f"recorded={self.sector_recorded},deferred={self.sector_deferred}]"
            )
        if self.news is not None:
            parts.append(f"NEWS[{self.news}]")
        if self.tripped_datasets:
            parts.append("circuit_open=" + ",".join(self.tripped_datasets))
        if self.stopped_early:
            parts.append("stopped_early=true")
        return " ".join(parts)


class MarketCoverageEngine:
    """One bounded, synchronous coverage cycle over the SQLite market universe."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        chain: ProviderChain,
        config: CoverageConfig,
        *,
        history: HistoryClient | None = None,
        sector_requester: Callable[[str], bool] | None = None,
        news_runner: object | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleep: Callable[[float], object] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        should_stop: Callable[[], bool] = lambda: False,
        in_progress_lease_seconds: float = DEFAULT_IN_PROGRESS_LEASE_SECONDS,
    ) -> None:
        self.connection = connection
        self.chain = chain
        self.config = config
        self.history = history
        self.sector_requester = sector_requester
        self.news_runner = news_runner
        self._clock = clock
        self._sleep = sleep
        self._monotonic = monotonic
        self._should_stop = should_stop
        self._lease = in_progress_lease_seconds
        self._news_last_attempt: float | None = None
        self._news_last_failed = False

    # ------------------------------------------------------------- policy
    def is_due(
        self, status: CoverageStatus | None, dataset: str, *, now: datetime,
        force: bool = False,
    ) -> bool:
        """Whether ``dataset`` should be attempted now (pure; no I/O)."""
        if force or status is None:
            return True
        interval = self.config.interval_for(dataset)
        current = now.timestamp()
        eff = effective_status(
            status, interval, now=now, in_progress_lease_seconds=self._lease
        )
        if eff == "IN_PROGRESS":
            return False  # another pass owns it and its lease has not expired
        if eff in ("NEVER_ATTEMPTED", "STALE"):
            return True
        if eff in ("READY", "PARTIAL"):
            return False  # fresh: never call a provider for fresh data
        attempted = status.last_attempt_at or 0
        if eff == "MISSING":
            # Permanent-missing cooldown: never every cycle; at most once per
            # missing_cooldown (capped by the refresh interval).
            return current - attempted >= min(interval, self.config.missing_cooldown_seconds)
        if eff == "ERROR":
            recovered = (
                status.last_success_at is not None
                and current - status.last_success_at <= interval
            )
            return (not recovered) and current - attempted >= self.config.error_cooldown_seconds
        return True

    def _plan(
        self, universe: Sequence[MarketSymbol],
        coverage: dict[tuple[str, str], CoverageStatus],
        datasets: Sequence[str], now: datetime, force: bool,
    ) -> list[tuple[MarketSymbol, tuple[str, ...]]]:
        """Due work ordered: never-attempted first, then least recently attempted,
        ties broken alphabetically by symbol (fully deterministic)."""
        entries: list[tuple[int, str, MarketSymbol, tuple[str, ...]]] = []
        for item in universe:
            due: list[str] = []
            priority: int | None = None
            for dataset in datasets:
                status = coverage.get((item.symbol, dataset))
                if not self.is_due(status, dataset, now=now, force=force):
                    continue
                due.append(dataset)
                attempted = 0 if status is None or status.last_attempt_at is None else status.last_attempt_at
                priority = attempted if priority is None else min(priority, attempted)
            if due:
                entries.append((priority or 0, item.symbol, item, tuple(due)))
        entries.sort(key=lambda entry: (entry[0], entry[1]))
        return [(entry[2], entry[3]) for entry in entries]

    # -------------------------------------------------------------- cycle
    def run_cycle(
        self, *, symbols: Sequence[str] | None = None, limit: int | None = None,
        force: bool = False, datasets: Iterable[str] | None = None,
    ) -> CycleReport:
        """Run one bounded pass. Never raises for ordinary provider/DB conditions."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        now = self._clock()
        report = CycleReport(started_at=now)
        active = set(datasets) if datasets is not None else set(self.config.datasets)

        universe = load_market_universe(
            self.connection, symbols=None if symbols is None else tuple(symbols)
        )
        report.universe_size = len(universe)
        for dataset in sorted(active):
            try:
                mark_stale(self.connection, dataset, self.config.interval_for(dataset), now=now)
            except sqlite3.Error:
                logger.exception("coverage stale sweep failed dataset=%s", dataset)
        coverage = {
            (row.symbol, row.dataset): row for row in load_all_coverage(self.connection)
        }

        batch_datasets = [name for name in BATCH_DATASETS if name in active]
        if "MARKET_HISTORY" in batch_datasets and self.history is None:
            logger.warning(
                "coverage market history skipped: no historical client configured"
            )
            batch_datasets.remove("MARKET_HISTORY")
        plan = self._plan(universe, coverage, batch_datasets, now, force)
        report.due_symbols = len(plan)
        selected = plan[: limit or self.config.batch_size]
        report.selected = tuple(item.symbol for item, _ in selected)
        self._run_batch(selected, report, force)

        if "SECTOR_HISTORY" in active and not self._stopping(report):
            self._run_sector_step(universe, coverage, now, force, report)
        if "NEWS" in active and not self._stopping(report):
            self._run_news_step(universe, now, force, report)

        logger.info("coverage cycle finished %s", report.summary())
        return report

    def preview(
        self, *, symbols: Sequence[str] | None = None, limit: int | None = None,
        force: bool = False, datasets: Iterable[str] | None = None,
    ) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """The (symbol, due datasets) a cycle would process — no writes, no network."""
        now = self._clock()
        active = set(datasets) if datasets is not None else set(self.config.datasets)
        universe = load_market_universe(
            self.connection, symbols=None if symbols is None else tuple(symbols)
        )
        coverage = {
            (row.symbol, row.dataset): row for row in load_all_coverage(self.connection)
        }
        batch = [name for name in BATCH_DATASETS if name in active]
        if "MARKET_HISTORY" in batch and self.history is None:
            batch.remove("MARKET_HISTORY")
        plan = self._plan(universe, coverage, batch, now, force)
        return tuple((item.symbol, due) for item, due in plan[: limit or self.config.batch_size])

    def close(self) -> None:
        closer = getattr(self.news_runner, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                logger.exception("coverage news runner close failed")

    # -------------------------------------------------------------- batch
    def _stopping(self, report: CycleReport) -> bool:
        if self._should_stop():
            report.stopped_early = True
            return True
        return False

    def _pause(self, seconds: float) -> None:
        if seconds > 0:
            self._sleep(seconds)

    def _run_batch(
        self, selected: Sequence[tuple[MarketSymbol, tuple[str, ...]]],
        report: CycleReport, force: bool,
    ) -> None:
        streak: dict[str, int] = {}
        tripped: set[str] = set()
        need_pause = False
        for item, due in selected:
            if self._stopping(report):
                return
            for dataset in due:
                if dataset in tripped:
                    continue
                if self._stopping(report):
                    return
                if need_pause:
                    self._pause(self.config.request_delay_seconds)
                outcome = self._refresh_one(item, dataset, force)
                report.outcomes.append(outcome)
                need_pause = outcome.result != RefreshResult.SKIPPED_FRESH.value
                if outcome.result == RefreshResult.FAILED.value:
                    streak[dataset] = streak.get(dataset, 0) + 1
                    rate_limited = bool(
                        outcome.detail and _RATE_LIMIT_PATTERN.search(outcome.detail)
                    )
                    if rate_limited or streak[dataset] >= CIRCUIT_BREAKER_FAILURES:
                        tripped.add(dataset)
                        report.tripped_datasets.append(dataset)
                        logger.warning(
                            "coverage circuit open dataset=%s reason=%s",
                            dataset, "rate_limited" if rate_limited else "consecutive_failures",
                        )
                else:
                    streak[dataset] = 0

    def _refresh_one(self, item: MarketSymbol, dataset: str, force: bool) -> DatasetOutcome:
        """One dataset for one symbol, with in-cycle retry/backoff on ERROR."""
        started = self._monotonic()
        attempts = 0
        try:
            mark_in_progress(self.connection, item.symbol, dataset, now=self._clock())
            while True:
                attempts += 1
                result, provider, reason = self._call(item, dataset, force)
                if result != RefreshResult.FAILED.value or attempts > self.config.max_retries:
                    break
                wait = self.config.retry_wait(attempts)
                logger.warning(
                    "coverage retry symbol=%s dataset=%s provider=%s attempt=%d wait=%.1fs",
                    item.symbol, dataset, provider, attempts, wait,
                )
                if _RATE_LIMIT_PATTERN.search(reason or ""):
                    break  # do not hammer a provider that is asking us to slow down
                self._pause(wait)
                if self._should_stop():
                    break
        except Exception as error:  # isolate: one symbol must never abort the batch
            reason = safe_reason(f"{type(error).__name__}: {error}")
            self._record_failure(item.symbol, dataset, reason)
            result, provider = RefreshResult.FAILED.value, None
        elapsed = self._monotonic() - started
        logger.info(
            "coverage refresh symbol=%s dataset=%s provider=%s status=%s attempts=%d elapsed=%.2fs",
            item.symbol, dataset, provider, result, attempts, elapsed,
        )
        return DatasetOutcome(
            item.symbol, dataset, result, provider, attempts, elapsed,
            None if reason is None else safe_reason(reason),
        )

    def _call(
        self, item: MarketSymbol, dataset: str, force: bool
    ) -> tuple[str, str | None, str | None]:
        """Delegate to the owning component; return (result, provider, reason)."""
        if dataset == "FINANCIALS":
            outcome = refresh_financials(
                self.connection, self.chain, item.symbol, exchange=item.provider_exchange,
                force=force,
                refresh_interval_seconds=self.config.financials_interval_seconds,
                now=self._clock(),
            )
            return outcome.result.value, outcome.provider, outcome.error_reason
        if dataset == "INSTITUTIONAL":
            outcome = refresh_institutional_flow(
                self.connection, self.chain, item.symbol, exchange=item.provider_exchange,
                force=force,
                refresh_interval_seconds=self.config.institutional_interval_seconds,
                now=self._clock(),
            )
            return outcome.result.value, outcome.provider, outcome.error_reason
        if dataset == "MARKET_HISTORY":
            return self._refresh_market_history(item.symbol)
        raise ValueError(f"unsupported batch dataset: {dataset}")

    def _refresh_market_history(self, symbol: str) -> tuple[str, str | None, str | None]:
        assert self.history is not None
        fetched = self.history.refresh_symbol_history(symbol)
        if fetched.bars:
            count = len(fetched.bars)
            minimum = getattr(
                self.history, "strategy_minimum_bars",
                getattr(self.history, "minimum_bars", MINIMUM_STRATEGY_HISTORY)
            )
            if count >= minimum:
                status, result, reason = "READY", RefreshResult.SUCCESS.value, None
            else:
                status, result = "PARTIAL", RefreshResult.PARTIAL.value
                reason = f"short history: {count} of {minimum} daily bars; need {minimum} for ASMF/CL1"
        elif fetched.errored:
            status, result = "ERROR", RefreshResult.FAILED.value
            reason = "Vietcap history request failed"
        else:
            status, result = "MISSING", RefreshResult.MISSING.value
            reason = "Vietcap returned no daily bars"
        record_attempt(
            self.connection, symbol, "MARKET_HISTORY", status,
            provider="Vietcap", provider_source="gap-chart ONE_DAY",
            error_reason=reason, now=self._clock(),
        )
        return result, "Vietcap", reason

    def _record_failure(self, symbol: str, dataset: str, reason: str) -> None:
        try:
            record_attempt(
                self.connection, symbol, dataset, "ERROR",
                error_reason=reason, now=self._clock(),
            )
        except Exception:
            logger.exception(
                "coverage could not persist failure symbol=%s dataset=%s", symbol, dataset
            )

    # ------------------------------------------------------------- sector
    def _usable_peers(self, members: Sequence[str]) -> int:
        if not members:
            return 0
        marks = ",".join("?" for _ in members)
        rows = self.connection.execute(
            "SELECT symbol, COUNT(*) AS n FROM candles "
            f"WHERE timeframe='ONE_DAY' AND symbol IN ({marks}) GROUP BY symbol",
            tuple(members),
        ).fetchall()
        return sum(1 for row in rows if int(row["n"]) >= MINIMUM_SECTOR_HISTORY)

    def _run_sector_step(
        self, universe: Sequence[MarketSymbol],
        coverage: dict[tuple[str, str], CoverageStatus],
        now: datetime, force: bool, report: CycleReport,
    ) -> None:
        """Reconcile sector coverage; hand incomplete sectors to the sector worker.

        DB-only bookkeeping (no network) is unbounded but cheap; the *network*
        work — the existing sector worker downloading peer histories — is
        capped at ``sector_requests_per_cycle`` accepted requests per cycle.
        """
        due = [
            item.symbol for item in universe
            if self.is_due(coverage.get((item.symbol, "SECTOR_HISTORY")),
                           "SECTOR_HISTORY", now=now, force=force)
        ]
        if not due:
            return
        as_of = now.astimezone(VIETNAM_TIMEZONE).date()
        by_sector: dict[str, list[str]] = {}
        no_membership: list[str] = []
        try:
            for symbol in due:
                membership = active_sector(self.connection, symbol, as_of)
                if membership is None:
                    no_membership.append(symbol)
                else:
                    by_sector.setdefault(membership["sector_code"], []).append(symbol)
            if no_membership:
                report.sector_recorded += record_attempts_bulk(
                    self.connection, "SECTOR_HISTORY",
                    [(s, "MISSING", None, None, "no sector membership") for s in no_membership],
                    now=now,
                )
            requests = 0
            for code in sorted(by_sector):
                symbols = by_sector[code]
                members = sector_members(self.connection, code, as_of)
                usable = self._usable_peers(members)
                if usable >= MINIMUM_USABLE_PEERS:
                    report.sector_recorded += record_attempts_bulk(
                        self.connection, "SECTOR_HISTORY",
                        [(s, "READY", "SQLite", "candles",
                          f"{usable}/{len(members)} peer histories cached") for s in symbols],
                        now=now,
                    )
                    continue
                if self.sector_requester is None or requests >= self.config.sector_requests_per_cycle:
                    report.sector_deferred += len(symbols)
                    continue
                try:
                    accepted = bool(self.sector_requester(symbols[0]))
                except Exception:
                    logger.exception("coverage sector request failed sector=%s", code)
                    accepted = False
                if accepted:
                    requests += 1
                    report.sector_requested.append(code)
                    mark_in_progress_bulk(self.connection, "SECTOR_HISTORY", symbols, now=now)
                else:
                    report.sector_deferred += len(symbols)  # duplicate or cooling down
        except sqlite3.Error:
            logger.exception("coverage sector reconciliation failed")

    # --------------------------------------------------------------- news
    def _news_due(self, now: datetime, force: bool) -> bool:
        if force:
            return True
        row = self.connection.execute(
            "SELECT MAX(last_attempt_at) AS last FROM symbol_data_coverage WHERE dataset='NEWS'"
        ).fetchone()
        candidates = [t for t in (row["last"], self._news_last_attempt) if t is not None]
        if not candidates:
            return True
        wait = self.config.news_interval_seconds
        if self._news_last_failed:
            wait = min(wait, self.config.error_cooldown_seconds)
        return now.timestamp() - max(candidates) >= wait

    def _run_news_step(
        self, universe: Sequence[MarketSymbol], now: datetime, force: bool,
        report: CycleReport,
    ) -> None:
        if self.news_runner is None:
            report.news = "UNAVAILABLE"
            return
        if not self._news_due(now, force):
            report.news = "NOT_DUE"
            return
        self._news_last_attempt = now.timestamp()
        try:
            result = self.news_runner.run(self.config.news_ingest_limit)
        except Exception as error:  # CafeF timeout, DB error, model failure ...
            reason = safe_reason(f"{type(error).__name__}: {error}")
            self._news_last_failed = True
            logger.warning("coverage news ingestion failed reason=%s", reason)
            report.news = f"FAILED {reason}"
            try:
                existing = self._news_symbols()
                known = [
                    (item.symbol, "ERROR", "CafeF", "rss", reason)
                    for item in universe if item.symbol in existing
                ]
                record_attempts_bulk(self.connection, "NEWS", known, now=now)
            except sqlite3.Error:
                logger.exception("coverage could not persist news failure")
            return
        self._news_last_failed = False
        window = self.config.news_window_days
        known_tickers = getattr(result, "known_tickers", frozenset())
        rows = []
        for item in universe:
            articles = int(result.ticker_counts.get(item.symbol, 0))
            if articles >= 3:
                rows.append((item.symbol, "READY", "CafeF", "rss",
                             f"{articles} article(s) in last {window}d"))
            elif articles > 0:
                rows.append((item.symbol, "PARTIAL", "CafeF", "rss",
                             f"{articles} article(s) in last {window}d"))
            elif item.symbol in known_tickers:
                rows.append((item.symbol, "STALE", "CafeF", "rss",
                             f"newest article is older than {window}d"))
            else:
                # Absence of articles is MISSING, never Neutral sentiment.
                rows.append((item.symbol, "MISSING", "CafeF", "rss",
                             f"no relevant news in last {window}d"))
        try:
            record_attempts_bulk(self.connection, "NEWS", rows, now=now)
        except sqlite3.Error:
            logger.exception("coverage could not persist news coverage")
        report.news = (
            f"OK inserted={result.inserted} duplicates={result.duplicates} "
            f"linked={sum(1 for r in rows if r[1] in SUCCESS_STATES)}"
        )

    def _news_symbols(self) -> set[str]:
        return {
            row["symbol"] for row in self.connection.execute(
                "SELECT symbol FROM symbol_data_coverage WHERE dataset='NEWS'"
            ).fetchall()
        }


def record_sector_result(
    connection: sqlite3.Connection, result: SectorSyncResult, *,
    now: datetime | None = None,
) -> int:
    """Translate one finished sector-worker pass into SECTOR_HISTORY coverage.

    Mirrors the bot's own definition: five usable peer histories is READY. The
    status applies to every member of the sector because they share the same
    peer set. Returns the number of coverage rows written.
    """
    stamp = now or datetime.now(timezone.utc)
    if result.sector_code is None:
        return record_attempts_bulk(
            connection, "SECTOR_HISTORY",
            [(result.requested_symbol, "MISSING", None, None, "no sector membership")],
            now=stamp,
        )
    provider, source = "Vietcap", "gap-chart ONE_DAY"
    detail = f"usable {result.usable}/{result.members}"
    if result.usable >= MINIMUM_USABLE_PEERS:
        status, reason = "READY", detail
    elif result.usable > 0:
        status, reason = "PARTIAL", f"{detail}; need {MINIMUM_USABLE_PEERS}"
    elif result.failed:
        status, reason = "ERROR", f"no peer history downloaded ({len(result.failed)} failed)"
    else:
        status, reason = "MISSING", f"no peer history available ({result.members} members)"
    as_of = stamp.astimezone(VIETNAM_TIMEZONE).date()
    members = set(sector_members(connection, result.sector_code, as_of))
    members.add(result.requested_symbol)
    return record_attempts_bulk(
        connection, "SECTOR_HISTORY",
        [(symbol, status, provider, source, reason) for symbol in sorted(members)],
        now=stamp,
    )


EngineFactory = Callable[[Callable[[], bool], Callable[[float], object]], MarketCoverageEngine]


class MarketCoverageWorker:
    """Run the engine on a daemon thread; stop cooperatively.

    The engine (and therefore its SQLite connection, provider clients and
    PhoBERT model) is built *inside* the worker thread by ``engine_factory``
    because sqlite3 connections are thread-affine. Startup never waits on a
    market-wide refresh: ``start()`` only spawns the thread.
    """

    def __init__(
        self,
        engine_factory: EngineFactory,
        config: CoverageConfig,
        *,
        connection_factory: Callable[[], sqlite3.Connection],
    ) -> None:
        self.config = config
        self._engine_factory = engine_factory
        self._connection_factory = connection_factory
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.last_report: CycleReport | None = None
        self.cycles_completed = 0

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> threading.Thread:
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError("coverage worker has been stopped")
            if self._thread is not None:
                return self._thread
            self._thread = threading.Thread(
                target=self._run, name="market-coverage", daemon=True
            )
            self._thread.start()
            return self._thread

    def stop(self, timeout: float | None = None) -> None:
        with self._lock:
            self._stop.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def on_sector_result(self, result: SectorSyncResult) -> None:
        """Sector-worker listener: persist its outcome as SECTOR_HISTORY coverage.

        Runs on the sector worker's thread, so it opens its own short-lived
        connection rather than sharing this worker's.
        """
        try:
            connection = self._connection_factory()
        except Exception:
            logger.exception("coverage could not open a connection for a sector result")
            return
        try:
            record_sector_result(connection, result)
        except Exception:
            logger.exception(
                "coverage could not record sector result symbol=%s", result.requested_symbol
            )
        finally:
            connection.close()

    def _run(self) -> None:
        engine: MarketCoverageEngine | None = None
        try:
            if self._stop.wait(self.config.startup_delay_seconds):
                return
            engine = self._engine_factory(self._stop.is_set, self._stop.wait)
            while not self._stop.is_set():
                try:
                    self.last_report = engine.run_cycle()
                    self.cycles_completed += 1
                except Exception:
                    logger.exception("coverage cycle crashed; will retry next interval")
                if self._stop.wait(self.config.worker_interval_seconds):
                    break
        except Exception:
            logger.exception("coverage worker could not start")
        finally:
            if engine is not None:
                engine.close()
                try:
                    engine.connection.close()
                except sqlite3.Error:
                    logger.warning("coverage worker connection close failed")
