"""Presentation-free Phase 23 view models rendered by the portfolio formatters.

They compose the immutable domain results with the Phase 22 ``DataQualityView``;
no computation and no I/O happens here.  ``PositionSizingResult`` is already a
presentation-free value object and is rendered directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from portfolio.models import PortfolioRiskAssessment, PortfolioSnapshot, StressTestResult
from runtime.views import DataQualityView, Freshness


@dataclass(frozen=True, slots=True)
class WatchlistItemView:
    symbol: str
    price: Decimal | None
    trend: str | None
    strategy_state: str | None
    session_date: str | None
    freshness: Freshness


@dataclass(frozen=True, slots=True)
class WatchlistView:
    items: tuple[WatchlistItemView, ...]
    data_quality: DataQualityView | None


@dataclass(frozen=True, slots=True)
class PortfolioView:
    snapshot: PortfolioSnapshot
    data_quality: DataQualityView


@dataclass(frozen=True, slots=True)
class PortfolioRiskView:
    assessment: PortfolioRiskAssessment
    data_quality: DataQualityView


@dataclass(frozen=True, slots=True)
class StressTestView:
    result: StressTestResult
    data_quality: DataQualityView


@dataclass(frozen=True, slots=True)
class PortfolioContextView:
    """Informational `/soi` section; it never alters strategy state."""

    symbol: str
    held: bool
    quantity: int | None = None
    weight_pct: Decimal | None = None
    pnl_pct: Decimal | None = None
    sector_label: str | None = None
    sector_weight_pct: Decimal | None = None
    concentration_note: str | None = None
    valuation_note: str | None = None