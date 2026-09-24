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
from runtime.index_stream_worker import start_index_stream_worker_from_env
from runtime.news_refresh import start_targeted_news_worker_from_env
from runtime.redaction import configure_logging
from runtime.scanner_worker import start_scanner_worker_from_env
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

    database_url = os.getenv("DATABASE_URL", "sqlite:///stock_bot.db")
    news_refresh_worker = start_targeted_news_worker_from_env(
        lambda: connect_database(database_url)
    )
    service.set_news_refresh_requester(news_refresh_worker.request)

    # Phase 25: market-wide coverage refresh. Starting it only spawns a daemon
    # thread (its first cycle runs after COVERAGE_STARTUP_DELAY), so bot startup
    # never waits on a full-market refresh. It reuses the sector worker for
    # sector histories and records that worker's results as coverage.
    coverage_worker = start_coverage_worker_from_env(
        sector_worker, news_ticker_requester=news_refresh_worker.request
    )
    # Phase 25/Issue 1 fix: persist market-wide /scan snapshots on a daemon
    # thread. Without this, /scan had no snapshot to read and silently fell
    # back to the small legacy BOT_WATCH_SYMBOLS watch list (e.g. FPT/ACB)
    # instead of the full HOSE/HNX/UPCoM universe.
    scanner_worker = start_scanner_worker_from_env(
        financials_requester=(
            coverage_worker.request_financials if coverage_worker is not None else None
        ),
        before_start=(
            lambda scanner: coverage_worker.add_financial_refresh_listener(
                lambda _symbols: scanner.request_scan()
            )
            if coverage_worker is not None else None
        ),
    )
    if coverage_worker is not None:
        service.set_financials_refresh_requester(coverage_worker.request_financials)
    # Issue 2 fix: without this, ``service.index_state`` was always empty in
    # production (nothing ever populated it), so /market and /soi always
    # reported "BREADTH: unavailable" and a regime reason that could never
    # move past "chỉ dựa trên xu hướng EMA". This reuses the same
    # VietcapRealtimeClient/IndexStatePipeline previously only exercised by
    # scripts/test_realtime_index.py, on a bounded daemon thread.
    index_stream_worker = None
    if service.index_state is not None:
        index_stream_worker = start_index_stream_worker_from_env(service.index_state)
    try:
        run_polling(TelegramCommandService(service), sector_notifications)
    finally:
        if scanner_worker is not None:
            scanner_worker.stop(timeout=10.0)
        if coverage_worker is not None:
            coverage_worker.stop(timeout=10.0)
        if index_stream_worker is not None:
            index_stream_worker.stop(timeout=10.0)
        news_refresh_worker.stop(timeout=10.0)
        news_refresh_worker.close()
        sector_worker.stop(timeout=10.0)
