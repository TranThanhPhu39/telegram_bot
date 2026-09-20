"""Deterministic price-shock arithmetic on current holdings (not a forecast)."""

from __future__ import annotations

from decimal import Decimal

from portfolio.models import PortfolioError, PortfolioSnapshot, StressTestResult

_HUNDRED = Decimal(100)


def stress_test(
    snapshot: PortfolioSnapshot, shock_pct: Decimal, symbol: str | None = None
) -> StressTestResult:
    if not isinstance(shock_pct, Decimal) or not shock_pct.is_finite() \
            or not (Decimal(-100) <= shock_pct <= _HUNDRED):
        raise PortfolioError("Shock must be a percentage between -100 and 100.")
    if not snapshot.holdings:
        raise PortfolioError("Your portfolio is empty. Add one with /addholding FPT 1000 150000")
    current = snapshot.market_value
    if not snapshot.priced_holdings or current <= 0:
        raise PortfolioError("Data unavailable: no holding has a usable price.")

    if symbol is None:
        change = current * shock_pct / _HUNDRED
        return StressTestResult(
            "PORTFOLIO", None, shock_pct, current, current, change, change,
            current + change, change / current * _HUNDRED, snapshot.unpriced_symbols,
        )
    symbol = symbol.strip().upper()
    holding = next((h for h in snapshot.holdings if h.symbol == symbol), None)
    if holding is None:
        raise PortfolioError(f"You do not hold {symbol}.")
    if holding.market_value is None:
        raise PortfolioError(f"Price unavailable for {symbol}; cannot stress it.")
    change = holding.market_value * shock_pct / _HUNDRED
    return StressTestResult(
        "SYMBOL", symbol, shock_pct, current, holding.market_value, change, change,
        current + change, change / current * _HUNDRED, snapshot.unpriced_symbols,
    )