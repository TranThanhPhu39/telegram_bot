"""Tests for provider-independent trade-tick normalization."""

from dataclasses import FrozenInstanceError

import pytest

from data.models import TradeTick
from data.vietcap.normalizer import normalize_match_price
from data.vietcap.proto import price_pb2


def valid_message() -> price_pb2.MatchPriceMessage:
    return price_pb2.MatchPriceMessage(
        symbol="fpt",
        matchPrice=103.2,
        matchVol=1_500,
        accumulatedVolume=2_345_600,
        accumulatedValue=242_000_000_000,
        highest=104,
        lowest=101,
        openPrice=102,
        avgMatchPrice=103.1,
        referencePrice=103,
        ceilingPrice=110,
        floorPrice=96,
        time="10:15:30",
        session="CONTINUOUS",
    )


def test_normalize_match_price_maps_to_trade_tick() -> None:
    tick = normalize_match_price(valid_message())

    assert tick == TradeTick(
        symbol="FPT",
        price=103.2,
        volume=1_500.0,
        accumulated_volume=2_345_600.0,
        accumulated_value=242_000_000_000.0,
        high_price=104.0,
        low_price=101.0,
        open_price=102.0,
        average_price=103.1,
        reference_price=103.0,
        ceiling_price=110.0,
        floor_price=96.0,
        exchange_time="10:15:30",
        session="CONTINUOUS",
    )


def test_trade_tick_is_immutable() -> None:
    tick = normalize_match_price(valid_message())

    with pytest.raises(FrozenInstanceError):
        tick.price = 104.0  # type: ignore[misc]


def test_normalize_match_price_maps_unset_snapshot_fields_to_none() -> None:
    message = valid_message()
    message.ClearField("highest")
    message.ClearField("lowest")
    message.ClearField("openPrice")
    message.ClearField("avgMatchPrice")
    message.ClearField("referencePrice")
    message.ClearField("ceilingPrice")
    message.ClearField("floorPrice")
    message.ClearField("time")
    message.ClearField("session")

    tick = normalize_match_price(message)

    assert tick.high_price is None
    assert tick.low_price is None
    assert tick.open_price is None
    assert tick.average_price is None
    assert tick.reference_price is None
    assert tick.ceiling_price is None
    assert tick.floor_price is None
    assert tick.exchange_time is None
    assert tick.session is None


def test_normalize_match_price_rejects_invalid_message() -> None:
    message = valid_message()
    message.matchPrice = 0

    with pytest.raises(
        ValueError,
        match="Invalid MatchPriceMessage: matchPrice must be positive",
    ):
        normalize_match_price(message)
