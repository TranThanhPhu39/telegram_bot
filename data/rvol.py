"""Time-matched intraday relative-volume calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from typing import Sequence

from data.models import OHLCVBar


VIETNAM_TIMEZONE = timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")


@dataclass(frozen=True, slots=True)
class IntradayRvolPoint:
    """RVOL observation aligned to one current-session minute."""

    timestamp: int
    cumulative_volume: float
    historical_average_cumulative_volume: float
    historical_session_count: int
    rvol: float | None


def time_matched_rvol(
    current_session: Sequence[OHLCVBar],
    historical_sessions: Sequence[Sequence[OHLCVBar]],
) -> tuple[IntradayRvolPoint, ...]:
    """Compare today's cumulative volume with prior sessions at the same time.

    Each historical value is its cumulative volume through the current local
    minute (not its full-day volume). Historical sessions must have unique local
    dates strictly before the current session, making future-session leakage an
    input error. If the historical average is zero, ``rvol`` is unavailable.
    """
    current, current_date, symbol = _validate_session(current_session, "current")
    if not historical_sessions:
        raise ValueError("at least one historical session is required")

    histories: list[tuple[OHLCVBar, ...]] = []
    historical_dates: set[date] = set()
    for index, session in enumerate(historical_sessions):
        checked, session_date, session_symbol = _validate_session(
            session, f"historical session {index}"
        )
        if session_symbol != symbol:
            raise ValueError("all sessions must use the same symbol")
        if session_date >= current_date:
            raise ValueError(
                "historical sessions must be strictly before the current session"
            )
        if session_date in historical_dates:
            raise ValueError("historical session dates must be unique")
        historical_dates.add(session_date)
        histories.append(checked)

    historical_curves = [_cumulative_curve(session) for session in histories]
    current_cumulative = 0.0
    result: list[IntradayRvolPoint] = []
    for bar in current:
        current_cumulative += bar.volume
        minute = _local_minute(bar.timestamp)
        historical_values = [
            _cumulative_at_or_before(curve, minute) for curve in historical_curves
        ]
        historical_average = sum(historical_values) / len(historical_values)
        rvol = (
            None
            if historical_average == 0.0
            else current_cumulative / historical_average
        )
        result.append(
            IntradayRvolPoint(
                timestamp=bar.timestamp,
                cumulative_volume=current_cumulative,
                historical_average_cumulative_volume=historical_average,
                historical_session_count=len(histories),
                rvol=rvol,
            )
        )
    return tuple(result)


def _validate_session(
    bars: Sequence[OHLCVBar], label: str
) -> tuple[tuple[OHLCVBar, ...], date, str]:
    checked = tuple(bars)
    if not checked:
        raise ValueError(f"{label} must not be empty")

    first = checked[0]
    if not isinstance(first, OHLCVBar):
        raise TypeError("RVOL sessions accept only OHLCVBar values")
    session_date = _local_datetime(first.timestamp).date()
    symbol = first.symbol
    previous_timestamp: int | None = None
    for bar in checked:
        if not isinstance(bar, OHLCVBar):
            raise TypeError("RVOL sessions accept only OHLCVBar values")
        if bar.symbol != symbol:
            raise ValueError(f"{label} must contain one symbol")
        if bar.timeframe != "ONE_MINUTE":
            raise ValueError("RVOL requires ONE_MINUTE bars")
        if _local_datetime(bar.timestamp).date() != session_date:
            raise ValueError(f"{label} must contain one local trading date")
        if bar.timestamp % 60 != 0:
            raise ValueError("RVOL bar timestamps must align to minute boundaries")
        if previous_timestamp is not None and bar.timestamp <= previous_timestamp:
            raise ValueError(f"{label} bars must be strictly chronological")
        if not isfinite(bar.volume) or bar.volume < 0:
            raise ValueError("RVOL volume must be finite and non-negative")
        previous_timestamp = bar.timestamp
    return checked, session_date, symbol


def _cumulative_curve(session: Sequence[OHLCVBar]) -> tuple[tuple[int, float], ...]:
    cumulative = 0.0
    curve: list[tuple[int, float]] = []
    for bar in session:
        cumulative += bar.volume
        curve.append((_local_minute(bar.timestamp), cumulative))
    return tuple(curve)


def _cumulative_at_or_before(
    curve: Sequence[tuple[int, float]], minute: int
) -> float:
    cumulative = 0.0
    for curve_minute, curve_value in curve:
        if curve_minute > minute:
            break
        cumulative = curve_value
    return cumulative


def _local_datetime(timestamp: int) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=VIETNAM_TIMEZONE)


def _local_minute(timestamp: int) -> int:
    local = _local_datetime(timestamp)
    return local.hour * 60 + local.minute
