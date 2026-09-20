"""Bounded Phase 23 acceptance using live EOD history and a temporary database.

No real portfolio data is read or written.  Credentials remain in local
environment variables and are passed directly to the existing Vietcap client.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from dotenv import load_dotenv

from data.database import connect_database
from data.vietcap.rest import VietcapRestClient
from runtime.bot_service import RuntimeBotDataService
from scanner.universe import ScannerInstrument
from telegram_bot.commands import TelegramCommandService


SYNTHETIC_USER_ID = 9_999_999_999


def _client() -> VietcapRestClient:
    load_dotenv()
    required = {
        name: os.getenv(name, "").strip()
        for name in ("VIETCAP_AUTHORIZATION", "VIETCAP_DEVICE_ID", "VIETCAP_COOKIE")
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError("Missing local Vietcap configuration: " + ", ".join(missing))
    return VietcapRestClient(
        authorization=required["VIETCAP_AUTHORIZATION"],
        device_id=required["VIETCAP_DEVICE_ID"],
        cookie=required["VIETCAP_COOKIE"],
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with TemporaryDirectory(prefix="phase23-live-") as directory:
        database = Path(directory, "portfolio.sqlite3").as_posix()
        connection = connect_database(f"sqlite:///{database}")
        try:
            service = RuntimeBotDataService(
                _client(), connection,
                (ScannerInstrument("ACB", "HOSE", "STOCK"),),
                history_count=130,
            )
            commands = TelegramCommandService(service)

            def run(name: str, *args: str) -> str:
                return commands.portfolio_command(name, SYNTHETIC_USER_ID, args)

            responses = {
                "addwatch": run("addwatch", "ACB"),
                "watchlist": run("watchlist"),
                "addholding": run("addholding", "ACB", "100", "22000"),
                "portfolio": run("portfolio"),
                "risk": run("risk"),
                "size": run("size", "ACB", "24000", "22000", "500000000", "1"),
                "stress": run("stress", "ACB", "-10"),
            }
            expected = {
                "addwatch": "added to your watchlist",
                "watchlist": "⭐ WATCHLIST",
                "addholding": "100 shares",
                "portfolio": "💼 MY PORTFOLIO",
                "risk": "⚠ PORTFOLIO RISK",
                "size": "📐 POSITION SIZE",
                "stress": "🧪 STRESS TEST",
            }
            failures = [
                name for name, marker in expected.items()
                if marker not in responses[name] or "Data unavailable." in responses[name]
            ]
            if failures:
                print("[FAIL] Phase 23 live command(s): " + ", ".join(failures))
                return 1
            if "Vietcap historical" not in responses["portfolio"]:
                print("[FAIL] Portfolio valuation did not use a live Vietcap EOD response")
                return 1
            print("[PASS] Phase 23 live EOD valuation and all portfolio command paths")
            print("[PASS] Temporary database used; no real holdings were persisted")
            return 0
        finally:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
