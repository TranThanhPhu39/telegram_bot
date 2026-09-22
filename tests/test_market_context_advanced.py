"""Comprehensive tests for Advanced Market Context & Top % Sector Performance Chart."""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest

from charts.sector_chart import PNG_MAGIC
from data.database import connect_database
from data.migrations import bootstrap_schema
from data.models import OHLCVBar
from runtime.analysis import build_market_view
from runtime.bot_service import RuntimeBotDataService
from runtime.views import ChartRequestView, Freshness, MarketContextView
from asmf_data.models import SectorMembership
from asmf_data.store import upsert_sector_memberships
from telegram_bot.app import (
    build_application,
    build_market_keyboard,
    parse_callback,
)
from telegram_bot.commands import TelegramCommandService
from telegram_bot.formatters import format_data_quality, format_market


def _make_bars(
    count: int,
    start_price: float = 1000.0,
    trend: float = 1.0,
    symbol: str = "VNINDEX",
) -> list[OHLCVBar]:
    bars = []
    base_ts = 1_700_000_000
    price = start_price
    for i in range(count):
        price = max(10.0, price + trend * (1.0 if i % 2 == 0 else -0.5))
        bars.append(
            OHLCVBar(
                symbol=symbol,
                timeframe="ONE_DAY",
                timestamp=base_ts + i * 86400,
                open=price - 1.0,
                high=price + 2.0,
                low=price - 2.0,
                close=price,
                volume=10_000_000,
            )
        )
    return bars


def test_build_market_view_computes_hurst_and_volatility_percentile() -> None:
    bars = _make_bars(120, start_price=1200.0, trend=1.5)
    view = build_market_view(
        bars,
        top_sectors=("Bảo hiểm", "Ngân hàng", "Dược & Y tế"),
        weakest_sector="Thủy sản & Nông nghiệp",
        weakest_sector_score=5.0,
    )

    assert view is not None
    assert view.hurst is not None
    assert 0.0 <= view.hurst <= 1.0
    assert view.volatility_percentile is not None
    assert 0.0 <= view.volatility_percentile <= 100.0
    assert view.hurst_lookback == 100
    assert view.ma50_status is not None
    assert view.ma200_status is None  # 120 bars < 200 bars
    assert "chưa đứng vững" in (view.trend_stability_reason or "")
    assert view.top_sectors == ("Bảo hiểm", "Ngân hàng", "Dược & Y tế")
    assert view.weakest_sector == "Thủy sản & Nông nghiệp"
    assert view.weakest_sector_score == 5.0


def test_moving_average_stability_reason_variations() -> None:
    # 250 bars all trending up => price > MA50 and price > MA200
    up_bars = []
    base_ts = 1_700_000_000
    for i in range(250):
        up_bars.append(
            OHLCVBar(
                symbol="VNINDEX", timeframe="ONE_DAY", timestamp=base_ts + i * 86400,
                open=100.0 + i, high=102.0 + i, low=99.0 + i, close=101.0 + i, volume=1000,
            )
        )
    up_view = build_market_view(up_bars)
    assert up_view is not None
    assert up_view.ma50_status == "TRÊN MA50"
    assert up_view.ma200_status == "TRÊN MA200"
    assert "tăng bền vững" in up_view.trend_stability_reason

    # Down trend
    down_bars = []
    for i in range(250):
        down_bars.append(
            OHLCVBar(
                symbol="VNINDEX", timeframe="ONE_DAY", timestamp=base_ts + i * 86400,
                open=500.0 - i, high=501.0 - i, low=498.0 - i, close=499.0 - i, volume=1000,
            )
        )
    down_view = build_market_view(down_bars)
    assert down_view is not None
    assert down_view.ma50_status == "DƯỚI MA50"
    assert down_view.ma200_status == "DƯỚI MA200"
    assert "giảm chiếm ưu thế" in down_view.trend_stability_reason


def test_format_market_renders_exact_national_standard_visuals() -> None:
    view = MarketContextView(
        symbol="VNINDEX",
        close=1793.05,
        change_percent=-1.25,
        trend="TĂNG",
        regime="BULL",
        regime_reason="EMA20 cắt lên EMA50",
        ema20=1780.0,
        ema50=1750.0,
        breadth="250 tăng / 120 giảm",
        liquidity="15,000 tỷ",
        foreign_flow="+250 tỷ",
        hurst=0.61,
        volatility_percentile=35.0,
        hurst_lookback=100,
        ma50_status="TRÊN MA50",
        ma200_status="DƯỚI MA200",
        trend_stability_reason="Chỉ số chưa đứng vững trên cả MA50 và MA200 -> xu hướng chưa chắc chắn.",
        top_sectors=("Bảo hiểm", "Ngân hàng", "Dược & Y tế"),
        weakest_sector="Thủy sản & Nông nghiệp",
        weakest_sector_score=5.0,
    )

    text = format_market(view, None, "Dữ liệu hợp lệ")

    assert "🌐 BỐI CẢNH THỊ TRƯỜNG" in text
    assert "VN-Index (VNINDEX): 1,793.05 (-1.25%)" in text
    assert "• Xu hướng: 📈 TĂNG" in text
    assert "• Số mũ Hurst = 0.61 (> 0.55) - Phân vị biến động = 35%" in text
    assert "(Dựa trên 100 phiên gần nhất)" in text
    assert "Hurst = 0.61 > 0.55 -> thị trường có quán tính xu hướng." in text
    assert "Chỉ số chưa đứng vững trên cả MA50 và MA200 -> xu hướng chưa chắc chắn." in text
    assert "🏭 Ngành mạnh nhất" in text
    assert "🥇 Bảo hiểm" in text
    assert "🥈 Ngân hàng" in text
    assert "🥉 Dược & Y tế" in text
    assert "Yếu nhất: Thủy sản & Nông nghiệp — 5/100" in text
    assert "👉 Chọn một mục bên dưới để xem chi tiết:" in text
    assert "🔎 Chatbot này chỉ dùng với mục đích tham khảo." in text


