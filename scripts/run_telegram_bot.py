"""Run the Telegram command bot with the historical-first data runtime."""

import os

from dotenv import load_dotenv

from telegram_bot.app import run_polling
from telegram_bot.commands import TelegramCommandService
from runtime.bot_service import build_runtime_service_from_env
from runtime.sector_history_sync import start_sector_history_background_sync


if __name__ == "__main__":
    load_dotenv()
    service = build_runtime_service_from_env()
    sector_worker = start_sector_history_background_sync(
        tuple(item.symbol for item in service.instruments),
        interval_seconds=float(
            os.getenv("SECTOR_HISTORY_SYNC_INTERVAL_SECONDS", "21600")
        ),
        request_cooldown_seconds=float(
            os.getenv("SECTOR_HISTORY_ON_DEMAND_COOLDOWN_SECONDS", "900")
        ),
        max_members_per_run=int(
            os.getenv("SECTOR_HISTORY_MAX_MEMBERS_PER_RUN", "8")
        ),
    )
    service.set_sector_history_requester(sector_worker.request)
    run_polling(TelegramCommandService(service))
