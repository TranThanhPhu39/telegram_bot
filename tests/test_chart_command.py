"""`/chart` and the inline chart button deliver a PNG, never plain text."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from runtime.views import ChartRequestView
from telegram_bot.app import build_application
from telegram_bot.commands import TelegramCommandService

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class ChartData:
    """Minimal data service exposing only what /chart needs."""

    def __init__(self, *, fail_symbol: str | None = None) -> None:
        self.fail_symbol = fail_symbol
        self.requested: list[str] = []

    def candlestick_chart(self, symbol: str) -> ChartRequestView:
        self.requested.append(symbol)
        if symbol == self.fail_symbol:
            return ChartRequestView(
                symbol=symbol, png_bytes=None, caption="",
                error=f"Không thể vẽ biểu đồ {symbol}: cần tối thiểu 5 phiên",
            )
        return ChartRequestView(
            symbol=symbol, png_bytes=PNG_MAGIC + b"\x00" * 8,
            caption=f"{symbol} · ONE_DAY · 90 phiên", error=None,
        )

    # Unused by these tests but required so build_application can render
    # the rest of /soi's keyboard and other commands without crashing.
    def symbol_overview(self, symbol, strategy="CL1", **kwargs): return f"{symbol} {strategy}"
    def scan_results(self): return ()
    def market_overview(self): return "MARKET"
    def signal_explanation(self, symbol): return "WHY"
    def performance_overview(self): return "PERFORMANCE"
    def strategy_catalog(self): return "CL1, ASMF"
    def latest_news(self, symbol): return "NEWS"
    def sentiment_overview(self, symbol): return "SENTIMENT"


def _command_handlers(application):
    return {
        command: handler
        for handler in application.handlers[0]
        for command in getattr(handler, "commands", ())
    }


def _callback_handler(application):
    from telegram.ext import CallbackQueryHandler

    for handler in application.handlers[0]:
        if isinstance(handler, CallbackQueryHandler):
            return handler
    raise AssertionError("no CallbackQueryHandler registered")


def test_chart_command_replies_with_a_photo_not_text() -> None:
    data = ChartData()
    application = build_application("123456:TEST_TOKEN", TelegramCommandService(data))
    handlers = _command_handlers(application)
    photos: list[dict] = []
    texts: list[str] = []

    async def reply_photo(photo, caption=None):
        photos.append({"photo": photo.getvalue(), "caption": caption})

    async def reply_text(text, reply_markup=None):
        texts.append(text)

    update = SimpleNamespace(
        effective_message=SimpleNamespace(
            reply_photo=reply_photo, reply_text=reply_text
        ),
    )

    asyncio.run(handlers["chart"].callback(update, SimpleNamespace(args=["VHM"])))

    assert data.requested == ["VHM"]
    assert texts == []
    assert len(photos) == 1
    assert photos[0]["photo"].startswith(PNG_MAGIC)
    assert "VHM" in photos[0]["caption"]


def test_chart_command_reports_honest_error_as_text_not_a_broken_image() -> None:
    data = ChartData(fail_symbol="NEW")
    application = build_application("123456:TEST_TOKEN", TelegramCommandService(data))
    handlers = _command_handlers(application)
    photos: list[dict] = []
    texts: list[str] = []

    async def reply_photo(photo, caption=None):
        photos.append({"photo": photo, "caption": caption})

    async def reply_text(text, reply_markup=None):
        texts.append(text)

    update = SimpleNamespace(
        effective_message=SimpleNamespace(
            reply_photo=reply_photo, reply_text=reply_text
        ),
    )

    asyncio.run(handlers["chart"].callback(update, SimpleNamespace(args=["NEW"])))

    assert photos == []
    assert len(texts) == 1
    assert "cần tối thiểu 5 phiên" in texts[0]


def test_inline_chart_button_replies_with_a_photo() -> None:
    data = ChartData()
    application = build_application("123456:TEST_TOKEN", TelegramCommandService(data))
    callback_handler = _callback_handler(application)
    photos: list[dict] = []

    async def reply_photo(photo, caption=None):
        photos.append({"photo": photo.getvalue(), "caption": caption})

    async def answer():
        return None

    message = SimpleNamespace(reply_photo=reply_photo, reply_text=None)
    query = SimpleNamespace(
        data="soi:chart:VHM", answer=answer, message=message,
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_message=message,  # PTB derives this from the callback query
        effective_user=SimpleNamespace(id=7),
        effective_chat=SimpleNamespace(id=77, type="private"),
    )

    asyncio.run(callback_handler.callback(update, SimpleNamespace()))

    assert data.requested == ["VHM"]
    assert len(photos) == 1
    assert photos[0]["photo"].startswith(PNG_MAGIC)


def test_chart_button_sits_alongside_the_other_drilldown_buttons() -> None:
    from telegram_bot.app import build_symbol_keyboard

    keyboard = build_symbol_keyboard("FPT")
    callbacks = {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    }
    assert "soi:chart:FPT" in callbacks
