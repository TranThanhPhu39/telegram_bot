"""Explainable fundamental context/filter; never a direct signal trigger."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Mapping, Sequence

from fundamentals.models import FundamentalSnapshot
from scanner.universe import ScreenedSymbol


class FundamentalStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class FundamentalFilterConfig:
    minimum_eps: float
    maximum_pe: float
    maximum_pb: float
    minimum_roe_percent: float
    minimum_revenue_growth_percent: float
    minimum_profit_growth_percent: float

    def __post_init__(self) -> None:
        for name in self.__slots__:
            value = getattr(self, name)
            if not isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.maximum_pe <= 0 or self.maximum_pb <= 0:
            raise ValueError("maximum valuation multiples must be positive")


@dataclass(frozen=True, slots=True)
class FundamentalAssessment:
    symbol: str
    status: FundamentalStatus
    positive_factors: tuple[str, ...]
    negative_factors: tuple[str, ...]
    missing_fields: tuple[str, ...]
    source: str
    as_of_date: str

    def to_context(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "positive_factors": list(self.positive_factors),
            "negative_factors": list(self.negative_factors),
            "missing_fields": list(self.missing_fields),
            "source": self.source,
            "as_of_date": self.as_of_date,
        }


def assess_fundamentals(
    snapshot: FundamentalSnapshot, config: FundamentalFilterConfig
) -> FundamentalAssessment:
    checks = (
        ("eps", snapshot.eps, ">=", config.minimum_eps),
        ("pe", snapshot.pe, "<=", config.maximum_pe),
        ("pb", snapshot.pb, "<=", config.maximum_pb),
        ("roe_percent", snapshot.roe_percent, ">=", config.minimum_roe_percent),
        ("revenue_growth_percent", snapshot.revenue_growth_percent, ">=", config.minimum_revenue_growth_percent),
        ("profit_growth_percent", snapshot.profit_growth_percent, ">=", config.minimum_profit_growth_percent),
    )
    positive: list[str] = []
    negative: list[str] = []
    missing: list[str] = []
    for name, value, operator, threshold in checks:
        if value is None:
            missing.append(name)
        elif (value >= threshold if operator == ">=" else value <= threshold):
            positive.append(f"{name}={value:g} {operator} {threshold:g}")
        else:
            negative.append(f"{name}={value:g} violates {operator} {threshold:g}")
    status = (
        FundamentalStatus.FAIL if negative else
        FundamentalStatus.INSUFFICIENT_DATA if missing else
        FundamentalStatus.PASS
    )
    return FundamentalAssessment(
        snapshot.symbol, status, tuple(positive), tuple(negative), tuple(missing),
        snapshot.source, snapshot.as_of_date.isoformat(),
    )


def apply_fundamental_filter(
    screened: Sequence[ScreenedSymbol],
    assessments: Mapping[str, FundamentalAssessment],
    *,
    include_insufficient: bool = False,
) -> tuple[ScreenedSymbol, ...]:
    """Apply context after technical/liquidity screening; never emit a signal."""
    accepted: list[ScreenedSymbol] = []
    for item in screened:
        assessment = assessments.get(item.symbol)
        if assessment is None:
            if include_insufficient:
                accepted.append(item)
            continue
        if assessment.status is FundamentalStatus.PASS or (
            include_insufficient and assessment.status is FundamentalStatus.INSUFFICIENT_DATA
        ):
            accepted.append(item)
    return tuple(accepted)
