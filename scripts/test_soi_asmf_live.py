import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

load_dotenv()
from runtime.bot_service import build_runtime_service_from_env
from telegram_bot.commands import TelegramCommandService


def main() -> int:
    bot_data = build_runtime_service_from_env()
    try:
        cmd_service = TelegramCommandService(bot_data)
        for symbol in ("FPT", "VIC"):
            print(f"\n==================== /soi {symbol} ASMF ====================")
            print(cmd_service.soi([symbol, "ASMF"], user_id=123))
    finally:
        bot_data.connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
