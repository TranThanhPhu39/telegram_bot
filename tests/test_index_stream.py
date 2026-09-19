"""Tests for the Vietcap index stream: decode, validate, normalize, cache."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from data.market_state import LatestIndexState
from data.models import IndexSnapshot
from data.vietcap.decoder import VietcapDecodeError, decode_index
from data.vietcap.normalizer import normalize_index
from data.vietcap.pipeline import IndexStatePipeline
from data.vietcap.proto import price_pb2
from data.vietcap.validation import validate_index
from scripts.test_realtime_index import DistinctIndexTracker


def valid_message(symbol: str = "VNINDEX", price: float = 1_280.5) -> price_pb2.IndexMessage:
    return price_pb2.IndexMessage(
        code=symbol,
        symbol=symbol,
        price=price,
        change=5.25,
        changePercent=0.41,
        totalShares=500_000_000,
        totalValue=12_500_000_000_000,
        totalStockIncrease=250,
        totalStockDecline=120,
        totalStockNoChange=60,
        totalStockCeiling=8,
        totalStockFloor=3,
        time="11:05:22",
    )


def payload(symbol: str = "VNINDEX", price: float = 1_280.5) -> bytes:
    return valid_message(symbol, price).SerializeToString()


# --- decoding -------------------------------------------------------------


@pytest.mark.parametrize("container", [bytes, bytearray, memoryview])
def test_decode_index_accepts_bytes_like_payloads(container: type) -> None:
    source = valid_message()

    assert decode_index(container(source.SerializeToString())) == source


def test_decode_index_rejects_non_binary_payload() -> None:
    with pytest.raises(TypeError, match="must be bytes-like"):
        decode_index("not binary")  # type: ignore[arg-type]


def test_decode_index_wraps_protobuf_decode_error() -> None:
    with pytest.raises(VietcapDecodeError, match="Invalid IndexMessage"):
        decode_index(b"\xff")


# --- validation -----------------------------------------------------------


def test_validate_index_accepts_valid_message() -> None:
    assert validate_index(valid_message()) == []


def test_validate_index_reports_invalid_values() -> None:
    message = valid_message()
    message.symbol = ""
    message.price = 0
    message.totalShares = -1
    message.totalValue = -1

    errors = validate_index(message)

    assert errors == [
        "symbol is empty",
        "price must be a positive finite index value",
        "totalShares must be a non-negative finite number",
        "totalValue must be a non-negative finite number",
    ]


@pytest.mark.parametrize(
    "field",
    [
        "totalStockIncrease",
        "totalStockDecline",
        "totalStockNoChange",
        "totalStockCeiling",
        "totalStockFloor",
    ],
)
def test_validate_index_rejects_negative_breadth_counts(field: str) -> None:
    message = valid_message()
    setattr(message, field, -1)

    assert validate_index(message) == [f"{field} must be non-negative"]


@pytest.mark.parametrize(
    "field",
    [
        "totalStockIncrease",
        "totalStockDecline",
        "totalStockNoChange",
        "totalStockCeiling",
        "totalStockFloor",
    ],
)
def test_validate_index_rejects_fractional_breadth_counts(field: str) -> None:
    message = valid_message()
    setattr(message, field, 1.5)

    assert validate_index(message) == [f"{field} must be a whole stock count"]


def test_validate_index_accepts_zero_breadth_and_negative_change() -> None:
    message = valid_message()
    message.change = -7.5
    message.changePercent = -0.6
    message.totalStockIncrease = 0
    message.totalStockDecline = 0
    message.totalStockNoChange = 0
    message.totalStockCeiling = 0
    message.totalStockFloor = 0

    assert validate_index(message) == []


def test_validate_index_rejects_non_finite_numbers() -> None:
    message = valid_message()
    message.price = float("inf")
    message.change = float("nan")

    errors = validate_index(message)

    assert "price must be a positive finite index value" in errors
    assert "change must be a finite number" in errors


# --- normalization --------------------------------------------------------


def test_normalize_index_maps_to_index_snapshot() -> None:
    message = valid_message()
    message.symbol = "vnindex"

    snapshot = normalize_index(message)

    assert snapshot == IndexSnapshot(
        symbol="VNINDEX",
        value=1_280.5,
        change=5.25,
        change_percent=0.41,
        total_volume=500_000_000.0,
        total_value=12_500_000_000_000.0,
        advances=250.0,
        declines=120.0,
        unchanged=60.0,
        ceiling_count=8.0,
        floor_count=3.0,
        exchange_time="11:05:22",
    )


def test_normalize_index_normalizes_mixed_case_index_identifier() -> None:
    message = valid_message(symbol="HNXIndex")

    assert normalize_index(message).symbol == "HNXINDEX"


def test_index_snapshot_is_immutable_and_provider_independent() -> None:
    snapshot = normalize_index(valid_message())

    with pytest.raises(FrozenInstanceError):
        snapshot.value = 1_300.0  # type: ignore[misc]

    assert all(
        type(getattr(snapshot, field)).__module__ == "builtins"
        for field in IndexSnapshot.__slots__
        if getattr(snapshot, field) is not None
    )


def test_normalize_index_maps_unset_time_to_none() -> None:
    message = valid_message()
    message.ClearField("time")

    assert normalize_index(message).exchange_time is None


def test_normalize_index_rejects_invalid_message() -> None:
    message = valid_message()
    message.price = 0

    with pytest.raises(
        ValueError,
        match="Invalid IndexMessage: price must be a positive finite index value",
    ):
        normalize_index(message)


# --- index state ----------------------------------------------------------


def test_index_state_stores_and_replaces_by_symbol() -> None:
    state = LatestIndexState()
    first = normalize_index(valid_message())
    latest = replace(first, value=1_281.0, exchange_time="11:05:25")

    assert state.update(first) is None
    assert state.update(latest) is first
    assert state.get(" vnindex ") is latest
    assert len(state) == 1


def test_index_state_snapshot_is_read_only_and_point_in_time() -> None:
    state = LatestIndexState()
    vnindex = normalize_index(valid_message())
    state.update(vnindex)
    snapshot = state.snapshot()

    with pytest.raises(TypeError):
        snapshot["VN30"] = vnindex  # type: ignore[index]

    state.update(normalize_index(valid_message(symbol="VN30", price=1_350.0)))

    assert snapshot == {"VNINDEX": vnindex}
    assert set(state.snapshot()) == {"VNINDEX", "VN30"}


def test_index_state_rejects_trade_ticks_and_denormalized_symbols() -> None:
    state = LatestIndexState()

    with pytest.raises(TypeError, match="only IndexSnapshot"):
        state.update(object())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="symbol must be non-empty and normalized"):
        state.update(replace(normalize_index(valid_message()), symbol="vnindex"))


# --- pipeline -------------------------------------------------------------


def test_index_pipeline_decodes_normalizes_and_caches_vnindex() -> None:
    state = LatestIndexState()
    pipeline = IndexStatePipeline(state, ("vnindex",))

    snapshot = pipeline.handle(payload())

    assert pipeline.expected_symbols == frozenset({"VNINDEX"})
    assert snapshot is not None
    assert state.get("VNINDEX") is snapshot
    assert snapshot.value == 1_280.5


def test_index_pipeline_ignores_unexpected_index() -> None:
    state = LatestIndexState()
    pipeline = IndexStatePipeline(state, ("VNINDEX",))

    assert pipeline.handle(payload(symbol="VN30", price=1_350.0)) is None
    assert len(state) == 0


@pytest.mark.parametrize("invalid_payload", [object(), b"\x80"])
def test_index_pipeline_rejects_malformed_payload(invalid_payload: object) -> None:
    state = LatestIndexState()
    pipeline = IndexStatePipeline(state, ("VNINDEX",))

    assert pipeline.handle(invalid_payload) is None
    assert len(state) == 0


def test_index_pipeline_rejects_invalid_decoded_index() -> None:
    state = LatestIndexState()
    pipeline = IndexStatePipeline(state, ("VNINDEX",))
    message = valid_message()
    message.totalStockDecline = -1

    assert pipeline.handle(message.SerializeToString()) is None
    assert len(state) == 0


def test_index_pipeline_requires_index_state() -> None:
    with pytest.raises(TypeError, match="must be a LatestIndexState"):
        IndexStatePipeline(object(), ("VNINDEX",))  # type: ignore[arg-type]


# --- live acceptance logic ------------------------------------------------


def test_index_tracker_requires_changing_vnindex_snapshots() -> None:
    state = LatestIndexState()
    pipeline = IndexStatePipeline(state, ("VNINDEX",))
    tracker = DistinctIndexTracker(("VNINDEX",), minimum=2)
    snapshot = pipeline.handle(payload())
    assert snapshot is not None

    tracker.record(snapshot)
    tracker.record(snapshot)
    assert tracker.counts() == {"VNINDEX": 1}
    assert not tracker.complete

    tracker.record(replace(snapshot, value=1_281.0, exchange_time="11:05:25"))
    assert tracker.complete