"""Tests for the Vietcap bid-ask stream: decode, validate, normalize, cache."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from data.market_state import LatestOrderBookState
from data.models import OrderBook, OrderBookLevel
from data.vietcap.decoder import VietcapDecodeError, decode_bid_ask
from data.vietcap.normalizer import normalize_bid_ask
from data.vietcap.pipeline import BidAskStatePipeline
from data.vietcap.proto import price_pb2
from data.vietcap.validation import validate_bid_ask
from scripts.test_realtime_bidask import DistinctOrderBookTracker


def valid_message(
    symbol: str = "FPT", best_bid: float = 103.1
) -> price_pb2.BidAskMessage:
    return price_pb2.BidAskMessage(
        type="BID_ASK",
        code=symbol,
        symbol=symbol,
        bidPrices=[
            price_pb2.BidAskPrice(price=best_bid, volume=10_000),
            price_pb2.BidAskPrice(price=round(best_bid - 0.1, 2), volume=8_000),
        ],
        askPrices=[
            price_pb2.BidAskPrice(price=round(best_bid + 0.1, 2), volume=12_000),
            price_pb2.BidAskPrice(price=round(best_bid + 0.2, 2), volume=5_000),
        ],
        session="CONTINUOUS",
        bidCount=3,
        askCount=3,
    )


def payload(symbol: str = "FPT", best_bid: float = 103.1) -> bytes:
    return valid_message(symbol, best_bid).SerializeToString()


# --- decoding -------------------------------------------------------------


@pytest.mark.parametrize("container", [bytes, bytearray, memoryview])
def test_decode_bid_ask_accepts_bytes_like_payloads(container: type) -> None:
    source = valid_message()

    assert decode_bid_ask(container(source.SerializeToString())) == source


def test_decode_bid_ask_rejects_non_binary_payload() -> None:
    with pytest.raises(TypeError, match="must be bytes-like"):
        decode_bid_ask("not binary")  # type: ignore[arg-type]


def test_decode_bid_ask_wraps_protobuf_decode_error() -> None:
    with pytest.raises(VietcapDecodeError, match="Invalid BidAskMessage"):
        decode_bid_ask(b"\xff")


# --- validation -----------------------------------------------------------


def test_validate_bid_ask_accepts_valid_message() -> None:
    assert validate_bid_ask(valid_message()) == []


def test_validate_bid_ask_accepts_empty_sides() -> None:
    message = valid_message()
    message.ClearField("bidPrices")
    message.ClearField("askPrices")

    assert validate_bid_ask(message) == []


def test_validate_bid_ask_reports_empty_symbol() -> None:
    message = valid_message()
    message.symbol = ""

    assert validate_bid_ask(message) == ["symbol is empty"]


@pytest.mark.parametrize("side", ["bidPrices", "askPrices"])
def test_validate_bid_ask_rejects_non_positive_level_price(side: str) -> None:
    message = valid_message()
    getattr(message, side)[1].price = 0
    label = "bid" if side == "bidPrices" else "ask"

    assert validate_bid_ask(message) == [f"{label}Prices[1].price must be positive"]


@pytest.mark.parametrize("side", ["bidPrices", "askPrices"])
def test_validate_bid_ask_rejects_negative_level_volume(side: str) -> None:
    message = valid_message()
    getattr(message, side)[0].volume = -1
    label = "bid" if side == "bidPrices" else "ask"

    assert validate_bid_ask(message) == [
        f"{label}Prices[0].volume must be non-negative"
    ]


def test_validate_bid_ask_rejects_non_finite_level_values() -> None:
    message = valid_message()
    message.bidPrices[0].price = float("nan")
    message.askPrices[0].volume = float("inf")

    errors = validate_bid_ask(message)

    assert "bidPrices[0].price must be a finite number" in errors
    assert "askPrices[0].volume must be a finite number" in errors


def test_validate_bid_ask_rejects_repeated_price_level() -> None:
    message = valid_message()
    message.bidPrices[1].price = message.bidPrices[0].price

    assert validate_bid_ask(message) == ["bidPrices must not repeat a price level"]


def test_validate_bid_ask_accepts_crossed_and_unordered_book() -> None:
    """Auction sessions can cross, and level ordering is undocumented."""
    message = valid_message()
    message.bidPrices[0].price = 104.0
    message.bidPrices[1].price = 104.5
    message.askPrices[0].price = 103.0

    assert validate_bid_ask(message) == []


# --- normalization --------------------------------------------------------


def test_normalize_bid_ask_maps_to_order_book() -> None:
    message = valid_message()
    message.symbol = "fpt"

    book = normalize_bid_ask(message)

    assert book == OrderBook(
        symbol="FPT",
        bids=(
            OrderBookLevel(price=103.1, volume=10_000.0),
            OrderBookLevel(price=103.0, volume=8_000.0),
        ),
        asks=(
            OrderBookLevel(price=103.2, volume=12_000.0),
            OrderBookLevel(price=103.3, volume=5_000.0),
        ),
        session="CONTINUOUS",
    )


def test_normalize_bid_ask_preserves_provider_level_order() -> None:
    message = valid_message()
    message.bidPrices[0].price = 102.0
    message.bidPrices[1].price = 103.5

    book = normalize_bid_ask(message)

    assert [level.price for level in book.bids] == [102.0, 103.5]


def test_order_book_is_immutable_and_provider_independent() -> None:
    book = normalize_bid_ask(valid_message())

    with pytest.raises(FrozenInstanceError):
        book.symbol = "ACB"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        book.bids[0].price = 1.0  # type: ignore[misc]
    with pytest.raises(TypeError):
        book.bids[0] = OrderBookLevel(1.0, 1.0)  # type: ignore[index]

    assert all(
        type(level) is OrderBookLevel for level in book.bids + book.asks
    )


def test_normalize_bid_ask_maps_unset_session_to_none() -> None:
    message = valid_message()
    message.ClearField("session")

    assert normalize_bid_ask(message).session is None


def test_normalize_bid_ask_maps_empty_sides_to_empty_tuples() -> None:
    message = valid_message()
    message.ClearField("askPrices")

    book = normalize_bid_ask(message)

    assert book.asks == ()
    assert len(book.bids) == 2


def test_normalize_bid_ask_rejects_invalid_message() -> None:
    message = valid_message()
    message.bidPrices[0].price = 0

    with pytest.raises(
        ValueError,
        match="Invalid BidAskMessage: bidPrices\\[0\\].price must be positive",
    ):
        normalize_bid_ask(message)


# --- order-book state -----------------------------------------------------


def test_order_book_state_stores_fpt_and_acb_by_symbol() -> None:
    state = LatestOrderBookState()
    fpt = normalize_bid_ask(valid_message())
    acb = normalize_bid_ask(valid_message(symbol="ACB", best_bid=25.5))

    assert state.update(fpt) is None
    assert state.update(acb) is None
    assert state.get(" fpt ") is fpt
    assert state.get("acb") is acb
    assert len(state) == 2


def test_order_book_state_replaces_and_returns_previous() -> None:
    state = LatestOrderBookState()
    first = normalize_bid_ask(valid_message())
    latest = replace(first, session="ATC")

    state.update(first)

    assert state.update(latest) is first
    assert state.get("FPT") is latest
    assert len(state) == 1


def test_order_book_state_snapshot_is_read_only_and_point_in_time() -> None:
    state = LatestOrderBookState()
    fpt = normalize_bid_ask(valid_message())
    state.update(fpt)
    snapshot = state.snapshot()

    with pytest.raises(TypeError):
        snapshot["ACB"] = fpt  # type: ignore[index]

    state.update(normalize_bid_ask(valid_message(symbol="ACB", best_bid=25.5)))

    assert snapshot == {"FPT": fpt}
    assert set(state.snapshot()) == {"FPT", "ACB"}


def test_order_book_state_rejects_wrong_types_and_denormalized_symbols() -> None:
    state = LatestOrderBookState()

    with pytest.raises(TypeError, match="only OrderBook"):
        state.update(object())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="symbol must be non-empty and normalized"):
        state.update(replace(normalize_bid_ask(valid_message()), symbol="fpt"))


# --- pipeline -------------------------------------------------------------


def test_bid_ask_pipeline_decodes_normalizes_and_caches_fpt_and_acb() -> None:
    state = LatestOrderBookState()
    pipeline = BidAskStatePipeline(state, ("fpt", "ACB"))

    fpt = pipeline.handle(payload())
    acb = pipeline.handle(payload(symbol="ACB", best_bid=25.5))

    assert pipeline.expected_symbols == frozenset({"FPT", "ACB"})
    assert state.get("FPT") is fpt
    assert state.get("ACB") is acb
    assert fpt is not None and fpt.bids[0].price == 103.1
    assert acb is not None and acb.asks[0].price == 25.6


def test_bid_ask_pipeline_ignores_unexpected_symbol() -> None:
    state = LatestOrderBookState()
    pipeline = BidAskStatePipeline(state, ("FPT", "ACB"))

    assert pipeline.handle(payload(symbol="HPG", best_bid=27.1)) is None
    assert len(state) == 0


@pytest.mark.parametrize("invalid_payload", [object(), b"\x80"])
def test_bid_ask_pipeline_rejects_malformed_payload(invalid_payload: object) -> None:
    state = LatestOrderBookState()
    pipeline = BidAskStatePipeline(state, ("FPT", "ACB"))

    assert pipeline.handle(invalid_payload) is None
    assert len(state) == 0


def test_bid_ask_pipeline_rejects_invalid_decoded_book() -> None:
    state = LatestOrderBookState()
    pipeline = BidAskStatePipeline(state, ("FPT", "ACB"))
    message = valid_message()
    message.askPrices[0].volume = -1

    assert pipeline.handle(message.SerializeToString()) is None
    assert len(state) == 0


def test_bid_ask_pipeline_requires_order_book_state() -> None:
    with pytest.raises(TypeError, match="must be a LatestOrderBookState"):
        BidAskStatePipeline(object(), ("FPT",))  # type: ignore[arg-type]


# --- live acceptance logic ------------------------------------------------


def test_order_book_tracker_requires_changing_books_for_both_symbols() -> None:
    state = LatestOrderBookState()
    pipeline = BidAskStatePipeline(state, ("FPT", "ACB"))
    tracker = DistinctOrderBookTracker(("FPT", "ACB"), minimum=2)
    fpt = pipeline.handle(payload())
    acb = pipeline.handle(payload(symbol="ACB", best_bid=25.5))
    assert fpt is not None and acb is not None

    tracker.record(fpt)
    tracker.record(fpt)
    tracker.record(acb)
    assert tracker.counts() == {"FPT": 1, "ACB": 1}
    assert not tracker.complete

    tracker.record(replace(fpt, session="ATC"))
    assert not tracker.complete

    tracker.record(
        replace(acb, bids=(OrderBookLevel(price=25.4, volume=1_000.0),))
    )
    assert tracker.complete