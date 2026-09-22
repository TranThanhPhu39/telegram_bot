"""Market-wide background scanner worker and snapshot persistence.

This module provides:
1. Snapshot persistence in SQLite (`scan_snapshots` table).
2. Background scan execution over all active common stocks from SQLite.
3. Fast snapshot retrieval for Telegram /scan command (<50ms).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
import sqlite3
import threading
import time
from typing import Callable, Mapping, Sequence

from asmf_data.store import latest_financial_reports
from data.models import OHLCVBar
from runtime.analysis import build_scan_row, build_strategy_view, build_technical_view
from runtime.market_universe import load_market_universe
from runtime.views import ScanRowView
from scanner.universe import (
    ScannerConfig,
    ScannerInstrument,
    daily_prescreen,
    realtime_watch_universe,
)
from strategy.technical_strategies import evaluate_cl1

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScanSnapshot:
    id: int
    strategy: str
    as_of_date: str
    scanned_at: int
    total_universe: int
    screened_count: int
    rows: tuple[ScanRowView, ...]


@dataclass(frozen=True, slots=True)
class ScannerWorkerConfig:
    lookback_days: int = 20
    minimum_average_daily_volume: float = 10_000.0
    minimum_average_daily_value: float = 1_000_000_000.0
    maximum_watch_symbols: int = 20
    scan_interval_seconds: int = 300


def save_scan_snapshot(
    connection: sqlite3.Connection,
    *,
    strategy: str,
    as_of_date: str,
    scanned_at: int,
    total_universe: int,
    screened_count: int,
    rows: Sequence[ScanRowView],
) -> int:
    """Serialize and store a scan snapshot in SQLite, pruning snapshots older than 7 days."""
    payload = [
        {
            "symbol": r.symbol,
            "trend": r.trend,
            "relative_strength": r.relative_strength,
            "liquidity": r.liquidity,
            "fundamental": r.fundamental,
            "strategy_state": r.strategy_state,
        }
        for r in rows
    ]
    payload_json = json.dumps(payload, ensure_ascii=False)
    with connection:
        cursor = connection.execute(
            """
            INSERT INTO scan_snapshots (
                strategy, as_of_date, scanned_at, total_universe, screened_count, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                strategy.upper(),
                as_of_date,
                int(scanned_at),
                int(total_universe),
                int(screened_count),
                payload_json,
            ),
        )
        snapshot_id = cursor.lastrowid
        connection.execute(
            "DELETE FROM scan_snapshots WHERE scanned_at < ?",
            (int(scanned_at) - 7 * 86400,),
        )
    return snapshot_id


def load_latest_scan_snapshot(
    connection: sqlite3.Connection, strategy: str = "CL1"
) -> ScanSnapshot | None:
    """Retrieve the most recent scan snapshot for a given strategy."""
    row = connection.execute(
        """
        SELECT id, strategy, as_of_date, scanned_at, total_universe, screened_count, payload_json
        FROM scan_snapshots
        WHERE strategy = ?
        ORDER BY scanned_at DESC
        LIMIT 1
        """,
        (strategy.upper(),),
    ).fetchone()
    if row is None:
        return None
    try:
        raw_rows = json.loads(row["payload_json"])
        rows = tuple(
            ScanRowView(
                symbol=item["symbol"],
                trend=item["trend"],
                relative_strength=item["relative_strength"],
                liquidity=item["liquidity"],
                fundamental=item["fundamental"],
                strategy_state=item["strategy_state"],
            )
            for item in raw_rows
        )
    except Exception:
        rows = ()
    return ScanSnapshot(
        id=row["id"],
        strategy=row["strategy"],
        as_of_date=row["as_of_date"],
        scanned_at=row["scanned_at"],
        total_universe=row["total_universe"],
        screened_count=row["screened_count"],
        rows=rows,
    )


def load_symbol_bars(
    connection: sqlite3.Connection, symbol: str, limit: int = 260
) -> tuple[OHLCVBar, ...]:
    """Fetch completed daily bars from candles table in chronological order."""
    rows = connection.execute(
        "SELECT * FROM candles WHERE symbol=? AND timeframe='ONE_DAY' ORDER BY timestamp DESC LIMIT ?",
        (symbol, limit),
    ).fetchall()
    return tuple(
        OHLCVBar(
            row["symbol"],
            row["timeframe"],
            row["timestamp"],
            row["open"],
            row["high"],
            row["low"],
            row["close"],
            row["volume"],
        )
        for row in reversed(rows)
    )


def _fundamental_status_for_scan(
    connection: sqlite3.Connection, symbol: str, as_of_timestamp: int
) -> str:
    as_of_date = datetime.fromtimestamp(as_of_timestamp, timezone.utc).date()
    try:
        reports = latest_financial_reports(connection, symbol, as_of_date)
        if not reports:
            return "MISSING"
        report = reports[0]
        if report["net_profit"] is not None and report["net_profit"] > 0:
            return "PASS"
        return "NEUTRAL"
    except Exception:
        return "MISSING"


