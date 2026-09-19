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
