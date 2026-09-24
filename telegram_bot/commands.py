"""Pure command rendering for the Telegram bot.

The command layer holds no business logic.  It validates arguments, calls one
data-service method and returns text.  New drill-down commands degrade safely
when a data service predates them, so older services keep working unchanged.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from runtime.views import ChartRequestView
from telegram_bot.portfolio_commands import PortfolioCommands

class BotDataService(Protocol):
    def symbol_overview(self, symbol: str, strategy: str = "CL1") -> str | None: ...
    def scan_results(self) -> Sequence[str]: ...
    def market_overview(self) -> str: ...
    def signal_explanation(self, symbol: str) -> str | None: ...
    def performance_overview(self, strategy: str | None = None) -> str: ...
    def strategy_catalog(self) -> str: ...
    def latest_news(self, symbol: str) -> str: ...
    def sentiment_overview(self, symbol: str) -> str: ...


HELP_TEXT = (
    "🤖 HỆ THỐNG TRỢ LÝ ĐỊNH LƯỢNG CHỨNG KHOÁN\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "🔍 TRA CỨU & PHÂN TÍCH CỔ PHIẾU:\n"
    "• /soi FPT [CL1|ASMF] - dashboard tổng quan một mã\n"
    "• /why FPT - giải thích vì sao ở trạng thái đó\n"
    "• /technical FPT - chi tiết kỹ thuật + hỗ trợ/kháng cự\n"
    "• /fundamental FPT - chỉ số cơ bản theo ngày công bố\n"
    "• /sentiment FPT - sentiment tin tức gần đây (tối đa 30 ngày)\n"
    "• /tin FPT - các tin mới nhất\n"
    "• /sector ACB - bối cảnh ngành\n"
    "• /chart FPT - biểu đồ nến kèm EMA20/EMA50\n"
    "\n"
    "🌐 THỊ TRƯỜNG & CHIẾN LƯỢC:\n"
    "• /market - trạng thái thị trường\n"
    "• /scan - danh sách quét kèm lý do\n"
    "• /chienluoc - mô tả CL1 và ASMF\n"
    "• /performance - kết quả backtest\n"
    "\n"
    "💼 QUẢN LÝ DANH MỤC & RỦI RO:\n"
    "• /watchlist - danh sách theo dõi | /addwatch FPT | /removewatch FPT\n"
    "• /portfolio - danh mục, P&L chưa thực hiện, tỷ trọng, phơi nhiễm\n"
    "• /addholding FPT 1000 150000 - thêm/cập nhật vị thế (số lượng, giá vốn)\n"
    "• /removeholding FPT - xóa vị thế\n"
    "• /risk - rủi ro danh mục (tập trung, biến động lịch sử)\n"
    "• /size FPT 150000 142000 500000000 [rủi ro %] - tính khối lượng theo ngân sách rủi ro\n"
    "• /stress portfolio -5 | /stress FPT -10 - kịch bản giảm giá tất định\n"
    "• /setrisk 1 | /risksettings - rủi ro mặc định mỗi lệnh\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "💡 Gõ /soi <MÃ> hoặc bấm vào các nút điều hướng để xem chi tiết."
)


UNSUPPORTED = "Tính năng này chưa được bật trong runtime hiện tại."


class UnavailableBotDataService:
    """Safe runtime fallback until live orchestration wires the data layers."""

    def symbol_overview(self, symbol: str, strategy: str = "CL1") -> None:
        return None

    def scan_results(self) -> tuple[str, ...]:
        return ()

    def market_overview(self) -> str:
        return "Dữ liệu thị trường realtime hiện chưa sẵn sàng."

    def signal_explanation(self, symbol: str) -> None:
        return None

    def performance_overview(self, strategy: str | None = None) -> str:
        return "Kết quả backtest hiện chưa sẵn sàng."

    def strategy_catalog(self) -> str:
        return "CL1 và ASMF hiện chưa sẵn sàng."

    def latest_news(self, symbol: str) -> str:
        return "News sentiment unavailable."

    def sentiment_overview(self, symbol: str) -> str:
        return "News sentiment unavailable."

    def technical_overview(self, symbol: str) -> str:
        return "Dữ liệu kỹ thuật hiện chưa sẵn sàng."

    def fundamental_overview(self, symbol: str) -> str:
        return "Fundamental data missing."

    def sector_overview(self, name: str) -> str:
        return "Dữ liệu ngành hiện chưa sẵn sàng."


class TelegramCommandService:
    def __init__(self, data: BotDataService) -> None:
        self.data = data
        self.portfolio = PortfolioCommands(data)

    def portfolio_command(
        self, name: str, user_id: int | None, arguments: Sequence[str]
    ) -> str:
        """Portfolio/watchlist/risk commands, keyed by Telegram numeric user id."""
        return self.portfolio.execute(name, user_id, arguments)

    def start(self) -> str:
        return "Bot tín hiệu chứng khoán Việt Nam đã sẵn sàng.\n" + HELP_TEXT

    def help(self) -> str:
        return HELP_TEXT

    def soi(self, arguments: Sequence[str], user_id: int | None = None) -> str:
        symbol, strategy = _symbol_and_strategy(arguments)
        if user_id is not None and getattr(self.data, "portfolio", None) is not None:
            result = self.data.symbol_overview(symbol, strategy, user_id=user_id)
        else:
            result = self.data.symbol_overview(symbol, strategy)
        return result if result is not None else f"Chưa có dữ liệu cho {symbol}."

    def scan(self, arguments: Sequence[str] | None = None) -> str:
        strategy = "CL1"
        if arguments and len(arguments) > 0 and arguments[0].strip().upper() in {"CL1", "ASMF"}:
            strategy = arguments[0].strip().upper()
        detailed = getattr(self.data, "scan_overview", None)
        if callable(detailed):
            try:
                return detailed(strategy=strategy)
            except TypeError:
                return detailed()
        symbols = tuple(self.data.scan_results())
        return "Chưa có mã đạt bộ lọc." if not symbols else "Watchlist: " + ", ".join(symbols)

    def market(self) -> str:
        return self.data.market_overview()

    def why(self, arguments: Sequence[str]) -> str:
        symbol = _one_symbol(arguments, "/why FPT")
        result = self.data.signal_explanation(symbol)
        return result if result is not None else f"Chưa có giải thích tín hiệu cho {symbol}."

    def performance(self, arguments: Sequence[str] | None = None) -> str:
        values = tuple(arguments or ())
        if not values:
            return self.data.performance_overview()
        if len(values) != 1 or values[0].strip().upper() not in {"CL1", "ASMF"}:
            raise ValueError("Cách dùng: /performance [CL1|ASMF]")
        return self.data.performance_overview(values[0].strip().upper())

    def strategies(self) -> str:
        return self.data.strategy_catalog()

    def news(self, arguments: Sequence[str]) -> str:
        return self.data.latest_news(_one_symbol(arguments, "/tin FPT"))

    def sentiment(self, arguments: Sequence[str]) -> str:
        return self.data.sentiment_overview(_one_symbol(arguments, "/sentiment FPT"))

    def technical(self, arguments: Sequence[str]) -> str:
        symbol = _one_symbol(arguments, "/technical FPT")
        return self._optional("technical_overview", symbol)

    def fundamental(self, arguments: Sequence[str]) -> str:
        symbol = _one_symbol(arguments, "/fundamental FPT")
        return self._optional("fundamental_overview", symbol)

    def sector(self, arguments: Sequence[str]) -> str:
        name = _one_symbol(arguments, "/sector ACB")
        return self._optional("sector_overview", name)

    def chart(self, arguments: Sequence[str]) -> ChartRequestView:
        """Return a rendered candlestick or market sector chart; text stays out of this path."""
        symbol = _one_symbol(arguments, "/chart FPT")
        if symbol == "MARKET":
            handler = getattr(self.data, "sector_performance_chart", None)
            if not callable(handler):
                raise ValueError(UNSUPPORTED)
            result = handler()
            if not isinstance(result, ChartRequestView):
                raise ValueError(UNSUPPORTED)
            return result
        handler = getattr(self.data, "candlestick_chart", None)
        if not callable(handler):
            raise ValueError(UNSUPPORTED)
        result = handler(symbol)
        if not isinstance(result, ChartRequestView):
            raise ValueError(UNSUPPORTED)
        return result

    def sector_chart(self) -> ChartRequestView:
        return self.chart(["MARKET"])

    def _optional(self, method: str, argument: str) -> str:
        handler = getattr(self.data, method, None)
        if not callable(handler):
            return UNSUPPORTED
        result = handler(argument)
        return result if result else UNSUPPORTED


def _symbol_and_strategy(arguments: Sequence[str]) -> tuple[str, str]:
    if len(arguments) not in (1, 2):
        raise ValueError("Cách dùng: /soi FPT [CL1|ASMF]")
    symbol = _one_symbol(arguments[:1], "/soi FPT [CL1|ASMF]")
    strategy = "CL1" if len(arguments) == 1 else arguments[1].strip().upper()
    if strategy not in {"CL1", "ASMF"}:
        raise ValueError("Chiến lược phải là CL1 hoặc ASMF.")
    return symbol, strategy


def _one_symbol(arguments: Sequence[str], usage: str) -> str:
    if len(arguments) != 1:
        raise ValueError(f"Cách dùng: {usage}")
    symbol = arguments[0].strip().upper()
    if not symbol or not symbol.isalnum():
        raise ValueError(f"Cách dùng: {usage}")
    return symbol
