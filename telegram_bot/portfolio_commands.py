"""Phase 23 command layer: parse input, call the portfolio runtime, render.

No portfolio arithmetic happens here.  Every user-facing failure is a short
message; raw exceptions and ``None`` never reach Telegram.
"""

from __future__ import annotations

from decimal import Decimal
import logging
import re
import sqlite3
from collections.abc import Sequence

from portfolio.models import PortfolioError
from portfolio.repository import normalize_symbol
from telegram_bot.portfolio_formatters import (
    format_portfolio,
    format_position_size,
    format_risk,
    format_risk_settings,
    format_stress,
    format_watch_change,
    format_watchlist,
    money,
    price,
)

LOGGER = logging.getLogger(__name__)
PORTFOLIO_UNSUPPORTED = "Portfolio features are not enabled in the current runtime."
DATA_UNAVAILABLE = "Data unavailable."

USAGE = {
    "addwatch": "/addwatch FPT",
    "removewatch": "/removewatch FPT",
    "addholding": "/addholding FPT 1000 150000",
    "removeholding": "/removeholding FPT",
    "size": "/size FPT 150000 142000 500000000 1",
    "stress": "/stress portfolio -5   or   /stress FPT -10",
    "setrisk": "/setrisk 1",
}
COMMANDS = frozenset({
    "watchlist", "addwatch", "removewatch", "portfolio", "addholding",
    "removeholding", "risk", "size", "stress", "setrisk", "risksettings",
})

_POSITIVE = re.compile(r"^\d+(\.\d+)?$")
_SIGNED = re.compile(r"^[+-]?\d+(\.\d+)?$")
_WHOLE = re.compile(r"^\d+$")


def _usage(command: str) -> PortfolioError:
    return PortfolioError(f"Usage:\n{USAGE[command]}")


def _decimal(raw: str, command: str, *, signed: bool = False) -> Decimal:
    text = raw.strip().rstrip("%") if signed else raw.strip()
    if not (_SIGNED if signed else _POSITIVE).match(text):
        raise _usage(command)
    return Decimal(text)


class PortfolioCommands:
    def __init__(self, data: object) -> None:
        self.data = data

    def execute(self, command: str, user_id: int | None, arguments: Sequence[str]) -> str:
        runtime = getattr(self.data, "portfolio", None)
        if runtime is None or command not in COMMANDS:
            return PORTFOLIO_UNSUPPORTED
        if user_id is None:
            return "Cannot identify your Telegram account."
        try:
            return getattr(self, f"_{command}")(runtime, user_id, list(arguments))
        except ValueError as error:  # PortfolioError is a ValueError
            return str(error)
        except sqlite3.Error:
            LOGGER.exception("Portfolio storage error")
            return DATA_UNAVAILABLE

    # ------------------------------------------------------------ watchlist

    def _watchlist(self, runtime, user_id, args) -> str:
        return format_watchlist(runtime.watchlist_view(user_id))

    def _addwatch(self, runtime, user_id, args) -> str:
        if len(args) != 1:
            raise _usage("addwatch")
        symbol, added = runtime.add_watch(user_id, normalize_symbol(args[0]))
        return format_watch_change(symbol, added, added=True)

    def _removewatch(self, runtime, user_id, args) -> str:
        if len(args) != 1:
            raise _usage("removewatch")
        symbol, removed = runtime.remove_watch(user_id, normalize_symbol(args[0]))
        return format_watch_change(symbol, removed, added=False)

    # ------------------------------------------------------------- holdings

    def _portfolio(self, runtime, user_id, args) -> str:
        return format_portfolio(runtime.portfolio_view(user_id))

    def _addholding(self, runtime, user_id, args) -> str:
        if len(args) != 3:
            raise _usage("addholding")
        symbol = normalize_symbol(args[0])
        if not _WHOLE.match(args[1].strip()):
            raise _usage("addholding")
        quantity = int(args[1])
        cost = _decimal(args[2], "addholding")
        symbol, created = runtime.upsert_holding(user_id, symbol, quantity, cost)
        verb = "added" if created else "updated (quantity and average cost replaced)"
        return f"💼 {symbol}: {quantity:,} shares @ {price(cost)} {verb}."

    def _removeholding(self, runtime, user_id, args) -> str:
        if len(args) != 1:
            raise _usage("removeholding")
        symbol, removed = runtime.remove_holding(user_id, normalize_symbol(args[0]))
        return f"{symbol} removed from your portfolio." if removed else f"You do not hold {symbol}."

    # ----------------------------------------------------------------- risk

    def _risk(self, runtime, user_id, args) -> str:
        return format_risk(runtime.risk_view(user_id))

    def _size(self, runtime, user_id, args) -> str:
        if len(args) not in (4, 5):
            raise _usage("size")
        symbol = normalize_symbol(args[0])
        entry, stop, capital = (_decimal(item, "size") for item in args[1:4])
        risk = _decimal(args[4], "size") if len(args) == 5 else None
        return format_position_size(runtime.size(user_id, symbol, entry, stop, capital, risk))

    def _stress(self, runtime, user_id, args) -> str:
        if len(args) != 2:
            raise _usage("stress")
        target = None if args[0].strip().lower() == "portfolio" else normalize_symbol(args[0])
        shock = _decimal(args[1], "stress", signed=True)
        return format_stress(runtime.stress_view(user_id, shock, target))

    def _setrisk(self, runtime, user_id, args) -> str:
        if len(args) != 1:
            raise _usage("setrisk")
        settings = runtime.set_default_risk(user_id, _decimal(args[0], "setrisk"))
        return "✅ Default risk/trade saved.\n\n" + format_risk_settings(settings)

    def _risksettings(self, runtime, user_id, args) -> str:
        return format_risk_settings(runtime.risk_settings(user_id))


__all__ = ["COMMANDS", "PortfolioCommands", "money"]