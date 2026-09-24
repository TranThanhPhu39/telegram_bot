"""Pure Telegram rendering for persisted backtest results."""

from __future__ import annotations

from collections.abc import Mapping

from backtest.models import BacktestRun


DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━━━"
LIVE_UNAVAILABLE = (
    "📡 LIVE PERFORMANCE: NOT AVAILABLE\n"
    "Bot chưa lưu đủ lịch sử khớp lệnh, khối lượng, chi phí và equity thực tế."
)


def format_performance_summary(runs: Mapping[str, BacktestRun | None]) -> str:
    blocks = [f"📊 STRATEGY BACKTEST — KẾT QUẢ GẦN NHẤT\n{DIVIDER}"]
    for strategy in ("CL1", "ASMF"):
        run = runs.get(strategy)
        if run is None:
            blocks.append(f"⚠️ {strategy}: Chưa có backtest {strategy} hợp lệ.")
            continue
        activity = (
            f"Tín hiệu đánh giá: {run.config.get('decision_count', 'N/A')} | Execution: chưa mô phỏng"
            if _signals_only(run)
            else f"Giao dịch đóng: {run.trade_count}"
        )
        blocks.append(
            f"{strategy} — {run.start_date:%d/%m/%Y} → {run.end_date:%d/%m/%Y}\n"
            f"• Universe: {len(run.symbols)} mã | {activity}\n"
            f"• Total Return: {_percent(run.total_return_percent)} | "
            f"VNINDEX: {_percent(run.benchmark_return_percent)}\n"
            f"• Max Drawdown: {_percent(run.max_drawdown_percent)} | "
            f"Status: {_validation(run)}"
        )
    blocks.extend((
        "🧪 ENGINE VALIDATION là chẩn đoán nội bộ riêng, không phải hiệu suất CL1/ASMF.",
        LIVE_UNAVAILABLE,
        "Dùng /performance CL1 hoặc /performance ASMF để xem chi tiết.\n"
        "Không phải khuyến nghị đầu tư.",
    ))
    return "\n\n".join(blocks)


