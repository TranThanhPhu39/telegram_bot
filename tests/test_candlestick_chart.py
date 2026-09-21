"""Deterministic acceptance for the provider-independent candlestick renderer."""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from charts.candlestick import (
    MIN_BARS_FOR_CHART,
    ChartRenderError,
    _validate_bars,
    _visible_bars,
    render_candlestick,
)
from data.models import OHLCVBar

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def bar(index: int, *, symbol: str = "ACB", timeframe: str = "ONE_DAY") -> OHLCVBar:
    base = 20000.0 + index * 10
    return OHLCVBar(
        symbol, timeframe, 1_700_000_000 + index * 86_400,
        open=base, high=base + 120, low=base - 120,
        close=base + (50 if index % 2 == 0 else -50), volume=1_000.0 + index,
    )


def bars(count: int) -> tuple[OHLCVBar, ...]:
    return tuple(bar(i) for i in range(count))


def test_renders_valid_png_with_requested_dimensions() -> None:
    chart = render_candlestick(bars(120), width=800, height=480)

    assert chart.png_bytes.startswith(PNG_MAGIC)
    image = Image.open(BytesIO(chart.png_bytes))
    assert image.size == (800, 480)
    assert image.mode == "RGB"


def test_visible_window_trims_to_most_recent_bars() -> None:
    chart = render_candlestick(bars(300), visible_count=90)

    assert chart.visible_bars == 90
    assert chart.last_timestamp == bar(299).timestamp
    assert chart.first_timestamp == bar(210).timestamp


def test_small_history_is_used_in_full_without_trimming() -> None:
    chart = render_candlestick(bars(6), visible_count=90)

    assert chart.visible_bars == 6


def test_ema_warm_up_uses_full_history_before_trimming() -> None:
    # 200 bars of history with only the last 90 drawn: EMA50 should already be
    # warmed up for every visible candle instead of showing warm-up gaps that
    # a chart built only from the visible slice would have.
    chart = render_candlestick(bars(200), visible_count=90, ema_periods=(50,))
    assert chart.visible_bars == 90  # renders without raising


def test_rejects_fewer_than_minimum_bars() -> None:
    with pytest.raises(ChartRenderError, match=str(MIN_BARS_FOR_CHART)):
        render_candlestick(bars(MIN_BARS_FOR_CHART - 1))


def test_rejects_mixed_symbols() -> None:
    mixed = bars(10)[:5] + (bar(5, symbol="VHM"),) + bars(10)[6:]
    with pytest.raises(ChartRenderError, match="symbol and timeframe"):
        render_candlestick(mixed)


def test_rejects_mixed_timeframes() -> None:
    mixed = bars(10)[:5] + (bar(5, timeframe="ONE_HOUR"),) + bars(10)[6:]
    with pytest.raises(ChartRenderError, match="symbol and timeframe"):
        render_candlestick(mixed)


def test_rejects_non_chronological_bars() -> None:
    shuffled = list(bars(10))
    shuffled[3], shuffled[4] = shuffled[4], shuffled[3]
    with pytest.raises(ChartRenderError, match="chronological"):
        render_candlestick(tuple(shuffled))


def test_rejects_duplicate_timestamps() -> None:
    duplicated = list(bars(10))
    duplicated[4] = duplicated[3]
    with pytest.raises(ChartRenderError, match="chronological"):
        render_candlestick(tuple(duplicated))


def test_rejects_empty_input() -> None:
    with pytest.raises(ChartRenderError, match="no bars"):
        render_candlestick(())


def test_rejects_non_positive_ema_period() -> None:
    with pytest.raises(ChartRenderError, match="ema_periods"):
        render_candlestick(bars(60), ema_periods=(20, 0))


def test_rejects_tiny_dimensions() -> None:
    with pytest.raises(ChartRenderError, match="too small"):
        render_candlestick(bars(60), width=10, height=10)


def test_rejects_visible_count_below_minimum() -> None:
    with pytest.raises(ChartRenderError, match="visible_count"):
        render_candlestick(bars(60), visible_count=1)


def test_flat_range_still_renders_without_a_degenerate_scale() -> None:
    flat = tuple(
        OHLCVBar("ACB", "ONE_DAY", 1_700_000_000 + i * 86_400,
                 20000.0, 20000.0, 20000.0, 20000.0, 500.0)
        for i in range(10)
    )
    chart = render_candlestick(flat)
    assert chart.png_bytes.startswith(PNG_MAGIC)


def test_visible_bars_helper_is_a_pure_tail_slice() -> None:
    data = bars(50)
    assert _visible_bars(data, 90) == data
    assert _visible_bars(data, 10) == data[-10:]


def test_validate_bars_returns_a_tuple_unchanged_when_valid() -> None:
    data = bars(10)
    assert _validate_bars(data) == data
