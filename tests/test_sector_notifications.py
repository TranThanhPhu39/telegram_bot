"""Sector-sync completion notifications stay deduplicated and actionable."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from runtime.sector_history_sync import SectorSyncResult
from telegram_bot.app import build_application
from telegram_bot.commands import TelegramCommandService
from telegram_bot.sector_notifications import (
    SectorSyncNotificationBroker,
    deliver_sector_notifications,
)


class NotificationData:
    def __init__(self, *, needs_sync: bool = True) -> None:
        self.needs_sync = needs_sync

    def symbol_overview(self, symbol, strategy="CL1"):
        return f"{symbol} {strategy}"

    def sector_overview(self, symbol):
        return f"SECTOR {symbol}"

    def sector_history_needs_sync(self, symbol):
        return self.needs_sync

    def scan_results(self): return ()
    def market_overview(self): return "MARKET"
    def signal_explanation(self, symbol): return "WHY"
    def performance_overview(self): return "PERFORMANCE"
    def strategy_catalog(self): return "CL1, ASMF"
    def latest_news(self, symbol): return "NEWS"
    def sentiment_overview(self, symbol): return "SENTIMENT"


class FakeBot:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.sent = []

    async def send_message(self, **kwargs):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("temporary Telegram failure")
        self.sent.append(kwargs)


def result(*, usable: int, failed=(), sector="8600") -> SectorSyncResult:
    return SectorSyncResult("VHM", sector, 123, 0, usable, tuple(failed))


def test_broker_sends_one_incomplete_then_one_ready_notice_per_chat() -> None:
    broker = SectorSyncNotificationBroker()
    broker.watch(10, "vhm")
    broker.watch(20, "VHM")

    assert broker.publish(result(usable=2, failed=("AAA",))) == 2
    first = broker.drain()
    assert {item.chat_id for item in first} == {10, 20}
    assert all(not item.ready and "2/123" in item.text for item in first)

    assert broker.publish(result(usable=3, failed=("BBB",))) == 0
    assert broker.drain() == ()
    assert broker.publish(result(usable=5)) == 2
    ready = broker.drain()
    assert all(item.ready and "đã sẵn sàng" in item.text for item in ready)
    assert not broker.is_watching(10, "VHM")
    assert broker.publish(result(usable=5)) == 0


def test_late_watcher_receives_last_incomplete_result_without_waiting_for_periodic_run() -> None:
    broker = SectorSyncNotificationBroker()
    assert broker.publish(result(usable=2, failed=("AAA",))) == 0

    broker.watch(10, "VHM")

    pending = broker.drain()
    assert len(pending) == 1
    assert pending[0].chat_id == 10
    assert "2/123" in pending[0].text
    assert broker.is_watching(10, "VHM")


def test_failed_telegram_delivery_is_requeued_with_asmf_button() -> None:
    broker = SectorSyncNotificationBroker()
    broker.watch(10, "VHM")
    broker.publish(result(usable=5))
    bot = FakeBot(fail_once=True)

    with pytest.raises(RuntimeError, match="temporary"):
        asyncio.run(deliver_sector_notifications(bot, broker))
    assert asyncio.run(deliver_sector_notifications(bot, broker)) == 1
    assert bot.sent[0]["chat_id"] == 10
    button = bot.sent[0]["reply_markup"].inline_keyboard[0][0]
    assert button.text == "🎯 Xem lại ASMF"
    assert button.callback_data == "soi:asmf:VHM"


def test_telegram_handlers_watch_only_sector_dependent_requests() -> None:
    broker = SectorSyncNotificationBroker()
    data = NotificationData()
    application = build_application(
        "123456:TEST_TOKEN", TelegramCommandService(data), broker
    )
    handlers = {
        command: handler
        for handler in application.handlers[0]
        for command in getattr(handler, "commands", ())
    }
    replies = []

    async def reply_text(text, reply_markup=None):
        replies.append((text, reply_markup))

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=7),
        effective_chat=SimpleNamespace(id=77, type="private"),
        effective_message=SimpleNamespace(reply_text=reply_text),
    )

    asyncio.run(handlers["soi"].callback(
        update, SimpleNamespace(args=["VHM", "ASMF"])
    ))
    assert broker.is_watching(77, "VHM")

    broker.unwatch(77, "VHM")
    asyncio.run(handlers["soi"].callback(
        update, SimpleNamespace(args=["VHM", "CL1"])
    ))
    assert not broker.is_watching(77, "VHM")

    asyncio.run(handlers["sector"].callback(
        update, SimpleNamespace(args=["VHM"])
    ))
    assert broker.is_watching(77, "VHM")

    data.needs_sync = False
    broker.unwatch(77, "VHM")
    asyncio.run(handlers["soi"].callback(
        update, SimpleNamespace(args=["VHM", "ASMF"])
    ))
    assert not broker.is_watching(77, "VHM")
