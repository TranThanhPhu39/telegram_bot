"""Offline tests for Telegram commands, wiring, and alert deduplication."""

import asyncio
from dataclasses import dataclass, field

import pytest
from datetime import datetime, timezone

from data.market_regime import MarketRegime
from strategy.signal_engine import SignalEngine, SignalEngineConfig, SignalInputs
from telegram_bot.alerts import TelegramAlertPublisher, format_signal_alert
from intelligence.news.models import NewsItem
from telegram_bot.app import build_application
from telegram_bot.commands import TelegramCommandService, UnavailableBotDataService


@dataclass
class FakeData:
    overviews: dict[str, str] = field(default_factory=lambda: {"FPT": "FPT: ACTIVE"})
    explanations: dict[str, str] = field(default_factory=lambda: {"FPT": "RVOL tốt"})

    def symbol_overview(self, symbol: str, strategy: str = "CL1") -> str | None:
        return self.overviews.get(symbol)

    def scan_results(self) -> tuple[str, ...]:
        return ("FPT", "ACB")

    def market_overview(self) -> str:
        return "VNINDEX: BULL"

    def signal_explanation(self, symbol: str) -> str | None:
        return self.explanations.get(symbol)

    def performance_overview(self) -> str:
        return "Win rate: 50%"

    def strategy_catalog(self) -> str:
        return "CL1, ASMF"

    def latest_news(self, symbol: str) -> str:
        return f"TIN MỚI NHẤT — {symbol}"

    def sentiment_overview(self, symbol: str) -> str:
        return f"NEWS SENTIMENT: {symbol}"


class FakeBot:
    def __init__(self, fail_chat: int | None = None) -> None:
        self.fail_chat = fail_chat
        self.sent: list[tuple[int | str, str]] = []

    async def send_message(self, *, chat_id: int | str, text: str) -> None:
        if chat_id == self.fail_chat:
            raise RuntimeError("send failed")
        self.sent.append((chat_id, text))


def event():
    engine = SignalEngine(SignalEngineConfig(1.5, 2.0, 300))
    return engine.evaluate(
        SignalInputs("FPT", 100, 100.0, MarketRegime.BULL, True, 3.0, 2.0, False, False)
    )


def test_start_help_and_all_data_commands() -> None:
    commands = TelegramCommandService(FakeData())
    assert "/soi FPT" in commands.start()
    assert "/why FPT" in commands.help()
    assert commands.soi(["fpt"]) == "FPT: ACTIVE"
    assert commands.soi(["fpt", "asmf"]) == "FPT: ACTIVE"
    assert commands.strategies() == "CL1, ASMF"
    assert commands.scan() == "Watchlist: FPT, ACB"
    assert commands.market() == "VNINDEX: BULL"
    assert commands.why(["fpt"]) == "RVOL tốt"
    assert commands.performance() == "Win rate: 50%"
    assert commands.news(["fpt"]) == "TIN MỚI NHẤT — FPT"
    assert commands.sentiment(["fpt"]) == "NEWS SENTIMENT: FPT"
    assert "24 giờ" not in commands.help()
    assert "24h" not in commands.help()
    assert "/sentiment FPT - sentiment tin tức gần đây" in commands.help()


def test_commands_handle_missing_data_and_usage() -> None:
    commands = TelegramCommandService(FakeData())
    assert commands.soi(["ACB"]) == "Chưa có dữ liệu cho ACB."
    assert commands.why(["ACB"]) == "Chưa có giải thích tín hiệu cho ACB."
    with pytest.raises(ValueError, match="/soi FPT"):
        commands.soi([])
    with pytest.raises(ValueError, match="CL1 hoặc ASMF"):
        commands.soi(["FPT", "unknown"])
    with pytest.raises(ValueError, match="/why FPT"):
        commands.why(["FPT", "ACB"])


def test_safe_runtime_fallback_never_fabricates_market_data() -> None:
    commands = TelegramCommandService(UnavailableBotDataService())
    assert commands.soi(["FPT"]) == "Chưa có dữ liệu cho FPT."
    assert commands.scan() == "Chưa có mã đạt bộ lọc."
    assert "chưa sẵn sàng" in commands.market()
    assert commands.why(["FPT"]) == "Chưa có giải thích tín hiệu cho FPT."
    assert "chưa sẵn sàng" in commands.performance()


def test_application_registers_all_required_commands() -> None:
    application = build_application("123456:TEST_TOKEN", TelegramCommandService(FakeData()))
    commands = {
        command
        for handler in application.handlers[0]
        for command in getattr(handler, "commands", ())
    }
    assert commands == {"start", "help", "soi", "scan", "market", "why", "performance", "chienluoc", "tin", "sentiment", "technical", "fundamental", "sector", "chart"} | {
        "watchlist", "addwatch", "removewatch", "portfolio", "addholding", "removeholding",
        "risk", "size", "stress", "setrisk", "risksettings",
    }

def test_alert_format_contains_transition_and_reason() -> None:
    signal = event()
    assert signal is not None
    text = format_signal_alert(signal)
    assert "FPT: NEW → WATCH" in text
    assert "new symbol" in text


def test_auto_alerts_are_deduplicated_per_chat() -> None:
    signal = event()
    assert signal is not None
    bot = FakeBot()
    publisher = TelegramAlertPublisher(bot, (1, 2))  # type: ignore[arg-type]

    assert asyncio.run(publisher.publish(signal)) == 2
    assert asyncio.run(publisher.publish(signal)) == 0
    assert [chat for chat, _ in bot.sent] == [1, 2]


def test_failed_alert_is_not_marked_as_sent() -> None:
    signal = event()
    assert signal is not None
    bot = FakeBot(fail_chat=2)
    publisher = TelegramAlertPublisher(bot, (1, 2))  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="send failed"):
        asyncio.run(publisher.publish(signal))
    assert publisher.deduplicator.was_sent(1, signal)
    assert not publisher.deduplicator.was_sent(2, signal)


def test_empty_alert_recipient_list_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one"):
        TelegramAlertPublisher(FakeBot(), ())  # type: ignore[arg-type]


def test_news_alerts_use_existing_publisher_and_are_deduplicated() -> None:
    item = NewsItem("n1", "cafef", "https://example/n1", datetime.now(timezone.utc),
                    "ACB công bố báo cáo", tickers=("ACB",), primary_ticker="ACB")
    bot = FakeBot()
    publisher = TelegramAlertPublisher(bot, (1,))  # type: ignore[arg-type]
    assert asyncio.run(publisher.publish_news(item)) == 1
    assert asyncio.run(publisher.publish_news(item)) == 0
