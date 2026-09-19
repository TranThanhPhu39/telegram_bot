"""Tests for the Vietcap match-price normalization pipeline."""

import pytest
from dataclasses import replace

from data.market_state import LatestMarketState
from data.vietcap.pipeline import MatchPriceStatePipeline
from data.vietcap.proto import price_pb2
from scripts.test_realtime_market_state import DistinctTickTracker


def payload(symbol: str, price: float) -> bytes:
    return price_pb2.MatchPriceMessage(
        symbol=symbol,
        matchPrice=price,
        matchVol=1_000,
        accumulatedVolume=10_000,
        accumulatedValue=1_000_000,
        time="10:15:30",
    ).SerializeToString()


def test_pipeline_decodes_normalizes_and_caches_fpt_and_acb() -> None:
    state = LatestMarketState()
    pipeline = MatchPriceStatePipeline(state, ("fpt", "ACB"))

    fpt = pipeline.handle(payload("FPT", 103.2))
    acb = pipeline.handle(payload("ACB", 25.5))

    assert pipeline.expected_symbols == frozenset({"FPT", "ACB"})
    assert fpt is not None
    assert acb is not None
    assert state.get("FPT") is fpt
    assert state.get("ACB") is acb
    assert fpt.price == 103.2
    assert acb.price == 25.5


def test_pipeline_replaces_cached_tick_for_same_symbol() -> None:
    state = LatestMarketState()
    pipeline = MatchPriceStatePipeline(state, ("FPT", "ACB"))

    pipeline.handle(payload("FPT", 103.2))
    latest = pipeline.handle(payload("FPT", 103.5))

    assert state.get("FPT") is latest
    assert latest is not None
    assert latest.price == 103.5
    assert len(state) == 1


def test_pipeline_ignores_unexpected_symbol() -> None:
    state = LatestMarketState()
    pipeline = MatchPriceStatePipeline(state, ("FPT", "ACB"))

    assert pipeline.handle(payload("HPG", 27.1)) is None
    assert len(state) == 0


@pytest.mark.parametrize(
    "invalid_payload",
    [object(), b"\x80"],
)
def test_pipeline_rejects_malformed_payload(invalid_payload: object) -> None:
    state = LatestMarketState()
    pipeline = MatchPriceStatePipeline(state, ("FPT", "ACB"))

    assert pipeline.handle(invalid_payload) is None
    assert len(state) == 0


def test_pipeline_rejects_invalid_decoded_trade() -> None:
    state = LatestMarketState()
    pipeline = MatchPriceStatePipeline(state, ("FPT", "ACB"))

    assert pipeline.handle(payload("FPT", 0)) is None
    assert len(state) == 0


def test_acceptance_tracker_requires_distinct_updates_for_both_symbols() -> None:
    state = LatestMarketState()
    pipeline = MatchPriceStatePipeline(state, ("FPT", "ACB"))
    tracker = DistinctTickTracker(("FPT", "ACB"), minimum=2)
    fpt = pipeline.handle(payload("FPT", 103.2))
    acb = pipeline.handle(payload("ACB", 25.5))
    assert fpt is not None
    assert acb is not None

    tracker.record(fpt)
    tracker.record(fpt)
    tracker.record(acb)
    assert tracker.counts() == {"FPT": 1, "ACB": 1}
    assert not tracker.complete

    tracker.record(replace(fpt, price=103.5))
    assert not tracker.complete

    tracker.record(replace(acb, price=25.6))
    assert tracker.complete
