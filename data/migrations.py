"""Versioned SQLite schema bootstrap for the V1 datastore."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from data.schema import (
    CANDLES_TABLE_SQL,
    SIGNAL_EVENTS_INDEX_SQL,
    SIGNAL_EVENTS_TABLE_SQL,
    SIGNALS_INDEX_SQL,
    SIGNALS_TABLE_SQL,
    SYMBOLS_TABLE_SQL,
    SECTOR_MEMBERSHIPS_TABLE_SQL,
    FINANCIAL_REPORTS_TABLE_SQL,
    INSTITUTIONAL_FLOWS_TABLE_SQL,
    BANK_FINANCIAL_REPORTS_TABLE_SQL,
    USERS_TABLE_SQL,
    WATCHLIST_TABLE_SQL,
    WATCHLIST_INDEX_SQL,
    PORTFOLIO_HOLDINGS_TABLE_SQL,
    PORTFOLIO_HOLDINGS_INDEX_SQL,
)

SCHEMA_MIGRATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    applied_at INTEGER NOT NULL DEFAULT (unixepoch()),
    CHECK (version > 0),
    CHECK (length(trim(name)) > 0),
    CHECK (applied_at > 0)
)
"""


class SchemaMigrationError(RuntimeError):
    """Raised when the database schema cannot be migrated safely."""


@dataclass(frozen=True, slots=True)
class Migration:
    """One ordered, atomic schema migration."""

    version: int
    name: str
    statements: tuple[str, ...]


MIGRATIONS = (
    Migration(
        version=1,
        name="initial_v1_schema",
        statements=(
            SYMBOLS_TABLE_SQL,
            CANDLES_TABLE_SQL,
            SIGNALS_TABLE_SQL,
            SIGNALS_INDEX_SQL,
            SIGNAL_EVENTS_TABLE_SQL,
            SIGNAL_EVENTS_INDEX_SQL,
        ),
    ),
    Migration(
        version=2,
        name="asmf_eod_inputs",
        statements=(
            SECTOR_MEMBERSHIPS_TABLE_SQL,
            FINANCIAL_REPORTS_TABLE_SQL,
            INSTITUTIONAL_FLOWS_TABLE_SQL,
        ),
    ),
    Migration(
        version=3,
        name="asmf_bank_financials",
        statements=(BANK_FINANCIAL_REPORTS_TABLE_SQL,),
    ),
    Migration(
    version=4,
    name="portfolio_watchlist_holdings",
    statements=(
        USERS_TABLE_SQL,
        WATCHLIST_TABLE_SQL,
        WATCHLIST_INDEX_SQL,
        PORTFOLIO_HOLDINGS_TABLE_SQL,
        PORTFOLIO_HOLDINGS_INDEX_SQL,
        ),
    ),
)

LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version


def bootstrap_schema(connection: sqlite3.Connection) -> int:
    """Apply every pending migration atomically and return the schema version."""
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be a sqlite3.Connection")

    with connection:
        connection.execute(SCHEMA_MIGRATIONS_TABLE_SQL)
        applied_rows = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        known_by_version = {migration.version: migration for migration in MIGRATIONS}
        for row in applied_rows:
            version = int(row["version"])
            migration = known_by_version.get(version)
            if migration is None:
                raise SchemaMigrationError(
                    f"Database schema version {version} is newer or unknown"
                )
            if row["name"] != migration.name:
                raise SchemaMigrationError(
                    f"Database migration {version} name does not match code"
                )

        applied_versions = {int(row["version"]) for row in applied_rows}
        for migration in MIGRATIONS:
            if migration.version in applied_versions:
                continue
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )

    return LATEST_SCHEMA_VERSION
