"""Decode Vietcap protobuf payloads without applying strategy logic."""

from __future__ import annotations

import logging

from google.protobuf.message import DecodeError

from data.vietcap.proto import price_pb2

logger = logging.getLogger(__name__)


class VietcapDecodeError(ValueError):
    """Raised when an incoming Vietcap payload cannot be decoded safely."""


def decode_match_price(
    payload: bytes | bytearray | memoryview,
) -> price_pb2.MatchPriceMessage:
    """Decode one binary ``MatchPriceMessage`` payload."""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError(
            "Match-price payload must be bytes-like, "
            f"received {type(payload).__name__}"
        )

    raw = bytes(payload)
    message = price_pb2.MatchPriceMessage()
    try:
        message.ParseFromString(raw)
    except DecodeError as exc:
        logger.exception(
            "Failed to decode MatchPriceMessage",
            extra={"event": "w-match-price", "payload_size": len(raw)},
        )
        raise VietcapDecodeError("Invalid MatchPriceMessage payload") from exc
    return message
