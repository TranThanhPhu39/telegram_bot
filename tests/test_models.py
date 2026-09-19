"""Tests for provider-independent market-data models."""

from dataclasses import FrozenInstanceError

import pytest

from data.models import OHLCVBar


def make_bar() -> OHLCVBar:
    return OHLCVBar(
        symbol="FPT",
        timeframe="ONE_DAY",
        timestamp=1_789_787_719,
        open=100.0,
        high=105.0,
        low=99.0,
        close=103.0,
        volume=1_250_000.0,
    )


def test_ohlcv_bar_preserves_normalized_values() -> None:
    bar = make_bar()

    assert bar.symbol == "FPT"
    assert bar.timeframe == "ONE_DAY"
    assert bar.timestamp == 1_789_787_719
    assert (bar.open, bar.high, bar.low, bar.close) == (100.0, 105.0, 99.0, 103.0)
    assert bar.volume == 1_250_000.0


def test_ohlcv_bar_is_immutable_and_slotted() -> None:
    bar = make_bar()

    with pytest.raises(FrozenInstanceError):
        bar.close = 104.0  # type: ignore[misc]

    assert not hasattr(bar, "__dict__")