def run_scan_cycle(
    connection: sqlite3.Connection,
    config: ScannerWorkerConfig | None = None,
    *,
    strategies: Sequence[str] = ("CL1", "ASMF"),
    bar_loader: Callable[[str], Sequence[OHLCVBar]] | None = None,
    now: int | None = None,
) -> dict[str, ScanSnapshot]:
    """Execute a full-market prescreen and strategy evaluation, persisting snapshots to SQLite."""
    if config is None:
        config = ScannerWorkerConfig()
    current_timestamp = int(time.time() if now is None else now)
    as_of_date = datetime.fromtimestamp(current_timestamp, timezone.utc).strftime("%Y-%m-%d")

    market_symbols = load_market_universe(connection)
    if not market_symbols:
        return {}

    instruments = tuple(
        ScannerInstrument(item.symbol, item.exchange or "HOSE", "STOCK")
        for item in market_symbols
    )

    loader = bar_loader or (lambda s: load_symbol_bars(connection, s))
    benchmark_bars = tuple(loader("VNINDEX"))

    scanner_cfg = ScannerConfig(
        lookback_days=config.lookback_days,
        minimum_average_daily_volume=config.minimum_average_daily_volume,
        minimum_average_daily_value=config.minimum_average_daily_value,
        maximum_watch_symbols=config.maximum_watch_symbols,
    )
    histories: dict[str, tuple[OHLCVBar, ...]] = {}
    for inst in instruments:
        bars = tuple(loader(inst.symbol))
        if bars:
            histories[inst.symbol] = bars

    screened = daily_prescreen(
        instruments, histories, scanner_cfg, as_of_timestamp=current_timestamp + 1
    )
    ranked_symbols = realtime_watch_universe(screened, scanner_cfg)

    results: dict[str, ScanSnapshot] = {}

    for strat in strategies:
        strat_upper = strat.strip().upper()
        rows: list[ScanRowView] = []
        for sym in ranked_symbols:
            bars = histories.get(sym, ())
            tech = build_technical_view(bars, benchmark_bars) if bars else None
            strategy_view = None
            f_status = None
            if bars:
                if strat_upper == "CL1":
                    try:
                        strategy_view = build_strategy_view(evaluate_cl1(bars))
                    except ValueError:
                        strategy_view = None
                f_status = _fundamental_status_for_scan(connection, sym, bars[-1].timestamp)
            rows.append(build_scan_row(sym, tech, strategy_view, True, f_status))

        snapshot_id = save_scan_snapshot(
            connection,
            strategy=strat_upper,
            as_of_date=as_of_date,
            scanned_at=current_timestamp,
            total_universe=len(market_symbols),
            screened_count=len(ranked_symbols),
            rows=rows,
        )
        snapshot = ScanSnapshot(
            id=snapshot_id,
            strategy=strat_upper,
            as_of_date=as_of_date,
            scanned_at=current_timestamp,
            total_universe=len(market_symbols),
            screened_count=len(ranked_symbols),
            rows=tuple(rows),
        )
        results[strat_upper] = snapshot

    return results


class MarketScannerWorker:
    """Daemon thread executing market scan cycles on an interval, persisting to SQLite."""

    def __init__(
        self,
        connection_factory: Callable[[], sqlite3.Connection],
        config: ScannerWorkerConfig | None = None,
        *,
        bar_loader: Callable[[str], Sequence[OHLCVBar]] | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self.config = config or ScannerWorkerConfig()
        self._bar_loader = bar_loader
        self._now = now
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.cycles_completed = 0
        self.last_results: dict[str, ScanSnapshot] = {}

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> threading.Thread:
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError("scanner worker has been stopped")
            if self._thread is not None:
                return self._thread
            self._thread = threading.Thread(
                target=self._run, name="market-scanner", daemon=True
            )
            self._thread.start()
            return self._thread

    def stop(self, timeout: float | None = None) -> None:
        with self._lock:
            self._stop.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    def _run(self) -> None:
        connection = self._connection_factory()
        try:
            while not self._stop.is_set():
                now_val = int(self._now() if self._now else time.time())
                try:
                    self.last_results = run_scan_cycle(
                        connection,
                        self.config,
                        bar_loader=self._bar_loader,
                        now=now_val,
                    )
                    self.cycles_completed += 1
                except Exception:
                    LOGGER.exception("Error during market scan cycle")
                self._stop.wait(self.config.scan_interval_seconds)
        finally:
            connection.close()

def _flag(raw: str | None, default: bool) -> bool:
    value = (raw or "").strip().lower()
    if not value:
        return default
    return value not in {"0", "false", "no", "off"}


def start_scanner_worker_from_env(
    *, environ: Mapping[str, str] | None = None,
) -> "MarketScannerWorker | None":
    """Start the background market scanner worker; returns ``None`` when disabled.

    Never blocks the Telegram polling loop: the worker runs its scan cycles on
    its own daemon thread. This is what lets ``/scan`` read a persisted,
    market-wide snapshot instead of ever prescreening the full universe
    synchronously inside a command handler.
    """
    source = os.environ if environ is None else environ
    if not _flag(source.get("SCANNER_WORKER_ENABLED"), True):
        LOGGER.info("Market scanner worker disabled (SCANNER_WORKER_ENABLED=false)")
        return None

    # Imported lazily to avoid a module-level dependency between the two
    # worker modules; both already depend on `data.database` independently.
    from runtime.coverage_factory import connection_factory_from_env

    connection_factory = connection_factory_from_env(environ)
    config = ScannerWorkerConfig(
        scan_interval_seconds=int(
            source.get("SCANNER_INTERVAL_SECONDS", "") or ScannerWorkerConfig().scan_interval_seconds
        ),
    )
    worker = MarketScannerWorker(connection_factory, config)
    worker.start()
    LOGGER.info(
        "Market scanner worker started interval=%.0fs", config.scan_interval_seconds
    )
    return worker