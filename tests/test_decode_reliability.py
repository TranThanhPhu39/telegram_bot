"""Reliability tests for malformed realtime payload isolation."""

import logging

from data.market_state import (
    LatestIndexState,
    LatestMarketState,
    LatestOrderBookState,
)
from data.vietcap.pipeline import (
    BidAskStatePipeline,
    IndexStatePipeline,
    MatchPriceStatePipeline,
)
from data.vietcap.proto import price_pb2


def test_match_price_pipeline_recovers_after_decode_error(
    caplog,
) -> None:
    state = LatestMarketState()
    pipeline = MatchPriceStatePipeline(state, ("FPT",))
    valid_payload = price_pb2.MatchPriceMessage(
        symbol="FPT",
        matchPrice=103.2,
        matchVol=1_000,
        accumulatedVolume=10_000,
        accumulatedValue=1_000_000,
    ).SerializeToString()

    with caplog.at_level(logging.ERROR):
        assert pipeline.handle(b"\x80") is None
    tick = pipeline.handle(valid_payload)

    assert "Rejected Vietcap match-price payload" in caplog.text
    assert tick is not None
    assert state.get("FPT") is tick


def test_index_pipeline_recovers_after_decode_error(caplog) -> None:
    state = LatestIndexState()
    pipeline = IndexStatePipeline(state, ("VNINDEX",))
    valid_payload = price_pb2.IndexMessage(
        symbol="VNINDEX",
        price=1_280.5,
        totalShares=500_000_000,
        totalValue=12_000_000_000,
        totalStockIncrease=250,
        totalStockDecline=120,
        totalStockNoChange=30,
        totalStockCeiling=12,
        totalStockFloor=5,
    ).SerializeToString()

    with caplog.at_level(logging.ERROR):
        assert pipeline.handle(b"\x80") is None
    snapshot = pipeline.handle(valid_payload)

    assert "Rejected Vietcap index payload" in caplog.text
    assert snapshot is not None
    assert state.get("VNINDEX") is snapshot


def test_bid_ask_pipeline_recovers_after_decode_error(caplog) -> None:
    state = LatestOrderBookState()
    pipeline = BidAskStatePipeline(state, ("FPT",))
    message = price_pb2.BidAskMessage(symbol="FPT")
    message.bidPrices.add(price=103.1, volume=2_000)
    message.askPrices.add(price=103.3, volume=1_500)

    with caplog.at_level(logging.ERROR):
        assert pipeline.handle(b"\x80") is None
    book = pipeline.handle(message.SerializeToString())

    assert "Rejected Vietcap bid-ask payload" in caplog.text
    assert book is not None
    assert state.get("FPT") is book
