"""Historical-first runtime service backing Telegram commands."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import sqlite3
import time
from collections.abc import Callable
from typing import Protocol

from dotenv import load_dotenv

from data.database import connect_database
from data.indicators import breakout_levels, ema20, ema50, rsi14
from data.migrations import bootstrap_schema
from data.models import OHLCVBar
from data.vietcap.historical import normalize_gap_chart
from data.vietcap.rest import VietcapRestClient, VietcapRestError, VietcapTimeFrame
from scanner.universe import ScannerConfig, ScannerInstrument, daily_prescreen, realtime_watch_universe


VIETNAM_TIMEZONE = timezone(timedelta(hours=7))


class HistoricalClient(Protocol):
    def get_gap_chart(self, symbols: tuple[str, ...], *, time_frame: object, count_back: int, to_timestamp: int) -> list[dict[str, object]]: ...


class RuntimeBotDataService:
    """Connect REST history, SQLite cache, indicators, scanner, and Telegram."""

    def __init__(
        self,
        client: HistoricalClient,
        connection: sqlite3.Connection,
        instruments: tuple[ScannerInstrument, ...],
        *,
        history_count: int = 170,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.client = client
        self.connection = connection
        self.instruments = instruments
        self.history_count = history_count
        self.now = now
        bootstrap_schema(connection)

    def symbol_overview(self, symbol: str) -> str:
        bars, note = self._history(symbol)
        if not bars:
            return f"Chưa có dữ liệu lịch sử cho {symbol}. {note}"
        latest = bars[-1]
        previous = bars[-2] if len(bars) > 1 else None
        change = 0.0 if previous is None else (latest.close / previous.close - 1.0) * 100.0
        ema_20, ema_50, rsi_14 = ema20(bars)[-1], ema50(bars)[-1], rsi14(bars)[-1]
        return (
            f"{symbol} — phiên {_date(latest.timestamp)}\n"
            f"Đóng cửa: {latest.close:g} ({change:+.2f}%)\n"
            f"Khối lượng: {latest.volume:g}\n"
            f"EMA20: {_number(ema_20)} | EMA50: {_number(ema_50)} | RSI14: {_number(rsi_14)}\n"
            f"Nguồn: {note}"
        )

    def scan_results(self) -> tuple[str, ...]:
        histories = {item.symbol: self._history(item.symbol)[0] for item in self.instruments}
        config = ScannerConfig(20, 0.0, 0.0, min(20, len(self.instruments)))
        screened = daily_prescreen(
            self.instruments, histories, config, as_of_timestamp=int(self.now()) + 1
        )
        return realtime_watch_universe(screened, config)

    def market_overview(self) -> str:
        bars, note = self._history("VNINDEX")
        if not bars:
            return f"Chưa có dữ liệu lịch sử VNINDEX. {note}"
        latest = bars[-1]
        previous = bars[-2] if len(bars) > 1 else None
        change = 0.0 if previous is None else (latest.close / previous.close - 1.0) * 100.0
        e20, e50 = ema20(bars)[-1], ema50(bars)[-1]
        if e20 is None or e50 is None:
            trend = "CHƯA ĐỦ DỮ LIỆU"
        elif latest.close > e20 > e50:
            trend = "TĂNG"
        elif latest.close < e20 < e50:
            trend = "GIẢM"
        else:
            trend = "TRUNG TÍNH"
        return (
            f"VNINDEX — phiên {_date(latest.timestamp)}\n"
            f"Đóng cửa: {latest.close:g} ({change:+.2f}%)\n"
            f"Xu hướng EMA: {trend}\nNguồn: {note}\n"
            "Breadth realtime không có ngoài phiên; không suy đoán Market Regime đầy đủ."
        )

    def signal_explanation(self, symbol: str) -> str:
        bars, note = self._history(symbol)
        if len(bars) < 50:
            return f"Chưa đủ tối thiểu 50 phiên để giải thích {symbol}. {note}"
        e20, e50, rsi_values = ema20(bars), ema50(bars), rsi14(bars)
        levels = breakout_levels(bars, 20)
        latest = bars[-1]
        positives: list[str] = []
        negatives: list[str] = []
        if e20[-1] is not None and e50[-1] is not None and latest.close > e20[-1] > e50[-1]:
            positives.append("giá > EMA20 > EMA50")
        else:
            negatives.append("xu hướng EMA chưa xác nhận")
        if levels[-1] is not None and latest.close > levels[-1].resistance:
            positives.append("đóng cửa vượt kháng cự 20 phiên")
        else:
            negatives.append("chưa vượt kháng cự 20 phiên")
        return (
            f"{symbol} — phiên {_date(latest.timestamp)}\n"
            f"Tích cực: {', '.join(positives) or 'không có'}\n"
            f"Chưa xác nhận: {', '.join(negatives) or 'không có'}\n"
            f"RSI14: {_number(rsi_values[-1])}\nNguồn: {note}\n"
            "Đây là context lịch sử; không phải khuyến nghị mua/bán."
        )

    def performance_overview(self) -> str:
        return (
            "Preliminary backtest: 120 phiên ACB/VNINDEX (175 ngày lịch)\n"
            "Giao dịch: 0 | Win rate: 0.00% | Lợi nhuận TB: 0.00%\n"
            "Max drawdown: 0.00% | Profit factor: N/A\n"
            "Kết quả zero-activity, không phải tuyên bố lợi nhuận."
        )

    def _history(self, symbol: str) -> tuple[tuple[OHLCVBar, ...], str]:
        symbol = symbol.strip().upper()
        try:
            payload = self.client.get_gap_chart(
                (symbol,), time_frame=VietcapTimeFrame.ONE_DAY,
                count_back=self.history_count, to_timestamp=int(self.now()),
            )
            bars = tuple(
                bar for bar in normalize_gap_chart(payload, time_frame=VietcapTimeFrame.ONE_DAY)
                if bar.symbol == symbol
            )
            if bars:
                self._store(symbol, bars)
                return bars, "Vietcap historical"
        except (VietcapRestError, ValueError):
            pass
        cached = self._load(symbol)
        return cached, "SQLite cache" if cached else "Vietcap/SQLite đều không có dữ liệu"

    def _store(self, symbol: str, bars: tuple[OHLCVBar, ...]) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO symbols(symbol, instrument_type) VALUES (?, 'STOCK') "
                "ON CONFLICT(symbol) DO NOTHING", (symbol,),
            )
            self.connection.executemany(
                "INSERT INTO candles(symbol,timeframe,timestamp,open,high,low,close,volume) "
                "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(symbol,timeframe,timestamp) DO UPDATE SET "
                "open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,volume=excluded.volume",
                [(bar.symbol, bar.timeframe, bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume) for bar in bars],
            )

    def _load(self, symbol: str) -> tuple[OHLCVBar, ...]:
        rows = self.connection.execute(
            "SELECT * FROM candles WHERE symbol=? AND timeframe='ONE_DAY' ORDER BY timestamp DESC LIMIT ?",
            (symbol, self.history_count),
        ).fetchall()
        return tuple(
            OHLCVBar(row["symbol"], row["timeframe"], row["timestamp"], row["open"], row["high"], row["low"], row["close"], row["volume"])
            for row in reversed(rows)
        )


def build_runtime_service_from_env() -> RuntimeBotDataService:
    load_dotenv()
    required = {name: os.getenv(name, "").strip() for name in (
        "VIETCAP_AUTHORIZATION", "VIETCAP_DEVICE_ID", "VIETCAP_COOKIE"
    )}
    if not all(required.values()):
        raise RuntimeError("Vietcap historical credentials are missing from .env")
    client = VietcapRestClient(
        authorization=required["VIETCAP_AUTHORIZATION"],
        device_id=required["VIETCAP_DEVICE_ID"], cookie=required["VIETCAP_COOKIE"],
    )
    connection = connect_database(os.getenv("DATABASE_URL", "sqlite:///stock_bot.db"))
    instruments = _instruments(os.getenv("BOT_WATCH_SYMBOLS", "FPT:HOSE,ACB:HOSE"))
    return RuntimeBotDataService(client, connection, instruments)


def _instruments(raw: str) -> tuple[ScannerInstrument, ...]:
    result = []
    for item in raw.split(","):
        parts = item.strip().upper().split(":")
        if len(parts) != 2:
            raise ValueError("BOT_WATCH_SYMBOLS must use SYMBOL:EXCHANGE entries")
        result.append(ScannerInstrument(parts[0], parts[1], "STOCK"))
    return tuple(result)


def _date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, VIETNAM_TIMEZONE).strftime("%d/%m/%Y")


def _number(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"
