"""Point-in-time ASMF scores derived from persisted EOD inputs."""

from __future__ import annotations

from datetime import date
import sqlite3
from typing import Mapping, Sequence

from asmf_data.store import (
    active_sector, latest_bank_financial_reports, latest_financial_reports,
    recent_flows, sector_members,
)
from asmf_data.quarters import analyze_quarter_continuity
from data.models import OHLCVBar


def fundamental_score(connection: sqlite3.Connection, symbol: str, as_of: date) -> float | None:
    # The presence of point-in-time bank rows identifies the bank branch.  An
    # incomplete bank score must stay unavailable; it must never fall through
    # to industrial-company leverage rules.
    if latest_bank_financial_reports(connection, symbol, as_of):
        return bank_fundamental_score(connection, symbol, as_of)
    reports = latest_financial_reports(connection, symbol, as_of)
    continuity = analyze_quarter_continuity(
        (row["report_period"] for row in reports), required=8
    )
    if not continuity.ready:
        return None
    by_period = {row["report_period"]: row for row in reports}
    ordered = tuple(by_period[period] for period in continuity.expected)
    current, previous = ordered[:4], ordered[4:8]
    revenue_now = sum(row["revenue"] for row in current)
    revenue_before = sum(row["revenue"] for row in previous)
    profit_now = sum(row["net_profit"] for row in current)
    profit_before = sum(row["net_profit"] for row in previous)
    latest = current[0]
    if revenue_before <= 0 or profit_before <= 0 or previous[0]["net_profit"] <= 0 or previous[1]["net_profit"] <= 0:
        return None
    roe = profit_now / latest["equity"] * 100
    revenue_growth = (revenue_now / revenue_before - 1) * 100
    profit_growth = (profit_now / profit_before - 1) * 100
    latest_profit_growth = (current[0]["net_profit"] / previous[0]["net_profit"] - 1) * 100
    prior_profit_growth = (current[1]["net_profit"] / previous[1]["net_profit"] - 1) * 100
    debt_equity = latest["total_debt"] / latest["equity"]
    checks = (
        roe > 15,
        revenue_growth > 15,
        profit_growth > 15,
        latest_profit_growth > prior_profit_growth,
        debt_equity < 1.5,
    )
    return 100 * sum(checks) / len(checks)


def fundamental_status(connection: sqlite3.Connection, symbol: str, as_of: date) -> str:
    """Canonical PASS/FAIL/INSUFFICIENT mapping for every Fundamental consumer."""
    try:
        score = fundamental_score(connection, symbol, as_of)
    except (sqlite3.Error, ValueError, ZeroDivisionError):
        return "INSUFFICIENT"
    return fundamental_status_from_score(score)


def fundamental_status_from_score(score: float | None) -> str:
    """Map the canonical ASMF Fundamental score to its shared readiness state."""
    if score is None:
        return "INSUFFICIENT"
    return "PASS" if score >= 60 else "FAIL"


def bank_fundamental_score(connection: sqlite3.Connection, symbol: str, as_of: date) -> float | None:
    """Score banks without applying industrial-company leverage rules."""
    rows = latest_bank_financial_reports(connection, symbol, as_of)
    by_period = {row["report_period"]: row for row in rows}
    continuity = analyze_quarter_continuity(by_period, required=8)
    if not continuity.ready:
        return None
    periods = list(continuity.expected)
    standalone: dict[str, tuple[float, float]] = {}
    for period in periods:
        row = by_period[period]
        quarter = int(period[-1])
        if quarter == 1:
            standalone[period] = (row["net_interest_income"], row["net_profit"])
            continue
        prior = by_period.get(f"{period[:4]}Q{quarter - 1}")
        if prior is None:
            return None
        standalone[period] = (
            row["net_interest_income"] - prior["net_interest_income"],
            row["net_profit"] - prior["net_profit"],
        )
    current_periods, previous_periods = periods[:4], periods[4:8]
    nii_now = sum(standalone[p][0] for p in current_periods)
    nii_before = sum(standalone[p][0] for p in previous_periods)
    profit_now = sum(standalone[p][1] for p in current_periods)
    profit_before = sum(standalone[p][1] for p in previous_periods)
    latest = by_period[periods[0]]
    required = (latest["nonperforming_loans"], latest["loan_loss_reserve"], latest["car_percent"])
    if min(nii_before, profit_before) <= 0 or any(value is None for value in required):
        return None
    npl_ratio = latest["nonperforming_loans"] / latest["gross_loans"] * 100
    coverage = latest["loan_loss_reserve"] / latest["nonperforming_loans"] * 100 if latest["nonperforming_loans"] else 999.0
    roe = profit_now / latest["equity"] * 100
    checks = (
        roe > 15,
        (nii_now / nii_before - 1) * 100 > 10,
        (profit_now / profit_before - 1) * 100 > 15,
        npl_ratio < 3,
        coverage > 100,
        latest["car_percent"] >= 8,
    )
    return 100 * sum(checks) / len(checks)


def institutional_flow_score(connection: sqlite3.Connection, symbol: str, as_of: date) -> float | None:
    rows = recent_flows(connection, symbol, as_of)
    if len(rows) < 5:
        return None
    nets = []
    gross = 0.0
    for row in rows:
        values = [row[name] for name in ("foreign_buy_value", "foreign_sell_value",
                  "proprietary_buy_value", "proprietary_sell_value")]
        if all(value is None for value in values):
            continue
        buy = (values[0] or 0) + (values[2] or 0)
        sell = (values[1] or 0) + (values[3] or 0)
        nets.append(buy - sell)
        gross += buy + sell
    if not nets or gross <= 0:
        return None
    ratio = sum(nets) / gross
    return min(100.0, max(0.0, 50 + ratio * 100))


def sector_strength_score(
    connection: sqlite3.Connection,
    symbol: str,
    as_of: date,
    histories: Mapping[str, Sequence[OHLCVBar]],
    benchmark: Sequence[OHLCVBar],
) -> float | None:
    membership = active_sector(connection, symbol, as_of)
    if membership is None or len(benchmark) < 126:
        return None
    members = sector_members(connection, membership["sector_code"], as_of)
    usable = [tuple(histories[item]) for item in members if len(histories.get(item, ())) >= 126]
    if len(usable) < 5:
        return None
    breadth = sum(series[-1].close > _mean_close(series[-50:]) for series in usable) / len(usable)
    sector_returns = []
    for lookback, weight in ((21, .40), (63, .35), (126, .25)):
        stock_return = sum(series[-1].close / series[-lookback - 1].close - 1 for series in usable) / len(usable)
        benchmark_return = benchmark[-1].close / benchmark[-lookback - 1].close - 1
        sector_returns.append((stock_return - benchmark_return) * weight)
    rs = sum(sector_returns)
    rs_score = min(100.0, max(0.0, 50 + rs * 200))
    return .6 * rs_score + .4 * breadth * 100


def _mean_close(bars: Sequence[OHLCVBar]) -> float:
    return sum(bar.close for bar in bars) / len(bars)