class FakeDataService:
    def sector_performance_chart(self, visible_count: int = 20) -> ChartRequestView:
        return ChartRequestView(
            symbol="MARKET",
            png_bytes=PNG_MAGIC + b"\x00" * 32,
            caption=(
                "🏭 Top % biến động ngành — 20 phiên gần nhất.\n"
                "Chỉ số ngành là trung bình equal-weight các đường giá đã chuẩn hóa về 100."
            ),
            error=None,
        )

    def market_overview(self) -> str:
        return "🌐 BỐI CẢNH THỊ TRƯỜNG"


def test_command_chart_market_delivers_sector_performance_chart() -> None:
    data = FakeDataService()
    commands = TelegramCommandService(data)
    result = commands.chart(["MARKET"])

    assert result.symbol == "MARKET"
    assert result.png_bytes is not None
    assert result.png_bytes.startswith(PNG_MAGIC)
    assert "Top % biến động ngành" in result.caption
    assert result.error is None


def test_build_market_keyboard_and_callback_routing() -> None:
    keyboard = build_market_keyboard()
    button = keyboard.inline_keyboard[0][0]
    assert button.text == "📊 Top % biến động ngành"
    assert button.callback_data == "soi:mchart:VNINDEX"

    action, symbol = parse_callback(button.callback_data)
    assert action == "mchart"
    assert symbol == "VNINDEX"


def test_mchart_callback_replies_with_photo() -> None:
    data = FakeDataService()
    application = build_application("123456:TEST_TOKEN", TelegramCommandService(data))
    photos: list[dict] = []

    async def reply_photo(photo, caption=None):
        photos.append({"photo": photo.getvalue(), "caption": caption})

    async def answer():
        return None

    message = SimpleNamespace(reply_photo=reply_photo, reply_text=None)
    query = SimpleNamespace(data="soi:mchart:VNINDEX", answer=answer, message=message)
    update = SimpleNamespace(
        callback_query=query,
        effective_message=message,
        effective_user=SimpleNamespace(id=123),
        effective_chat=SimpleNamespace(id=456, type="private"),
    )

    from telegram.ext import CallbackQueryHandler
    cb_handler = next(h for h in application.handlers[0] if isinstance(h, CallbackQueryHandler))
    asyncio.run(cb_handler.callback(update, SimpleNamespace()))

    assert len(photos) == 1
    assert photos[0]["photo"].startswith(PNG_MAGIC)
    assert "Top % biến động ngành" in photos[0]["caption"]


def test_runtime_service_sector_performance_chart_e2e() -> None:
    db = connect_database("sqlite:///:memory:")
    bootstrap_schema(db)
    as_of = date(2020, 1, 1)
    members = [
        SectorMembership("AAA", "BANK", "Ngân hàng", as_of, None, "TEST"),
        SectorMembership("BBB", "BANK", "Ngân hàng", as_of, None, "TEST"),
        SectorMembership("CCC", "OIL", "Dầu khí", as_of, None, "TEST"),
        SectorMembership("DDD", "OIL", "Dầu khí", as_of, None, "TEST"),
    ]
    upsert_sector_memberships(db, members)

    histories: dict[str, list[OHLCVBar]] = {}
    for m in ("AAA", "BBB", "CCC", "DDD", "VNINDEX"):
        trend = 2.0 if m in ("AAA", "BBB") else 0.5
        histories[m] = _make_bars(30, start_price=50.0, trend=trend, symbol=m)

    class MockClient:
        def get_gap_chart(self, symbols, time_frame, count_back, to_timestamp):
            return []

    service = RuntimeBotDataService(
        MockClient(),
        db,
        (),
        now=lambda: 1_700_000_000 + 30 * 86400,
    )
    for sym, bars in histories.items():
        service._store(sym, bars)

    chart_view = service.sector_performance_chart(visible_count=20)
    assert chart_view.error is None
    assert chart_view.png_bytes is not None
    assert chart_view.png_bytes.startswith(PNG_MAGIC)
    assert "Top % biến động ngành — 20 phiên gần nhất." in chart_view.caption
    assert "Chỉ số ngành là trung bình equal-weight các đường giá đã chuẩn hóa về 100." in chart_view.caption

    market_text = service.market_overview()
    assert "🌐 BỐI CẢNH THỊ TRƯỜNG" in market_text
    assert "🏭 Ngành mạnh nhất" in market_text
    assert "Ngân hàng" in market_text
    assert "Dầu khí" in market_text
