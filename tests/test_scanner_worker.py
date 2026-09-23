"""Tests for MarketScannerWorker, snapshot persistence, and strategy-aware /scan."""

from __future__ import annotations

import sqlite3
import time

import pytest

from data.database import connect_database
from data.migrations import bootstrap_schema
from data.models import OHLCVBar
from runtime.bot_service import RuntimeBotDataService
from runtime.scanner_worker import (
    MarketScannerWorker,
    ScannerWorkerConfig,
    load_latest_scan_snapshot,
    run_scan_cycle,
    save_scan_snapshot,
)
from runtime.views import ScanRowView
from scanner.universe import ScannerInstrument
from telegram_bot.commands import TelegramCommandService


def make_test_db() -> sqlite3.Connection:
    conn = connect_database("sqlite:///:memory:")
    bootstrap_schema(conn)
    return conn


def seed_test_universe(conn: sqlite3.Connection) -> None:
    with conn:
        conn.executemany(
            "INSERT INTO symbols (symbol, exchange, instrument_type, is_active) VALUES (?, ?, 'STOCK', 1)",
            [
                ("FPT", "HOSE"),
                ("MWG", "HOSE"),
                ("VNM", "HOSE"),
                ("PENNY", "UPCOM"),
            ],
        )
        # Seed daily candles (25 days)
        now_ts = 1_700_000_000
        for sym, base_p, vol in [
            ("FPT", 100_000.0, 50_000.0),
            ("MWG", 50_000.0, 40_000.0),
            ("VNM", 70_000.0, 30_000.0),
            ("PENNY", 2_000.0, 100.0),  # Illiquid
            ("VNINDEX", 1100.0, 1_000_000.0),
        ]:
            if sym == "VNINDEX":
                conn.execute("INSERT OR IGNORE INTO symbols (symbol, instrument_type) VALUES ('VNINDEX', 'INDEX')")
            bars = [
                (
                    sym,
                    "ONE_DAY",
                    now_ts - (25 - i) * 86400,
                    base_p + i * 0.2,
                    base_p + i * 0.2 + 1.0,
                    base_p + i * 0.2 - 1.0,
                    base_p + i * 0.2,
                    vol,
                )
                for i in range(25)
            ]
            conn.executemany(
                "INSERT INTO candles (symbol, timeframe, timestamp, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                bars,
            )


def test_snapshot_save_and_load_roundtrip() -> None:
    conn = make_test_db()
    rows = [
        ScanRowView("FPT", "TĂNG", "+2.5% vs VNINDEX", "PASS", "PASS", "THEO DÕI"),
        ScanRowView("MWG", "TĂNG", "+1.2% vs VNINDEX", "PASS", "PASS", "WATCH"),
    ]
    snapshot_id = save_scan_snapshot(
        conn,
        strategy="CL1",
        as_of_date="2026-09-21",
        scanned_at=1_700_000_000,
        total_universe=100,
        screened_count=2,
        prescreen_count=7,
        rows=rows,
    )
    assert snapshot_id > 0

    loaded = load_latest_scan_snapshot(conn, "CL1")
    assert loaded is not None
    assert loaded.strategy == "CL1"
    assert loaded.as_of_date == "2026-09-21"
    assert loaded.total_universe == 100
    assert loaded.prescreen_count == 7
    assert loaded.screened_count == 2
    assert len(loaded.rows) == 2
    assert loaded.rows[0].symbol == "FPT"
    assert loaded.rows[1].symbol == "MWG"

    # Non-existent strategy returns None
    assert load_latest_scan_snapshot(conn, "UNKNOWN") is None


def test_snapshot_prescreen_count_defaults_to_screened_count_for_old_callers() -> None:
    """Callers that predate Issue 3.4 don't pass prescreen_count explicitly."""
    conn = make_test_db()
    save_scan_snapshot(
        conn,
        strategy="CL1",
        as_of_date="2026-09-21",
        scanned_at=1_700_000_000,
        total_universe=100,
        screened_count=3,
        rows=[ScanRowView("FPT", "TĂNG", "+1.0% vs VNINDEX", "PASS", "PASS", "THEO DÕI")],
    )
    loaded = load_latest_scan_snapshot(conn, "CL1")
    assert loaded is not None
    assert loaded.prescreen_count == 3


