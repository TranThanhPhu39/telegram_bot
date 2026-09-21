"""Coverage state semantics and the v8 migration that widened the dataset set."""

from __future__ import annotations

from datetime import timedelta
import sqlite3

import pytest

import data.migrations as migrations
from data.database import connect_database
from fundamentals.coverage_store import (
    COVERAGE_DATASETS,
    coverage_counts,
    effective_status,
    load_coverage,
    mark_in_progress,
    mark_in_progress_bulk,
    mark_stale,
    record_attempt,
    record_attempts_bulk,
)
from tests.coverage_fakes import T0, make_connection, seed_symbols


@pytest.fixture()
def connection(tmp_path):
    conn = make_connection(tmp_path)
    seed_symbols(conn, [("FPT", "HOSE", "STOCK", 1), ("ACB", "HOSE", "STOCK", 1)])
    return conn


# ------------------------------------------------------------------ states
def test_no_row_means_never_attempted(connection) -> None:
    assert load_coverage(connection, "FPT", "FINANCIALS") is None
    assert effective_status(None, 3600, now=T0) == "NEVER_ATTEMPTED"


@pytest.mark.parametrize("status,success", [
    ("READY", True), ("PARTIAL", True), ("MISSING", False), ("ERROR", False),
])
def test_each_outcome_is_recorded_and_success_only_on_usable_data(connection, status, success) -> None:
    row = record_attempt(connection, "FPT", "NEWS", status, provider="CafeF", now=T0)
    assert row.status == status
    assert row.attempts == 1
    assert row.last_attempt_at == int(T0.timestamp())
    assert (row.last_success_at is not None) is success


def test_attempt_count_increments_and_last_success_survives_a_later_error(connection) -> None:
    record_attempt(connection, "FPT", "FINANCIALS", "READY", provider="VNStock", now=T0)
    later = T0 + timedelta(hours=2)
    row = record_attempt(connection, "FPT", "FINANCIALS", "ERROR", error_reason="timeout", now=later)
    assert row.status == "ERROR" and row.attempts == 2
    assert row.last_attempt_at == int(later.timestamp())
    assert row.last_success_at == int(T0.timestamp())     # preserved
    row = record_attempt(connection, "FPT", "FINANCIALS", "MISSING", now=later + timedelta(hours=1))
    assert row.attempts == 3 and row.last_success_at == int(T0.timestamp())


def test_stale_is_derived_from_age_and_can_be_persisted(connection) -> None:
    record_attempt(connection, "FPT", "FINANCIALS", "READY", now=T0)
    record_attempt(connection, "ACB", "FINANCIALS", "MISSING", now=T0)
    row = load_coverage(connection, "FPT", "FINANCIALS")
    later = T0 + timedelta(days=8)
    assert effective_status(row, 7 * 86400, now=T0 + timedelta(days=1)) == "READY"
    assert effective_status(row, 7 * 86400, now=later) == "STALE"

    assert mark_stale(connection, "FINANCIALS", 7 * 86400, now=later) == 1
    stale = load_coverage(connection, "FPT", "FINANCIALS")
    assert stale.status == "STALE" and stale.last_success_at == int(T0.timestamp())
    assert load_coverage(connection, "ACB", "FINANCIALS").status == "MISSING"  # untouched
    assert mark_stale(connection, "FINANCIALS", 7 * 86400, now=later) == 0     # idempotent


def test_in_progress_keeps_attempts_and_success_and_expires(connection) -> None:
    record_attempt(connection, "FPT", "NEWS", "READY", now=T0)
    mark_in_progress(connection, "FPT", "NEWS", now=T0 + timedelta(hours=1))
    row = load_coverage(connection, "FPT", "NEWS")
    assert row.status == "IN_PROGRESS" and row.attempts == 1
    assert row.last_success_at == int(T0.timestamp())
    fresh = T0 + timedelta(hours=1, minutes=5)
    assert effective_status(row, 86400, now=fresh, in_progress_lease_seconds=1800) == "IN_PROGRESS"
    abandoned = T0 + timedelta(hours=3)
    assert effective_status(row, 86400, now=abandoned, in_progress_lease_seconds=1800) == "STALE"


def test_new_row_via_in_progress_starts_at_zero_attempts(connection) -> None:
    mark_in_progress(connection, "FPT", "MARKET_HISTORY", now=T0)
    row = load_coverage(connection, "FPT", "MARKET_HISTORY")
    assert (row.status, row.attempts, row.last_success_at) == ("IN_PROGRESS", 0, None)


def test_invalid_dataset_or_status_is_rejected(connection) -> None:
    with pytest.raises(ValueError):
        record_attempt(connection, "FPT", "BOGUS", "READY")
    with pytest.raises(ValueError):
        record_attempt(connection, "FPT", "NEWS", "IN_PROGRESS")
    with pytest.raises(ValueError):
        record_attempt(connection, "FPT", "NEWS", "NEVER_ATTEMPTED")
    with pytest.raises(ValueError):
        record_attempts_bulk(connection, "NEWS", [("FPT", "READY!", None, None, None)])


