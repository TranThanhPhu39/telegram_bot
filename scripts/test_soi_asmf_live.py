import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

load_dotenv()
from runtime.bot_service import build_runtime_service_from_env
from telegram_bot.commands import TelegramCommandService

bot_data = build_runtime_service_from_env()
cmd_service = TelegramCommandService(bot_data)

for sym in ['FPT', 'VIC']:
    print(f'\n==================== /soi {sym} ASMF ====================')
    res = cmd_service.soi([sym, 'ASMF'], user_id=123)
    print(res)

bot_data.connection.close()