def test_snapshot_pruning_removes_old_records() -> None:
    conn = make_test_db()
    old_ts = 1_700_000_000 - 10 * 86400
    new_ts = 1_700_000_000
    save_scan_snapshot(
        conn,
        strategy="CL1",
        as_of_date="2026-09-11",
        scanned_at=old_ts,
        total_universe=50,
        screened_count=1,
        rows=[ScanRowView("OLD", "GIẢM", "N/A", "PASS", "PASS", "N/A")],
    )
    # Save a fresh snapshot which triggers pruning (>7 days)
    save_scan_snapshot(
        conn,
        strategy="CL1",
        as_of_date="2026-09-21",
        scanned_at=new_ts,
        total_universe=50,
        screened_count=1,
        rows=[ScanRowView("NEW", "TĂNG", "N/A", "PASS", "PASS", "N/A")],
    )
    count = conn.execute("SELECT COUNT(*) FROM scan_snapshots").fetchone()[0]
    assert count == 1
    loaded = load_latest_scan_snapshot(conn, "CL1")
    assert loaded.rows[0].symbol == "NEW"


def test_run_scan_cycle_filters_liquidity_and_persists() -> None:
    conn = make_test_db()
    seed_test_universe(conn)

    cfg = ScannerWorkerConfig(
        lookback_days=20,
        minimum_average_daily_volume=10_000.0,
        minimum_average_daily_value=1_000_000_000.0,  # 1B VND
        maximum_watch_symbols=10,
    )
    results = run_scan_cycle(conn, cfg, now=1_700_000_000)

    assert "CL1" in results
    cl1_snap = results["CL1"]
    assert cl1_snap.total_universe == 4  # FPT, MWG, VNM, PENNY
    # PENNY is filtered out by liquidity, so prescreen_count (pre-cap) < universe
    # while screened_count/rows reflect the (here, uncapped) watch-list size.
    assert cl1_snap.prescreen_count == 3  # FPT, MWG, VNM pass; PENNY fails liquidity
    assert cl1_snap.screened_count == len(cl1_snap.rows)
    symbols = [r.symbol for r in cl1_snap.rows]
    assert "PENNY" not in symbols
    assert "FPT" in symbols

    # Check persistence
    loaded = load_latest_scan_snapshot(conn, "CL1")
    assert loaded is not None
    assert loaded.id == cl1_snap.id



def test_scanner_worker_daemon_lifecycle(tmp_path) -> None:
    db_path = f"sqlite:///{(tmp_path / 'worker.sqlite3').as_posix()}"
    init_conn = connect_database(db_path)
    bootstrap_schema(init_conn)
    seed_test_universe(init_conn)
    init_conn.close()

    worker = MarketScannerWorker(
        connection_factory=lambda: connect_database(db_path),
        config=ScannerWorkerConfig(scan_interval_seconds=1),
        now=lambda: 1_700_000_000,
    )
    thread = worker.start()
    assert worker.running
    time.sleep(0.5)
    worker.stop(timeout=2.0)
    assert not worker.running
    assert worker.cycles_completed >= 1

def test_start_scanner_worker_from_env_persists_market_wide_snapshot(tmp_path) -> None:
    """Regression for Issue 1: production never started MarketScannerWorker, so
    /scan permanently fell back to the tiny BOT_WATCH_SYMBOLS list instead of
    the full HOSE/HNX/UPCoM universe. This exercises the same factory that
    scripts/run_telegram_bot.py now calls at startup."""
    from runtime.scanner_worker import start_scanner_worker_from_env

    db_path = f"sqlite:///{(tmp_path / 'prod_worker.sqlite3').as_posix()}"
    init_conn = connect_database(db_path)
    bootstrap_schema(init_conn)
    seed_test_universe(init_conn)
    init_conn.close()

    environ = {
        "DATABASE_URL": db_path,
        "SCANNER_INTERVAL_SECONDS": "1",
    }
    worker = start_scanner_worker_from_env(environ=environ)
    assert worker is not None
    try:
        assert worker.running
        for _ in range(50):
            if worker.cycles_completed >= 1:
                break
            time.sleep(0.1)
        assert worker.cycles_completed >= 1
    finally:
        worker.stop(timeout=2.0)

    conn = connect_database(db_path)
    snapshot = load_latest_scan_snapshot(conn, "CL1")
    assert snapshot is not None
    # Full seeded universe (4 symbols), not the 2-symbol BOT_WATCH_SYMBOLS default.
    assert snapshot.total_universe == 4


