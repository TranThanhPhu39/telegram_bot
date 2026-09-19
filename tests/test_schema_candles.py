"""Tests for the Phase 9 candles table."""

from __future__ import annotations

import sqlite3

import pytest

from data.database import connect_database
from data.schema import create_candles_table, create_symbols_table


@pytest.fixture
def connection() -> sqlite3.Connection:
    database = connect_database("sqlite:///:memory:")
    create_symbols_table(database)
    create_candles_table(database)
    database.execute(
        "INSERT INTO symbols (symbol, exchange) VALUES (?, ?)",
        ("ACB", "HOSE"),
    )
    try:
        yield database
    finally:
        database.close()


def insert_bar(
    connection: sqlite3.Connection,
    *,
    symbol: object = "ACB",
    timeframe: object = "ONE_MINUTE",
    timestamp: object = 1_789_703_880,
    open_price: object = 22_000.0,
    high_price: object = 22_200.0,
    low_price: object = 21_900.0,
    close_price: object = 22_100.0,
    volume: object = 150_000.0,
) -> None:
    connection.execute(
        "INSERT INTO candles "
        "(symbol, timeframe, timestamp, open, high, low, close, volume) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            symbol,
            timeframe,
            timestamp,
            open_price,
            high_price,
            low_price,
            close_price,
            volume,
        ),
    )


def test_candles_table_has_expected_columns_and_composite_key(
    connection: sqlite3.Connection,
) -> None:
    columns = connection.execute("PRAGMA table_info(candles)").fetchall()

    assert [column["name"] for column in columns] == [
        "symbol",
        "timeframe",
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    assert [column["pk"] for column in columns[:3]] == [1, 2, 3]


def test_candles_table_round_trips_ohlcv(connection: sqlite3.Connection) -> None:
    insert_bar(connection)

    row = connection.execute("SELECT * FROM candles").fetchone()
    assert tuple(row) == (
        "ACB",
        "ONE_MINUTE",
        1_789_703_880,
        22_000.0,
        22_200.0,
        21_900.0,
        22_100.0,
        150_000.0,
    )


def test_candle_identity_rejects_duplicates(connection: sqlite3.Connection) -> None:
    insert_bar(connection)

    with pytest.raises(sqlite3.IntegrityError):
        insert_bar(connection)


def test_candles_require_known_symbol(connection: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        insert_bar(connection, symbol="FPT")


def test_referenced_symbol_cannot_be_deleted(connection: sqlite3.Connection) -> None:
    insert_bar(connection)

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        connection.execute("DELETE FROM symbols WHERE symbol = 'ACB'")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"timeframe": "one_minute"}, "CHECK"),
        ({"timeframe": "ONE MINUTE"}, "CHECK"),
        ({"timestamp": 0}, "CHECK"),
        ({"timestamp": 1.5}, "CHECK"),
        ({"open_price": 0}, "CHECK"),
        ({"high_price": 21_000}, "CHECK"),
        ({"low_price": 22_150}, "CHECK"),
        ({"close_price": -1}, "CHECK"),
        ({"volume": -1}, "CHECK"),
        ({"volume": "not-a-number"}, "CHECK"),
    ],
)
def test_candles_reject_invalid_values(
    connection: sqlite3.Connection,
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(sqlite3.IntegrityError, match=message):
        insert_bar(connection, **overrides)


def test_create_candles_table_is_idempotent_and_preserves_rows(
    connection: sqlite3.Connection,
) -> None:
    insert_bar(connection)

    create_candles_table(connection)

    assert connection.execute("SELECT COUNT(*) FROM candles").fetchone()[0] == 1


def test_create_candles_table_requires_sqlite_connection() -> None:
    with pytest.raises(TypeError):
        create_candles_table(object())  # type: ignore[arg-type]
