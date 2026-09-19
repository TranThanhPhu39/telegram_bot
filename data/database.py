"""SQLite connection boundary for the V1 local datastore."""

from __future__ import annotations

import sqlite3

SQLITE_URL_PREFIX = "sqlite:///"
IN_MEMORY_DATABASE_URL = "sqlite:///:memory:"


class DatabaseConfigurationError(ValueError):
    """Raised when the configured database URL is unsupported or malformed."""


def sqlite_path_from_url(database_url: str) -> str:
    """Return the sqlite3 path encoded by a supported database URL."""
    if not isinstance(database_url, str):
        raise TypeError("database_url must be a string")
    normalized = database_url.strip()
    if not normalized.startswith(SQLITE_URL_PREFIX):
        raise DatabaseConfigurationError(
            "V1 supports only DATABASE_URL values beginning with sqlite:///"
        )
    path = normalized.removeprefix(SQLITE_URL_PREFIX)
    if not path:
        raise DatabaseConfigurationError("SQLite database path must not be empty")
    return ":memory:" if normalized == IN_MEMORY_DATABASE_URL else path


def connect_database(database_url: str) -> sqlite3.Connection:
    """Open a configured SQLite connection without creating application tables."""
    connection = sqlite3.connect(sqlite_path_from_url(database_url))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection
