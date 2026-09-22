"""Tests for historical-first runtime orchestration."""

from datetime import date, datetime, timezone

from asmf_data.models import SectorMembership
from asmf_data.store import upsert_sector_memberships
from data.database import connect_database
from data.market_state import LatestIndexState
from data.models import IndexSnapshot
from data.vietcap.historical import normalize_gap_chart
from data.vietcap.rest import VietcapTimeFrame
from runtime.bot_service import RuntimeBotDataService
from scanner.universe import ScannerInstrument
from strategy.technical_strategies import StrategyAction, StrategyName, StrategyResult


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.fail = False
        self.calls = []

    def get_gap_chart(self, symbols, **kwargs):
        self.calls.append(tuple(symbols))
        if self.fail:
            raise ValueError("offline")
        rows = []
        for symbol in symbols:
            row = dict(self.payload)
            row["symbol"] = symbol
            rows.append(row)
        return rows


def payload(count=260):
    timestamps = [1_789_300_800 + index * 86_400 for index in range(count)]
    closes = [100.0 + index for index in range(count)]
    return {
        "symbol": "FPT", "t": [str(value) for value in timestamps],
        "o": closes, "h": [value + 1 for value in closes],
        "l": [value - 1 for value in closes], "c": closes,
        "v": [100_000.0 + index for index in range(count)],
    }


def service(client, *, index_state=None):
    return RuntimeBotDataService(
        client, connect_database("sqlite:///:memory:"),
        (ScannerInstrument("FPT", "HOSE", "STOCK"),),
        now=lambda: 1_800_000_000,
        index_state=index_state,
    )


def vnindex_snapshot(**overrides):
    fields = dict(
        symbol="VNINDEX", value=1_280.5, change=5.25, change_percent=0.41,
        total_volume=500_000_000.0, total_value=12_500_000_000_000.0,
        advances=250.0, declines=120.0, unchanged=60.0,
        ceiling_count=8.0, floor_count=3.0, exchange_time="11:05:22",
    )
    fields.update(overrides)
    return IndexSnapshot(**fields)


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


def test_asmf_fetches_bounded_sector_member_histories() -> None:
    client = FakeClient(payload())
    runtime = service(client)
    members = ("FPT", "AAA", "BBB", "CCC", "DDD")
    upsert_sector_memberships(runtime.connection, [
        SectorMembership(symbol, "TECH", "Technology", date(2020, 1, 1), None, "TEST")
        for symbol in members
    ])
    for symbol in members[1:]:
        row = dict(payload())
        row["symbol"] = symbol
        runtime._store(symbol, normalize_gap_chart(
            [row], time_frame=VietcapTimeFrame.ONE_DAY
        ))

    result = runtime.symbol_overview("FPT", "ASMF")

    assert client.calls[0] == ("FPT",)
    assert client.calls[1] == ("VNINDEX",)
    assert len(client.calls) == 2
    assert all(len(runtime._load(symbol)) == 260 for symbol in members)
    assert "sức mạnh ngành/breadth" not in result


def test_sector_history_fetch_uses_sqlite_cache_without_refetching_peers() -> None:
    client = FakeClient(payload())
    runtime = service(client)
    members = ("FPT", "AAA", "BBB", "CCC", "DDD")
    upsert_sector_memberships(runtime.connection, [
        SectorMembership(symbol, "TECH", "Technology", date(2020, 1, 1), None, "TEST")
        for symbol in members
    ])
    for symbol in members[1:]:
        row = dict(payload())
        row["symbol"] = symbol
        runtime._store(symbol, normalize_gap_chart(
            [row], time_frame=VietcapTimeFrame.ONE_DAY
        ))
    runtime.symbol_overview("FPT", "ASMF")
    first_calls = len(client.calls)

    runtime.symbol_overview("FPT", "ASMF")

    assert len(client.calls) == first_calls + 2


def test_arbitrary_asmf_symbol_queues_missing_sector_history_without_blocking() -> None:
    requested: list[str] = []

    def request(symbol: str) -> bool:
        requested.append(symbol)
        return True

    runtime = RuntimeBotDataService(
        FakeClient(payload()), connect_database("sqlite:///:memory:"),
        (ScannerInstrument("FPT", "HOSE", "STOCK"),),
        now=lambda: 1_800_000_000,
        sector_history_requester=request,
    )
    members = ("VHM", "AAA", "BBB", "CCC", "DDD", "EEE")
    upsert_sector_memberships(runtime.connection, [
        SectorMembership(symbol, "REAL_ESTATE", "Real Estate", date(2020, 1, 1), None, "TEST")
        for symbol in members
    ])

    result = runtime.symbol_overview("VHM", "ASMF")

    assert requested == ["VHM"]
    assert "Dữ liệu ngành: 1/6 mã đủ 126 phiên." in result
    assert "Đã xếp VHM vào hàng đợi đồng bộ nền." in result
    assert runtime.client.calls == [("VHM",), ("VNINDEX",)]


def test_sector_command_queues_arbitrary_symbol_without_provider_io() -> None:
    requested: list[str] = []

    def request(symbol: str) -> bool:
        requested.append(symbol)
        return True

    runtime = RuntimeBotDataService(
        FakeClient(payload()), connect_database("sqlite:///:memory:"),
        (ScannerInstrument("FPT", "HOSE", "STOCK"),),
        now=lambda: 1_800_000_000,
        sector_history_requester=request,
    )
    upsert_sector_memberships(runtime.connection, [
        SectorMembership(symbol, "REAL_ESTATE", "Real Estate", date(2020, 1, 1), None, "TEST")
        for symbol in ("VHM", "AAA", "BBB", "CCC", "DDD", "EEE")
    ])

    result = runtime.sector_overview("VHM")

    assert requested == ["VHM"]
    assert "Đã xếp VHM vào hàng đợi đồng bộ nền." in result
    assert runtime.client.calls == []


class BrokenNews:
    def latest_news(self, *args, **kwargs): raise RuntimeError("news offline")
    def ticker_sentiment(self, *args, **kwargs): raise RuntimeError("news offline")
    def severe_negative(self, *args, **kwargs): raise RuntimeError("news offline")


def test_news_failure_does_not_break_market_commands() -> None:
    runtime = RuntimeBotDataService(
        FakeClient(payload()), connect_database("sqlite:///:memory:"),
        (ScannerInstrument("FPT", "HOSE", "STOCK"),),
        news_service=BrokenNews(), now=lambda: 1_800_000_000,
    )
    assert "VNINDEX" in runtime.market_overview()
    assert "News sentiment unavailable" in runtime.symbol_overview("FPT")
    assert runtime.latest_news("FPT") == "News sentiment unavailable."


def test_asmf_buy_is_blocked_only_when_severe_news_exists(monkeypatch) -> None:
    class News(BrokenNews):
        def ticker_sentiment(self, *args, **kwargs): return None
        def severe_negative(self, *args, **kwargs): return object()

    runtime = RuntimeBotDataService(
        FakeClient(payload()), connect_database("sqlite:///:memory:"),
        (ScannerInstrument("FPT", "HOSE", "STOCK"),),
        news_service=News(), now=lambda: 1_800_000_000,
    )
    buy = StrategyResult(StrategyName.ASMF, "FPT", 1, StrategyAction.BUY,
                         80.0, ("trigger",), (), ())
    monkeypatch.setattr("runtime.bot_service.evaluate_asmf", lambda *a, **k: buy)
    monkeypatch.setattr("runtime.bot_service.fundamental_score", lambda *a: 80.0)
    monkeypatch.setattr("runtime.bot_service.institutional_flow_score", lambda *a: 80.0)
    monkeypatch.setattr("runtime.bot_service.sector_strength_score", lambda *a: 80.0)
    assert "CHƯA ĐỦ ĐIỀU KIỆN" in runtime.symbol_overview("FPT", "ASMF")


# --- Issue 2: realtime breadth shared by /market and /soi -----------------


def test_market_overview_reports_unavailable_breadth_without_index_state() -> None:
    runtime = service(FakeClient(payload()))
    result = runtime.market_overview()
    assert "BREADTH: unavailable" in result
    assert "chỉ dựa trên xu hướng EMA; chưa có breadth" in result


def test_market_overview_uses_index_state_breadth_when_available() -> None:
    state = LatestIndexState()
    state.update(vnindex_snapshot())
    runtime = service(FakeClient(payload()), index_state=state)
    result = runtime.market_overview()
    assert "250 tăng (8 trần) / 120 giảm (3 sàn) / 60 tham chiếu" in result
    assert "12,500 tỷ" in result
    assert "BREADTH: unavailable" not in result
    assert "xu hướng EMA + breadth" in result


def test_soi_stock_analysis_uses_the_same_breadth_state_as_market(monkeypatch) -> None:
    state = LatestIndexState()
    state.update(vnindex_snapshot())
    runtime = service(FakeClient(payload()), index_state=state)
    market_breadth = runtime.market_overview()
    soi_view = runtime.stock_analysis("FPT")
    assert soi_view.market is not None
    assert soi_view.market.breadth == "250 tăng (8 trần) / 120 giảm (3 sàn) / 60 tham chiếu"
    assert soi_view.market.breadth in market_breadth
    assert "xu hướng EMA + breadth" in soi_view.market.regime_reason


def test_soi_stock_analysis_has_no_breadth_when_index_state_absent() -> None:
    runtime = service(FakeClient(payload()))
    soi_view = runtime.stock_analysis("FPT")
    assert soi_view.market is not None
    assert soi_view.market.breadth is None
    assert "chỉ dựa trên xu hướng EMA" in soi_view.market.regime_reason
