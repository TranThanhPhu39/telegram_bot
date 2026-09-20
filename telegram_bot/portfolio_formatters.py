"""Telegram rendering for Phase 23 views.

Formatters only render values that services already computed.  Missing values
print as ``unavailable``; ``None``, ``NaN`` and ``inf`` never reach the user.
"""

from __future__ import annotations

from decimal import Decimal
import math

from portfolio.models import PositionSizingResult, StressTestResult
from portfolio.service import RiskSettings
from runtime.portfolio_views import (
    PortfolioContextView,
    PortfolioRiskView,
    PortfolioView,
    StressTestView,
    WatchlistView,
)
from runtime.views import DataQualityView, Freshness

UNAVAILABLE = "unavailable"
COST_BASIS_NOTE = "P&L is unrealized; average cost is user-supplied and fees/taxes are excluded."
EXECUTION_NOTE = "Risk calculation only; not an execution instruction."
STRESS_NOTE = "Deterministic price-shock arithmetic, not a forecast. " + EXECUTION_NOTE
TREND_LABELS = {
    "TĂNG": "Bullish",
    "TĂNG NGẮN HẠN": "Short-term bullish",
    "GIẢM": "Bearish",
    "TRUNG TÍNH": "Neutral",
    "CHƯA ĐỦ DỮ LIỆU": "Insufficient data",
}
_MILLION = Decimal(10) ** 6
_BILLION = Decimal(10) ** 9


# ------------------------------------------------------------------ helpers

def _finite(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, Decimal):
        return value.is_finite()
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    return False


def _trim(value: Decimal) -> str:
    text = f"{value:.2f}"
    return text[:-1] if text.endswith("0") else text


def money(value: Decimal | float | int | None, *, signed: bool = False) -> str:
    """VND in B/M shorthand (`535.0M`, `93.75M`); plain thousands below 1M."""
    if not _finite(value):
        return UNAVAILABLE
    number = Decimal(str(value)) if not isinstance(value, Decimal) else value
    sign = "-" if number < 0 else ("+" if signed and number > 0 else "")
    magnitude = abs(number)
    if magnitude >= _BILLION:
        body = _trim(magnitude / _BILLION) + "B"
    elif magnitude >= _MILLION:
        body = _trim(magnitude / _MILLION) + "M"
    else:
        body = f"{magnitude:,.0f}"
    return sign + body


def price(value: Decimal | float | None) -> str:
    if not _finite(value):
        return UNAVAILABLE
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    return f"{number:,.0f}" if number == number.to_integral_value() else f"{number:,.2f}"


def pct(value: Decimal | float | None, digits: int = 1, *, signed: bool = False) -> str:
    if not _finite(value):
        return UNAVAILABLE
    return f"{value:+.{digits}f}%" if signed else f"{value:.{digits}f}%"


