"""Phase 26 bounded Telegram/live acceptance for /soi, /market, /sentiment, /chart.

Runs the REAL command path (RuntimeBotDataService -> TelegramCommandService) on a
TEMPORARY copy of the runtime database, so portfolio/watchlist data is never
modified. Symbols are chosen from that database by metadata (HOSE, HNX, UPCoM,
bank, non-bank outside BOT_WATCH_SYMBOLS, short history) plus FPT/ACB baselines.

Delivery is opt-in:  --send  posts the results through the configured bot using
TEST_TELEGRAM_CHAT_ID (falls back to TELEGRAM_CHAT_ID). The chat id is read only
from the environment and is never printed. No polling loop is started.

    py -3.12 scripts/test_phase26_telegram_live.py [--send] [--max-symbols 5]

Without Vietcap credentials the run is NOT TESTED (exit 3). Outside a trading
session the script says so: /soi, /market and /sentiment live-SESSION acceptance
(Phase 22) cannot be claimed from an off-hours run.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import shutil
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from data.database import connect_database
from data.migrations import bootstrap_schema
from runtime.acceptance import (
    EXIT_CODES, FAIL, NOT_TESTED, PASS, deliver_checks, market_session_note,
    pick_diverse_symbols, probe_host, run_command_matrix,
)
from runtime.bot_service import RuntimeBotDataService, _instruments
from runtime.redaction import configure_logging, redact_secrets, safe_reason
from telegram_bot.commands import TelegramCommandService


def _temp_database(tmp: Path, url: str):
    """Copy the runtime DB (if it exists) into ``tmp``; production is opened read-only-by-copy."""
    source = url.removeprefix("sqlite:///")
    target = tmp / "acceptance.sqlite3"
    if source and Path(source).is_file():
        shutil.copyfile(source, target)
    return connect_database(f"sqlite:///{target.as_posix()}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--send", action="store_true", help="deliver results to Telegram")
    parser.add_argument("--max-symbols", type=int, default=5)
    parser.add_argument("--symbols", nargs="+", help="override the automatic diverse sample")
    args = parser.parse_args(argv)
    if not 1 <= args.max_symbols <= 8:
        parser.error("--max-symbols must be between 1 and 8")
    load_dotenv()
    configure_logging()
    print(market_session_note())

    required = ("VIETCAP_AUTHORIZATION", "VIETCAP_DEVICE_ID", "VIETCAP_COOKIE")
    if not all((os.getenv(name) or "").strip() for name in required):
        print("NOT TESTED: Vietcap credentials are not configured (external blocker)")
        return EXIT_CODES[NOT_TESTED]

    reachable, note = probe_host("https://trading.vietcap.com.vn")
    print(f"probe Vietcap: {'reachable' if reachable else 'BLOCKED'} ({note})")
    if not reachable:
        print("NOT TESTED: Vietcap is unreachable from this environment (external blocker)")
        return EXIT_CODES[NOT_TESTED]

    from data.vietcap.rest import VietcapRestClient

    client = VietcapRestClient(
        authorization=os.environ["VIETCAP_AUTHORIZATION"].strip(),
        device_id=os.environ["VIETCAP_DEVICE_ID"].strip(), cookie=os.environ["VIETCAP_COOKIE"].strip())
    with tempfile.TemporaryDirectory() as tmp:
        conn = _temp_database(Path(tmp), os.getenv("DATABASE_URL", "sqlite:///stock_bot.db"))
        bootstrap_schema(conn)
        watch = _instruments(os.getenv("BOT_WATCH_SYMBOLS", "FPT:HOSE,ACB:HOSE"))
        picks = pick_diverse_symbols(conn, [i.symbol for i in watch])
        symbols = [s.upper() for s in args.symbols] if args.symbols else list(dict.fromkeys(picks.values()))
        symbols = symbols[: args.max_symbols] or ["FPT", "ACB"]
        for label, symbol in picks.items():
            if symbol in symbols:
                print(f"sample: {symbol} ({label})")
        instruments = tuple(watch) + tuple(
            i for i in _instruments(",".join(f"{s}:HOSE" for s in symbols)) if i.symbol not in {w.symbol for w in watch})
        news_service = None
        try:
            from intelligence.news.repository import SQLiteNewsRepository
            from intelligence.news.service import SentimentQueryService
            news_service = SentimentQueryService(
                SQLiteNewsRepository(os.getenv("NEWS_DATABASE_PATH", "news_sentiment.db")),
                float(os.getenv("SENTIMENT_HALF_LIFE_HOURS", "24")))
        except Exception as error:
            print("news service unavailable:", safe_reason(error))
        commands = TelegramCommandService(
            RuntimeBotDataService(client, conn, instruments, news_service=news_service))
        checks = run_command_matrix(commands, symbols)
        for check in checks:
            print(redact_secrets(check.line()))
        failed = [c for c in checks if not c.ok]

        if args.send:
            chat = (os.getenv("TEST_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or "").strip()
            token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
            if not chat or not token:
                print("NOT TESTED: --send needs TELEGRAM_BOT_TOKEN and TEST_TELEGRAM_CHAT_ID")
                return EXIT_CODES[NOT_TESTED]
            from telegram import Bot

            async def send():
                async with Bot(token) as bot:
                    return await deliver_checks(bot, int(chat) if chat.lstrip("-").isdigit() else chat, checks)

            outcomes = asyncio.run(send())
            for line in outcomes:
                print(redact_secrets(line))
            failed += [o for o in outcomes if o.startswith("SEND-FAILED")]
        conn.close()
    verdict = FAIL if failed else PASS
    if verdict == PASS and all(c.degraded for c in checks if c.command in ("/soi", "/chart")):
        verdict = NOT_TESTED   # every answer was an honest "no data": nothing live was actually exercised
        print("no live market data was obtained; result downgraded to NOT TESTED")
    print(f"\nPhase 26 Telegram/live acceptance: {verdict} "
          f"({len(checks) - len([c for c in checks if not c.ok])}/{len(checks)} checks ok)")
    return EXIT_CODES[verdict]


if __name__ == "__main__":
    raise SystemExit(main())