def test_bulk_writes_are_single_transaction_and_idempotent(connection) -> None:
    rows = [("FPT", "READY", "CafeF", "rss", "2 article(s)"),
            ("ACB", "MISSING", "CafeF", "rss", "none")]
    assert record_attempts_bulk(connection, "NEWS", rows, now=T0) == 2
    assert record_attempts_bulk(connection, "NEWS", rows, now=T0 + timedelta(hours=1)) == 2
    fpt = load_coverage(connection, "FPT", "NEWS")
    assert fpt.attempts == 2 and fpt.status == "READY"
    assert connection.execute("SELECT COUNT(*) FROM symbol_data_coverage").fetchone()[0] == 2
    assert coverage_counts(connection, "NEWS") == {"READY": 1, "MISSING": 1}
    assert mark_in_progress_bulk(connection, "NEWS", ["FPT", "ACB"], now=T0) == 2
    assert coverage_counts(connection, "NEWS") == {"IN_PROGRESS": 2}


def test_reason_is_redacted_single_line_and_bounded(connection, monkeypatch) -> None:
    monkeypatch.setenv("VIETCAP_COOKIE", "sessionid=SUPERSECRETVALUE123")
    row = record_attempt(
        connection, "FPT", "FINANCIALS", "ERROR",
        error_reason="failed\nwith sessionid=SUPERSECRETVALUE123 " + "x" * 1000, now=T0,
    )
    assert "SUPERSECRETVALUE123" not in row.error_reason
    assert "\n" not in row.error_reason and len(row.error_reason) <= 300


# ---------------------------------------------------------- migration v8
V7 = [m for m in migrations.MIGRATIONS if m.version <= 7]


def _v7_database(tmp_path, monkeypatch):
    path = f"sqlite:///{(tmp_path / 'old.sqlite3').as_posix()}"
    conn = connect_database(path)
    monkeypatch.setattr(migrations, "MIGRATIONS", tuple(V7))
    monkeypatch.setattr(migrations, "LATEST_SCHEMA_VERSION", 7)
    assert migrations.bootstrap_schema(conn) == 7
    monkeypatch.undo()
    return conn


def test_v8_preserves_v7_rows_and_accepts_new_datasets(tmp_path, monkeypatch) -> None:
    conn = _v7_database(tmp_path, monkeypatch)
    seed_symbols(conn, [("FPT", "HOSE", "STOCK", 1)])
    with conn:
        conn.execute(
            "INSERT INTO symbol_data_coverage(symbol,dataset,status,provider,attempts,"
            "last_attempt_at,last_success_at,updated_at) "
            "VALUES ('FPT','FINANCIALS','READY','VNStock',3,100,100,100)"
        )
    with pytest.raises(sqlite3.IntegrityError):  # v7 rejected the new datasets
        conn.execute("INSERT INTO symbol_data_coverage(symbol,dataset,status,updated_at) "
                     "VALUES ('FPT','NEWS','READY',1)")
    conn.rollback()

    assert migrations.bootstrap_schema(conn) == 8
    row = load_coverage(conn, "FPT", "FINANCIALS")
    assert (row.status, row.provider, row.attempts, row.last_success_at) == ("READY", "VNStock", 3, 100)
    for dataset in COVERAGE_DATASETS:
        record_attempt(conn, "FPT", dataset, "READY", now=T0)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO symbol_data_coverage(symbol,dataset,status,updated_at) "
                     "VALUES ('FPT','BOGUS','READY',1)")
    conn.rollback()
    index = conn.execute("SELECT name FROM sqlite_master WHERE type='index' "
                         "AND name='idx_symbol_data_coverage_status'").fetchone()
    assert index is not None
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='symbol_data_coverage_v8'").fetchone() is None
    assert migrations.bootstrap_schema(conn) == 8   # idempotent


def test_v8_is_atomic_when_a_step_fails(tmp_path, monkeypatch) -> None:
    conn = _v7_database(tmp_path, monkeypatch)
    seed_symbols(conn, [("FPT", "HOSE", "STOCK", 1)])
    with conn:
        conn.execute("INSERT INTO symbol_data_coverage(symbol,dataset,status,updated_at) "
                     "VALUES ('FPT','FINANCIALS','READY',5)")
    real_v8 = next(m for m in migrations.MIGRATIONS if m.version == 8)
    broken = migrations.Migration(8, real_v8.name, (*real_v8.statements, "THIS IS NOT SQL"))
    monkeypatch.setattr(migrations, "MIGRATIONS", (*V7, broken))
    with pytest.raises(sqlite3.Error):
        migrations.bootstrap_schema(conn)
    monkeypatch.undo()
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "symbol_data_coverage" in names and "symbol_data_coverage_v8" not in names
    assert conn.execute("SELECT status FROM symbol_data_coverage").fetchone()[0] == "READY"
    assert conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 7
    assert migrations.bootstrap_schema(conn) == 8   # and recovers cleanly
