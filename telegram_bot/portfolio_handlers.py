"""Thin python-telegram-bot handlers for the Phase 23 commands."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from telegram_bot.portfolio_commands import COMMANDS

Reply = Callable[[Update, str], Awaitable[None]]


def build_portfolio_handlers(commands, reply: Reply) -> list[CommandHandler]:
    """One handler per command; each parses nothing itself and simply delegates."""

    def make(name: str):
        async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            user = update.effective_user
            text = commands.portfolio_command(
                name, None if user is None else user.id, context.args or []
            )
            await reply(update, text)

        return handler

    return [CommandHandler(name, make(name)) for name in sorted(COMMANDS)]