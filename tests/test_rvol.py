"""Tests for time-matched intraday RVOL and look-ahead prevention."""

from datetime import datetime, timedelta, timezone

import pytest

from data.models import OHLCVBar
from data.rvol import time_matched_rvol


VIETNAM = timezone(timedelta(hours=7))


def session(
    day: int,
    minute_volumes: list[tuple[int, float]],
    *,
    symbol: str = "FPT",
) -> list[OHLCVBar]:
    result = []
    for minute, volume in minute_volumes:
        local = datetime(2026, 9, day, 9, 0, tzinfo=VIETNAM) + timedelta(
            minutes=minute
        )
        result.append(
            OHLCVBar(
                symbol=symbol,
                timeframe="ONE_MINUTE",
                timestamp=int(local.timestamp()),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=volume,
            )
        )
    return result


def test_rvol_uses_cumulative_volume_at_same_local_time() -> None:
    current = session(18, [(0, 100.0), (1, 200.0), (2, 300.0)])
    history_a = session(16, [(0, 50.0), (1, 50.0), (2, 100.0)])
    history_b = session(17, [(0, 100.0), (1, 100.0), (2, 200.0)])

    result = time_matched_rvol(current, [history_a, history_b])

    assert [point.cumulative_volume for point in result] == [100.0, 300.0, 600.0]
    assert [point.historical_average_cumulative_volume for point in result] == [
        75.0,
        150.0,
        300.0,
    ]
    assert [point.rvol for point in result] == pytest.approx(
        [100.0 / 75.0, 2.0, 2.0]
    )
    assert all(point.historical_session_count == 2 for point in result)


def test_missing_historical_minute_carries_prior_cumulative_volume() -> None:
    current = session(18, [(0, 40.0), (1, 60.0), (2, 100.0)])
    history = session(17, [(0, 25.0), (2, 75.0)])

    result = time_matched_rvol(current, [history])

    assert [point.historical_average_cumulative_volume for point in result] == [
        25.0,
        25.0,
        100.0,
    ]
    assert [point.rvol for point in result] == pytest.approx([1.6, 4.0, 2.0])


def test_zero_historical_baseline_returns_unavailable_rvol() -> None:
    result = time_matched_rvol(
        session(18, [(0, 10.0)]),
        [session(17, [(0, 0.0)])],
    )

    assert result[0].historical_average_cumulative_volume == 0.0
    assert result[0].rvol is None


def test_future_intraday_volumes_do_not_affect_earlier_points() -> None:
    current = session(18, [(0, 100.0), (1, 200.0)])
    base_history = session(17, [(0, 50.0), (1, 50.0), (2, 50.0)])
    changed_future = session(17, [(0, 50.0), (1, 50.0), (2, 50_000.0)])

    base = time_matched_rvol(current, [base_history])
    changed = time_matched_rvol(current, [changed_future])

    assert base == changed


def test_current_future_bars_do_not_change_prior_rvol_points() -> None:
    current_prefix = session(18, [(0, 100.0), (1, 200.0)])
    current_extended = session(18, [(0, 100.0), (1, 200.0), (2, 999_999.0)])
    history = session(17, [(0, 50.0), (1, 50.0), (2, 50.0)])

    prefix_result = time_matched_rvol(current_prefix, [history])
    extended_result = time_matched_rvol(current_extended, [history])

    assert extended_result[:2] == prefix_result


def test_rejects_same_day_or_future_historical_sessions() -> None:
    current = session(18, [(0, 100.0)])

    with pytest.raises(ValueError, match="strictly before"):
        time_matched_rvol(current, [session(18, [(0, 50.0)])])
    with pytest.raises(ValueError, match="strictly before"):
        time_matched_rvol(current, [session(19, [(0, 50.0)])])


def test_rejects_duplicate_dates_symbols_and_invalid_sessions() -> None:
    current = session(18, [(0, 100.0)])
    history = session(17, [(0, 50.0)])

    with pytest.raises(ValueError, match="unique"):
        time_matched_rvol(current, [history, history])
    with pytest.raises(ValueError, match="same symbol"):
        time_matched_rvol(current, [session(17, [(0, 50.0)], symbol="ACB")])
    with pytest.raises(ValueError, match="at least one"):
        time_matched_rvol(current, [])
    with pytest.raises(ValueError, match="must not be empty"):
        time_matched_rvol([], [history])


def test_requires_one_minute_chronological_minute_aligned_bars() -> None:
    current = session(18, [(0, 100.0)])
    history = session(17, [(0, 50.0)])
    wrong_timeframe = [
        OHLCVBar(
            symbol="FPT",
            timeframe="ONE_DAY",
            timestamp=history[0].timestamp,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=50.0,
        )
    ]

    with pytest.raises(ValueError, match="ONE_MINUTE"):
        time_matched_rvol(current, [wrong_timeframe])
    with pytest.raises(ValueError, match="chronological"):
        time_matched_rvol(current + current, [history])

    unaligned = session(17, [(0, 50.0)])
    original = unaligned[0]
    unaligned[0] = OHLCVBar(
        symbol=original.symbol,
        timeframe=original.timeframe,
        timestamp=original.timestamp + 1,
        open=original.open,
        high=original.high,
        low=original.low,
        close=original.close,
        volume=original.volume,
    )
    with pytest.raises(ValueError, match="minute boundaries"):
        time_matched_rvol(current, [unaligned])
