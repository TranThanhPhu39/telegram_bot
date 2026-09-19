"""Backtest adapter that reuses the production SignalEngine unchanged."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable

from strategy.signal_engine import SignalEngine, SignalInputs, SignalState


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    symbol: str
    entry_timestamp: int
    entry_price: float
    exit_timestamp: int
    exit_price: float
    return_percent: float


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    start_timestamp: int
    end_timestamp: int
    observation_count: int
    trade_count: int
    win_rate_percent: float
    average_return_percent: float
    max_drawdown_percent: float
    profit_factor: float | None
    open_position_count: int


def run_backtest(
    engine: SignalEngine, observations: Iterable[SignalInputs]
) -> tuple[tuple[BacktestTrade, ...], PerformanceReport]:
    """Replay chronological inputs through the shared live SignalEngine."""
    if not isinstance(engine, SignalEngine):
        raise TypeError("engine must be a SignalEngine")
    inputs = tuple(observations)
    if not inputs:
        raise ValueError("backtest requires at least one observation")
    if any(not isinstance(item, SignalInputs) for item in inputs):
        raise TypeError("observations must contain SignalInputs values")
    if any(inputs[index].timestamp > inputs[index + 1].timestamp for index in range(len(inputs) - 1)):
        raise ValueError("backtest observations must be globally chronological")

    positions: dict[str, tuple[int, float]] = {}
    trades: list[BacktestTrade] = []
    for item in inputs:
        event = engine.evaluate(item)
        if event is None:
            continue
        if event.to_state is SignalState.ACTIVE:
            positions.setdefault(event.symbol, (event.occurred_at, event.price))
        elif event.to_state is SignalState.EXIT:
            opened = positions.pop(event.symbol, None)
            if opened is None:
                continue
            entry_timestamp, entry_price = opened
            trade_return = (event.price / entry_price - 1.0) * 100.0
            trades.append(
                BacktestTrade(
                    event.symbol,
                    entry_timestamp,
                    entry_price,
                    event.occurred_at,
                    event.price,
                    trade_return,
                )
            )

    report = calculate_performance(
        trades,
        start_timestamp=inputs[0].timestamp,
        end_timestamp=inputs[-1].timestamp,
        observation_count=len(inputs),
        open_position_count=len(positions),
    )
    return tuple(trades), report


def calculate_performance(
    trades: Iterable[BacktestTrade],
    *,
    start_timestamp: int,
    end_timestamp: int,
    observation_count: int,
    open_position_count: int = 0,
) -> PerformanceReport:
    checked = tuple(trades)
    if start_timestamp <= 0 or end_timestamp < start_timestamp:
        raise ValueError("invalid backtest time range")
    if observation_count <= 0 or open_position_count < 0:
        raise ValueError("invalid backtest counts")
    returns = [trade.return_percent for trade in checked]
    if not all(isfinite(value) for value in returns):
        raise ValueError("trade returns must be finite")
    wins = sum(value > 0 for value in returns)
    win_rate = wins / len(returns) * 100.0 if returns else 0.0
    average_return = sum(returns) / len(returns) if returns else 0.0
    gains = sum(value for value in returns if value > 0)
    losses = abs(sum(value for value in returns if value < 0))
    profit_factor = None if losses == 0.0 else gains / losses

    equity = peak = 1.0
    max_drawdown = 0.0
    for value in returns:
        equity *= 1.0 + value / 100.0
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak * 100.0)
    return PerformanceReport(
        start_timestamp,
        end_timestamp,
        observation_count,
        len(checked),
        win_rate,
        average_return,
        max_drawdown,
        profit_factor,
        open_position_count,
    )


def format_performance(report: PerformanceReport) -> str:
    factor = "N/A (không có giao dịch lỗ)" if report.profit_factor is None else f"{report.profit_factor:.2f}"
    return (
        f"Backtest: {report.trade_count} giao dịch\n"
        f"Win rate: {report.win_rate_percent:.2f}%\n"
        f"Lợi nhuận TB: {report.average_return_percent:.2f}%\n"
        f"Max drawdown: {report.max_drawdown_percent:.2f}%\n"
        f"Profit factor: {factor}\n"
        f"Vị thế chưa đóng: {report.open_position_count}"
    )