def _compact(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _plain(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text if "." in text else text + ".0"


def _shock(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text if text.startswith("-") or value == 0 else "+" + text


def market_status(quality: DataQualityView) -> str:
    cached = "sqlite" in quality.market_source.lower()
    label = {
        Freshness.REALTIME: "Realtime",
        Freshness.EOD_TODAY: "Cached EOD (today)" if cached else "EOD (today)",
        Freshness.EOD: "Cached EOD" if cached else "EOD",
        Freshness.STALE: "Stale",
        Freshness.UNAVAILABLE: "Unavailable",
    }[quality.freshness]
    if quality.staleness_days and quality.freshness is not Freshness.UNAVAILABLE:
        label += f" ({quality.staleness_days} days old)"
    return label


def data_block(quality: DataQualityView | None) -> str:
    if quality is None:
        return "DATA\nMarket:\nUnavailable"
    lines = [
        "DATA",
        f"Market: {market_status(quality)}",
        f"Session: {quality.session_date or UNAVAILABLE}",
        f"Source: {quality.market_source}",
    ]
    lines.extend(f"- {note}" for note in quality.notes)
    if quality.freshness is Freshness.STALE:
        lines.append("- Data is stale; refresh before relying on these figures.")
    return "\n".join(lines)


# ---------------------------------# ---------------------------------------------------------------- watchlist

def format_watchlist(view: WatchlistView) -> str:
    if not view.items:
        return "⭐ WATCHLIST\n\nYour watchlist is empty.\nAdd a stock: /addwatch FPT"
    blocks = ["⭐ WATCHLIST"]
    for index, item in enumerate(view.items, start=1):
        lines = [f"{index}. {item.symbol}", f"   Price: {price(item.price)}"]
        if item.price is not None:
            trend = TREND_LABELS.get(item.trend or "", item.trend or UNAVAILABLE)
            state = f"{item.strategy_state} (CL1)" if item.strategy_state else UNAVAILABLE
            lines += [f"   Trend: {trend}", f"   Strategy: {state}"]
        blocks.append("\n".join(lines))
    blocks.append(data_block(view.data_quality))
    return "\n\n".join(blocks)


def format_watch_change(symbol: str, changed: bool, *, added: bool) -> str:
    if added:
        return f"⭐ {symbol} added to your watchlist." if changed \
            else f"{symbol} is already on your watchlist."
    return f"{symbol} removed from your watchlist." if changed \
        else f"{symbol} is not on your watchlist."


# ---------------------------------------------------------------- portfolio

def format_portfolio(view: PortfolioView) -> str:
    snap = view.snapshot
    if not snap.holdings:
        return "💼 MY PORTFOLIO\n\nNo holdings yet.\nAdd one: /addholding FPT 1000 150000"
    priced = len(snap.priced_holdings)
    label = "Market value" if snap.complete else "Market value (priced holdings)"
    summary = [
        "💼 MY PORTFOLIO",
        f"{label}:\n{money(snap.market_value)} VND" if priced else f"{label}:\n{UNAVAILABLE}",
        f"Cost:\n{money(snap.total_cost)} VND" if priced else f"Cost:\n{UNAVAILABLE}",
        "UNREALIZED P&L:\n" + (
            f"{money(snap.unrealized_pnl, signed=True)} ({pct(snap.unrealized_pnl_pct, signed=True)})"
            if priced else UNAVAILABLE
        ),
        f"Holdings:\n{len(snap.holdings)}",
    ]
    if not snap.complete:
        summary.append(
            f"⚠ Valuation incomplete: {len(snap.unpriced_symbols)} of {len(snap.holdings)} "
            f"holdings have no price ({', '.join(snap.unpriced_symbols)})."
        )
    blocks = ["\n\n".join(summary)]
    lines = []
    for index, item in enumerate(snap.holdings, start=1):
        lines.append(
            f"{index}. {item.symbol}\n"
            f"   Qty: {item.quantity:,}\n"
            f"   Avg cost: {price(item.average_cost)}\n"
            f"   Price: {price(item.price)}\n"
            f"   Value: {money(item.market_value)}\n"
            f"   P&L: {pct(item.unrealized_pnl_pct, signed=True)}\n"
            f"   Weight: {pct(item.weight_pct)}"
        )
    blocks.append("\n\n".join(lines))
    if snap.sector_exposure:
        blocks.append("SECTOR EXPOSURE\n" + "\n".join(
            f"{item.label}: {pct(item.weight_pct)}" for item in snap.sector_exposure
        ))
    risk = ["RISK"]
    if snap.largest_position is not None:
        risk.append(f"Largest position:\n{snap.largest_position.symbol} {pct(snap.largest_position.weight_pct)}")
    if snap.largest_sector is not None:
        risk.append(f"Largest sector:\n{snap.largest_sector.label} {pct(snap.largest_sector.weight_pct)}")
    if len(risk) > 1:
        blocks.append("\n".join(risk))
    if snap.concentration:
        blocks.append(_concentration_block(snap.concentration))
    blocks.append(data_block(view.data_quality))
    blocks.append(COST_BASIS_NOTE)
    return "\n\n".join(blocks)


def _concentration_block(warnings) -> str:
    lines = ["⚠ CONCENTRATION"]
    for item in warnings:
        what = "of portfolio" if item.kind == "STOCK" else "of portfolio (sector)"
        lines.append(f"{item.subject}: {pct(item.weight_pct)} {what} — {item.status.value}")
    lines.append("Exposure warnings, not predictions.")
    return "\n".join(lines)


# --------------------------------------------------------------------- risk

def format_risk(view: PortfolioRiskView) -> str:
    assessment = view.assessment
    snap = assessment.snapshot
    if not snap.holdings:
        return "⚠ PORTFOLIO RISK\n\nNo holdings yet.\nAdd one: /addholding FPT 1000 150000"
    priced = len(snap.priced_holdings)
    blocks = [
        "⚠ PORTFOLIO RISK",
        f"Value:\n{money(snap.market_value) if priced else UNAVAILABLE}"
        + ("" if snap.complete else " (priced holdings only)"),
        f"Holdings:\n{len(snap.holdings)}",
        "Largest position:\n" + (
            UNAVAILABLE if snap.largest_position is None
            else f"{snap.largest_position.symbol} {pct(snap.largest_position.weight_pct)}"
        ),
        "Largest sector:\n" + (
            "Unavailable (sector data missing)" if snap.largest_sector is None
            else f"{snap.largest_sector.label} {pct(snap.largest_sector.weight_pct)}"
        ),
        f"Concentration:\n{assessment.overall_concentration.value}"
        if priced else f"Concentration:\n{UNAVAILABLE}",
    ]
    unknown = next((e for e in snap.sector_exposure if e.sector_code is None), None)
    if unknown is not None:
        blocks.append(f"Unknown sector:\n{pct(unknown.weight_pct)} of value")
    if snap.concentration:
        blocks.append(_concentration_block(snap.concentration))
    if not snap.complete:
        blocks.append(
            "⚠ Data completeness: " f"{priced}/{len(snap.holdings)} holdings priced "
            f"(missing: {', '.join(snap.unpriced_symbols)})."
        )
    blocks.append(_historical_block(assessment.historical))
    blocks.append(data_block(view.data_quality))
    return "\n\n".join(blocks)


def _historical_block(risk) -> str:
    lines = ["HISTORICAL (static-weight proxy: current weights over past daily returns)"]
    lines.append("Volatility (annualized):\n" + (
        f"Unavailable — {risk.unavailable_reason or 'insufficient data'}"
        if not _finite(risk.annualized_volatility_pct)
        else pct(risk.annualized_volatility_pct)
    ))
    lines.append("Beta vs VNINDEX:\n" + (
        f"Unavailable — {risk.beta_unavailable_reason or 'insufficient data'}"
        if not _finite(risk.beta_vs_vnindex) else f"{risk.beta_vs_vnindex:.2f}"
    ))
    lines.append("Max drawdown:\n" + (
        f"Unavailable — {risk.unavailable_reason or 'insufficient data'}"
        if not _finite(risk.max_drawdown_pct)
        else pct(risk.max_drawdown_pct)
    ))
    if risk.sessions:
        lines.append(f"Window: {risk.window_start} to {risk.window_end} ({risk.sessions} daily returns)")
        lines.append("Not the account's actual drawdown or a forecast.")
    return "\n".join(lines)


# ------------------------------------------------------------------- sizing

def format_position_size(result: PositionSizingResult) -> str:
    lines = [
        "📐 POSITION SIZE",
        result.symbol,
        f"Capital:\n{money(result.capital)}",
        f"Risk budget:\n{_plain(result.risk_pct)}%",
        f"Entry:\n{price(result.entry)}",
        f"Stop:\n{price(result.stop)}",
        f"Risk/share:\n{price(result.risk_per_share)}",
        f"Max risk:\n{money(result.max_loss)}",
        f"Position size under this risk budget:\n{result.shares:,} shares",
        f"Position value:\n{money(result.position_value)}",
        f"Portfolio allocation:\n{pct(result.allocation_pct, 2)}",
    ]
    lines.extend(f"- {note}" for note in result.notes)
    lines.append(EXECUTION_NOTE)
    return "\n\n".join(lines)


def format_risk_settings(settings: RiskSettings) -> str:
    origin = "set by you" if settings.is_custom else "configured default"
    return (
        "⚙ RISK SETTINGS\n\n"
        f"Default risk/trade:\n{_compact(settings.default_risk_pct)}% ({origin})\n\n"
        f"Maximum allowed:\n{_compact(settings.max_risk_pct)}%"
    )


# ------------------------------------------------------------------- stress

def format_stress(view: StressTestView) -> str:
    result: StressTestResult = view.result
    shock = _shock(result.shock_pct)
    if result.scenario == "PORTFOLIO":
        scenario = f"All holdings {shock}%"
        change_label = "Estimated loss" if result.target_change <= 0 else "Estimated gain"
        lines = [
            "🧪 STRESS TEST",
            f"Scenario:\n{scenario}",
            f"Current value:\n{money(result.current_value)}",
            f"{change_label}:\n{money(result.target_change)}",
            f"Estimated value:\n{money(result.new_portfolio_value)}",
            f"Impact:\n{pct(result.portfolio_impact_pct, 1, signed=True)}",
        ]
    else:
        lines = [
            "🧪 STRESS TEST",
            f"Scenario:\n{result.symbol} {shock}%",
            f"{result.symbol} current value:\n{money(result.target_value)}",
            f"Estimated impact:\n{money(result.target_change)}",
            f"Portfolio impact:\n{pct(result.portfolio_impact_pct, 2, signed=True)}",
            f"New portfolio value:\n{money(result.new_portfolio_value)}",
        ]
    if result.excluded_symbols:
        lines.append(
            "⚠ Valuation incomplete; excluded (no price): " + ", ".join(result.excluded_symbols)
        )
    lines.append(data_block(view.data_quality))
    lines.append(STRESS_NOTE)
    return "\n\n".join(lines)


# ------------------------------------------------------------ `/soi` context

def format_portfolio_context(context: PortfolioContextView | None) -> str:
    if context is None:
        return ""
    if not context.held:
        return "💼 PORTFOLIO CONTEXT\nHolding: No"
    lines = [
        "💼 PORTFOLIO CONTEXT",
        "Holding: Yes",
        f"Quantity: {context.quantity:,}" if context.quantity is not None else "Quantity: unavailable",
        f"Current weight: {pct(context.weight_pct)}",
        f"P&L: {pct(context.pnl_pct, signed=True)} (unrealized)",
    ]
    if context.sector_label is not None:
        lines.append(f"Sector exposure: {context.sector_label} {pct(context.sector_weight_pct)}")
    if context.concentration_note:
        lines.append(f"⚠ Portfolio context:\n{context.concentration_note}")
    if context.valuation_note:
        lines.append(context.valuation_note)
    return "\n".join(lines)