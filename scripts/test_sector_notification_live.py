"""Bounded live acceptance for the sector-sync -> Telegram notification path.

It runs one real Vietcap sector synchronization for one symbol, feeds the real
worker result through the real broker, and delivers the resulting notification
through the real Telegram Bot API.  Nothing here polls forever, reads real
holdings, or writes to the configured production database.

Usage:
    py -3.12 scripts/test_sector_notification_live.py --symbol VHM
    py -3.12 scripts/test_sector_notification_live.py --symbol VHM --dry-run

Exit status:
    0  PASS        a real Telegram message was delivered
    2  INCOMPLETE  the provider or the sector data could not reach READY
    1  FAIL        configuration, authentication, or send failure
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):  # allow direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from data.database import connect_database
from data.vietcap.rest import VietcapRestClient, VietcapRestError
from runtime.sector_history_sync import SectorHistorySynchronizer
from telegram_bot.sector_notification_store import SQLiteNotificationStore
from telegram_bot.sector_notifications import (
    SectorSyncNotificationBroker,
    deliver_sector_notifications,
)

PASS, FAIL, INCOMPLETE = 0, 1, 2


def report(status: str, message: str) -> None:
    print(f"[{status}] {message}")


def required_env(*names: str) -> dict[str, str] | None:
    """Read secrets from .env; never print or log their values."""
    values = {name: os.getenv(name, "").strip() for name in names}
    missing = sorted(name for name, value in values.items() if not value)
    if missing:
        report("FAIL", f"missing .env values: {', '.join(missing)}")
        return None
    return values


def copy_runtime_database(destination: Path) -> str:
    """Work on a copy so a live probe can never mutate real user data."""
    source_url = os.getenv("DATABASE_URL", "sqlite:///stock_bot.db")
    source = source_url.removeprefix("sqlite:///")
    target = destination / "sector_notification_live.sqlite3"
    if source != ":memory:" and Path(source).exists():
        shutil.copyfile(source, target)
    return f"sqlite:///{target.as_posix()}"


async def send_once(token: str, broker: SectorSyncNotificationBroker) -> int:
    from telegram import Bot
    from telegram.error import InvalidToken, TelegramError

    bot = Bot(token)
    try:
        await bot.initialize()
    except InvalidToken:
        report("FAIL", "Telegram authentication failed (invalid token)")
        return FAIL
    except TelegramError as error:
        report("FAIL", f"Telegram authentication failed: {type(error).__name__}")
        return FAIL
    try:
        identity = await bot.get_me()
        report("INFO", f"Telegram authenticated as @{identity.username}")
        try:
            delivered = await deliver_sector_notifications(bot, broker)
        except TelegramError as error:
            report("FAIL", f"Telegram send failed: {type(error).__name__}")
            return FAIL
        if delivered < 1:
            report("FAIL", "broker produced no notification to deliver")
            return FAIL
        report("PASS", f"delivered {delivered} real Telegram notification(s)")
        return PASS
    finally:
        await bot.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="VHM", help="stock ticker to synchronize")
    parser.add_argument(
        "--max-members", type=int, default=8,
        help="uncached sector members fetched in this bounded pass",
    )
    parser.add_argument(
        "--provider-timeout", type=float, default=90.0,
        help="hard upper bound in seconds for the whole sync pass",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="run the provider and broker path but send nothing to Telegram",
    )
    args = parser.parse_args()
    symbol = args.symbol.strip().upper()
    if not symbol.isalnum():
        report("FAIL", "symbol must be alphanumeric")
        return FAIL

    load_dotenv()
    vietcap = required_env(
        "VIETCAP_AUTHORIZATION", "VIETCAP_DEVICE_ID", "VIETCAP_COOKIE"
    )
    if vietcap is None:
        return FAIL
    telegram_env = None
    if not args.dry_run:
        telegram_env = required_env("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
        if telegram_env is None:
            return FAIL

    workspace = Path(tempfile.mkdtemp(prefix="sector-notify-live-"))
    try:
        database_url = copy_runtime_database(workspace)
        connection = connect_database(database_url)
        broker = SectorSyncNotificationBroker(
            SQLiteNotificationStore(lambda: connect_database(database_url))
        )
        chat_id = (
            "0" if telegram_env is None else telegram_env["TELEGRAM_CHAT_ID"]
        )
        broker.watch(chat_id, symbol)

        synchronizer = SectorHistorySynchronizer(
            VietcapRestClient(
                authorization=vietcap["VIETCAP_AUTHORIZATION"],
                device_id=vietcap["VIETCAP_DEVICE_ID"],
                cookie=vietcap["VIETCAP_COOKIE"],
            ),
            connection,
            retry_attempts=1,
        )
        started = time.monotonic()
        try:
            result = synchronizer.sync_symbol_sector(
                symbol, max_uncached_members=max(1, args.max_members)
            )
        except VietcapRestError as error:
            report("FAIL", f"provider request failed: {type(error).__name__}")
            return FAIL
        elapsed = time.monotonic() - started
        if elapsed > args.provider_timeout:
            report("FAIL", f"provider exceeded the {args.provider_timeout:.0f}s bound")
            return FAIL

        if result.sector_code is None:
            report("INCOMPLETE", f"{symbol} has no effective sector membership")
            return INCOMPLETE
        report(
            "INFO",
            f"sector={result.sector_code} members={result.members} "
            f"usable={result.usable} downloaded={result.downloaded} "
            f"failed={len(result.failed)} elapsed={elapsed:.1f}s",
        )
        if result.usable == 0 and result.downloaded == 0:
            report("INCOMPLETE", "provider returned no usable member history")
            return INCOMPLETE

        queued = broker.publish(result)
        if queued < 1:
            report("FAIL", "worker result produced no broker notification")
            return FAIL
        if result.usable < 5:
            report(
                "INCOMPLETE",
                f"sector not READY: {result.usable}/5 usable peer histories; "
                "an INCOMPLETE notice is what the broker queued",
            )
        if args.dry_run:
            pending = broker.drain()
            report("INFO", f"dry run queued {len(pending)} notification(s)")
            for item in pending:
                print(item.text)
            return PASS if result.usable >= 5 else INCOMPLETE

        status = asyncio.run(send_once(telegram_env["TELEGRAM_BOT_TOKEN"], broker))
        if status == PASS and result.usable < 5:
            return INCOMPLETE
        return status
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
