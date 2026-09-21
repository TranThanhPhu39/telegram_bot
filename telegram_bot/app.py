"""python-telegram-bot application wiring.

Handlers stay thin: they parse arguments, call the command service and reply.
The inline keyboard is an optional convenience layer; every action it offers is
also reachable as a plain command, so losing the keyboard never loses a feature.
"""

from __future__ import annotations

import asyncio
import logging
import os
from io import BytesIO

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from runtime.redaction import redact_secrets
from telegram_bot.commands import TelegramCommandService
from telegram_bot.portfolio_handlers import build_portfolio_handlers
from telegram_bot.sector_notifications import (
    SectorSyncNotificationBroker,
    deliver_sector_notifications,
)


LOGGER = logging.getLogger(__name__)

GENERIC_ERROR_TEXT = "Đã xảy ra lỗi tạm thời, vui lòng thử lại sau."
CHART_SEND_ERROR_TEXT = "Không thể gửi biểu đồ lúc này, vui lòng thử lại sau."

TELEGRAM_MESSAGE_LIMIT = 3900

CALLBACK_PREFIX = "soi"
CALLBACK_ACTIONS = ("tech", "fund", "asmf", "why", "news", "sent", "market", "chart")


def load_telegram_token() -> str:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing or empty")
    return token


def build_symbol_keyboard(symbol: str) -> InlineKeyboardMarkup:
    """Offer drill-down without hiding the equivalent text commands."""
    symbol = symbol.strip().upper()
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📈 Technical", callback_data=f"{CALLBACK_PREFIX}:tech:{symbol}"),
                InlineKeyboardButton("🧾 Fundamental", callback_data=f"{CALLBACK_PREFIX}:fund:{symbol}"),
            ],
            [
                InlineKeyboardButton("🎯 ASMF", callback_data=f"{CALLBACK_PREFIX}:asmf:{symbol}"),
                InlineKeyboardButton("❓ Why", callback_data=f"{CALLBACK_PREFIX}:why:{symbol}"),
            ],
            [
                InlineKeyboardButton("📰 Tin", callback_data=f"{CALLBACK_PREFIX}:news:{symbol}"),
                InlineKeyboardButton("📊 Sentiment", callback_data=f"{CALLBACK_PREFIX}:sent:{symbol}"),
            ],
            [
                InlineKeyboardButton("🌐 Market", callback_data=f"{CALLBACK_PREFIX}:market:{symbol}"),
                InlineKeyboardButton("📉 Biểu đồ nến", callback_data=f"{CALLBACK_PREFIX}:chart:{symbol}"),
            ],
        ]
    )


def parse_callback(data: str) -> tuple[str, str]:
    """Return (action, symbol); raise ValueError on anything unexpected."""
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX or parts[1] not in CALLBACK_ACTIONS:
        raise ValueError("callback không hợp lệ")
    symbol = parts[2].strip().upper()
    if not symbol or not symbol.isalnum():
        raise ValueError("callback không hợp lệ")
    return parts[1], symbol


def render_callback(
    commands: TelegramCommandService, action: str, symbol: str, user_id: int | None = None
)-> str:
    handlers = {
        "tech": lambda: commands.technical([symbol]),
        "fund": lambda: commands.fundamental([symbol]),
        "asmf": lambda: commands.soi([symbol, "ASMF"], user_id),
        "why": lambda: commands.why([symbol]),
        "news": lambda: commands.news([symbol]),
        "sent": lambda: commands.sentiment([symbol]),
        "market": commands.market,
    }
    handler = handlers.get(action)
    if handler is None:
        return "Tuỳ chọn không hợp lệ."
    try:
        return handler()
    except ValueError as error:
        return str(error)


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> tuple[str, ...]:
    """Chunk on paragraph boundaries so Telegram never rejects a long answer."""
    if not text:
        return ("",)
    if len(text) <= limit:
        return (text,)
    chunks: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = block if not current else f"{current}\n\n{block}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(block) > limit:
            chunks.append(block[:limit])
            block = block[limit:]
        current = block
    if current:
        chunks.append(current)
    return tuple(chunks)


