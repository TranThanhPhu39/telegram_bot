"""Tests for the versioned Phase 9 schema bootstrap."""

from __future__ import annotations

import sqlite3

import pytest

from data.database import connect_database
from data.migrations import (
    LATEST_SCHEMA_VERSION,
    SCHEMA_MIGRATIONS_TABLE_SQL,
    SchemaMigrationError,
    bootstrap_schema,
)


EXPECTED_TABLES = {
    "schema_migrations",
    "symbols",
    "candles",
    "signals",
    "signal_events",
    "sector_memberships",
    "financial_reports",
    "institutional_flows",
    "bank_financial_reports",
    "users",
    "watchlist",
    "portfolio_holdings",
}


def table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {row["name"] for row in rows}


def test_bootstrap_creates_versioned_schema_in_dependency_order(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'bot.sqlite3').as_posix()}"
    connection = connect_database(database_url)
    try:
        version = bootstrap_schema(connection)

        assert version == LATEST_SCHEMA_VERSION == 8
        assert EXPECTED_TABLES <= table_names(connection)
        migrations = connection.execute(
            "SELECT version, name, applied_at FROM schema_migrations"
        ).fetchall()
        assert [tuple(row[:2]) for row in migrations] == [
            (1, "initial_v1_schema"), (2, "asmf_eod_inputs"),
            (3, "asmf_bank_financials"), (4, "portfolio_watchlist_holdings"),
            (5, "portfolio_exact_decimals"),
            (6, "sector_sync_notifications"),
            (7, "automated_fundamentals_coverage"),
            (8, "market_coverage_datasets"),
        ]
        assert all(row["applied_at"] > 0 for row in migrations)
    finally:
        connection.close()


def test_bootstrap_is_idempotent_and_preserves_data() -> None:
    connection = connect_database("sqlite:///:memory:")
    try:
        bootstrap_schema(connection)
        connection.execute("INSERT INTO symbols (symbol) VALUES ('FPT')")
        connection.commit()

        assert bootstrap_schema(connection) == 8
        assert connection.execute(
            "SELECT symbol FROM symbols"
        ).fetchone()["symbol"] == "FPT"
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()[0] == 8
    finally:
        connection.close()


def test_file_schema_version_survives_reopen(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'persistent.sqlite3').as_posix()}"
    first = connect_database(database_url)
    bootstrap_schema(first)
    first.close()

    second = connect_database(database_url)
    try:
        assert bootstrap_schema(second) == 8
        assert EXPECTED_TABLES <= table_names(second)
    finally:
        second.close()


def test_bootstrap_rejects_unknown_future_schema_version() -> None:
    connection = connect_database("sqlite:///:memory:")
    try:
        connection.execute(SCHEMA_MIGRATIONS_TABLE_SQL)
        connection.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (999, "future_schema"),
        )
        connection.commit()

        with pytest.raises(SchemaMigrationError, match="newer or unknown"):
            bootstrap_schema(connection)
    finally:
        connection.close()


def test_bootstrap_rejects_changed_migration_identity() -> None:
    connection = connect_database("sqlite:///:memory:")
    try:
        connection.execute(SCHEMA_MIGRATIONS_TABLE_SQL)
        connection.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (1, "different_name"),
        )
        connection.commit()

        with pytest.raises(SchemaMigrationError, match="name does not match"):
            bootstrap_schema(connection)
    finally:
        connection.close()


def test_bootstrap_requires_sqlite_connection() -> None:
    with pytest.raises(TypeError):
        bootstrap_schema(object())  # type: ignore[arg-type]
