"""Pure command rendering for the Telegram bot."""

from __future__ import annotations

from typing import Protocol, Sequence


class BotDataService(Protocol):
    def symbol_overview(self, symbol: str) -> str | None: ...
    def scan_results(self) -> Sequence[str]: ...
    def market_overview(self) -> str: ...
    def signal_explanation(self, symbol: str) -> str | None: ...
    def performance_overview(self) -> str: ...


HELP_TEXT = (
    "Các lệnh:\n"
    "/soi FPT - xem trạng thái một mã\n"
    "/scan - xem danh sách quét\n"
    "/market - xem trạng thái thị trường\n"
    "/why FPT - xem lý do tín hiệu\n"
    "/performance - xem kết quả backtest"
)


class UnavailableBotDataService:
    """Safe runtime fallback until live orchestration wires the data layers."""

    def symbol_overview(self, symbol: str) -> None:
        return None

    def scan_results(self) -> tuple[str, ...]:
        return ()

    def market_overview(self) -> str:
        return "Dữ liệu thị trường realtime hiện chưa sẵn sàng."

    def signal_explanation(self, symbol: str) -> None:
        return None

    def performance_overview(self) -> str:
        return "Kết quả backtest hiện chưa sẵn sàng."


class TelegramCommandService:
    def __init__(self, data: BotDataService) -> None:
        self.data = data

    def start(self) -> str:
        return "Bot tín hiệu chứng khoán Việt Nam đã sẵn sàng.\n" + HELP_TEXT

    def help(self) -> str:
        return HELP_TEXT

    def soi(self, arguments: Sequence[str]) -> str:
        symbol = _one_symbol(arguments, "/soi FPT")
        result = self.data.symbol_overview(symbol)
        return result if result is not None else f"Chưa có dữ liệu cho {symbol}."

    def scan(self) -> str:
        symbols = tuple(self.data.scan_results())
        return "Chưa có mã đạt bộ lọc." if not symbols else "Watchlist: " + ", ".join(symbols)

    def market(self) -> str:
        return self.data.market_overview()

    def why(self, arguments: Sequence[str]) -> str:
        symbol = _one_symbol(arguments, "/why FPT")
        result = self.data.signal_explanation(symbol)
        return result if result is not None else f"Chưa có giải thích tín hiệu cho {symbol}."

    def performance(self) -> str:
        return self.data.performance_overview()


def _one_symbol(arguments: Sequence[str], usage: str) -> str:
    if len(arguments) != 1:
        raise ValueError(f"Cách dùng: {usage}")
    symbol = arguments[0].strip().upper()
    if not symbol or not symbol.isalnum():
        raise ValueError(f"Cách dùng: {usage}")
    return symbol
