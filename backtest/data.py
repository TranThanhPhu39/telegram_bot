"""Read-only normalized historical-data ports for offline backtest jobs."""

from __future__ import annotations

import sqlite3

from data.models import OHLCVBar


class SQLiteDailyBarData:
    def __init__(self, connection: sqlite3.Connection) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        self.connection = connection

    def daily_bars(self, symbol: str) -> tuple[OHLCVBar, ...]:
        normalized = symbol.strip().upper()
        rows = self.connection.execute(
            "SELECT symbol,timeframe,timestamp,open,high,low,close,volume "
            "FROM candles WHERE symbol=? AND timeframe='ONE_DAY' ORDER BY timestamp",
            (normalized,),
        ).fetchall()
        return tuple(
            OHLCVBar(
                row["symbol"], row["timeframe"], row["timestamp"], row["open"],
                row["high"], row["low"], row["close"], row["volume"],
            )
            for row in rows
        )
