"""python-telegram-bot application wiring."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from telegram_bot.commands import TelegramCommandService


LOGGER = logging.getLogger(__name__)


def load_telegram_token() -> str:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing or empty")
    return token


def build_application(token: str, commands: TelegramCommandService) -> Application:
    if not token or not token.strip():
        raise ValueError("Telegram token must not be empty")
    application = ApplicationBuilder().token(token.strip()).build()

    async def reply(update: Update, text: str) -> None:
        if update.effective_message is not None:
            await update.effective_message.reply_text(text)

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.start())

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.help())

    async def soi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _reply_with_usage(update, lambda: commands.soi(context.args))

    async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.scan())

    async def market(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.market())

    async def why(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _reply_with_usage(update, lambda: commands.why(context.args))

    async def _reply_with_usage(update: Update, render: object) -> None:
        try:
            text = render()  # type: ignore[operator]
        except ValueError as error:
            text = str(error)
        await reply(update, text)

    application.add_handlers(
        [
            CommandHandler("start", start),
            CommandHandler("help", help_command),
            CommandHandler("soi", soi),
            CommandHandler("scan", scan),
            CommandHandler("market", market),
            CommandHandler("why", why),
        ]
    )
    return application


def run_polling(commands: TelegramCommandService) -> None:
    application = build_application(load_telegram_token(), commands)
    LOGGER.info("Starting Telegram polling")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
