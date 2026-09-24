"""Performance analytics derived from dated portfolio equity and closed trades."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import fmean, pstdev
from typing import Sequence

from backtest.execution import ExecutionResult
from data.models import OHLCVBar


MIN_RISK_OBSERVATIONS = 30


@dataclass(frozen=True, slots=True)
class PerformanceAnalytics:
    total_return_percent: float | None
    cagr_percent: float | None
    max_drawdown_percent: float | None
    sharpe_ratio: float | None
    sortino_ratio: float | None
    calmar_ratio: float | None
    win_rate_percent: float
    average_return_percent: float | None
    profit_factor: float | None
    expectancy_percent: float | None
    average_win_percent: float | None
    average_loss_percent: float | None
    payoff_ratio: float | None
    best_trade_percent: float | None
    worst_trade_percent: float | None
    average_holding_sessions: float | None
    longest_losing_streak: int
    exposure_percent: float | None
    trades_per_year: float | None
    benchmark_return_percent: float | None
    benchmark_max_drawdown_percent: float | None
    excess_return_percent: float | None
    benchmark_start_timestamp: int | None
    benchmark_end_timestamp: int | None


def calculate_performance_analytics(
    execution: ExecutionResult,
    benchmark: Sequence[OHLCVBar],
) -> PerformanceAnalytics:
    curve = execution.equity_curve
    trades = execution.trades
    values = [point.equity for point in curve]
    has_trades = bool(trades)
    total_return = (
        (values[-1] / execution.initial_capital - 1.0) * 100.0
        if values and has_trades else None
    )
    drawdown = max_drawdown_percent(values) if values and has_trades else None
    duration_days = (curve[-1].timestamp - curve[0].timestamp) / 86_400 if len(curve) >= 2 else 0.0
    years = duration_days / 365.25
    cagr = None
    if total_return is not None and duration_days >= 1 and values[-1] > 0:
        cagr = ((values[-1] / execution.initial_capital) ** (1.0 / years) - 1.0) * 100.0

    returns = [right / left - 1.0 for left, right in zip(values, values[1:]) if left > 0]
    sharpe = sortino = None
    if has_trades and len(returns) >= MIN_RISK_OBSERVATIONS:
        deviation = pstdev(returns)
        sharpe = None if deviation == 0 else fmean(returns) / deviation * sqrt(252)
        downside = [min(value, 0.0) for value in returns]
        downside_deviation = sqrt(fmean(value * value for value in downside))
        sortino = None if downside_deviation == 0 else fmean(returns) / downside_deviation * sqrt(252)
    calmar = None if cagr is None or drawdown in (None, 0.0) else cagr / abs(drawdown)

    net_returns = [trade.net_return_percent for trade in trades]
    wins = [value for value in net_returns if value > 0]
    losses = [value for value in net_returns if value < 0]
    realized_gains = sum(trade.realized_pnl for trade in trades if trade.realized_pnl > 0)
    realized_losses = abs(sum(trade.realized_pnl for trade in trades if trade.realized_pnl < 0))
    profit_factor = None if realized_losses == 0 else realized_gains / realized_losses
    average_win = fmean(wins) if wins else None
    average_loss = fmean(losses) if losses else None
    payoff = (
        average_win / abs(average_loss)
        if average_win is not None and average_loss not in (None, 0.0) else None
    )
    benchmark_return, benchmark_drawdown, benchmark_start, benchmark_end = _benchmark(
        benchmark,
        None if not curve else curve[0].timestamp,
        None if not curve else curve[-1].timestamp,
    )
    excess = (
        total_return - benchmark_return
        if total_return is not None and benchmark_return is not None else None
    )
    return PerformanceAnalytics(
        total_return, cagr, drawdown, sharpe, sortino, calmar,
        len(wins) / len(trades) * 100.0 if trades else 0.0,
        fmean(net_returns) if net_returns else None,
        profit_factor,
        fmean(net_returns) if net_returns else None,
        average_win, average_loss, payoff,
        max(net_returns) if net_returns else None,
        min(net_returns) if net_returns else None,
        fmean(trade.holding_sessions for trade in trades) if trades else None,
        _longest_losing_streak(net_returns),
        fmean(point.exposure_percent for point in curve) if curve else None,
        len(trades) / years if trades and duration_days >= 1 else None,
        benchmark_return, benchmark_drawdown, excess,
        benchmark_start, benchmark_end,
    )


def max_drawdown_percent(values: Sequence[float]) -> float | None:
    if not values:
        return None
    peak = values[0]
    worst = 0.0
    for value in values:
        if value <= 0:
            raise ValueError("equity values must be positive")
        peak = max(peak, value)
        worst = min(worst, value / peak - 1.0)
    return worst * 100.0


def _benchmark(
    bars: Sequence[OHLCVBar], start_timestamp: int | None, end_timestamp: int | None,
) -> tuple[float | None, float | None, int | None, int | None]:
    if start_timestamp is None or end_timestamp is None:
        return None, None, None, None
    aligned = tuple(
        bar for bar in bars
        if bar.symbol == "VNINDEX" and bar.timeframe == "ONE_DAY"
        and start_timestamp <= bar.timestamp <= end_timestamp
    )
    if len(aligned) < 2:
        return None, None, None, None
    if any(left.timestamp >= right.timestamp for left, right in zip(aligned, aligned[1:])):
        raise ValueError("benchmark bars must be strictly chronological")
    values = [aligned[0].open, *(bar.close for bar in aligned)]
    return (
        (aligned[-1].close / aligned[0].open - 1.0) * 100.0,
        max_drawdown_percent(values),
        aligned[0].timestamp,
        aligned[-1].timestamp,
    )


def _longest_losing_streak(returns: Sequence[float]) -> int:
    longest = current = 0
    for value in returns:
        current = current + 1 if value < 0 else 0
        longest = max(longest, current)
    return longest
