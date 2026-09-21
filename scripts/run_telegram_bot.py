"""Run the Telegram command bot with the historical-first data runtime."""

import os

from dotenv import load_dotenv

from data.database import connect_database
from telegram_bot.app import run_polling
from telegram_bot.commands import TelegramCommandService
from telegram_bot.sector_notification_store import SQLiteNotificationStore
from telegram_bot.sector_notifications import SectorSyncNotificationBroker
from runtime.bot_service import build_runtime_service_from_env
from runtime.coverage_factory import start_coverage_worker_from_env
from runtime.redaction import configure_logging
from runtime.sector_history_sync import start_sector_history_background_sync


def build_sector_notification_broker() -> SectorSyncNotificationBroker:
    """Persist notification registrations in the existing runtime database."""
    database_url = os.getenv("DATABASE_URL", "sqlite:///stock_bot.db")
    broker = SectorSyncNotificationBroker(
        SQLiteNotificationStore(lambda: connect_database(database_url)),
        max_delivery_attempts=int(
            os.getenv("SECTOR_NOTIFICATION_MAX_ATTEMPTS", "5")
        ),
        registration_ttl_seconds=float(
            os.getenv("SECTOR_NOTIFICATION_TTL_SECONDS", "86400")
        ),
        purge_interval_seconds=float(
            os.getenv("SECTOR_NOTIFICATION_PURGE_INTERVAL_SECONDS", "300")
        ),
    )
    broker.purge_stale()
    return broker


if __name__ == "__main__":
    load_dotenv()
    configure_logging()
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
    sector_notifications = build_sector_notification_broker()
    sector_worker.add_listener(sector_notifications.publish)
    # Phase 25: market-wide coverage refresh. Starting it only spawns a daemon
    # thread (its first cycle runs after COVERAGE_STARTUP_DELAY), so bot startup
    # never waits on a full-market refresh. It reuses the sector worker for
    # sector histories and records that worker's results as coverage.
    coverage_worker = start_coverage_worker_from_env(sector_worker)
    try:
        run_polling(TelegramCommandService(service), sector_notifications)
    finally:
        if coverage_worker is not None:
            coverage_worker.stop(timeout=10.0)
        sector_worker.stop(timeout=10.0)
