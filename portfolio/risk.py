"""Transparent concentration classification and static-weight historical risk.

Concentration is a plain threshold comparison (no opaque score).  Historical
volatility, beta and drawdown use DAILY simple returns of the *current* weights
held constant over the window ("static-weight proxy"); they are not the
account's realised statistics and are never fabricated when data is short.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
import math
import statistics

from portfolio.config import PortfolioConfig
from portfolio.models import ConcentrationStatus, HistoricalRisk

TRADING_DAYS = 252
_SEVERITY = {
    ConcentrationStatus.NORMAL: 0,
    ConcentrationStatus.WARNING: 1,
    ConcentrationStatus.HIGH: 2,
}


def classify(weight_pct: Decimal, warning_pct: Decimal, high_pct: Decimal) -> ConcentrationStatus:
    if weight_pct >= high_pct:
        return ConcentrationStatus.HIGH
    if weight_pct >= warning_pct:
        return ConcentrationStatus.WARNING
    return ConcentrationStatus.NORMAL


def classify_stock(weight_pct: Decimal, config: PortfolioConfig) -> ConcentrationStatus:
    return classify(weight_pct, config.single_stock_warning_pct, config.single_stock_high_pct)


def classify_sector(weight_pct: Decimal, config: PortfolioConfig) -> ConcentrationStatus:
    return classify(weight_pct, config.sector_warning_pct, config.sector_high_pct)


def worst_status(statuses) -> ConcentrationStatus:
    return max(statuses, key=_SEVERITY.__getitem__, default=ConcentrationStatus.NORMAL)


def _returns(closes: Mapping[str, float]) -> dict[str, tuple[str, float]]:
    """date -> (previous session date, simple return); skips non-positive closes."""
    ordered = sorted((d, c) for d, c in closes.items() if c is not None and c > 0)
    result: dict[str, tuple[str, float]] = {}
    for (prev_date, prev), (date, close) in zip(ordered, ordered[1:]):
        result[date] = (prev_date, close / prev - 1.0)
    return result


def _aligned_portfolio_returns(
    weights: Mapping[str, float], closes: Mapping[str, Mapping[str, float]]
) -> list[tuple[str, str, float]]:
    """(date, previous date, weighted return) where every holding shares the same session pair."""
    series = {symbol: _returns(closes[symbol]) for symbol in weights}
    common = set.intersection(*(set(item) for item in series.values())) if series else set()
    rows: list[tuple[str, str, float]] = []
    for date in sorted(common):
        previous = {series[symbol][date][0] for symbol in weights}
        if len(previous) != 1:
            continue  # holdings skipped different sessions: never mix frequencies
        value = sum(weights[s] * series[s][date][1] for s in weights)
        rows.append((date, previous.pop(), value))
    return rows


def historical_risk(
    weights_pct: Mapping[str, Decimal],
    closes: Mapping[str, Mapping[str, float]],
    benchmark: Mapping[str, float] | None,
    *,
    lookback: int,
    min_sessions: int,
) -> HistoricalRisk:
    def unavailable(reason: str) -> HistoricalRisk:
        return HistoricalRisk(None, None, None, None, None, None, reason, reason)

    total = sum(weights_pct.values(), Decimal(0))
    if not weights_pct or total <= 0:
        return unavailable("No priced holdings.")
    missing = sorted(s for s in weights_pct if len(closes.get(s, {})) < 2)
    if missing:
        return unavailable("Daily history unavailable for " + ", ".join(missing) + ".")
    weights = {s: float(w / total) for s, w in weights_pct.items()}
    rows = _aligned_portfolio_returns(weights, closes)[-lookback:]
    if len(rows) < min_sessions:
        return unavailable(
            f"Only {len(rows)} aligned daily sessions across holdings; need {min_sessions}."
        )
    values = [row[2] for row in rows]
    volatility = statistics.stdev(values) * math.sqrt(TRADING_DAYS) * 100.0
    equity = peak = 1.0
    drawdown = 0.0
    for value in values:
        equity *= 1.0 + value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1.0)
    beta, beta_reason = _beta(rows, benchmark, min_sessions)
    return HistoricalRisk(
        sessions=len(rows),
        annualized_volatility_pct=volatility,
        beta_vs_vnindex=beta,
        max_drawdown_pct=drawdown * 100.0,
        window_start=rows[0][0],
        window_end=rows[-1][0],
        beta_unavailable_reason=beta_reason,
    )


def _beta(rows, benchmark, min_sessions) -> tuple[float | None, str | None]:
    if not benchmark:
        return None, "VNINDEX history unavailable."
    market = _returns(benchmark)
    pairs = [
        (value, market[date][1])
        for date, previous, value in rows
        if date in market and market[date][0] == previous
    ]
    if len(pairs) < min_sessions:
        return None, f"Only {len(pairs)} sessions aligned with VNINDEX; need {min_sessions}."
    portfolio = [p for p, _ in pairs]
    index = [m for _, m in pairs]
    variance = statistics.variance(index)
    if variance <= 0:
        return None, "VNINDEX variance is zero over the window."
    mean_p, mean_m = statistics.fmean(portfolio), statistics.fmean(index)
    covariance = sum((p - mean_p) * (m - mean_m) for p, m in pairs) / (len(pairs) - 1)
    return covariance / variance, None