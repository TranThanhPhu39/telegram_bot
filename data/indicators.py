"""Deterministic, provider-independent technical indicators.

All returned series align one-to-one with their input bars. ``None`` denotes a
warm-up position with insufficient completed history.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

from data.models import OHLCVBar


IndicatorSeries = tuple[float | None, ...]


@dataclass(frozen=True, slots=True)
class BreakoutLevel:
    """Resistance/support from completed bars preceding the current bar."""

    resistance: float
    support: float


def ema(bars: Sequence[OHLCVBar], period: int) -> IndicatorSeries:
    """Return close-price EMA seeded by the first ``period``-bar SMA."""
    checked = _validate_bars(bars)
    period = _validate_period(period)
    result: list[float | None] = [None] * len(checked)
    if len(checked) < period:
        return tuple(result)

    value = sum(bar.close for bar in checked[:period]) / period
    result[period - 1] = value
    multiplier = 2.0 / (period + 1.0)
    for index in range(period, len(checked)):
        value = (checked[index].close - value) * multiplier + value
        result[index] = value
    return tuple(result)


def rsi(bars: Sequence[OHLCVBar], period: int = 14) -> IndicatorSeries:
    """Return Wilder RSI using close-to-close changes."""
    checked = _validate_bars(bars)
    period = _validate_period(period)
    result: list[float | None] = [None] * len(checked)
    if len(checked) <= period:
        return tuple(result)

    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, period + 1):
        change = checked[index].close - checked[index - 1].close
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    result[period] = _rsi_value(average_gain, average_loss)

    for index in range(period + 1, len(checked)):
        change = checked[index].close - checked[index - 1].close
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period
        result[index] = _rsi_value(average_gain, average_loss)
    return tuple(result)


def atr(bars: Sequence[OHLCVBar], period: int = 14) -> IndicatorSeries:
    """Return Wilder ATR, including high-low as the first true range."""
    checked = _validate_bars(bars)
    period = _validate_period(period)
    result: list[float | None] = [None] * len(checked)
    if len(checked) < period:
        return tuple(result)

    true_ranges = [checked[0].high - checked[0].low]
    for index in range(1, len(checked)):
        bar = checked[index]
        previous_close = checked[index - 1].close
        true_ranges.append(
            max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        )

    value = sum(true_ranges[:period]) / period
    result[period - 1] = value
    for index in range(period, len(checked)):
        value = ((value * (period - 1)) + true_ranges[index]) / period
        result[index] = value
    return tuple(result)


def daily_average_volume(
    bars: Sequence[OHLCVBar], period: int = 20
) -> IndicatorSeries:
    """Return average volume of the preceding ``period`` completed daily bars."""
    checked = _validate_bars(bars, required_timeframe="ONE_DAY")
    period = _validate_period(period)
    result: list[float | None] = [None] * len(checked)
    rolling_sum = 0.0
    for index, bar in enumerate(checked):
        if index >= period:
            result[index] = rolling_sum / period
            rolling_sum -= checked[index - period].volume
        rolling_sum += bar.volume
    return tuple(result)


def relative_strength_vs_benchmark(
    stock_bars: Sequence[OHLCVBar],
    benchmark_bars: Sequence[OHLCVBar],
    period: int = 20,
) -> IndicatorSeries:
    """Return stock minus benchmark percentage return over the same lookback."""
    stock = _validate_bars(stock_bars)
    benchmark = _validate_bars(benchmark_bars)
    period = _validate_period(period)
    if len(stock) != len(benchmark):
        raise ValueError("stock and benchmark series must have equal length")
    if any(a.timestamp != b.timestamp for a, b in zip(stock, benchmark)):
        raise ValueError("stock and benchmark timestamps must align exactly")

    result: list[float | None] = [None] * len(stock)
    for index in range(period, len(stock)):
        stock_return = stock[index].close / stock[index - period].close - 1.0
        benchmark_return = (
            benchmark[index].close / benchmark[index - period].close - 1.0
        )
        result[index] = (stock_return - benchmark_return) * 100.0
    return tuple(result)


def breakout_levels(
    bars: Sequence[OHLCVBar], period: int = 20
) -> tuple[BreakoutLevel | None, ...]:
    """Return prior-period resistance and support, excluding the current bar."""
    checked = _validate_bars(bars)
    period = _validate_period(period)
    result: list[BreakoutLevel | None] = [None] * len(checked)
    for index in range(period, len(checked)):
        previous = checked[index - period : index]
        result[index] = BreakoutLevel(
            resistance=max(bar.high for bar in previous),
            support=min(bar.low for bar in previous),
        )
    return tuple(result)


def ema20(bars: Sequence[OHLCVBar]) -> IndicatorSeries:
    return ema(bars, 20)


def ema50(bars: Sequence[OHLCVBar]) -> IndicatorSeries:
    return ema(bars, 50)


def rsi14(bars: Sequence[OHLCVBar]) -> IndicatorSeries:
    return rsi(bars, 14)


def atr14(bars: Sequence[OHLCVBar]) -> IndicatorSeries:
    return atr(bars, 14)


def _rsi_value(average_gain: float, average_loss: float) -> float:
    if average_loss == 0.0:
        return 100.0 if average_gain > 0.0 else 50.0
    if average_gain == 0.0:
        return 0.0
    relative_strength = average_gain / average_loss
    return 100.0 - 100.0 / (1.0 + relative_strength)


def _validate_period(period: int) -> int:
    if not isinstance(period, int) or isinstance(period, bool):
        raise TypeError("period must be an integer")
    if period <= 0:
        raise ValueError("period must be positive")
    return period


def _validate_bars(
    bars: Sequence[OHLCVBar], required_timeframe: str | None = None
) -> tuple[OHLCVBar, ...]:
    checked = tuple(bars)
    previous_timestamp: int | None = None
    symbol: str | None = None
    timeframe: str | None = None
    for bar in checked:
        if not isinstance(bar, OHLCVBar):
            raise TypeError("indicators accept only OHLCVBar values")
        if symbol is None:
            symbol = bar.symbol
            timeframe = bar.timeframe
        elif bar.symbol != symbol or bar.timeframe != timeframe:
            raise ValueError("bars must share one symbol and timeframe")
        if required_timeframe is not None and bar.timeframe != required_timeframe:
            raise ValueError(f"bars must use {required_timeframe} timeframe")
        if previous_timestamp is not None and bar.timestamp <= previous_timestamp:
            raise ValueError("bars must be strictly chronological")
        values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
        if not all(isfinite(value) for value in values):
            raise ValueError("bar values must be finite")
        if min(bar.open, bar.high, bar.low, bar.close) <= 0 or bar.volume < 0:
            raise ValueError("bar prices must be positive and volume non-negative")
        if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
            raise ValueError("bar OHLC relationship is invalid")
        previous_timestamp = bar.timestamp
    return checked
