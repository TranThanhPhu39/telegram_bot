"""Tests for the Phase 9 symbols table."""

from __future__ import annotations

import sqlite3

import pytest

from data.database import connect_database
from data.schema import create_symbols_table


@pytest.fixture
def connection() -> sqlite3.Connection:
    database = connect_database("sqlite:///:memory:")
    create_symbols_table(database)
    try:
        yield database
    finally:
        database.close()


def test_symbols_table_has_expected_columns(connection: sqlite3.Connection) -> None:
    columns = connection.execute("PRAGMA table_info(symbols)").fetchall()

    assert [column["name"] for column in columns] == [
        "symbol",
        "exchange",
        "instrument_type",
        "is_active",
    ]
    assert columns[0]["pk"] == 1
    assert columns[2]["dflt_value"] == "'STOCK'"
    assert columns[3]["dflt_value"] == "1"


def test_symbols_table_accepts_stock_and_index_rows(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        "INSERT INTO symbols (symbol, exchange) VALUES (?, ?)",
        ("FPT", "HOSE"),
    )
    connection.execute(
        "INSERT INTO symbols (symbol, exchange, instrument_type) VALUES (?, ?, ?)",
        ("VNINDEX", None, "INDEX"),
    )

    rows = connection.execute(
        "SELECT symbol, exchange, instrument_type, is_active "
        "FROM symbols ORDER BY symbol"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("FPT", "HOSE", "STOCK", 1),
        ("VNINDEX", None, "INDEX", 1),
    ]


def test_symbol_primary_key_rejects_duplicates(
    connection: sqlite3.Connection,
) -> None:
    connection.execute("INSERT INTO symbols (symbol) VALUES ('ACB')")

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO symbols (symbol) VALUES ('ACB')")


@pytest.mark.parametrize(
    ("symbol", "exchange", "instrument_type", "is_active"),
    [
        ("", "HOSE", "STOCK", 1),
        ("fpt", "HOSE", "STOCK", 1),
        ("FPT/../", "HOSE", "STOCK", 1),
        ("FPT", "hose", "STOCK", 1),
        ("FPT", "HO SE", "STOCK", 1),
        ("FPT", "HOSE", "common stock", 1),
        ("FPT", "HOSE", "STOCK", 2),
    ],
)
def test_symbols_table_rejects_non_normalized_values(
    connection: sqlite3.Connection,
    symbol: str,
    exchange: str,
    instrument_type: str,
    is_active: int,
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO symbols "
            "(symbol, exchange, instrument_type, is_active) VALUES (?, ?, ?, ?)",
            (symbol, exchange, instrument_type, is_active),
        )


def test_create_symbols_table_is_idempotent_and_preserves_rows(
    connection: sqlite3.Connection,
) -> None:
    connection.execute("INSERT INTO symbols (symbol) VALUES ('ACB')")

    create_symbols_table(connection)

    assert connection.execute(
        "SELECT symbol FROM symbols"
    ).fetchone()["symbol"] == "ACB"


def test_create_symbols_table_requires_sqlite_connection() -> None:
    with pytest.raises(TypeError):
        create_symbols_table(object())  # type: ignore[arg-type]
