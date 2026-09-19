"""Tests for the Phase 9 SQLite connection boundary."""

from __future__ import annotations

import sqlite3

import pytest

from data.database import (
    DatabaseConfigurationError,
    connect_database,
    sqlite_path_from_url,
)


def test_sqlite_path_from_relative_url() -> None:
    assert sqlite_path_from_url(" sqlite:///stock_bot.db ") == "stock_bot.db"


def test_in_memory_url_maps_to_sqlite_special_path() -> None:
    assert sqlite_path_from_url("sqlite:///:memory:") == ":memory:"


@pytest.mark.parametrize(
    "database_url",
    ["", "sqlite://", "sqlite:///", "postgresql://localhost/stock_bot"],
)
def test_rejects_unsupported_or_empty_database_urls(database_url: str) -> None:
    with pytest.raises(DatabaseConfigurationError):
        sqlite_path_from_url(database_url)


def test_rejects_non_string_database_url() -> None:
    with pytest.raises(TypeError):
        sqlite_path_from_url(None)  # type: ignore[arg-type]


def test_connect_database_configures_safe_connection_defaults() -> None:
    connection = connect_database("sqlite:///:memory:")
    try:
        assert connection.row_factory is sqlite3.Row
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_file_database_persists_across_connections(tmp_path) -> None:
    database_path = tmp_path / "phase9.sqlite3"
    database_url = f"sqlite:///{database_path.as_posix()}"

    first = connect_database(database_url)
    first.execute("CREATE TABLE probe (value INTEGER NOT NULL)")
    first.execute("INSERT INTO probe VALUES (42)")
    first.commit()
    first.close()

    second = connect_database(database_url)
    try:
        assert second.execute("SELECT value FROM probe").fetchone()[0] == 42
    finally:
        second.close()
