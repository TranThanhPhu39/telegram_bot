"""SQLite persistence and point-in-time queries for ASMF inputs."""

from __future__ import annotations

from datetime import date
import sqlite3
from typing import Iterable

from asmf_data.models import FinancialReport, InstitutionalFlow, SectorMembership


def upsert_sector_memberships(connection: sqlite3.Connection, rows: Iterable[SectorMembership]) -> int:
    values = tuple(rows)
    _ensure_symbols(connection, (row.symbol for row in values))
    with connection:
        connection.executemany(
            "INSERT INTO sector_memberships VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(symbol,sector_code,effective_from) DO UPDATE SET "
            "sector_name=excluded.sector_name,effective_to=excluded.effective_to,source=excluded.source",
            [(r.symbol, r.sector_code, r.sector_name, r.effective_from.isoformat(),
              None if r.effective_to is None else r.effective_to.isoformat(), r.source) for r in values],
        )
    return len(values)


def upsert_financial_reports(connection: sqlite3.Connection, rows: Iterable[FinancialReport]) -> int:
    values = tuple(rows)
    _ensure_symbols(connection, (row.symbol for row in values))
    with connection:
        connection.executemany(
            "INSERT INTO financial_reports VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(symbol,report_period,consolidated) DO UPDATE SET "
            "public_date=excluded.public_date,revenue=excluded.revenue,net_profit=excluded.net_profit,"
            "equity=excluded.equity,total_debt=excluded.total_debt,source=excluded.source",
            [(r.symbol, r.report_period, r.public_date.isoformat(), int(r.consolidated),
              r.revenue, r.net_profit, r.equity, r.total_debt, r.source) for r in values],
        )
    return len(values)


def upsert_institutional_flows(connection: sqlite3.Connection, rows: Iterable[InstitutionalFlow]) -> int:
    values = tuple(rows)
    _ensure_symbols(connection, (row.symbol for row in values))
    with connection:
        connection.executemany(
            "INSERT INTO institutional_flows VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(symbol,trading_date) DO UPDATE SET "
            "foreign_buy_value=excluded.foreign_buy_value,foreign_sell_value=excluded.foreign_sell_value,"
            "proprietary_buy_value=excluded.proprietary_buy_value,"
            "proprietary_sell_value=excluded.proprietary_sell_value,source=excluded.source",
            [(r.symbol, r.trading_date.isoformat(), r.foreign_buy_value, r.foreign_sell_value,
              r.proprietary_buy_value, r.proprietary_sell_value, r.source) for r in values],
        )
    return len(values)


def latest_financial_reports(connection: sqlite3.Connection, symbol: str, as_of: date) -> tuple[sqlite3.Row, ...]:
    return tuple(connection.execute(
        "SELECT * FROM financial_reports WHERE symbol=? AND consolidated=1 AND public_date<=? "
        "ORDER BY report_period DESC LIMIT 8", (symbol, as_of.isoformat())
    ).fetchall())


def recent_flows(connection: sqlite3.Connection, symbol: str, as_of: date) -> tuple[sqlite3.Row, ...]:
    return tuple(connection.execute(
        "SELECT * FROM institutional_flows WHERE symbol=? AND trading_date<=? "
        "ORDER BY trading_date DESC LIMIT 10", (symbol, as_of.isoformat())
    ).fetchall())


def active_sector(connection: sqlite3.Connection, symbol: str, as_of: date) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM sector_memberships WHERE symbol=? AND effective_from<=? "
        "AND (effective_to IS NULL OR effective_to>=?) ORDER BY effective_from DESC LIMIT 1",
        (symbol, as_of.isoformat(), as_of.isoformat()),
    ).fetchone()


def sector_members(connection: sqlite3.Connection, sector_code: str, as_of: date) -> tuple[str, ...]:
    rows = connection.execute(
        "SELECT symbol FROM sector_memberships WHERE sector_code=? AND effective_from<=? "
        "AND (effective_to IS NULL OR effective_to>=?) ORDER BY symbol",
        (sector_code, as_of.isoformat(), as_of.isoformat()),
    ).fetchall()
    return tuple(row["symbol"] for row in rows)


def _ensure_symbols(connection: sqlite3.Connection, symbols: Iterable[str]) -> None:
    with connection:
        connection.executemany(
            "INSERT INTO symbols(symbol,instrument_type) VALUES (?,'STOCK') ON CONFLICT(symbol) DO NOTHING",
            [(symbol,) for symbol in set(symbols)],
        )
