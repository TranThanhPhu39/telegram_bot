"""Offline strategy-evaluation orchestration.

P3-P4 intentionally stop before order execution. Their persisted strategy results
prove historical reuse and chronology; trade and performance metrics remain
unavailable until the execution simulator is introduced in P5.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import sqlite3
import time
from uuid import uuid4

from backtest.analytics import PerformanceAnalytics, calculate_performance_analytics
from backtest.adapters import (
    ASMFHistoricalAdapter,
    CL1HistoricalAdapter,
    HistoricalDataPort,
    HistoricalEvaluation,
)
from backtest.models import BacktestRun, BacktestValidationStatus
from backtest.repository import save_backtest_run
from backtest.execution import BacktestExecutionConfig, ExecutionResult, simulate_execution


VIETNAM_TIMEZONE = timezone(timedelta(hours=7))


@dataclass(frozen=True, slots=True)
class StrategyBacktestResult:
    run: BacktestRun
    evaluations: tuple[HistoricalEvaluation, ...]
    execution: ExecutionResult | None = None
    analytics: PerformanceAnalytics | None = None


def run_strategy_backtest(
    *,
    strategy: str,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    data_port: HistoricalDataPort,
    connection: sqlite3.Connection,
    initial_capital: float = 500_000_000.0,
    run_id: str | None = None,
    now: Callable[[], float] = time.time,
    cl1_adapter: CL1HistoricalAdapter | None = None,
    asmf_adapter: ASMFHistoricalAdapter | None = None,
    execution_config: BacktestExecutionConfig | None = None,
) -> StrategyBacktestResult:
    """Evaluate a caller-supplied universe and optionally execute it chronologically."""
    normalized_strategy = strategy.strip().upper()
    if normalized_strategy not in {"CL1", "ASMF"}:
        raise ValueError("strategy must be CL1 or ASMF")
    checked_symbols = tuple(symbol.strip().upper() for symbol in symbols)
    if not checked_symbols or any(not symbol or not symbol.isalnum() for symbol in checked_symbols):
        raise ValueError("symbols must contain alphanumeric tickers")
    if len(set(checked_symbols)) != len(checked_symbols):
        raise ValueError("symbols must not contain duplicates")
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    if not hasattr(data_port, "daily_bars"):
        raise TypeError("data_port must provide daily_bars(symbol)")
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be a sqlite3.Connection")

    started_at = int(now())
    adapter = (
        cl1_adapter or CL1HistoricalAdapter()
        if normalized_strategy == "CL1"
        else asmf_adapter or ASMFHistoricalAdapter(connection, data_port)
    )
    evaluations = tuple(
        adapter.evaluate(
            data_port.daily_bars(symbol), start_date=start_date, end_date=end_date
        )
        for symbol in checked_symbols
    )
    actions = Counter(
        decision.action.value
        for evaluation in evaluations
        for decision in evaluation.decisions
    )
    decision_count = sum(actions.values())
    completed_at = max(started_at, int(now()))
    if execution_config is not None:
        histories = {
            symbol: _range_bars(data_port.daily_bars(symbol), start_date, end_date)
            for symbol in checked_symbols
        }
        decision_map = {
            evaluation.symbol: evaluation.decisions for evaluation in evaluations
        }
        execution = simulate_execution(histories, decision_map, execution_config)
        analytics = calculate_performance_analytics(
            execution, data_port.daily_bars("VNINDEX")
        )
        actual_start = _bar_date(execution.equity_curve[0].timestamp)
        actual_end = _bar_date(execution.equity_curve[-1].timestamp)
        config = {
            "schema_version": 1,
            "execution_mode": "PORTFOLIO",
            "evaluator": f"strategy.technical_strategies.evaluate_{normalized_strategy.lower()}",
            "minimum_history": 200,
            "decision_count": decision_count,
            "action_counts": dict(sorted(actions.items())),
            "entry_mode": execution_config.entry_mode.value,
            "commission_rate": execution_config.commission_rate,
            "sell_tax_rate": execution_config.sell_tax_rate,
            "slippage_rate": execution_config.slippage_rate,
            "lot_size": execution_config.lot_size,
            "settlement_days": execution_config.settlement_sessions,
            "settlement_unit": "TRADING_SESSIONS",
            "allocation_mode": execution_config.allocation_mode.value,
            "unfilled_order_count": execution.unfilled_order_count,
            "total_explicit_costs": sum(
                fill.commission + fill.sell_tax for fill in execution.fills
            ),
            "total_slippage_cost": sum(fill.slippage_cost for fill in execution.fills),
            "benchmark_start_timestamp": analytics.benchmark_start_timestamp,
            "benchmark_end_timestamp": analytics.benchmark_end_timestamp,
        }
        warnings = [
            "IN-SAMPLE ONLY; chưa có walk-forward/out-of-sample validation.",
            "Settlement là số phiên giao dịch do người chạy cấu hình; repo không tự nhận định T+2/T+2.5.",
        ]
        if execution.open_positions:
            warnings.append(
                f"Còn {len(execution.open_positions)} vị thế mở được mark-to-market, chưa phát sinh chi phí thoát."
            )
        if not execution.trades:
            warnings.append("Không có giao dịch đóng; CAGR/Sharpe và trade-return metrics để N/A.")
        if normalized_strategy == "ASMF":
            warnings.append(
                "evaluate_asmf hiện không phát SELL; simulator không tự biến WATCH/BLOCKED thành exit."
            )
        run = BacktestRun(
            run_id=run_id or f"{normalized_strategy.lower()}-{uuid4().hex}",
            strategy=normalized_strategy, started_at=started_at,
            completed_at=completed_at, start_date=actual_start, end_date=actual_end,
            symbols=checked_symbols, initial_capital=execution_config.initial_capital,
            final_equity=execution.equity_curve[-1].equity,
            trade_count=len(execution.trades),
            open_position_count=len(execution.open_positions),
            validation_status=BacktestValidationStatus.IN_SAMPLE_ONLY,
            total_return_percent=analytics.total_return_percent,
            cagr_percent=analytics.cagr_percent,
            max_drawdown_percent=analytics.max_drawdown_percent,
            sharpe_ratio=analytics.sharpe_ratio,
            sortino_ratio=analytics.sortino_ratio,
            calmar_ratio=analytics.calmar_ratio,
            win_rate_percent=analytics.win_rate_percent,
            average_return_percent=analytics.average_return_percent,
            profit_factor=analytics.profit_factor,
            expectancy_percent=analytics.expectancy_percent,
            average_win_percent=analytics.average_win_percent,
            average_loss_percent=analytics.average_loss_percent,
            payoff_ratio=analytics.payoff_ratio,
            best_trade_percent=analytics.best_trade_percent,
            worst_trade_percent=analytics.worst_trade_percent,
            average_holding_sessions=analytics.average_holding_sessions,
            longest_losing_streak=analytics.longest_losing_streak,
            exposure_percent=analytics.exposure_percent,
            trades_per_year=analytics.trades_per_year,
            benchmark_return_percent=analytics.benchmark_return_percent,
            benchmark_max_drawdown_percent=analytics.benchmark_max_drawdown_percent,
            excess_return_percent=analytics.excess_return_percent,
            config=config, warnings=tuple(warnings), created_at=completed_at,
        )
        save_backtest_run(connection, run)
        return StrategyBacktestResult(run, evaluations, execution, analytics)

    run = BacktestRun(
        run_id=run_id or f"{normalized_strategy.lower()}-{uuid4().hex}",
        strategy=normalized_strategy,
        started_at=started_at,
        completed_at=completed_at,
        start_date=start_date,
        end_date=end_date,
        symbols=checked_symbols,
        initial_capital=initial_capital,
        final_equity=None,
        trade_count=0,
        open_position_count=0,
        validation_status=BacktestValidationStatus.IN_SAMPLE_ONLY,
        config={
            "schema_version": 1,
            "execution_mode": "SIGNALS_ONLY",
            "evaluator": f"strategy.technical_strategies.evaluate_{normalized_strategy.lower()}",
            "minimum_history": 200,
            "decision_count": decision_count,
            "action_counts": dict(sorted(actions.items())),
        },
        warnings=(
            f"P3/P4 chỉ đánh giá tín hiệu {normalized_strategy} theo lịch sử; chưa mô phỏng khớp lệnh.",
            "Trade, return, chi phí, settlement, equity và benchmark chờ execution simulator P5.",
            *(("evaluate_asmf hiện không phát SELL; không tự biến WATCH/BLOCKED thành exit.",)
              if normalized_strategy == "ASMF" else ()),
        ),
        created_at=completed_at,
    )
    save_backtest_run(connection, run)
    return StrategyBacktestResult(run, evaluations)


def _range_bars(
    bars: Sequence, start_date: date, end_date: date,
) -> tuple:
    selected = tuple(
        bar for bar in bars if start_date <= _bar_date(bar.timestamp) <= end_date
    )
    if not selected:
        raise ValueError("execution history has no bars in the requested date range")
    return selected


def _bar_date(timestamp: int) -> date:
    return datetime.fromtimestamp(timestamp, VIETNAM_TIMEZONE).date()
