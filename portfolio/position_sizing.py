"""Fixed-fractional risk sizing for a LONG trade (risk arithmetic only)."""

from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR

from portfolio.models import PortfolioError, PositionSizingResult


def size_position(
    symbol: str, entry: Decimal, stop: Decimal, capital: Decimal,
    risk_pct: Decimal, max_risk_pct: Decimal,
) -> PositionSizingResult:
    for label, value in (("Entry", entry), ("Stop", stop), ("Capital", capital)):
        if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
            raise PortfolioError(f"{label} must be greater than 0.")
    if stop >= entry:
        raise PortfolioError("Stop must be below entry for a long position.")
    if not isinstance(risk_pct, Decimal) or not risk_pct.is_finite() \
            or risk_pct <= 0 or risk_pct > max_risk_pct:
        raise PortfolioError(f"Risk % must be greater than 0 and at most {max_risk_pct:g}.")

    risk_budget = capital * risk_pct / Decimal(100)
    risk_per_share = entry - stop
    shares_by_risk = int(
        (risk_budget / risk_per_share).to_integral_value(rounding=ROUND_FLOOR)
    )
    shares_by_capital = int((capital / entry).to_integral_value(rounding=ROUND_FLOOR))
    # Long-only V1 never assumes leverage.  A very tight stop can otherwise make
    # fixed-fractional sizing return a position whose purchase price exceeds the
    # supplied capital even though its stop-loss budget is valid.
    shares = min(shares_by_risk, shares_by_capital)
    position_value = shares * entry
    notes = ["Shares are not rounded to the exchange lot size."]
    if shares == 0:
        notes.append("Risk budget is smaller than the risk on a single share.")
    if shares_by_capital < shares_by_risk:
        notes.append("Capped by available capital; no leverage is assumed.")
    return PositionSizingResult(
        symbol=symbol, capital=capital, risk_pct=risk_pct, entry=entry, stop=stop,
        risk_budget=risk_budget, risk_per_share=risk_per_share, shares=shares,
        position_value=position_value, max_loss=shares * risk_per_share,
        allocation_pct=position_value / capital * Decimal(100), notes=tuple(notes),
    )
