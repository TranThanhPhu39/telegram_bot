"""Tests for Vietcap binary protobuf decoding."""

from __future__ import annotations

import pytest

from data.vietcap.decoder import VietcapDecodeError, decode_match_price
from data.vietcap.proto import price_pb2


@pytest.mark.parametrize("container", [bytes, bytearray, memoryview])
def test_decode_match_price_accepts_bytes_like_payloads(container: type) -> None:
    source = price_pb2.MatchPriceMessage(
        type="MATCH_PRICE",
        code="FPT",
        symbol="FPT",
        matchPrice=103.2,
        matchVol=1_500,
        accumulatedVolume=2_345_600,
        accumulatedValue=242_000_000_000,
        time="11:05:21",
    )

    decoded = decode_match_price(container(source.SerializeToString()))

    assert decoded == source


def test_decode_match_price_rejects_non_binary_payload() -> None:
    with pytest.raises(TypeError, match="must be bytes-like"):
        decode_match_price("not binary")  # type: ignore[arg-type]


def test_decode_match_price_wraps_protobuf_decode_error() -> None:
    with pytest.raises(VietcapDecodeError, match="Invalid MatchPriceMessage"):
        decode_match_price(b"\xff")
