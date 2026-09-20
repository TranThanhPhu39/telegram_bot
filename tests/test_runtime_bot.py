"""Tests for historical-first runtime orchestration."""

from data.database import connect_database
from runtime.bot_service import RuntimeBotDataService
from scanner.universe import ScannerInstrument


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.fail = False

    def get_gap_chart(self, symbols, **kwargs):
        if self.fail:
            raise ValueError("offline")
        symbol = symbols[0]
        row = dict(self.payload)
        row["symbol"] = symbol
        return [row]


def payload(count=260):
    timestamps = [1_789_300_800 + index * 86_400 for index in range(count)]
    closes = [100.0 + index for index in range(count)]
    return {
        "symbol": "FPT", "t": [str(value) for value in timestamps],
        "o": closes, "h": [value + 1 for value in closes],
        "l": [value - 1 for value in closes], "c": closes,
        "v": [100_000.0 + index for index in range(count)],
    }


def service(client):
    return RuntimeBotDataService(
        client, connect_database("sqlite:///:memory:"),
        (ScannerInstrument("FPT", "HOSE", "STOCK"),),
        now=lambda: 1_800_000_000,
    )


def test_symbol_market_why_scan_and_performance_use_real_modules() -> None:
    runtime = service(FakeClient(payload()))
    assert "phiên" in runtime.symbol_overview("FPT")
    assert "EMA20" in runtime.symbol_overview("FPT")
    assert "Chiến lược CL1" in runtime.symbol_overview("FPT", "CL1")
    assert "Chiến lược ASMF" in runtime.symbol_overview("FPT", "ASMF")
    assert "CL1" in runtime.strategy_catalog()
    assert "VNINDEX" in runtime.market_overview()
    assert "khuyến nghị" in runtime.signal_explanation("FPT")
    assert runtime.scan_results() == ("FPT",)
    assert "120 phiên" in runtime.performance_overview()


def test_closed_market_or_network_failure_uses_sqlite_last_session() -> None:
    client = FakeClient(payload())
    runtime = service(client)
    online = runtime.symbol_overview("FPT")
    client.fail = True
    cached = runtime.symbol_overview("FPT")
    assert "Vietcap historical" in online
    assert "SQLite cache" in cached
    assert "phiên" in cached


def test_empty_provider_response_uses_cache() -> None:
    client = FakeClient(payload())
    runtime = service(client)
    runtime.symbol_overview("FPT")
    client.payload = {"t": [], "o": [], "h": [], "l": [], "c": [], "v": []}
    assert "SQLite cache" in runtime.symbol_overview("FPT")