def build_application(
    token: str,
    commands: TelegramCommandService,
    sector_notifications: SectorSyncNotificationBroker | None = None,
) -> Application:
    if not token or not token.strip():
        raise ValueError("Telegram token must not be empty")
    builder = ApplicationBuilder().token(token.strip())
    if sector_notifications is not None:
        async def notification_loop(application: Application) -> None:
            while True:
                try:
                    await deliver_sector_notifications(
                        application.bot, sector_notifications
                    )
                except Exception:
                    LOGGER.exception("Sector sync notification delivery failed")
                await asyncio.sleep(1)

        async def post_init(application: Application) -> None:
            application.bot_data["sector_notification_task"] = asyncio.create_task(
                notification_loop(application), name="sector-sync-notifications"
            )

        async def post_shutdown(application: Application) -> None:
            task = application.bot_data.pop("sector_notification_task", None)
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        builder = builder.post_init(post_init).post_shutdown(post_shutdown)
    application = builder.build()

    async def reply(update: Update, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        if update.effective_message is None:
            return
        parts = split_message(text)
        for index, part in enumerate(parts):
            await update.effective_message.reply_text(
                part, reply_markup=markup if index == len(parts) - 1 else None
            )

    async def _reply_with_usage(update: Update, render, markup_symbol=None) -> None:
        markup = None
        try:
            text = render()
            if markup_symbol is not None:
                markup = build_symbol_keyboard(markup_symbol(update))
        except ValueError as error:
            text = str(error)
        await reply(update, text, markup)

    def _first_argument(update_context) -> str:
        args = update_context.args or []
        return args[0].strip().upper() if args else ""

    def _private_user_id(update: Update) -> int | None:
        """Expose personal portfolio context only inside a private chat."""
        user = getattr(update, "effective_user", None)
        chat = getattr(update, "effective_chat", None)
        if user is None or chat is None or chat.type != "private":
            return None
        return user.id

    def _notification_chat_id(update: Update) -> int | str | None:
        chat = getattr(update, "effective_chat", None)
        return None if chat is None else chat.id

    def _watch_sector(update: Update, symbol: str) -> tuple[int | str, str] | None:
        if sector_notifications is None or not symbol or not symbol.isalnum():
            return None
        chat_id = _notification_chat_id(update)
        if chat_id is None:
            return None
        sector_notifications.watch(chat_id, symbol)
        return chat_id, symbol

    def _remove_unneeded_watch(watch: tuple[int | str, str] | None) -> None:
        if watch is None or sector_notifications is None:
            return
        checker = getattr(commands.data, "sector_history_needs_sync", None)
        try:
            needed = callable(checker) and checker(watch[1])
        except Exception:
            LOGGER.exception("Could not verify sector sync notification watch")
            return
        if not needed:
            sector_notifications.unwatch(*watch)

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.start())

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.help())

    async def soi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        markup = None
        watch = None
        try:
            symbol = _first_argument(context)
            args = context.args or []
            if symbol and len(args) == 2 and args[1].strip().upper() == "ASMF":
                watch = _watch_sector(update, symbol)
            text = commands.soi(context.args, _private_user_id(update))
            if symbol:
                markup = build_symbol_keyboard(symbol)
        except ValueError as error:
            text = str(error)
        finally:
            _remove_unneeded_watch(watch)
        await reply(update, text, markup)

    async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.scan(context.args))

    async def market(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.market())

    async def why(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _reply_with_usage(update, lambda: commands.why(context.args))

    async def performance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.performance())

    async def strategies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.strategies())

    async def reply_chart(update: Update, arguments) -> None:
        """Deliver a candlestick PNG, or the honest text error in its place."""
        if update.effective_message is None:
            return
        try:
            result = commands.chart(arguments)
        except ValueError as error:
            await update.effective_message.reply_text(str(error))
            return
        except Exception as error:  # upstream/provider failure must not kill the bot
            LOGGER.error("Chart command failed: %s", redact_secrets(f"{type(error).__name__}: {error}"))
            await update.effective_message.reply_text(GENERIC_ERROR_TEXT)
            return
        if result.error is not None or result.png_bytes is None:
            await update.effective_message.reply_text(
                result.error or "Không thể tạo biểu đồ."
            )
            return
        try:
            await update.effective_message.reply_photo(
                photo=BytesIO(result.png_bytes), caption=result.caption,
            )
        except TelegramError as error:
            # Never leave the user with silence, never leak the request URL/token.
            LOGGER.error("Chart delivery failed: %s", redact_secrets(f"{type(error).__name__}: {error}"))
            try:
                await update.effective_message.reply_text(CHART_SEND_ERROR_TEXT)
            except TelegramError:
                LOGGER.error("Chart failure notice could not be delivered")

    async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply_chart(update, context.args)

    async def news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _reply_with_usage(update, lambda: commands.news(context.args))

    async def sentiment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _reply_with_usage(update, lambda: commands.sentiment(context.args))

    async def technical(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _reply_with_usage(update, lambda: commands.technical(context.args))

    async def fundamental(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _reply_with_usage(update, lambda: commands.fundamental(context.args))

    async def sector(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        symbol = _first_argument(context)
        watch = _watch_sector(update, symbol) if symbol else None
        try:
            await _reply_with_usage(update, lambda: commands.sector(context.args))
        finally:
            _remove_unneeded_watch(watch)

    async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        try:
            action, symbol = parse_callback(query.data)
        except ValueError as error:
            if query.message is not None:
                await query.message.reply_text(str(error))
            return
        if action == "chart":
            await reply_chart(update, [symbol])
            return
        watch = _watch_sector(update, symbol) if action == "asmf" else None
        text = render_callback(
            commands, action, symbol,
            _private_user_id(update),
        )
        _remove_unneeded_watch(watch)
        if query.message is not None:
            parts = split_message(text)
            markup = build_symbol_keyboard(symbol)
            if hasattr(query, "edit_message_text") and callable(query.edit_message_text):
                try:
                    await query.edit_message_text(parts[0], reply_markup=markup)
                    for part in parts[1:]:
                        await query.message.reply_text(part, reply_markup=markup)
                    return
                except Exception:
                    pass
            for index, part in enumerate(parts):
                await query.message.reply_text(
                    part, reply_markup=markup if index == len(parts) - 1 else None
                )

    application.add_handlers(
        [
            CommandHandler("start", start),
            CommandHandler("help", help_command),
            CommandHandler("soi", soi),
            CommandHandler("scan", scan),
            CommandHandler("market", market),
            CommandHandler("why", why),
            CommandHandler("performance", performance),
            CommandHandler("chienluoc", strategies),
            CommandHandler("tin", news),
            CommandHandler("sentiment", sentiment),
            CommandHandler("technical", technical),
            CommandHandler("fundamental", fundamental),
            CommandHandler("sector", sector),
            CommandHandler("chart", chart),
            CallbackQueryHandler(on_callback),
        ]
    )
    application.add_handlers(build_portfolio_handlers(commands, reply))

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Last line of defence: log redacted, apologise once, keep polling."""
        error = context.error
        LOGGER.error(
            "Unhandled Telegram handler error: %s",
            redact_secrets(f"{type(error).__name__}: {error}"),
        )
        message = getattr(update, "effective_message", None)
        if message is not None:
            try:
                await message.reply_text(GENERIC_ERROR_TEXT)
            except Exception:
                LOGGER.error("Error notice could not be delivered")

    application.add_error_handler(on_error)
    return application


def run_polling(
    commands: TelegramCommandService,
    sector_notifications: SectorSyncNotificationBroker | None = None,
) -> None:
    application = build_application(
        load_telegram_token(), commands, sector_notifications
    )
    LOGGER.info("Starting Telegram polling")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
