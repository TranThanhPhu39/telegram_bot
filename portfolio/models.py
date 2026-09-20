"""Immutable Phase 23 domain models (long-only, VND, whole shares)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from runtime.views import Freshness


class PortfolioError(ValueError):
    """A user-facing validation or data problem; ``str(error)`` is safe to show."""


class ConcentrationStatus(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class UserProfile:
    telegram_user_id: int
    risk_profile: str | None
    default_risk_per_trade_pct: Decimal | None
    created_at: int
    updated_at: int


@dataclass(frozen=True, slots=True)
class WatchlistEntry:
    telegram_user_id: int
    symbol: str
    created_at: int


@dataclass(frozen=True, slots=True)
class PortfolioHolding:
    telegram_user_id: int
    symbol: str
    quantity: int
    average_cost: Decimal
    updated_at: int


@dataclass(frozen=True, slots=True)
class PriceQuote:
    """Latest usable price for one symbol, with its own data-quality facts."""

    symbol: str
    price: Decimal | None
    session_date: str | None
    freshness: Freshness
    source: str
    staleness_days: int | None = None


@dataclass(frozen=True, slots=True)
class SectorInfo:
    code: str
    name: str
    source: str | None = None


@dataclass(frozen=True, slots=True)
class HoldingSnapshot:
    symbol: str
    quantity: int
    average_cost: Decimal
    cost_basis: Decimal
    price: Decimal | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    unrealized_pnl_pct: Decimal | None
    weight_pct: Decimal | None
    sector_code: str | None
    sector_name: str | None
    quote: PriceQuote


@dataclass(frozen=True, slots=True)
class SectorExposure:
    sector_code: str | None
    label: str
    market_value: Decimal
    weight_pct: Decimal
    symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConcentrationWarning:
    subject: str
    kind: str  # "STOCK" | "SECTOR"
    weight_pct: Decimal
    status: ConcentrationStatus
    warning_threshold_pct: Decimal
    high_threshold_pct: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """Valuation of the priced holdings.

    Totals cover priced holdings only.  ``unpriced_symbols`` lists holdings that
    could not be valued; they are never treated as zero.
    """

    holdings: tuple[HoldingSnapshot, ...]
    total_cost: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: Decimal | None
    unpriced_symbols: tuple[str, ...]
    sector_exposure: tuple[SectorExposure, ...]
    concentration: tuple[ConcentrationWarning, ...]
    largest_position: HoldingSnapshot | None
    largest_sector: SectorExposure | None
    freshness: Freshness
    session_dates: tuple[str, ...]
    sources: tuple[str, ...]
    notes: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.unpriced_symbols

    @property
    def priced_holdings(self) -> tuple[HoldingSnapshot, ...]:
        return tuple(item for item in self.holdings if item.market_value is not None)


@dataclass(frozen=True, slots=True)
class HistoricalRisk:
    """Static-weight historical proxy; never an actual account statistic."""

    sessions: int | None
    annualized_volatility_pct: float | None
    beta_vs_vnindex: float | None
    max_drawdown_pct: float | None
    window_start: str | None
    window_end: str | None
    unavailable_reason: str | None = None
    beta_unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PortfolioRiskAssessment:
    snapshot: PortfolioSnapshot
    overall_concentration: ConcentrationStatus
    historical: HistoricalRisk


@dataclass(frozen=True, slots=True)
class PositionSizingResult:
    symbol: str
    capital: Decimal
    risk_pct: Decimal
    entry: Decimal
    stop: Decimal
    risk_budget: Decimal
    risk_per_share: Decimal
    shares: int
    position_value: Decimal
    max_loss: Decimal
    allocation_pct: Decimal
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StressTestResult:
    scenario: str  # "PORTFOLIO" | "SYMBOL"
    symbol: str | None
    shock_pct: Decimal
    current_value: Decimal
    target_value: Decimal
    target_change: Decimal
    portfolio_change: Decimal
    new_portfolio_value: Decimal
    portfolio_impact_pct: Decimal
    excluded_symbols: tuple[str, ...] = ()