"""Normalize Vietcap protobuf messages into provider-independent models."""

from __future__ import annotations

from data.models import TradeTick
from data.vietcap.proto import price_pb2
from data.vietcap.validation import validate_match_price


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
