"""RuntimeBotDataService.candlestick_chart acquires bars, never draws pixels."""

from __future__ import annotations

from data.database import connect_database
from runtime.bot_service import RuntimeBotDataService
from scanner.universe import ScannerInstrument


class FakeClient:
    def __init__(self, payload=None, *, fail: bool = False) -> None:
        self.payload = payload
        self.fail = fail
        self.calls: list[tuple[str, ...]] = []

    def get_gap_chart(self, symbols, **kwargs):
        self.calls.append(tuple(symbols))
        if self.fail or self.payload is None:
            raise ValueError("offline")
        rows = []
        for symbol in symbols:
            row = dict(self.payload)
            row["symbol"] = symbol
            rows.append(row)
        return rows


def payload(count: int = 200) -> dict:
    timestamps = [1_789_300_800 + index * 86_400 for index in range(count)]
    closes = [20_000.0 + index * 5 for index in range(count)]
    return {
        "symbol": "FPT", "t": [str(value) for value in timestamps],
        "o": closes, "h": [value + 100 for value in closes],
        "l": [value - 100 for value in closes], "c": closes,
        "v": [50_000.0 + index for index in range(count)],
    }


def service(client) -> RuntimeBotDataService:
    return RuntimeBotDataService(
        client, connect_database("sqlite:///:memory:"),
        (ScannerInstrument("FPT", "HOSE", "STOCK"),),
        now=lambda: 1_800_000_000,
    )


def test_chart_returns_png_bytes_and_caption_for_available_history() -> None:
    runtime = service(FakeClient(payload()))

    result = runtime.candlestick_chart("fpt")

    assert result.symbol == "FPT"
    assert result.error is None
    assert result.png_bytes is not None
    assert result.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert "FPT" in result.caption
    assert "phiên" in result.caption


def test_chart_reports_honest_error_when_no_history_exists() -> None:
    runtime = service(FakeClient(fail=True))

    result = runtime.candlestick_chart("FPT")

    assert result.png_bytes is None
    assert result.error is not None
    assert "Chưa có dữ liệu" in result.error


def test_chart_reports_honest_error_when_history_is_too_short() -> None:
    runtime = service(FakeClient(payload(count=3)))

    result = runtime.candlestick_chart("FPT")

    assert result.png_bytes is None
    assert result.error is not None
    assert "Không thể vẽ biểu đồ" in result.error


def test_chart_uses_sqlite_fallback_after_provider_failure() -> None:
    client = FakeClient(payload())
    warm = service(client)
    warm.candlestick_chart("FPT")  # populates the SQLite cache

    client.fail = True
    result = warm.candlestick_chart("FPT")

    assert result.error is None
    assert result.png_bytes is not None
    assert "SQLite" in result.caption or "cached" in result.caption.lower()


def test_chart_does_not_call_the_provider_a_second_time_needlessly() -> None:
    client = FakeClient(payload())
    runtime = service(client)

    runtime.candlestick_chart("FPT")
    calls_after_first = len(client.calls)
    runtime.candlestick_chart("FPT")

    assert len(client.calls) == calls_after_first + 1  # each call refreshes once
