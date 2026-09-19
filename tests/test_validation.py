"""Tests for match-price data-quality validation."""

from data.vietcap.proto import price_pb2
from data.vietcap.validation import validate_match_price


def valid_message() -> price_pb2.MatchPriceMessage:
    return price_pb2.MatchPriceMessage(
        symbol="FPT",
        matchPrice=103.2,
        matchVol=1_500,
        accumulatedVolume=2_345_600,
        accumulatedValue=242_000_000_000,
        highest=104,
        lowest=101,
        ceilingPrice=110,
        referencePrice=103,
        floorPrice=96,
    )


def test_validate_match_price_accepts_valid_message() -> None:
    assert validate_match_price(valid_message()) == []


def test_validate_match_price_reports_invalid_values() -> None:
    message = valid_message()
    message.symbol = ""
    message.matchPrice = 0
    message.matchVol = -1
    message.accumulatedVolume = -1
    message.accumulatedValue = -1
    message.highest = 100
    message.lowest = 101
    message.ceilingPrice = 90
    message.referencePrice = 100
    message.floorPrice = 110

    errors = validate_match_price(message)

    assert errors == [
        "symbol is empty",
        "matchPrice must be positive for an active trade",
        "matchVol must be non-negative",
        "accumulatedVolume must be non-negative",
        "accumulatedValue must be non-negative",
        "highest must be greater than or equal to lowest",
        "ceilingPrice >= referencePrice >= floorPrice is required",
    ]
