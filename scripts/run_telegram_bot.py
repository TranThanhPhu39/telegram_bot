"""Run the Telegram command bot with the historical-first data runtime."""

from telegram_bot.app import run_polling
from telegram_bot.commands import TelegramCommandService
from runtime.bot_service import build_runtime_service_from_env


if __name__ == "__main__":
    run_polling(TelegramCommandService(build_runtime_service_from_env()))