def test_start_scanner_worker_from_env_can_be_disabled(tmp_path) -> None:
    from runtime.scanner_worker import start_scanner_worker_from_env

    db_path = f"sqlite:///{(tmp_path / 'disabled.sqlite3').as_posix()}"
    worker = start_scanner_worker_from_env(
        environ={"DATABASE_URL": db_path, "SCANNER_WORKER_ENABLED": "false"}
    )
    assert worker is None


def test_scan_overview_flags_stale_snapshot() -> None:
    """Regression for Issue 1's staleness requirement: an old snapshot must be
    labelled stale rather than presented as a fresh full-market read."""
    conn = make_test_db()
    seed_test_universe(conn)
    save_scan_snapshot(
        conn,
        strategy="CL1",
        as_of_date="2026-09-01",
        scanned_at=1_700_000_000,
        total_universe=1600,
        screened_count=1,
        rows=[ScanRowView("FPT", "TĂNG", "+1.0% vs VNINDEX", "PASS", "PASS", "WATCH")],
    )

    class DummyClient:
        def get_gap_chart(self, *args, **kwargs):
            return []

    # now() is far past the snapshot's scanned_at + the stale threshold.
    service = RuntimeBotDataService(
        DummyClient(), conn, instruments=(), now=lambda: 1_700_000_000 + 7200,
    )
    text = service.scan_overview("CL1")
    assert "cũ" in text.lower()

def test_scan_overview_reads_persisted_snapshot() -> None:
    conn = make_test_db()
    seed_test_universe(conn)

    # Seed snapshot
    save_scan_snapshot(
        conn,
        strategy="CL1",
        as_of_date="2026-09-21",
        scanned_at=1_700_000_000,
        total_universe=1600,
        screened_count=2,
        rows=[
            ScanRowView("FPT", "TĂNG", "+3.5% vs VNINDEX", "PASS", "PASS", "THEO DÕI"),
            ScanRowView("MWG", "TĂNG", "+2.1% vs VNINDEX", "PASS", "PASS", "WATCH"),
        ],
    )

    class DummyClient:
        def get_gap_chart(self, *args, **kwargs):
            return []

    service = RuntimeBotDataService(
        DummyClient(),
        conn,
        instruments=(),  # Empty watch symbols: proves it uses snapshot, not BOT_WATCH_SYMBOLS
        now=lambda: 1_700_000_000,
    )

    text = service.scan_overview("CL1")
    assert "KẾT QUẢ QUÉT" in text
    assert "Vũ trụ: 1,600" in text
    assert "Hiển thị: Top 2" in text
    assert "1. FPT" in text
    assert "2. MWG" in text
    assert "THEO DÕI" in text


def test_telegram_commands_scan_routing() -> None:
    conn = make_test_db()
    save_scan_snapshot(
        conn,
        strategy="ASMF",
        as_of_date="2026-09-21",
        scanned_at=1_700_000_000,
        total_universe=1600,
        screened_count=1,
        rows=[ScanRowView("VHM", "TĂNG", "+1.0% vs VNINDEX", "PASS", "PASS", "CHƯA ĐỦ ĐIỀU KIỆN")],
    )

    class DummyClient:
        def get_gap_chart(self, *args, **kwargs):
            return []

    service = RuntimeBotDataService(
        DummyClient(),
        conn,
        instruments=(),
        now=lambda: 1_700_000_000,
    )
    cmds = TelegramCommandService(service)

    # /scan ASMF routes to ASMF snapshot
    text = cmds.scan(["ASMF"])
    assert "CHIẾN LƯỢC ASMF" in text
    assert "VHM" in text
