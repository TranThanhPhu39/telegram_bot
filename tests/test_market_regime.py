"""Tests for the Phase 12 VNINDEX market-regime classifier."""

from dataclasses import replace

import pytest

from data.market_regime import (
    MarketRegime,
    MarketRegimeConfig,
    TrendState,
    classify_vnindex_regime,
)
from data.models import IndexSnapshot


def snapshot(
    *,
    value: float = 1_300.0,
    advances: float = 260.0,
    declines: float = 100.0,
    unchanged: float = 40.0,
) -> IndexSnapshot:
    return IndexSnapshot(
        symbol="VNINDEX",
        value=value,
        change=5.0,
        change_percent=0.4,
        total_volume=500_000_000.0,
        total_value=12_000_000_000_000.0,
        advances=advances,
        declines=declines,
        unchanged=unchanged,
        ceiling_count=5.0,
        floor_count=2.0,
        exchange_time="10:30:00",
    )


CONFIG = MarketRegimeConfig(breadth_threshold=0.2, minimum_breadth_issues=100)


def test_classifies_bull_when_trend_and_breadth_confirm() -> None:
    result = classify_vnindex_regime(snapshot(), 1_280.0, 1_250.0, CONFIG)

    assert result.regime is MarketRegime.BULL
    assert result.trend is TrendState.BULLISH
    assert result.breadth_score == pytest.approx(0.4)
    assert result.breadth_issues == 400
    assert "bullish trend and breadth confirmed" in result.reasons


def test_classifies_bear_when_trend_and_breadth_confirm() -> None:
    result = classify_vnindex_regime(
        snapshot(value=1_200.0, advances=80.0, declines=280.0),
        1_230.0,
        1_260.0,
        CONFIG,
    )

    assert result.regime is MarketRegime.BEAR
    assert result.trend is TrendState.BEARISH
    assert result.breadth_score == pytest.approx(-0.5)
    assert "bearish trend and breadth confirmed" in result.reasons


@pytest.mark.parametrize(
    ("index", "ema20", "ema50", "expected_trend"),
    [
        (snapshot(advances=180.0, declines=180.0), 1_280.0, 1_250.0, TrendState.BULLISH),
        (snapshot(value=1_200.0, advances=250.0, declines=100.0), 1_230.0, 1_260.0, TrendState.BEARISH),
        (snapshot(), 1_250.0, 1_280.0, TrendState.MIXED),
        (snapshot(), None, 1_250.0, TrendState.UNAVAILABLE),
    ],
)
def test_conflicting_or_missing_evidence_is_neutral(
    index: IndexSnapshot,
    ema20: float | None,
    ema50: float | None,
    expected_trend: TrendState,
) -> None:
    result = classify_vnindex_regime(index, ema20, ema50, CONFIG)

    assert result.regime is MarketRegime.NEUTRAL
    assert result.trend is expected_trend


def test_boundary_threshold_is_inclusive() -> None:
    index = snapshot(advances=240.0, declines=160.0, unchanged=0.0)

    assert classify_vnindex_regime(index, 1_280.0, 1_250.0, CONFIG).regime is MarketRegime.BULL


def test_insufficient_breadth_is_neutral_and_explained() -> None:
    result = classify_vnindex_regime(
        snapshot(advances=20.0, declines=0.0, unchanged=0.0),
        1_280.0,
        1_250.0,
        CONFIG,
    )

    assert result.regime is MarketRegime.NEUTRAL
    assert result.breadth_score is None
    assert result.breadth_issues == 20
    assert "below minimum 100" in result.reasons[1]


def test_ceiling_and_floor_do_not_double_count_breadth_denominator() -> None:
    base = snapshot()
    changed = replace(base, ceiling_count=300.0, floor_count=300.0)

    first = classify_vnindex_regime(base, 1_280.0, 1_250.0, CONFIG)
    second = classify_vnindex_regime(changed, 1_280.0, 1_250.0, CONFIG)

    assert first.breadth_score == second.breadth_score
    assert first.breadth_issues == second.breadth_issues


@pytest.mark.parametrize("threshold", [-0.01, 1.01, float("nan")])
def test_config_rejects_invalid_breadth_threshold(threshold: float) -> None:
    with pytest.raises(ValueError, match="breadth_threshold"):
        MarketRegimeConfig(threshold)


def test_config_rejects_invalid_minimum_breadth() -> None:
    with pytest.raises(TypeError, match="integer"):
        MarketRegimeConfig(0.2, True)
    with pytest.raises(ValueError, match="positive"):
        MarketRegimeConfig(0.2, 0)


def test_classifier_requires_normalized_vnindex_and_valid_ema() -> None:
    with pytest.raises(ValueError, match="VNINDEX"):
        classify_vnindex_regime(replace(snapshot(), symbol="VN30"), 1_280.0, 1_250.0, CONFIG)
    with pytest.raises(ValueError, match="finite"):
        classify_vnindex_regime(snapshot(), float("nan"), 1_250.0, CONFIG)
    with pytest.raises(ValueError, match="positive"):
        classify_vnindex_regime(snapshot(), 0.0, 1_250.0, CONFIG)


def test_classifier_revalidates_breadth_boundary() -> None:
    with pytest.raises(ValueError, match="advances"):
        classify_vnindex_regime(
            replace(snapshot(), advances=1.5), 1_280.0, 1_250.0, CONFIG
        )