def format_performance_detail(strategy: str, run: BacktestRun | None) -> str:
    strategy = strategy.upper()
    header = f"📊 {strategy} — BACKTEST PERFORMANCE\n{DIVIDER}"
    if run is None:
        return (
            f"{header}\n\n⚠️ Chưa có backtest {strategy} hợp lệ.\n"
            f"Không sử dụng engine smoke test làm kết quả {strategy}.\n\n"
            f"{LIVE_UNAVAILABLE}\n\nKhông phải khuyến nghị đầu tư."
        )
    config = run.config
    signals_only = _signals_only(run)
    if signals_only:
        header = f"📊 {strategy} — HISTORICAL SIGNAL EVALUATION\n{DIVIDER}"
    activity = (
        f"Tín hiệu đánh giá: {config.get('decision_count', 'N/A')}\n"
        "Giao dịch đóng: N/A — chưa mô phỏng execution\n"
        "Vị thế chưa đóng: N/A — chưa mô phỏng execution\n"
        "Vốn sử dụng: N/A — chưa có portfolio accounting"
        if signals_only
        else (
            f"Giao dịch đóng: {run.trade_count}\n"
            f"Vị thế chưa đóng: {run.open_position_count}\n"
            f"Vốn mô phỏng: {run.initial_capital:,.0f} VND\n"
            f"Equity cuối kỳ: {_money(run.final_equity)}"
        )
    )
    warning_lines = "\n".join(f"• {item}" for item in run.warnings)
    blocks = [
        header,
        (
            f"Giai đoạn: {run.start_date:%d/%m/%Y} → {run.end_date:%d/%m/%Y}\n"
            f"Universe: {len(run.symbols)} mã\n"
            f"{activity}"
        ),
        _signal_evidence(config),
        (
            f"💰 HIỆU QUẢ ({'N/A — chưa execution' if signals_only else 'NET SAU CHI PHÍ'})\n"
            f"• Total Return: {_percent(run.total_return_percent)}\n"
            f"• CAGR: {_percent(run.cagr_percent)}\n"
            f"• VNINDEX: {_percent(run.benchmark_return_percent)}\n"
            f"• Excess Return: {_percent(run.excess_return_percent)}\n"
            f"• VNINDEX Max Drawdown: {_percent(run.benchmark_max_drawdown_percent)}"
        ),
        (
            "📉 RỦI RO\n"
            f"• Max Drawdown: {_percent(run.max_drawdown_percent)}\n"
            f"• Sharpe: {_number(run.sharpe_ratio)}\n"
            f"• Sortino: {_number(run.sortino_ratio)}\n"
            f"• Calmar: {_number(run.calmar_ratio)}"
        ),
        (
            "🎯 GIAO DỊCH\n"
            f"• Win rate: {_percent(run.win_rate_percent)}\n"
            f"• Profit Factor: {_number(run.profit_factor)}\n"
            f"• Avg trade (net): {_percent(run.average_return_percent)}\n"
            f"• Avg holding: {_sessions(run.average_holding_sessions)}\n"
            f"• Expectancy: {_percent(run.expectancy_percent)}\n"
            f"• Avg win / loss: {_percent(run.average_win_percent)} / {_percent(run.average_loss_percent)}\n"
            f"• Payoff: {_number(run.payoff_ratio)} | Best/Worst: "
            f"{_percent(run.best_trade_percent)} / {_percent(run.worst_trade_percent)}\n"
            f"• Losing streak dài nhất: {_integer(run.longest_losing_streak)}\n"
            f"• Exposure TB: {_percent(run.exposure_percent)} | Trades/năm: {_number(run.trades_per_year)}"
        ),
        (
            "⚙️ GIẢ ĐỊNH ĐÃ LƯU\n"
            f"• Entry: {_config(config, 'entry_mode')}\n"
            f"• Fee: {_rate(config, 'commission_rate')}\n"
            f"• Sell tax: {_rate(config, 'sell_tax_rate')}\n"
            f"• Slippage: {_rate(config, 'slippage_rate')}\n"
            f"• Lot: {_config(config, 'lot_size')} | Allocation: {_config(config, 'allocation_mode')}\n"
            f"• Settlement: {_settlement(config)}"
        ),
        (
            "🧪 KIỂM ĐỊNH\n"
            f"• Status: {_validation(run)}\n"
            "• Không gọi là VALIDATED nếu chưa có bằng chứng ngoài mẫu phù hợp."
        ),
    ]
    if warning_lines:
        blocks.append("⚠️ GIỚI HẠN\n" + warning_lines)
    blocks.extend((LIVE_UNAVAILABLE, "Không phải khuyến nghị đầu tư."))
    return "\n\n".join(blocks)


def _signal_evidence(config: Mapping[str, object]) -> str:
    actions = config.get("action_counts")
    missing = config.get("missing_reason_counts")
    action_text = "N/A"
    if isinstance(actions, Mapping) and actions:
        action_text = ", ".join(
            f"{key}={value}" for key, value in sorted(actions.items())
        )
    lines = ["🔎 TÍN HIỆU", f"• Actions: {action_text}"]
    if isinstance(missing, Mapping) and missing:
        lines.append("• Nguyên nhân thiếu:")
        lines.extend(
            f"  - {key}: {value} quyết định"
            for key, value in sorted(missing.items())
        )
    return "\n".join(lines)


def _percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value:+.2f}%"


def _number(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


def _sessions(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1f} phiên"


def _money(value: float | None) -> str:
    return "N/A" if value is None else f"{value:,.0f} VND"


def _integer(value: int | None) -> str:
    return "N/A" if value is None else str(value)


def _validation(run: BacktestRun) -> str:
    return run.validation_status.value.replace("_", "-")


def _config(config: Mapping[str, object], key: str) -> str:
    value = config.get(key)
    return "N/A — chưa lưu" if value in (None, "") else str(value)


def _rate(config: Mapping[str, object], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, (int, float)):
        return "N/A — chưa lưu"
    return f"{value * 100:.2f}%"


def _settlement(config: Mapping[str, object]) -> str:
    value = config.get("settlement_days")
    return "N/A — chưa có quy ước" if not isinstance(value, int) else f"T+{value} phiên"


def _signals_only(run: BacktestRun) -> bool:
    return run.config.get("execution_mode") == "SIGNALS_ONLY"
