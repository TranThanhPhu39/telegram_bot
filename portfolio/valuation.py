"""Pure valuation: cost basis, market value, unrealised P&L, weights, exposure."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from portfolio.config import PortfolioConfig
from portfolio.models import (
    ConcentrationStatus,
    ConcentrationWarning,
    HoldingSnapshot,
    PortfolioHolding,
    PortfolioSnapshot,
    PriceQuote,
    SectorExposure,
    SectorInfo,
)
from portfolio.risk import classify_sector, classify_stock
from runtime.views import Freshness

UNKNOWN_SECTOR = "Unknown"
_HUNDRED = Decimal(100)
_RANK = {
    Freshness.REALTIME: 0, Freshness.EOD_TODAY: 1, Freshness.EOD: 2,
    Freshness.STALE: 3, Freshness.UNAVAILABLE: 4,
}


def build_snapshot(
    holdings: Sequence[PortfolioHolding],
    quotes: Mapping[str, PriceQuote],
    sectors: Mapping[str, SectorInfo | None],
    config: PortfolioConfig,
) -> PortfolioSnapshot:
    """Value priced holdings only; unpriced ones are listed, never treated as zero."""
    partial: list[tuple[PortfolioHolding, PriceQuote, Decimal | None, SectorInfo | None]] = []
    for holding in holdings:
        quote = quotes.get(holding.symbol) or PriceQuote(
            holding.symbol, None, None, Freshness.UNAVAILABLE, "unavailable"
        )
        price = quote.price if quote.price is not None and quote.price > 0 else None
        partial.append((holding, quote, price, sectors.get(holding.symbol)))

    total_cost = sum((h.quantity * h.average_cost for h, _, p, _ in partial if p is not None), Decimal(0))
    total_value = sum((h.quantity * p for h, _, p, _ in partial if p is not None), Decimal(0))

    snapshots: list[HoldingSnapshot] = []
    for holding, quote, price, sector in partial:
        cost = holding.quantity * holding.average_cost
        value = pnl = pnl_pct = weight = None
        if price is not None:
            value = holding.quantity * price
            pnl = value - cost
            pnl_pct = pnl / cost * _HUNDRED
            weight = value / total_value * _HUNDRED if total_value > 0 else None
        snapshots.append(HoldingSnapshot(
            holding.symbol, holding.quantity, holding.average_cost, cost, price, value,
            pnl, pnl_pct, weight,
            None if sector is None else sector.code,
            None if sector is None else sector.name,
            quote,
        ))

    priced = [s for s in snapshots if s.market_value is not None]
    exposure = _sector_exposure(priced, total_value)
    largest = max(priced, key=lambda s: (s.market_value, s.symbol), default=None)
    largest_sector = max(
        (item for item in exposure if item.sector_code is not None),
        key=lambda item: (item.market_value, item.label), default=None,
    )
    warnings = _warnings(priced, exposure, config)
    unpriced = tuple(s.symbol for s in snapshots if s.market_value is None)
    dates = tuple(sorted({s.quote.session_date for s in priced if s.quote.session_date}))
    notes: list[str] = []
    if len(dates) > 1:
        notes.append(f"Holdings are priced from different sessions ({dates[0]} to {dates[-1]}).")
    if unpriced:
        notes.append(
            "Price unavailable for " + ", ".join(unpriced)
            + "; excluded from value, weights and exposure (valuation incomplete)."
        )
    pnl_total = total_value - total_cost
    return PortfolioSnapshot(
        holdings=tuple(snapshots),
        total_cost=total_cost,
        market_value=total_value,
        unrealized_pnl=pnl_total,
        unrealized_pnl_pct=pnl_total / total_cost * _HUNDRED if total_cost > 0 else None,
        unpriced_symbols=unpriced,
        sector_exposure=exposure,
        concentration=warnings,
        largest_position=largest,
        largest_sector=largest_sector,
        freshness=max((s.quote.freshness for s in priced), key=_RANK.__getitem__,
                      default=Freshness.UNAVAILABLE),
        session_dates=dates,
        sources=tuple(dict.fromkeys(s.quote.source for s in priced)),
        notes=tuple(notes),
    )


def _sector_exposure(priced: Sequence[HoldingSnapshot], total: Decimal) -> tuple[SectorExposure, ...]:
    groups: dict[str | None, list[HoldingSnapshot]] = {}
    for item in priced:
        groups.setdefault(item.sector_code, []).append(item)
    result = []
    for code, items in groups.items():
        value = sum((i.market_value for i in items), Decimal(0))
        label = UNKNOWN_SECTOR if code is None else (items[0].sector_name or code)
        result.append(SectorExposure(
            code, label, value, value / total * _HUNDRED if total > 0 else Decimal(0),
            tuple(sorted(i.symbol for i in items)),
        ))
    return tuple(sorted(result, key=lambda e: (-e.market_value, e.label)))


def _warnings(priced, exposure, config: PortfolioConfig) -> tuple[ConcentrationWarning, ...]:
    result: list[ConcentrationWarning] = []
    for item in sorted(priced, key=lambda s: (-(s.weight_pct or 0), s.symbol)):
        status = classify_stock(item.weight_pct or Decimal(0), config)
        if status is not ConcentrationStatus.NORMAL:
            result.append(ConcentrationWarning(
                item.symbol, "STOCK", item.weight_pct, status,
                config.single_stock_warning_pct, config.single_stock_high_pct,
            ))
    for item in exposure:
        if item.sector_code is None:
            continue  # "Unknown" is missing data, not a sector
        status = classify_sector(item.weight_pct, config)
        if status is not ConcentrationStatus.NORMAL:
            result.append(ConcentrationWarning(
                item.label, "SECTOR", item.weight_pct, status,
                config.sector_warning_pct, config.sector_high_pct,
            ))
    return tuple(result)