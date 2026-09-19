"""Bounded Telegram token authentication check; never prints the token."""

from __future__ import annotations

import asyncio

from telegram import Bot

from telegram_bot.app import load_telegram_token


async def _main() -> None:
    async with Bot(load_telegram_token()) as bot:
        identity = await bot.get_me()
    print(f"[PASS] Telegram getMe authenticated bot @{identity.username}")


if __name__ == "__main__":
    asyncio.run(_main())
