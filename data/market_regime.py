"""Provider-independent VNINDEX trend and market-breadth regime classifier."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from data.models import IndexSnapshot


class TrendState(str, Enum):
    BULLISH = "BULLISH"
    MIXED = "MIXED"
    BEARISH = "BEARISH"
    UNAVAILABLE = "UNAVAILABLE"


class MarketRegime(str, Enum):
    BULL = "BULL"
    NEUTRAL = "NEUTRAL"
    BEAR = "BEAR"


@dataclass(frozen=True, slots=True)
class MarketRegimeConfig:
    """Explicit, backtestable thresholds for market-regime classification."""

    breadth_threshold: float
    minimum_breadth_issues: int = 1

    def __post_init__(self) -> None:
        if not isfinite(self.breadth_threshold):
            raise ValueError("breadth_threshold must be finite")
        if not 0.0 <= self.breadth_threshold <= 1.0:
            raise ValueError("breadth_threshold must be between 0 and 1")
        if (
            not isinstance(self.minimum_breadth_issues, int)
            or isinstance(self.minimum_breadth_issues, bool)
        ):
            raise TypeError("minimum_breadth_issues must be an integer")
        if self.minimum_breadth_issues <= 0:
            raise ValueError("minimum_breadth_issues must be positive")


@dataclass(frozen=True, slots=True)
class MarketRegimeAssessment:
    """Explainable VNINDEX regime result for future signal consumers."""

    regime: MarketRegime
    trend: TrendState
    breadth_score: float | None
    breadth_issues: int
    reasons: tuple[str, ...]


def classify_vnindex_regime(
    snapshot: IndexSnapshot,
    ema20: float | None,
    ema50: float | None,
    config: MarketRegimeConfig,
) -> MarketRegimeAssessment:
    """Classify BULL/NEUTRAL/BEAR using VNINDEX trend and breadth together.

    Bull requires ``value > EMA20 > EMA50`` and positive breadth at or above
    the configured threshold. Bear requires the symmetric bearish conditions.
    Missing or conflicting evidence returns Neutral.
    """
    if not isinstance(snapshot, IndexSnapshot):
        raise TypeError("snapshot must be an IndexSnapshot")
    if snapshot.symbol != "VNINDEX":
        raise ValueError("market regime requires a normalized VNINDEX snapshot")
    if not isinstance(config, MarketRegimeConfig):
        raise TypeError("config must be a MarketRegimeConfig")
    _validate_snapshot_values(snapshot)

    trend = _trend_state(snapshot.value, ema20, ema50)
    breadth_issues_float = snapshot.advances + snapshot.declines + snapshot.unchanged
    breadth_issues = int(breadth_issues_float)
    breadth_score = (
        None
        if breadth_issues < config.minimum_breadth_issues
        else (snapshot.advances - snapshot.declines) / breadth_issues
    )

    reasons = [f"trend={trend.value}"]
    if breadth_score is None:
        reasons.append(
            f"breadth unavailable: {breadth_issues} issues below minimum "
            f"{config.minimum_breadth_issues}"
        )
        return MarketRegimeAssessment(
            MarketRegime.NEUTRAL,
            trend,
            None,
            breadth_issues,
            tuple(reasons),
        )

    reasons.append(f"breadth_score={breadth_score:.6f}")
    threshold = config.breadth_threshold
    if trend is TrendState.BULLISH and breadth_score >= threshold:
        regime = MarketRegime.BULL
        reasons.append("bullish trend and breadth confirmed")
    elif trend is TrendState.BEARISH and breadth_score <= -threshold:
        regime = MarketRegime.BEAR
        reasons.append("bearish trend and breadth confirmed")
    else:
        regime = MarketRegime.NEUTRAL
        reasons.append("trend and breadth are not jointly confirmed")

    return MarketRegimeAssessment(
        regime,
        trend,
        breadth_score,
        breadth_issues,
        tuple(reasons),
    )


def _trend_state(
    value: float, ema20: float | None, ema50: float | None
) -> TrendState:
    if ema20 is None or ema50 is None:
        return TrendState.UNAVAILABLE
    if not isfinite(ema20) or not isfinite(ema50):
        raise ValueError("EMA values must be finite when present")
    if ema20 <= 0 or ema50 <= 0:
        raise ValueError("EMA values must be positive when present")
    if value > ema20 > ema50:
        return TrendState.BULLISH
    if value < ema20 < ema50:
        return TrendState.BEARISH
    return TrendState.MIXED


def _validate_snapshot_values(snapshot: IndexSnapshot) -> None:
    numeric = (
        snapshot.value,
        snapshot.advances,
        snapshot.declines,
        snapshot.unchanged,
    )
    if not all(isfinite(value) for value in numeric):
        raise ValueError("VNINDEX regime inputs must be finite")
    if snapshot.value <= 0:
        raise ValueError("VNINDEX value must be positive")
    for name, value in (
        ("advances", snapshot.advances),
        ("declines", snapshot.declines),
        ("unchanged", snapshot.unchanged),
    ):
        if value < 0 or not float(value).is_integer():
            raise ValueError(f"{name} must be a non-negative whole count")
