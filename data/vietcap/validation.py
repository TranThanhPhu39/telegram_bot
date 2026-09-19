"""Validation helpers for decoded Vietcap market-data messages."""

from __future__ import annotations

from data.vietcap.proto import price_pb2


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
