"""Validation helpers for decoded Vietcap market-data messages."""

from __future__ import annotations

import math

from data.vietcap.proto import price_pb2

BREADTH_FIELDS: tuple[str, ...] = (
    "totalStockIncrease",
    "totalStockDecline",
    "totalStockNoChange",
    "totalStockCeiling",
    "totalStockFloor",
)


def validate_match_price(message: price_pb2.MatchPriceMessage) -> list[str]:
    """Return data-quality errors for a decoded match-price message."""
    errors: list[str] = []
    if not message.symbol:
        errors.append("symbol is empty")
    if message.matchPrice <= 0:
        errors.append("matchPrice must be positive for an active trade")
    if message.matchVol < 0:
        errors.append("matchVol must be non-negative")
    if message.accumulatedVolume < 0:
        errors.append("accumulatedVolume must be non-negative")
    if message.accumulatedValue < 0:
        errors.append("accumulatedValue must be non-negative")
    if message.highest and message.lowest and message.highest < message.lowest:
        errors.append("highest must be greater than or equal to lowest")
    if (
        message.ceilingPrice
        and message.referencePrice
        and message.floorPrice
        and not (
            message.ceilingPrice
            >= message.referencePrice
            >= message.floorPrice
        )
    ):
        errors.append("ceilingPrice >= referencePrice >= floorPrice is required")
    return errors


def validate_index(message: price_pb2.IndexMessage) -> list[str]:
    """Return data-quality errors for a decoded index message.

    Only schema-supported constraints are enforced. Relationships between
    breadth counters (for example whether ceiling stocks are also counted as
    advancing stocks) are not documented, so they are not asserted here.
    """
    errors: list[str] = []
    if not message.symbol:
        errors.append("symbol is empty")
    if not (message.price > 0) or math.isinf(message.price):
        errors.append("price must be a positive finite index value")
    if math.isnan(message.change) or math.isinf(message.change):
        errors.append("change must be a finite number")
    if math.isnan(message.changePercent) or math.isinf(message.changePercent):
        errors.append("changePercent must be a finite number")
    if not (message.totalShares >= 0) or math.isinf(message.totalShares):
        errors.append("totalShares must be a non-negative finite number")
    if not (message.totalValue >= 0) or math.isinf(message.totalValue):
        errors.append("totalValue must be a non-negative finite number")

    for field in BREADTH_FIELDS:
        value = getattr(message, field)
        if math.isnan(value) or math.isinf(value):
            errors.append(f"{field} must be a finite number")
        elif value < 0:
            errors.append(f"{field} must be non-negative")
        elif value != int(value):
            errors.append(f"{field} must be a whole stock count")
    return errors