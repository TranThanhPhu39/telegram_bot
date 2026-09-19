"""Tests for the Phase 9 signal_events table."""

from __future__ import annotations

import sqlite3

import pytest

from data.database import connect_database
from data.schema import (
    create_signal_events_table,
    create_signals_table,
    create_symbols_table,
)


@pytest.fixture
def connection() -> sqlite3.Connection:
    database = connect_database("sqlite:///:memory:")
    create_symbols_table(database)
    create_signals_table(database)
    create_signal_events_table(database)
    database.execute("INSERT INTO symbols (symbol) VALUES ('FPT')")
    database.execute(
        "INSERT INTO signals "
        "(symbol, strategy, timeframe, state, created_at, updated_at) "
        "VALUES ('FPT', 'BREAKOUT_V1', 'ONE_MINUTE', 'WATCH', ?, ?)",
        (1_789_703_880, 1_789_703_880),
    )
    try:
        yield database
    finally:
        database.close()


def insert_event(
    connection: sqlite3.Connection,
    *,
    signal_id: object = 1,
    sequence: object = 1,
    occurred_at: object = 1_789_703_880,
    from_state: object = None,
    to_state: object = "WATCH",
    price: object = 100_000.0,
    reason_json: object = '{"rule":"volume"}',
) -> int:
    cursor = connection.execute(
        "INSERT INTO signal_events "
        "(signal_id, sequence, occurred_at, from_state, to_state, price, "
        "reason_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            signal_id,
            sequence,
            occurred_at,
            from_state,
            to_state,
            price,
            reason_json,
        ),
    )
    return cursor.lastrowid


def test_signal_events_table_has_expected_columns(
    connection: sqlite3.Connection,
) -> None:
    columns = connection.execute("PRAGMA table_info(signal_events)").fetchall()

    assert [column["name"] for column in columns] == [
        "event_id",
        "signal_id",
        "sequence",
        "occurred_at",
        "from_state",
        "to_state",
        "price",
        "reason_json",
    ]
    assert columns[0]["pk"] == 1
    assert columns[-1]["dflt_value"] == "'{}'"


def test_signal_events_round_trip_initial_and_transition_events(
    connection: sqlite3.Connection,
) -> None:
    first_id = insert_event(connection)
    second_id = insert_event(
        connection,
        sequence=2,
        occurred_at=1_789_703_940,
        from_state="WATCH",
        to_state="MONEY_FLOW",
        price=100_500.0,
    )

    rows = connection.execute(
        "SELECT * FROM signal_events ORDER BY sequence"
    ).fetchall()
    assert tuple(rows[0]) == (
        first_id,
        1,
        1,
        1_789_703_880,
        None,
        "WATCH",
        100_000.0,
        '{"rule":"volume"}',
    )
    assert rows[1]["event_id"] == second_id
    assert rows[1]["from_state"] == "WATCH"
    assert rows[1]["to_state"] == "MONEY_FLOW"


def test_event_sequence_is_unique_per_signal(connection: sqlite3.Connection) -> None:
    insert_event(connection)

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        insert_event(connection)


def test_events_require_known_signal(connection: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        insert_event(connection, signal_id=999)


def test_signal_with_events_cannot_be_deleted(connection: sqlite3.Connection) -> None:
    insert_event(connection)

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        connection.execute("DELETE FROM signals WHERE signal_id = 1")


@pytest.mark.parametrize(
    "overrides",
    [
        {"sequence": 0},
        {"sequence": 1.5},
        {"occurred_at": 0},
        {"occurred_at": 1.5},
        {"from_state": "watch"},
        {"from_state": "MONEY FLOW"},
        {"to_state": ""},
        {"to_state": "money_flow"},
        {"price": 0},
        {"price": "not-a-number"},
        {"reason_json": "not-json"},
    ],
)
def test_signal_events_reject_invalid_values(
    connection: sqlite3.Connection,
    overrides: dict[str, object],
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        insert_event(connection, **overrides)


def test_event_price_can_be_unknown(connection: sqlite3.Connection) -> None:
    event_id = insert_event(connection, price=None)

    assert connection.execute(
        "SELECT price FROM signal_events WHERE event_id = ?", (event_id,)
    ).fetchone()[0] is None


def test_signal_event_lookup_index_exists(connection: sqlite3.Connection) -> None:
    indexes = connection.execute("PRAGMA index_list(signal_events)").fetchall()

    assert "idx_signal_events_signal_time" in {
        index["name"] for index in indexes
    }


def test_create_signal_events_table_is_idempotent_and_preserves_rows(
    connection: sqlite3.Connection,
) -> None:
    insert_event(connection)

    create_signal_events_table(connection)

    assert connection.execute(
        "SELECT COUNT(*) FROM signal_events"
    ).fetchone()[0] == 1


def test_create_signal_events_table_requires_sqlite_connection() -> None:
    with pytest.raises(TypeError):
        create_signal_events_table(object())  # type: ignore[arg-type]
