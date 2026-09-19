"""Tests for one-minute trade aggregation."""

import pytest

from data.candles import OneMinuteBarBuilder
from data.models import TradeTick


def tick(symbol: str, price: float, volume: float) -> TradeTick:
    return TradeTick(
        symbol=symbol,
        price=price,
        volume=volume,
        accumulated_volume=volume,
        accumulated_value=price * volume,
        high_price=None,
        low_price=None,
        open_price=None,
        average_price=None,
        reference_price=None,
        ceiling_price=None,
        floor_price=None,
        exchange_time=None,
        session=None,
    )


def test_builds_ohlcv_and_emits_only_after_next_minute() -> None:
    builder = OneMinuteBarBuilder()
    assert builder.update(tick("FPT", 100.0, 10.0), 125) is None
    assert builder.update(tick("FPT", 103.0, 20.0), 150) is None
    assert builder.update(tick("FPT", 99.0, 5.0), 179) is None

    completed = builder.update(tick("FPT", 102.0, 7.0), 180)

    assert completed is not None
    assert completed.symbol == "FPT"
    assert completed.timeframe == "ONE_MINUTE"
    assert completed.timestamp == 120
    assert (completed.open, completed.high, completed.low, completed.close) == (
        100.0,
        103.0,
        99.0,
        99.0,
    )
    assert completed.volume == 35.0
    assert builder.flush("fpt")[0].timestamp == 180


def test_tracks_symbols_independently_and_does_not_fill_gaps() -> None:
    builder = OneMinuteBarBuilder()
    builder.update(tick("FPT", 100.0, 1.0), 60)
    builder.update(tick("ACB", 20.0, 2.0), 121)

    completed = builder.update(tick("FPT", 105.0, 3.0), 300)

    assert completed is not None and completed.timestamp == 60
    assert [(bar.symbol, bar.timestamp) for bar in builder.flush()] == [
        ("ACB", 120),
        ("FPT", 300),
    ]
    assert builder.flush() == ()


def test_rejects_out_of_order_or_invalid_tick_input() -> None:
    builder = OneMinuteBarBuilder()
    builder.update(tick("FPT", 100.0, 1.0), 180)

    with pytest.raises(ValueError, match="out-of-order"):
        builder.update(tick("FPT", 99.0, 1.0), 119)
    with pytest.raises(ValueError, match="normalized"):
        OneMinuteBarBuilder().update(tick("fpt", 100.0, 1.0), 60)
    with pytest.raises(ValueError, match="price"):
        OneMinuteBarBuilder().update(tick("FPT", 0.0, 1.0), 60)
    with pytest.raises(ValueError, match="volume"):
        OneMinuteBarBuilder().update(tick("FPT", 1.0, -1.0), 60)
    with pytest.raises(TypeError, match="timestamp"):
        OneMinuteBarBuilder().update(tick("FPT", 1.0, 1.0), True)
