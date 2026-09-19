"""Normalize Vietcap protobuf messages into provider-independent models."""

from __future__ import annotations

from data.models import IndexSnapshot, OrderBook, OrderBookLevel, TradeTick
from data.vietcap.proto import price_pb2
from data.vietcap.validation import (
    validate_bid_ask,
    validate_index,
    validate_match_price,
)


def _optional_positive(value: float) -> float | None:
    """Map an unset proto3 numeric default to ``None``."""
    return float(value) if value > 0 else None


def _optional_text(value: str) -> str | None:
    """Map an empty proto3 string default to ``None``."""
    stripped = value.strip()
    return stripped or None


def normalize_match_price(message: price_pb2.MatchPriceMessage) -> TradeTick:
    """Validate and normalize a Vietcap match-price message."""
    errors = validate_match_price(message)
    if errors:
        raise ValueError(f"Invalid MatchPriceMessage: {'; '.join(errors)}")

    return TradeTick(
        symbol=message.symbol.strip().upper(),
        price=float(message.matchPrice),
        volume=float(message.matchVol),
        accumulated_volume=float(message.accumulatedVolume),
        accumulated_value=float(message.accumulatedValue),
        high_price=_optional_positive(message.highest),
        low_price=_optional_positive(message.lowest),
        open_price=_optional_positive(message.openPrice),
        average_price=_optional_positive(message.avgMatchPrice),
        reference_price=_optional_positive(message.referencePrice),
        ceiling_price=_optional_positive(message.ceilingPrice),
        floor_price=_optional_positive(message.floorPrice),
        exchange_time=_optional_text(message.time),
        session=_optional_text(message.session),
    )


def normalize_index(message: price_pb2.IndexMessage) -> IndexSnapshot:
    """Validate and normalize a Vietcap index message.

    ``estimatedChange`` and ``estimatedFsp`` are not mapped because the schema
    does not document their meaning. Provider numeric units are preserved.
    """
    errors = validate_index(message)
    if errors:
        raise ValueError(f"Invalid IndexMessage: {'; '.join(errors)}")

    return IndexSnapshot(
        symbol=message.symbol.strip().upper(),
        value=float(message.price),
        change=float(message.change),
        change_percent=float(message.changePercent),
        total_volume=float(message.totalShares),
        total_value=float(message.totalValue),
        advances=float(message.totalStockIncrease),
        declines=float(message.totalStockDecline),
        unchanged=float(message.totalStockNoChange),
        ceiling_count=float(message.totalStockCeiling),
        floor_count=float(message.totalStockFloor),
        exchange_time=_optional_text(message.time),
    )


def _normalize_levels(
    levels: "list[price_pb2.BidAskPrice]",
) -> tuple[OrderBookLevel, ...]:
    """Convert provider price levels while preserving their received order."""
    return tuple(
        OrderBookLevel(price=float(level.price), volume=float(level.volume))
        for level in levels
    )


def normalize_bid_ask(message: price_pb2.BidAskMessage) -> OrderBook:
    """Validate and normalize a Vietcap bid-ask message.

    ``bidCount`` and ``askCount`` are not mapped because the schema does not
    document their meaning. Provider numeric units and level order are kept.
    """
    errors = validate_bid_ask(message)
    if errors:
        raise ValueError(f"Invalid BidAskMessage: {'; '.join(errors)}")

    return OrderBook(
        symbol=message.symbol.strip().upper(),
        bids=_normalize_levels(list(message.bidPrices)),
        asks=_normalize_levels(list(message.askPrices)),
        session=_optional_text(message.session),
    )
