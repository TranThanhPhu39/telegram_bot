"""SQLite persistence for users, watchlists and holdings."""

from __future__ import annotations

from decimal import Decimal
import re
import sqlite3
import time
from collections.abc import Callable

from portfolio.models import (
    PortfolioError,
    PortfolioHolding,
    UserProfile,
    WatchlistEntry,
)

SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")
NON_STOCK_SYMBOLS = frozenset({"VNINDEX", "VN30", "HNXINDEX", "HNX30", "UPCOMINDEX"})


def normalize_symbol(raw: object) -> str:
    """Return an upper-case ticker or raise a user-facing error."""
    symbol = raw.strip().upper() if isinstance(raw, str) else ""
    if not SYMBOL_PATTERN.match(symbol):
        raise PortfolioError("Invalid symbol. Use a ticker such as FPT.")
    if symbol in NON_STOCK_SYMBOLS:
        raise PortfolioError(f"{symbol} is an index, not a stock.")
    return symbol


def _decimal(value: float | int | str) -> Decimal:
    return Decimal(str(value))


def _decimal_text(value: Decimal) -> str:
    """Canonical non-exponent form for exact SQLite round-tripping."""
    return format(value, "f")


class SQLitePortfolioRepository:
    """Requires ``bootstrap_schema`` (through migration 5) to have been applied."""

    def __init__(
        self, connection: sqlite3.Connection, now: Callable[[], float] = time.time
    ) -> None:
        self.connection = connection
        self.now = now

    def _ts(self) -> int:
        return max(1, int(self.now()))

    # ---------------------------------------------------------------- users

    def ensure_user(self, telegram_user_id: int) -> UserProfile:
        if not isinstance(telegram_user_id, int) or isinstance(telegram_user_id, bool) \
                or telegram_user_id <= 0:
            raise PortfolioError("Invalid Telegram user.")
        ts = self._ts()
        with self.connection:
            self.connection.execute(
                "INSERT INTO users(telegram_user_id, created_at, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(telegram_user_id) DO NOTHING",
                (telegram_user_id, ts, ts),
            )
        return self.get_user(telegram_user_id)  # type: ignore[return-value]

    def get_user(self, telegram_user_id: int) -> UserProfile | None:
        row = self.connection.execute(
            "SELECT * FROM users WHERE telegram_user_id=?", (telegram_user_id,)
        ).fetchone()
        if row is None:
            return None
        pct = row["default_risk_per_trade_decimal"]
        if pct is None:
            pct = row["default_risk_per_trade_pct"]  # pre-v5/backfill compatibility
        return UserProfile(
            row["telegram_user_id"], row["risk_profile"],
            None if pct is None else _decimal(pct), row["created_at"], row["updated_at"],
        )

    def set_default_risk(self, telegram_user_id: int, risk_pct: Decimal) -> None:
        self.ensure_user(telegram_user_id)
        with self.connection:
            self.connection.execute(
                "UPDATE users SET default_risk_per_trade_pct=?, "
                "default_risk_per_trade_decimal=?, updated_at=? WHERE telegram_user_id=?",
                (float(risk_pct), _decimal_text(risk_pct), self._ts(), telegram_user_id),
            )

    # ------------------------------------------------------------ watchlist

    def add_watch(self, telegram_user_id: int, symbol: str) -> bool:
        """Return True when newly added, False when it was already watched."""
        symbol = normalize_symbol(symbol)
        self.ensure_user(telegram_user_id)
        with self.connection:
            self._ensure_symbol(symbol)
            cursor = self.connection.execute(
                "INSERT INTO watchlist(telegram_user_id, symbol, created_at) VALUES (?,?,?) "
                "ON CONFLICT(telegram_user_id, symbol) DO NOTHING",
                (telegram_user_id, symbol, self._ts()),
            )
        return cursor.rowcount == 1

    def remove_watch(self, telegram_user_id: int, symbol: str) -> bool:
        symbol = normalize_symbol(symbol)
        with self.connection:
            cursor = self.connection.execute(
                "DELETE FROM watchlist WHERE telegram_user_id=? AND symbol=?",
                (telegram_user_id, symbol),
            )
        return cursor.rowcount == 1

    def list_watchlist(self, telegram_user_id: int) -> tuple[WatchlistEntry, ...]:
        rows = self.connection.execute(
            "SELECT * FROM watchlist WHERE telegram_user_id=? ORDER BY created_at, symbol",
            (telegram_user_id,),
        ).fetchall()
        return tuple(
            WatchlistEntry(row["telegram_user_id"], row["symbol"], row["created_at"])
            for row in rows
        )

    def is_watched(self, telegram_user_id: int, symbol: str) -> bool:
        """Alert-preparation hook; the existing alert manager is untouched."""
        return self.connection.execute(
            "SELECT 1 FROM watchlist WHERE telegram_user_id=? AND symbol=?",
            (telegram_user_id, str(symbol).strip().upper()),
        ).fetchone() is not None

    # ------------------------------------------------------------- holdings

    def upsert_holding(
        self, telegram_user_id: int, symbol: str, quantity: int, average_cost: Decimal
    ) -> bool:
        """Create or replace a long holding; return True when it was created."""
        symbol = normalize_symbol(symbol)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise PortfolioError("Quantity must be a whole number greater than 0.")
        if not isinstance(average_cost, Decimal) or not average_cost.is_finite() \
                or average_cost <= 0:
            raise PortfolioError("Average cost must be greater than 0.")
        self.ensure_user(telegram_user_id)
        existed = self.get_holding(telegram_user_id, symbol) is not None
        with self.connection:
            self._ensure_symbol(symbol)
            self.connection.execute(
                "INSERT INTO portfolio_holdings(telegram_user_id, symbol, quantity, "
                "average_cost, average_cost_decimal, updated_at) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(telegram_user_id, symbol) DO UPDATE SET "
                "quantity=excluded.quantity, average_cost=excluded.average_cost, "
                "average_cost_decimal=excluded.average_cost_decimal, "
                "updated_at=excluded.updated_at",
                (
                    telegram_user_id, symbol, quantity, float(average_cost),
                    _decimal_text(average_cost), self._ts(),
                ),
            )
        return not existed

    def remove_holding(self, telegram_user_id: int, symbol: str) -> bool:
        symbol = normalize_symbol(symbol)
        with self.connection:
            cursor = self.connection.execute(
                "DELETE FROM portfolio_holdings WHERE telegram_user_id=? AND symbol=?",
                (telegram_user_id, symbol),
            )
        return cursor.rowcount == 1

    def get_holding(self, telegram_user_id: int, symbol: str) -> PortfolioHolding | None:
        row = self.connection.execute(
            "SELECT * FROM portfolio_holdings WHERE telegram_user_id=? AND symbol=?",
            (telegram_user_id, str(symbol).strip().upper()),
        ).fetchone()
        return None if row is None else self._holding(row)

    def list_holdings(self, telegram_user_id: int) -> tuple[PortfolioHolding, ...]:
        rows = self.connection.execute(
            "SELECT * FROM portfolio_holdings WHERE telegram_user_id=? ORDER BY symbol",
            (telegram_user_id,),
        ).fetchall()
        return tuple(self._holding(row) for row in rows)

    def is_held(self, telegram_user_id: int, symbol: str) -> bool:
        """Alert-preparation hook; the existing alert manager is untouched."""
        return self.get_holding(telegram_user_id, symbol) is not None

    # ------------------------------------------------------------- internals

    @staticmethod
    def _holding(row: sqlite3.Row) -> PortfolioHolding:
        average_cost = row["average_cost_decimal"]
        if average_cost is None:
            average_cost = row["average_cost"]  # pre-v5/backfill compatibility
        return PortfolioHolding(
            row["telegram_user_id"], row["symbol"], int(row["quantity"]),
            _decimal(average_cost), row["updated_at"],
        )

    def _ensure_symbol(self, symbol: str) -> None:
        self.connection.execute(
            "INSERT INTO symbols(symbol, instrument_type) VALUES (?, 'STOCK') "
            "ON CONFLICT(symbol) DO NOTHING",
            (symbol,),
        )
