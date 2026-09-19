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


@dataclass(frozen=True, slots=True)
class OrderBookLevel:
    """One normalized price level without provider-specific types."""

    price: float
    volume: float


@dataclass(frozen=True, slots=True)
class OrderBook:
    """Normalized order-book state without provider-specific types.

    ``bids`` and ``asks`` keep the provider's level order, which is not
    documented as sorted, and are tuples so cached state cannot be mutated.
    ``bidCount`` and ``askCount`` are not exposed because their meaning is
    undocumented.
    """

    symbol: str
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    session: str | None


@dataclass(frozen=True, slots=True)
class OHLCVBar:
    """One provider-independent historical price bar.

    ``timestamp`` is the Unix-seconds value observed in Vietcap's historical
    response, normalized from the provider's decimal string.
    """

    symbol: str
    timeframe: str
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
