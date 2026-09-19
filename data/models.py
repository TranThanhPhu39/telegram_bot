"""Provider-independent normalized market-data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TradeTick:
    """Normalized latest-trade data without provider-specific types."""

    symbol: str
    price: float
    volume: float
    accumulated_volume: float
    accumulated_value: float
    high_price: float | None
    low_price: float | None
    open_price: float | None
    average_price: float | None
    reference_price: float | None
    ceiling_price: float | None
    floor_price: float | None
    exchange_time: str | None
    session: str | None


@dataclass(frozen=True, slots=True)
class IndexSnapshot:
    """Normalized index state without provider-specific types.

    Only fields whose meaning is supported by the vendored ``price.proto``
    schema and by observed protocol evidence are exposed. ``estimatedChange``
    and ``estimatedFsp`` are deliberately omitted because their semantics are
    undocumented.
    """

    symbol: str
    value: float
    change: float
    change_percent: float
    total_volume: float
    total_value: float
    advances: float
    declines: float
    unchanged: float
    ceiling_count: float
    floor_count: float
    exchange_time: str | None
