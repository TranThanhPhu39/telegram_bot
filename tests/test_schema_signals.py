"""Tests for the Phase 9 signals table."""

from __future__ import annotations

import sqlite3

import pytest

from data.database import connect_database
from data.schema import create_signals_table, create_symbols_table


@pytest.fixture
def connection() -> sqlite3.Connection:
    database = connect_database("sqlite:///:memory:")
    create_symbols_table(database)
    create_signals_table(database)
    database.execute(
        "INSERT INTO symbols (symbol, exchange) VALUES (?, ?)",
        ("FPT", "HOSE"),
    )
    try:
        yield database
    finally:
        database.close()


def insert_signal(
    connection: sqlite3.Connection,
    *,
    symbol: object = "FPT",
    strategy: object = "BREAKOUT_V1",
    timeframe: object = "ONE_MINUTE",
    state: object = "WATCH",
    created_at: object = 1_789_703_880,
    updated_at: object = 1_789_703_880,
    trigger_price: object = 100_000.0,
    reason_json: object = '{"rule":"volume"}',
) -> int:
    cursor = connection.execute(
        "INSERT INTO signals "
        "(symbol, strategy, timeframe, state, created_at, updated_at, "
        "trigger_price, reason_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            symbol,
            strategy,
            timeframe,
            state,
            created_at,
            updated_at,
            trigger_price,
            reason_json,
        ),
    )
    return cursor.lastrowid


def test_signals_table_has_expected_columns(connection: sqlite3.Connection) -> None:
    columns = connection.execute("PRAGMA table_info(signals)").fetchall()

    assert [column["name"] for column in columns] == [
        "signal_id",
        "symbol",
        "strategy",
        "timeframe",
        "state",
        "created_at",
        "updated_at",
        "trigger_price",
        "reason_json",
    ]
    assert columns[0]["pk"] == 1
    assert columns[-1]["dflt_value"] == "'{}'"


def test_signals_table_round_trips_high_level_signal(
    connection: sqlite3.Connection,
) -> None:
    signal_id = insert_signal(connection)

    row = connection.execute(
        "SELECT * FROM signals WHERE signal_id = ?", (signal_id,)
    ).fetchone()
    assert tuple(row) == (
        signal_id,
        "FPT",
        "BREAKOUT_V1",
        "ONE_MINUTE",
        "WATCH",
        1_789_703_880,
        1_789_703_880,
        100_000.0,
        '{"rule":"volume"}',
    )


def test_signal_ids_allow_multiple_lifecycles(connection: sqlite3.Connection) -> None:
    first = insert_signal(connection)
    second = insert_signal(connection)

    assert first != second
    assert connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 2


def test_signals_require_known_symbol(connection: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        insert_signal(connection, symbol="ACB")


@pytest.mark.parametrize(
    "overrides",
    [
        {"strategy": "breakout"},
        {"strategy": "BREAKOUT V1"},
        {"timeframe": "one_minute"},
        {"state": ""},
        {"state": "MONEY FLOW"},
        {"created_at": 0},
        {"created_at": 1.5},
        {"updated_at": 1_789_703_879},
        {"trigger_price": 0},
        {"trigger_price": "not-a-number"},
        {"reason_json": "not-json"},
    ],
)
def test_signals_reject_invalid_values(
    connection: sqlite3.Connection,
    overrides: dict[str, object],
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        insert_signal(connection, **overrides)


def test_trigger_price_can_be_unknown(connection: sqlite3.Connection) -> None:
    signal_id = insert_signal(connection, trigger_price=None)

    assert connection.execute(
        "SELECT trigger_price FROM signals WHERE signal_id = ?", (signal_id,)
    ).fetchone()[0] is None


def test_symbol_time_index_exists(connection: sqlite3.Connection) -> None:
    indexes = connection.execute("PRAGMA index_list(signals)").fetchall()

    assert "idx_signals_symbol_created_at" in {
        index["name"] for index in indexes
    }


def test_create_signals_table_is_idempotent_and_preserves_rows(
    connection: sqlite3.Connection,
) -> None:
    insert_signal(connection)

    create_signals_table(connection)

    assert connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 1


def test_create_signals_table_requires_sqlite_connection() -> None:
    with pytest.raises(TypeError):
        create_signals_table(object())  # type: ignore[arg-type]
