"""Deduplicated Telegram delivery for signal transition alerts."""

from __future__ import annotations

from telegram import Bot

from strategy.signal_engine import SignalEvent
from intelligence.news.models import NewsItem


class AlertDeduplicator:
    def __init__(self) -> None:
        self._sent: set[tuple[int | str, str, int, int]] = set()

    def was_sent(self, chat_id: int | str, event: SignalEvent) -> bool:
        return self._key(chat_id, event) in self._sent

    def mark_sent(self, chat_id: int | str, event: SignalEvent) -> None:
        self._sent.add(self._key(chat_id, event))

    @staticmethod
    def _key(chat_id: int | str, event: SignalEvent) -> tuple[int | str, str, int, int]:
        return (chat_id, event.symbol, event.lifecycle, event.sequence)


class TelegramAlertPublisher:
    def __init__(self, bot: Bot, chat_ids: tuple[int | str, ...]) -> None:
        if not chat_ids:
            raise ValueError("at least one Telegram chat ID is required")
        self.bot = bot
        self.chat_ids = chat_ids
        self.deduplicator = AlertDeduplicator()
        self._sent_news: set[tuple[int | str, str]] = set()

    async def publish(self, event: SignalEvent) -> int:
        """Send once per chat and mark only successful deliveries."""
        text = format_signal_alert(event)
        sent = 0
        for chat_id in self.chat_ids:
            if self.deduplicator.was_sent(chat_id, event):
                continue
            await self.bot.send_message(chat_id=chat_id, text=text)
            self.deduplicator.mark_sent(chat_id, event)
            sent += 1
        return sent

    async def publish_news(self, item: NewsItem) -> int:
        """Send news through the existing alert boundary, once per chat/item."""
        sent = 0
        for chat_id in self.chat_ids:
            key = (chat_id, item.id)
            if key in self._sent_news:
                continue
            await self.bot.send_message(chat_id=chat_id, text=format_news_alert(item))
            self._sent_news.add(key)
            sent += 1
        return sent


def format_signal_alert(event: SignalEvent) -> str:
    """Evidence-first alert; nothing is sent that the event did not establish."""
    previous = "NEW" if event.from_state is None else event.from_state.value
    positives = "; ".join(event.reason.positive_factors) or "không có"
    lines = [
        f"🚨 {event.symbol} — CHUYỂN TRẠNG THÁI",
        f"{event.symbol}: {previous} → {event.to_state.value}",
        f"Giá: {event.price:g}",
        f"Kích hoạt: {event.reason.trigger}",
        f"Yếu tố tích cực: {positives}",
    ]
    negatives = getattr(event.reason, "negative_factors", ())
    if negatives:
        lines.append("Chưa đạt: " + "; ".join(negatives))
    missing = getattr(event.reason, "missing_factors", ())
    if missing:
        lines.append("Thiếu dữ liệu: " + "; ".join(missing))
    lines.append(f"Thời điểm: {event.occurred_at}")
    lines.append("Tín hiệu định lượng, không phải khuyến nghị đầu tư.")
    return "\n".join(lines)


def format_news_alert(item: NewsItem) -> str:
    sentiment = item.sentiment.label.value if item.sentiment else "unavailable"
    ticker = item.primary_ticker or ",".join(item.tickers) or "MARKET"
    return f"TIN {ticker} | {item.event_type} | {sentiment}\n{item.title}\n{item.url}"
