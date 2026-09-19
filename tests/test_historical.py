"""Tests for evidence-backed Vietcap historical normalization."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from data.models import OHLCVBar
from data.vietcap.historical import VietcapHistoricalDataError, normalize_gap_chart

FIXTURE = Path(__file__).parent / "fixtures" / "vietcap_gap_chart_acb_one_day.json"


def load_fixture() -> object:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_normalize_observed_gap_chart_fixture() -> None:
    bars = normalize_gap_chart(load_fixture(), time_frame="ONE_DAY")

    assert len(bars) == 3
    assert bars[0] == OHLCVBar(
        symbol="ACB",
        timeframe="ONE_DAY",
        timestamp=1_767_916_800,
        open=21_281.52,
        high=21_496.92,
        low=21_109.2,
        close=21_152.28,
        volume=16_473_981.0,
    )
    assert bars[-1].timestamp == 1_768_262_400
    assert bars[-1].close == 21_453.84


def test_normalized_bars_are_immutable() -> None:
    bar = normalize_gap_chart(load_fixture(), time_frame="ONE_DAY")[0]

    with pytest.raises(FrozenInstanceError):
        bar.close = 1.0  # type: ignore[misc]


def test_normalize_multiple_symbol_rows_preserves_response_order() -> None:
    payload = load_fixture()
    second = dict(payload[0])  # type: ignore[index]
    second["symbol"] = "FPT"

    bars = normalize_gap_chart([payload[0], second], time_frame="ONE_DAY")  # type: ignore[index]

    assert [bar.symbol for bar in bars] == ["ACB"] * 3 + ["FPT"] * 3


@pytest.mark.parametrize("payload", [None, {}, "invalid", [None]])
def test_rejects_invalid_top_level_or_rows(payload: object) -> None:
    with pytest.raises(VietcapHistoricalDataError):
        normalize_gap_chart(payload, time_frame="ONE_DAY")


def test_rejects_missing_column() -> None:
    payload = load_fixture()
    del payload[0]["v"]  # type: ignore[index]

    with pytest.raises(VietcapHistoricalDataError, match="column 'v'"):
        normalize_gap_chart(payload, time_frame="ONE_DAY")


def test_rejects_unequal_column_lengths() -> None:
    payload = load_fixture()
    payload[0]["v"].pop()  # type: ignore[index]

    with pytest.raises(VietcapHistoricalDataError, match="equal lengths"):
        normalize_gap_chart(payload, time_frame="ONE_DAY")


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("t", "not-a-time", "Unix-seconds"),
        ("o", float("nan"), "finite"),
        ("h", 20_000, "highest"),
        ("l", 21_300, "lowest"),
        ("v", -1, "non-negative"),
    ],
)
def test_rejects_invalid_bar_values(column: str, value: object, message: str) -> None:
    payload = load_fixture()
    payload[0][column][0] = value  # type: ignore[index]

    with pytest.raises(VietcapHistoricalDataError, match=message):
        normalize_gap_chart(payload, time_frame="ONE_DAY")
