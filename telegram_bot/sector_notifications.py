"""Thread-safe Telegram notifications for background sector-history sync."""

from __future__ import annotations

from dataclasses import dataclass
import threading

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from runtime.sector_history_sync import SectorSyncResult


@dataclass(frozen=True, slots=True)
class SectorSyncNotification:
    chat_id: int | str
    symbol: str
    text: str
    ready: bool


@dataclass(slots=True)
class _Watcher:
    incomplete_sent: bool = False


class SectorSyncNotificationBroker:
    """Bridge a worker thread to the Telegram asyncio application."""

    def __init__(self) -> None:
        self._watchers: dict[str, dict[int | str, _Watcher]] = {}
        self._latest: dict[str, SectorSyncResult] = {}
        self._pending: list[SectorSyncNotification] = []
        self._lock = threading.Lock()

    def watch(self, chat_id: int | str, symbol: str) -> None:
        normalized = symbol.strip().upper()
        if not normalized or not normalized.isalnum():
            raise ValueError("invalid stock symbol")
        with self._lock:
            watcher = self._watchers.setdefault(normalized, {}).setdefault(
                chat_id, _Watcher()
            )
            latest = self._latest.get(normalized)
            if (
                latest is not None
                and latest.sector_code is not None
                and latest.usable < 5
                and not watcher.incomplete_sent
            ):
                self._pending.append(SectorSyncNotification(
                    chat_id, normalized, _format_result(latest), False
                ))
                watcher.incomplete_sent = True

    def unwatch(self, chat_id: int | str, symbol: str) -> None:
        normalized = symbol.strip().upper()
        with self._lock:
            watchers = self._watchers.get(normalized)
            if watchers is None:
                return
            watchers.pop(chat_id, None)
            if not watchers:
                self._watchers.pop(normalized, None)

    def is_watching(self, chat_id: int | str, symbol: str) -> bool:
        with self._lock:
            return chat_id in self._watchers.get(symbol.strip().upper(), {})

    def publish(self, result: SectorSyncResult) -> int:
        """Queue at most one incomplete notice and one eventual ready notice."""
        symbol = result.requested_symbol.strip().upper()
        ready = result.usable >= 5
        terminal = ready or result.sector_code is None
        with self._lock:
            self._latest[symbol] = result
            watchers = self._watchers.get(symbol)
            if not watchers:
                return 0
            queued = 0
            for chat_id, watcher in tuple(watchers.items()):
                if not ready and not terminal and watcher.incomplete_sent:
                    continue
                self._pending.append(SectorSyncNotification(
                    chat_id, symbol, _format_result(result), ready
                ))
                queued += 1
                if terminal:
                    watchers.pop(chat_id, None)
                else:
                    watcher.incomplete_sent = True
            if not watchers:
                self._watchers.pop(symbol, None)
            return queued

    def drain(self) -> tuple[SectorSyncNotification, ...]:
        with self._lock:
            pending = tuple(self._pending)
            self._pending.clear()
            return pending

    def requeue(self, notification: SectorSyncNotification) -> None:
        with self._lock:
            self._pending.insert(0, notification)


def sector_notification_keyboard(symbol: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🎯 Xem lại ASMF", callback_data=f"soi:asmf:{symbol.strip().upper()}"
        )
    ]])


async def deliver_sector_notifications(
    bot: Bot, broker: SectorSyncNotificationBroker
) -> int:
    """Deliver one broker snapshot and retain failed sends for retry."""
    sent = 0
    notifications = broker.drain()
    for index, notification in enumerate(notifications):
        try:
            await bot.send_message(
                chat_id=notification.chat_id,
                text=notification.text,
                reply_markup=sector_notification_keyboard(notification.symbol),
            )
        except Exception:
            for remaining in reversed(notifications[index:]):
                broker.requeue(remaining)
            raise
        sent += 1
    return sent


def _format_result(result: SectorSyncResult) -> str:
    if result.sector_code is None:
        return (
            f"⚠️ Không thể đồng bộ ngành cho {result.requested_symbol}: "
            "chưa có phân loại ngành hiệu lực."
        )
    if result.usable >= 5:
        return (
            f"✅ Dữ liệu ngành {result.requested_symbol} đã sẵn sàng: "
            f"{result.usable}/{result.members} mã đủ lịch sử.\n"
            "Bấm “Xem lại ASMF” để cập nhật phân tích."
        )
    return (
        f"⚠️ Đồng bộ ngành {result.requested_symbol} chưa đủ: "
        f"{result.usable}/{result.members} mã đủ lịch sử; "
        f"{len(result.failed)} mã thất bại trong lượt này.\n"
        "Bot sẽ tự thử lại ở chu kỳ sau."
    )
