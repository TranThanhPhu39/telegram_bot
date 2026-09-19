"""Run the Telegram command bot with the safe unavailable-data fallback."""

from telegram_bot.app import run_polling
from telegram_bot.commands import TelegramCommandService, UnavailableBotDataService


if __name__ == "__main__":
    run_polling(TelegramCommandService(UnavailableBotDataService()))
