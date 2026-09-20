"""Background synchronization of sector-member daily price histories."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
import logging
import os
from queue import Empty, Queue
import sqlite3
import threading
import time

from dotenv import load_dotenv

from asmf_data.store import active_sector, sector_members
from data.database import connect_database
from data.migrations import bootstrap_schema
from data.models import OHLCVBar
from data.vietcap.historical import normalize_gap_chart
from data.vietcap.rest import (
    VietcapRestClient,
    VietcapRestError,
    VietcapTimeFrame,
    normalize_stock_symbol,
)
from runtime.bot_service import HistoricalClient, VIETNAM_TIMEZONE

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SectorSyncResult:
    requested_symbol: str
    sector_code: str | None
    members: int
    downloaded: int
    cached: int
    failed: tuple[str, ...]

    @property
    def usable(self) -> int:
        return self.downloaded + self.cached


class SectorHistorySynchronizer:
    """Populate SQLite independently from Telegram command execution."""

    def __init__(
        self,
        client: HistoricalClient,
        connection: sqlite3.Connection,
        *,
        history_count: int = 260,
        minimum_bars: int = 126,
        retry_attempts: int = 3,
        retry_base_seconds: float = 2.0,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if history_count < minimum_bars:
            raise ValueError("history_count must cover minimum_bars")
        if minimum_bars < 1 or retry_attempts < 1 or retry_base_seconds < 0:
            raise ValueError("invalid sector history sync limits")
        self.client = client
        self.connection = connection
        self.history_count = history_count
        self.minimum_bars = minimum_bars
        self.retry_attempts = retry_attempts
        self.retry_base_seconds = retry_base_seconds
        self.now = now
        self.sleep = sleep
        bootstrap_schema(connection)

    def sync_symbol_sector(
        self,
        symbol: str,
        *,
        as_of: date | None = None,
        max_uncached_members: int | None = None,
    ) -> SectorSyncResult:
        if max_uncached_members is not None and max_uncached_members < 1:
            raise ValueError("max_uncached_members must be positive")
        symbol = symbol.strip().upper()
        effective_date = as_of or datetime.fromtimestamp(
            self.now(), VIETNAM_TIMEZONE
        ).date()
        membership = active_sector(self.connection, symbol, effective_date)
        if membership is None:
            return SectorSyncResult(symbol, None, 0, 0, 0, ())

        members = sector_members(
            self.connection, membership["sector_code"], effective_date
        )
        downloaded = 0
        cached = 0
        failed: list[str] = []
        uncached: list[str] = []
        for member in members:
            if self._cached_bar_count(member) >= self.minimum_bars:
                cached += 1
            else:
                uncached.append(member)
        candidates = (
            uncached if max_uncached_members is None
            else uncached[:max_uncached_members]
        )
        for member in candidates:
            bars = self._fetch_with_retry(member)
            if len(bars) < self.minimum_bars:
                failed.append(member)
                continue
            self._store(bars)
            downloaded += 1
        return SectorSyncResult(
            symbol, membership["sector_code"], len(members),
            downloaded, cached, tuple(failed),
        )

    def sync_symbols(self, symbols: Iterable[str]) -> tuple[SectorSyncResult, ...]:
        results: list[SectorSyncResult] = []
        visited_sectors: set[str] = set()
        for symbol in symbols:
            effective_date = datetime.fromtimestamp(
                self.now(), VIETNAM_TIMEZONE
            ).date()
            membership = active_sector(
                self.connection, symbol.strip().upper(), effective_date
            )
            if membership is not None and membership["sector_code"] in visited_sectors:
                continue
            result = self.sync_symbol_sector(symbol)
            results.append(result)
            if result.sector_code is not None:
                visited_sectors.add(result.sector_code)
        return tuple(results)

    def _fetch_with_retry(self, symbol: str) -> tuple[OHLCVBar, ...]:
        for attempt in range(self.retry_attempts):
            try:
                payload = self.client.get_gap_chart(
                    (symbol,), time_frame=VietcapTimeFrame.ONE_DAY,
                    count_back=self.history_count, to_timestamp=int(self.now()),
                )
                bars = tuple(
                    bar for bar in normalize_gap_chart(
                        payload, time_frame=VietcapTimeFrame.ONE_DAY
                    ) if bar.symbol == symbol
                )
                if bars:
                    return bars
            except (VietcapRestError, ValueError):
                logger.warning(
                    "Sector history fetch failed",
                    extra={"symbol": symbol, "attempt": attempt + 1},
                )
            if attempt + 1 < self.retry_attempts:
                self.sleep(self.retry_base_seconds * (2 ** attempt))
        return ()

    def _cached_bar_count(self, symbol: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM candles "
            "WHERE symbol=? AND timeframe='ONE_DAY'", (symbol,),
        ).fetchone()
        return int(row["count"])

    def _store(self, bars: tuple[OHLCVBar, ...]) -> None:
        symbol = bars[0].symbol
        with self.connection:
            self.connection.execute(
                "INSERT INTO symbols(symbol,instrument_type) VALUES (?,'STOCK') "
                "ON CONFLICT(symbol) DO NOTHING", (symbol,),
            )
            self.connection.executemany(
                "INSERT INTO candles(symbol,timeframe,timestamp,open,high,low,close,volume) "
                "VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(symbol,timeframe,timestamp) DO UPDATE SET "
                "open=excluded.open,high=excluded.high,low=excluded.low," 
                "close=excluded.close,volume=excluded.volume",
                [(bar.symbol, bar.timeframe, bar.timestamp, bar.open, bar.high,
                  bar.low, bar.close, bar.volume) for bar in bars],
            )


class SectorHistorySyncWorker:
    """Serialize periodic and on-demand sector synchronization off Telegram's path."""

    _STOP = object()

    def __init__(
        self,
        symbols: tuple[str, ...],
        *,
        interval_seconds: float,
        request_cooldown_seconds: float = 900.0,
        max_members_per_run: int = 8,
        synchronizer_factory: Callable[[], SectorHistorySynchronizer] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if request_cooldown_seconds < 0:
            raise ValueError("request_cooldown_seconds cannot be negative")
        if max_members_per_run < 1:
            raise ValueError("max_members_per_run must be positive")
        self.interval_seconds = interval_seconds
        self.request_cooldown_seconds = request_cooldown_seconds
        self.max_members_per_run = max_members_per_run
        self.synchronizer_factory = (
            synchronizer_factory or build_sector_history_synchronizer_from_env
        )
        self.monotonic = monotonic
        self._initial_symbols = tuple(
            dict.fromkeys(normalize_stock_symbol(symbol) for symbol in symbols)
        )
        self._tracked = set(self._initial_symbols)
        self._pending: set[str] = set()
        self._last_attempt: dict[str, float] = {}
        self._queue: Queue[str | object] = Queue()
        self._lock = threading.Lock()
        self._listeners: list[Callable[[SectorSyncResult], None]] = []
        self._thread: threading.Thread | None = None
        self._stopped = False

    def start(self) -> threading.Thread:
        """Start one daemon thread and seed the configured watch symbols."""
        with self._lock:
            if self._stopped:
                raise RuntimeError("sector history worker has been stopped")
            if self._thread is not None:
                return self._thread
            for symbol in self._initial_symbols:
                self._enqueue_locked(symbol, force=True)
            self._thread = threading.Thread(
                target=self._run, name="sector-history-sync", daemon=True
            )
            self._thread.start()
            return self._thread

    def request(self, symbol: str) -> bool:
        """Queue an arbitrary stock once; return False for duplicate/cooldown calls."""
        normalized = normalize_stock_symbol(symbol)
        with self._lock:
            if self._stopped:
                return False
            self._tracked.add(normalized)
            return self._enqueue_locked(normalized, force=False)

    def add_listener(self, listener: Callable[[SectorSyncResult], None]) -> None:
        """Register a quick, thread-safe observer for completed worker passes."""
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def stop(self, timeout: float | None = None) -> None:
        """Stop the daemon cooperatively; primarily useful for deterministic tests."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            thread = self._thread
            self._queue.put(self._STOP)
        if thread is not None:
            thread.join(timeout)

    def _enqueue_locked(self, symbol: str, *, force: bool) -> bool:
        if symbol in self._pending:
            return False
        last_attempt = self._last_attempt.get(symbol)
        if (
            not force
            and last_attempt is not None
            and self.monotonic() - last_attempt < self.request_cooldown_seconds
        ):
            return False
        self._pending.add(symbol)
        self._queue.put(symbol)
        return True

    def _enqueue_periodic(self) -> None:
        with self._lock:
            if self._stopped:
                return
            for symbol in sorted(self._tracked):
                self._enqueue_locked(symbol, force=True)

    def _run(self) -> None:
        synchronizer = self.synchronizer_factory()
        next_periodic = self.monotonic() + self.interval_seconds
        while True:
            timeout = max(0.0, next_periodic - self.monotonic())
            try:
                item = self._queue.get(timeout=timeout)
            except Empty:
                self._enqueue_periodic()
                next_periodic = self.monotonic() + self.interval_seconds
                continue
            if item is self._STOP:
                self._queue.task_done()
                return
            symbol = str(item)
            try:
                result = synchronizer.sync_symbol_sector(
                    symbol, max_uncached_members=self.max_members_per_run
                )
                self._publish(result)
            except Exception:
                logger.exception(
                    "Unexpected sector history synchronization failure",
                    extra={"symbol": symbol},
                )
            finally:
                with self._lock:
                    self._pending.discard(symbol)
                    self._last_attempt[symbol] = self.monotonic()
                self._queue.task_done()

    def _publish(self, result: SectorSyncResult) -> None:
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(result)
            except Exception:
                logger.exception(
                    "Sector history completion listener failed",
                    extra={"symbol": result.requested_symbol},
                )


def build_sector_history_synchronizer_from_env() -> SectorHistorySynchronizer:
    load_dotenv()
    required = {name: os.getenv(name, "").strip() for name in (
        "VIETCAP_AUTHORIZATION", "VIETCAP_DEVICE_ID", "VIETCAP_COOKIE"
    )}
    if not all(required.values()):
        raise RuntimeError("Vietcap historical credentials are missing from .env")
    client = VietcapRestClient(
        authorization=required["VIETCAP_AUTHORIZATION"],
        device_id=required["VIETCAP_DEVICE_ID"],
        cookie=required["VIETCAP_COOKIE"],
    )
    connection = connect_database(os.getenv("DATABASE_URL", "sqlite:///stock_bot.db"))
    return SectorHistorySynchronizer(
        client,
        connection,
        retry_attempts=int(os.getenv("SECTOR_HISTORY_RETRY_ATTEMPTS", "3")),
        retry_base_seconds=float(os.getenv("SECTOR_HISTORY_RETRY_BASE_SECONDS", "2")),
    )


def start_sector_history_background_sync(
    symbols: tuple[str, ...], *, interval_seconds: float,
    request_cooldown_seconds: float = 900.0,
    max_members_per_run: int = 8,
) -> SectorHistorySyncWorker:
    worker = SectorHistorySyncWorker(
        symbols,
        interval_seconds=interval_seconds,
        request_cooldown_seconds=request_cooldown_seconds,
        max_members_per_run=max_members_per_run,
    )
    worker.start()
    return worker
