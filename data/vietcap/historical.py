"""Validation and normalization for Vietcap historical chart responses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

from data.models import OHLCVBar
from data.vietcap.rest import (
    VietcapTimeFrame,
    normalize_stock_symbol,
    normalize_time_frame,
)

_COLUMNS = ("t", "o", "h", "l", "c", "v")


class VietcapHistoricalDataError(ValueError):
    """Raised when a gap-chart payload cannot be normalized safely."""


def _column(row: Mapping[str, Any], name: str) -> Sequence[Any]:
    value = row.get(name)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise VietcapHistoricalDataError(f"gap-chart column {name!r} must be an array")
    return value


def _finite_number(value: object, field: str, index: int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VietcapHistoricalDataError(f"{field}[{index}] must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise VietcapHistoricalDataError(f"{field}[{index}] must be finite")
    return normalized


def _timestamp(value: object, index: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise VietcapHistoricalDataError(f"t[{index}] must be a Unix-seconds string")
    raw = str(value)
    if not raw.isascii() or not raw.isdecimal():
        raise VietcapHistoricalDataError(f"t[{index}] must be a Unix-seconds string")
    timestamp = int(raw)
    if timestamp <= 0:
        raise VietcapHistoricalDataError(f"t[{index}] must be positive")
    return timestamp


def normalize_gap_chart(
    payload: object,
    *,
    time_frame: VietcapTimeFrame | str,
) -> tuple[OHLCVBar, ...]:
    """Convert an observed Vietcap columnar response into immutable bars."""
    normalized_time_frame = normalize_time_frame(time_frame).value
    if not isinstance(payload, list):
        raise VietcapHistoricalDataError("gap-chart payload must be an array")

    bars: list[OHLCVBar] = []
    for row_index, row in enumerate(payload):
        if not isinstance(row, Mapping):
            raise VietcapHistoricalDataError(
                f"gap-chart row {row_index} must be an object"
            )
        try:
            symbol = normalize_stock_symbol(row["symbol"])
        except (KeyError, TypeError, ValueError) as exc:
            raise VietcapHistoricalDataError(
                f"gap-chart row {row_index} has an invalid symbol"
            ) from exc

        columns = {name: _column(row, name) for name in _COLUMNS}
        lengths = {len(column) for column in columns.values()}
        if len(lengths) != 1:
            raise VietcapHistoricalDataError(
                f"gap-chart row {row_index} columns must have equal lengths"
            )

        for index, values in enumerate(zip(*(columns[name] for name in _COLUMNS))):
            timestamp = _timestamp(values[0], index)
            open_price = _finite_number(values[1], "o", index)
            high_price = _finite_number(values[2], "h", index)
            low_price = _finite_number(values[3], "l", index)
            close_price = _finite_number(values[4], "c", index)
            volume = _finite_number(values[5], "v", index)
            if min(open_price, high_price, low_price, close_price) <= 0:
                raise VietcapHistoricalDataError(
                    f"OHLC prices at index {index} must be positive"
                )
            if high_price < max(open_price, low_price, close_price):
                raise VietcapHistoricalDataError(
                    f"h[{index}] must be the highest OHLC price"
                )
            if low_price > min(open_price, high_price, close_price):
                raise VietcapHistoricalDataError(
                    f"l[{index}] must be the lowest OHLC price"
                )
            if volume < 0:
                raise VietcapHistoricalDataError(f"v[{index}] must be non-negative")
            bars.append(
                OHLCVBar(
                    symbol=symbol,
                    timeframe=normalized_time_frame,
                    timestamp=timestamp,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    volume=volume,
                )
            )
    return tuple(bars)
