"""Portfolio orchestration over the repository and an injected market-data port."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from portfolio.config import PortfolioConfig
from portfolio.models import (
    PortfolioError,
    PortfolioHolding,
    PortfolioRiskAssessment,
    PortfolioSnapshot,
    PositionSizingResult,
    PriceQuote,
    SectorInfo,
    StressTestResult,
    WatchlistEntry,
)
from portfolio.position_sizing import size_position
from portfolio.repository import SQLitePortfolioRepository, normalize_symbol
from portfolio.risk import classify_sector, classify_stock, historical_risk, worst_status
from portfolio.stress import stress_test
from portfolio.valuation import build_snapshot

SYMBOL_UNAVAILABLE = "Symbol not found or unavailable."


class MarketDataPort(Protocol):
    """Normalised market-data boundary; implemented by the runtime layer."""

    def quote(self, symbol: str) -> PriceQuote: ...
    def closes(self, symbol: str) -> Mapping[str, float]: ...
    def sector(self, symbol: str) -> SectorInfo | None: ...


@dataclass(frozen=True, slots=True)
class RiskSettings:
    default_risk_pct: Decimal
    max_risk_pct: Decimal
    is_custom: bool


class PortfolioService:
    def __init__(
        self, repository: SQLitePortfolioRepository, market: MarketDataPort,
        config: PortfolioConfig | None = None,
    ) -> None:
        self.repository = repository
        self.market = market
        self.config = config or PortfolioConfig()

    # ------------------------------------------------------------ watchlist

    def add_watch(self, user_id: int, symbol: str) -> bool:
        symbol = self._known_symbol(symbol)
        return self.repository.add_watch(user_id, symbol)

    def remove_watch(self, user_id: int, symbol: str) -> bool:
        return self.repository.remove_watch(user_id, symbol)

    def watchlist(self, user_id: int) -> tuple[WatchlistEntry, ...]:
        return self.repository.list_watchlist(user_id)

    # ------------------------------------------------------------- holdings

    def upsert_holding(
        self, user_id: int, symbol: str, quantity: int, average_cost: Decimal
    ) -> bool:
        """Validate then store; True when created, False when an existing holding was replaced."""
        symbol = normalize_symbol(symbol)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise PortfolioError("Quantity must be a whole number greater than 0.")
        if not isinstance(average_cost, Decimal) or not average_cost.is_finite() \
                or average_cost <= 0:
            raise PortfolioError("Average cost must be greater than 0.")
        self._known_symbol(symbol)
        return self.repository.upsert_holding(user_id, symbol, quantity, average_cost)

    def remove_holding(self, user_id: int, symbol: str) -> bool:
        return self.repository.remove_holding(user_id, symbol)

    def holdings(self, user_id: int) -> tuple[PortfolioHolding, ...]:
        return self.repository.list_holdings(user_id)

    # ------------------------------------------------------------ valuation

    def snapshot(self, user_id: int) -> PortfolioSnapshot:
        holdings = self.repository.list_holdings(user_id)
        quotes = {h.symbol: self.market.quote(h.symbol) for h in holdings}
        sectors = {h.symbol: self.market.sector(h.symbol) for h in holdings}
        return build_snapshot(holdings, quotes, sectors, self.config)

    def risk(self, user_id: int) -> PortfolioRiskAssessment:
        snapshot = self.snapshot(user_id)
        priced = snapshot.priced_holdings
        statuses = [classify_stock(h.weight_pct, self.config) for h in priced if h.weight_pct is not None]
        statuses += [
            classify_sector(e.weight_pct, self.config)
            for e in snapshot.sector_exposure if e.sector_code is not None
        ]
        weights = {h.symbol: h.weight_pct for h in priced if h.weight_pct is not None}
        closes = {symbol: self.market.closes(symbol) for symbol in weights}
        benchmark = self.market.closes("VNINDEX") if weights else None
        historical = historical_risk(
            weights, closes, benchmark,
            lookback=self.config.risk_lookback, min_sessions=self.config.risk_min_sessions,
        )
        return PortfolioRiskAssessment(snapshot, worst_status(statuses), historical)

    # --------------------------------------------------------- risk settings

    def risk_settings(self, user_id: int) -> RiskSettings:
        profile = self.repository.get_user(user_id)
        custom = profile.default_risk_per_trade_pct if profile else None
        return RiskSettings(
            custom if custom is not None else self.config.default_risk_per_trade_pct,
            self.config.max_risk_per_trade_pct, custom is not None,
        )

    def set_default_risk(self, user_id: int, risk_pct: Decimal) -> RiskSettings:
        if not isinstance(risk_pct, Decimal) or not risk_pct.is_finite() or risk_pct <= 0 \
                or risk_pct > self.config.max_risk_per_trade_pct:
            raise PortfolioError(
                f"Risk % must be greater than 0 and at most {self.config.max_risk_per_trade_pct:g}."
            )
        self.repository.set_default_risk(user_id, risk_pct)
        return self.risk_settings(user_id)

    # ------------------------------------------------- sizing and stress test

    def size(
        self, user_id: int, symbol: str, entry: Decimal, stop: Decimal,
        capital: Decimal, risk_pct: Decimal | None = None,
    ) -> PositionSizingResult:
        symbol = normalize_symbol(symbol)
        effective = risk_pct if risk_pct is not None else self.risk_settings(user_id).default_risk_pct
        return size_position(
            symbol, entry, stop, capital, effective, self.config.max_risk_per_trade_pct
        )

    def stress(
        self, user_id: int, shock_pct: Decimal, symbol: str | None = None,
        snapshot: PortfolioSnapshot | None = None,
    ) -> StressTestResult:
        if symbol is not None:
            symbol = normalize_symbol(symbol)
        return stress_test(snapshot or self.snapshot(user_id), shock_pct, symbol)

    # ------------------------------------------------------------ internals

    def _known_symbol(self, raw: str) -> str:
        symbol = normalize_symbol(raw)
        quote = self.market.quote(symbol)
        if quote.price is None:
            raise PortfolioError(SYMBOL_UNAVAILABLE)
        return symbol