"""python-telegram-bot application wiring.

Handlers stay thin: they parse arguments, call the command service and reply.
The inline keyboard is an optional convenience layer; every action it offers is
also reachable as a plain command, so losing the keyboard never loses a feature.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from telegram_bot.commands import TelegramCommandService
from telegram_bot.portfolio_handlers import build_portfolio_handlers


LOGGER = logging.getLogger(__name__)

TELEGRAM_MESSAGE_LIMIT = 3900

CALLBACK_PREFIX = "soi"
CALLBACK_ACTIONS = ("tech", "fund", "asmf", "why", "news", "sent", "market")


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
            [InlineKeyboardButton("🌐 Market", callback_data=f"{CALLBACK_PREFIX}:market:{symbol}")],
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


def build_application(token: str, commands: TelegramCommandService) -> Application:
    if not token or not token.strip():
        raise ValueError("Telegram token must not be empty")
    application = ApplicationBuilder().token(token.strip()).build()

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

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.start())

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.help())

    async def soi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        markup = None
        try:
            text = commands.soi(context.args, _private_user_id(update))
            symbol = _first_argument(context)
            if symbol:
                markup = build_symbol_keyboard(symbol)
        except ValueError as error:
            text = str(error)
        await reply(update, text, markup)

    async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.scan())

    async def market(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.market())

    async def why(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _reply_with_usage(update, lambda: commands.why(context.args))

    async def performance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.performance())

    async def strategies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.strategies())

    async def news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _reply_with_usage(update, lambda: commands.news(context.args))

    async def sentiment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _reply_with_usage(update, lambda: commands.sentiment(context.args))

    async def technical(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _reply_with_usage(update, lambda: commands.technical(context.args))

    async def fundamental(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _reply_with_usage(update, lambda: commands.fundamental(context.args))

    async def sector(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _reply_with_usage(update, lambda: commands.sector(context.args))

    async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        try:
            action, symbol = parse_callback(query.data)
        except ValueError as error:
            text = str(error)
        else:
            text = render_callback(
                commands, action, symbol,
                _private_user_id(update),
            )
        if query.message is not None:
            for part in split_message(text):
                await query.message.reply_text(part)

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
            CallbackQueryHandler(on_callback),
        ]
    )
    application.add_handlers(build_portfolio_handlers(commands, reply))
    return application


def run_polling(commands: TelegramCommandService) -> None:
    application = build_application(load_telegram_token(), commands)
    LOGGER.info("Starting Telegram polling")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
