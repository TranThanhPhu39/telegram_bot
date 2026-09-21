"""Migration 4: users, watchlist and portfolio_holdings."""

import sqlite3

import pytest

from data.database import connect_database
from data.migrations import (
    LATEST_SCHEMA_VERSION,
    MIGRATIONS,
    SCHEMA_MIGRATIONS_TABLE_SQL,
    bootstrap_schema,
)


def fresh():
    connection = connect_database("sqlite:///:memory:")
    bootstrap_schema(connection)
    return connection


def tables(connection):
    return {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_user_watchlist_and_holdings_tables_are_created() -> None:
    connection = fresh()
    assert LATEST_SCHEMA_VERSION == 7
    assert {"users", "watchlist", "portfolio_holdings"} <= tables(connection)
    columns = {r["name"] for r in connection.execute("PRAGMA table_info(users)")}
    assert columns == {
        "telegram_user_id", "risk_profile", "default_risk_per_trade_pct",
        "created_at", "updated_at", "default_risk_per_trade_decimal",
    }
    assert {r["name"] for r in connection.execute("PRAGMA table_info(portfolio_holdings)")} == {
        "telegram_user_id", "symbol", "quantity", "average_cost",
        "average_cost_decimal", "updated_at",
    }
    assert {r["name"] for r in connection.execute("PRAGMA table_info(watchlist)")} == {
        "telegram_user_id", "symbol", "created_at",
    }


def test_repeat_migration_is_idempotent_and_preserves_existing_data() -> None:
    connection = connect_database("sqlite:///:memory:")
    bootstrap_schema(connection)
    connection.execute("INSERT INTO symbols(symbol) VALUES ('FPT')")
    connection.execute("INSERT INTO users(telegram_user_id) VALUES (7)")
    connection.commit()
    assert bootstrap_schema(connection) == 7
    assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 7
    assert connection.execute("SELECT symbol FROM symbols").fetchone()[0] == "FPT"
    assert connection.execute("SELECT telegram_user_id FROM users").fetchone()[0] == 7


def test_upgrade_from_version_3_keeps_old_rows(tmp_path) -> None:
    url = f"sqlite:///{(tmp_path / 'old.sqlite3').as_posix()}"
    connection = connect_database(url)
    bootstrap_schema(connection)
    connection.execute("INSERT INTO symbols(symbol) VALUES ('ACB')")
    connection.execute("DELETE FROM schema_migrations WHERE version >= 4")
    for table in ("portfolio_holdings", "watchlist", "users"):
        connection.execute(f"DROP TABLE {table}")
    connection.commit()
    assert bootstrap_schema(connection) == 7
    assert "users" in tables(connection)
    assert connection.execute("SELECT symbol FROM symbols").fetchone()[0] == "ACB"


def test_upgrade_from_version_4_backfills_exact_decimal_text() -> None:
    connection = connect_database("sqlite:///:memory:")
    connection.execute(SCHEMA_MIGRATIONS_TABLE_SQL)
    for migration in MIGRATIONS[:4]:
        for statement in migration.statements:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
            (migration.version, migration.name),
        )
    connection.execute("INSERT INTO symbols(symbol) VALUES ('FPT')")
    connection.execute(
        "INSERT INTO users(telegram_user_id, default_risk_per_trade_pct) VALUES (1, 1.25)"
    )
    connection.execute(
        "INSERT INTO portfolio_holdings(telegram_user_id, symbol, quantity, average_cost) "
        "VALUES (1, 'FPT', 10, 150000.5)"
    )
    connection.commit()

    assert bootstrap_schema(connection) == 7
    user = connection.execute("SELECT * FROM users WHERE telegram_user_id=1").fetchone()
    holding = connection.execute("SELECT * FROM portfolio_holdings").fetchone()
    assert user["default_risk_per_trade_decimal"] == "1.25"
    assert holding["average_cost_decimal"] == "150000.5"


def test_primary_keys_enforce_uniqueness() -> None:
    connection = fresh()
    connection.execute("INSERT INTO symbols(symbol) VALUES ('FPT')")
    connection.execute("INSERT INTO users(telegram_user_id) VALUES (1)")
    connection.execute("INSERT INTO watchlist(telegram_user_id, symbol) VALUES (1,'FPT')")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO watchlist(telegram_user_id, symbol) VALUES (1,'FPT')")
    connection.execute(
        "INSERT INTO portfolio_holdings(telegram_user_id, symbol, quantity, average_cost) "
        "VALUES (1,'FPT',10,100.0)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO portfolio_holdings(telegram_user_id, symbol, quantity, average_cost) "
            "VALUES (1,'FPT',5,90.0)"
        )


def test_foreign_keys_and_checks_reject_bad_rows() -> None:
    connection = fresh()
    connection.execute("INSERT INTO symbols(symbol) VALUES ('FPT')")
    connection.execute("INSERT INTO users(telegram_user_id) VALUES (1)")
    with pytest.raises(sqlite3.IntegrityError):  # unknown user
        connection.execute("INSERT INTO watchlist(telegram_user_id, symbol) VALUES (2,'FPT')")
    with pytest.raises(sqlite3.IntegrityError):  # unknown symbol
        connection.execute("INSERT INTO watchlist(telegram_user_id, symbol) VALUES (1,'XXX')")
    for quantity, cost in ((0, 1.0), (-5, 1.0), (10, 0.0), (10, -1.0)):
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO portfolio_holdings(telegram_user_id, symbol, quantity, average_cost) "
                "VALUES (1,'FPT',?,?)", (quantity, cost),
            )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE users SET default_risk_per_trade_pct = 0 WHERE telegram_user_id = 1"
        )


def test_deleting_a_user_cascades_to_their_rows_only() -> None:
    connection = fresh()
    connection.execute("INSERT INTO symbols(symbol) VALUES ('FPT')")
    connection.executemany("INSERT INTO users(telegram_user_id) VALUES (?)", [(1,), (2,)])
    connection.executemany(
        "INSERT INTO watchlist(telegram_user_id, symbol) VALUES (?, 'FPT')", [(1,), (2,)]
    )
    connection.execute("DELETE FROM users WHERE telegram_user_id = 1")
    assert [r[0] for r in connection.execute("SELECT telegram_user_id FROM watchlist")] == [2]
