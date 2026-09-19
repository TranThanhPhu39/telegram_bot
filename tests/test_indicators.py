"""Tests for Phase 10 technical indicators and no-look-ahead behavior."""

import pytest

from data.indicators import (
    atr,
    atr14,
    breakout_levels,
    daily_average_volume,
    ema,
    ema20,
    ema50,
    relative_strength_vs_benchmark,
    rsi,
    rsi14,
)
from data.models import OHLCVBar


def bars(
    closes: list[float],
    *,
    symbol: str = "FPT",
    timeframe: str = "ONE_DAY",
    volumes: list[float] | None = None,
) -> list[OHLCVBar]:
    volumes = volumes or [100.0 + index for index in range(len(closes))]
    return [
        OHLCVBar(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=1_000 + index * 60,
            open=close,
            high=close + 1.0,
            low=max(close - 1.0, 0.5),
            close=close,
            volume=volumes[index],
        )
        for index, close in enumerate(closes)
    ]


def test_ema_uses_sma_seed_then_recursive_updates() -> None:
    result = ema(bars([1.0, 2.0, 3.0, 4.0, 5.0]), 3)
    assert result == (None, None, 2.0, 3.0, 4.0)


def test_named_ema_periods_have_expected_warmup() -> None:
    sample = bars([float(value) for value in range(1, 56)])
    assert ema20(sample)[18] is None
    assert ema20(sample)[19] == pytest.approx(10.5)
    assert ema50(sample)[48] is None
    assert ema50(sample)[49] == pytest.approx(25.5)


def test_rsi_wilder_values_and_flat_market() -> None:
    sample = bars([1.0, 2.0, 3.0, 2.0, 4.0, 3.0])
    result = rsi(sample, 3)
    assert result[:3] == (None, None, None)
    assert result[3] == pytest.approx(66.6666667)
    assert result[4] == pytest.approx(83.3333333)
    assert result[5] == pytest.approx(60.6060606)
    assert rsi(bars([5.0] * 4), 3)[3] == 50.0
    assert rsi14(bars([float(value) for value in range(1, 16)]))[14] == 100.0


def test_atr_uses_true_range_and_wilder_smoothing() -> None:
    sample = bars([10.0, 14.0, 13.0, 18.0])
    result = atr(sample, 3)
    assert result == (None, None, pytest.approx(3.0), pytest.approx(4.0))
    assert atr14(bars([10.0] * 14))[13] == 2.0


def test_daily_average_volume_excludes_current_bar() -> None:
    sample = bars([10.0] * 5, volumes=[10.0, 20.0, 30.0, 1000.0, 50.0])
    result = daily_average_volume(sample, 3)
    assert result == (None, None, None, 20.0, 350.0)

    changed_current = bars(
        [10.0] * 5, volumes=[10.0, 20.0, 30.0, 9999.0, 50.0]
    )
    assert daily_average_volume(changed_current, 3)[3] == result[3]


def test_daily_average_volume_requires_daily_bars() -> None:
    with pytest.raises(ValueError, match="ONE_DAY"):
        daily_average_volume(bars([10.0], timeframe="ONE_MINUTE"), 1)


def test_relative_strength_uses_aligned_same_lookback_returns() -> None:
    stock = bars([100.0, 110.0, 121.0])
    benchmark = bars([200.0, 210.0, 220.0], symbol="VNINDEX")
    result = relative_strength_vs_benchmark(stock, benchmark, 2)
    assert result == (None, None, pytest.approx(11.0))

    misaligned = bars([200.0, 210.0, 220.0], symbol="VNINDEX")
    misaligned[1] = OHLCVBar(
        symbol="VNINDEX",
        timeframe="ONE_DAY",
        timestamp=1_061,
        open=210.0,
        high=211.0,
        low=209.0,
        close=210.0,
        volume=101.0,
    )
    with pytest.raises(ValueError, match="timestamps"):
        relative_strength_vs_benchmark(stock, misaligned, 2)


def test_breakout_levels_exclude_current_bar() -> None:
    sample = bars([10.0, 12.0, 11.0, 50.0])
    result = breakout_levels(sample, 3)
    assert result[:3] == (None, None, None)
    assert result[3] is not None
    assert result[3].resistance == 13.0
    assert result[3].support == 9.0


def test_indicator_input_validation() -> None:
    with pytest.raises(ValueError, match="positive"):
        ema(bars([1.0]), 0)
    with pytest.raises(TypeError, match="integer"):
        ema(bars([1.0]), True)
    duplicate_time = bars([1.0, 2.0])
    duplicate_time[1] = OHLCVBar(
        symbol="FPT",
        timeframe="ONE_DAY",
        timestamp=duplicate_time[0].timestamp,
        open=2.0,
        high=3.0,
        low=1.0,
        close=2.0,
        volume=100.0,
    )
    with pytest.raises(ValueError, match="chronological"):
        ema(duplicate_time, 1)
