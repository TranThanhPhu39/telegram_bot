"""Point-in-time fundamental facts assembled from data the repo already stores.

Two independent sources are supported and never mixed silently:

* consolidated quarterly reports already persisted for ASMF (SQLite), which can
  establish ROE, growth and leverage but *cannot* establish P/E or P/B because
  no share count is stored;
* an optional controlled CSV snapshot (``FUNDAMENTALS_CSV_PATH``) that carries
  EPS/P/E/P/B with mandatory per-row provenance.

Anything neither source establishes stays ``None`` and is reported as missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import sqlite3

from asmf_data.store import latest_bank_financial_reports, latest_financial_reports
from fundamentals.csv_source import load_fundamental_csv
from fundamentals.models import FundamentalSnapshot


@dataclass(frozen=True, slots=True)
class FundamentalFacts:
    """Normalized fundamentals with explicit provenance and coverage."""

    symbol: str
    kind: str
    period: str | None
    as_of: str | None
    source: str
    eps: float | None = None
    pe: float | None = None
    pb: float | None = None
    roe_percent: float | None = None
    revenue_growth_percent: float | None = None
    profit_growth_percent: float | None = None
    debt_to_equity: float | None = None
    npl_percent: float | None = None
    coverage_percent: float | None = None
    car_percent: float | None = None

    @property
    def missing_fields(self) -> tuple[str, ...]:
        names = {
            "EPS": self.eps, "P/E": self.pe, "P/B": self.pb,
            "ROE": self.roe_percent,
            "Tăng trưởng doanh thu": self.revenue_growth_percent,
            "Tăng trưởng LNST": self.profit_growth_percent,
        }
        if self.kind == "BANK":
            names.pop("Tăng trưởng doanh thu")
            names["NPL"] = self.npl_percent
            names["CAR"] = self.car_percent
        else:
            names["Debt/Equity"] = self.debt_to_equity
        return tuple(label for label, value in names.items() if value is None)


def load_fundamental_facts(
    connection: sqlite3.Connection,
    symbol: str,
    as_of: date,
    *,
    csv_path: str | Path | None = None,
) -> FundamentalFacts | None:
    """Return merged facts, or ``None`` when no source covers the symbol."""
    symbol = symbol.strip().upper()
    stored = _from_sqlite(connection, symbol, as_of)
    snapshot = _from_csv(csv_path, symbol, as_of)
    if stored is None and snapshot is None:
        return None
    if stored is None:
        return FundamentalFacts(
            symbol=symbol, kind="CORPORATE", period=None,
            as_of=snapshot.as_of_date.isoformat(), source=snapshot.source,
            eps=snapshot.eps, pe=snapshot.pe, pb=snapshot.pb,
            roe_percent=snapshot.roe_percent,
            revenue_growth_percent=snapshot.revenue_growth_percent,
            profit_growth_percent=snapshot.profit_growth_percent,
        )
    if snapshot is None:
        return stored
    sources = tuple(dict.fromkeys((stored.source, snapshot.source)))
    return FundamentalFacts(
        symbol=symbol,
        kind=stored.kind,
        period=stored.period,
        as_of=max(filter(None, (stored.as_of, snapshot.as_of_date.isoformat()))),
        source=" + ".join(sources),
        eps=snapshot.eps,
        pe=snapshot.pe,
        pb=snapshot.pb,
        roe_percent=stored.roe_percent if stored.roe_percent is not None else snapshot.roe_percent,
        revenue_growth_percent=(
            stored.revenue_growth_percent
            if stored.revenue_growth_percent is not None
            else snapshot.revenue_growth_percent
        ),
        profit_growth_percent=(
            stored.profit_growth_percent
            if stored.profit_growth_percent is not None
            else snapshot.profit_growth_percent
        ),
        debt_to_equity=stored.debt_to_equity,
        npl_percent=stored.npl_percent,
        coverage_percent=stored.coverage_percent,
        car_percent=stored.car_percent,
    )


def _from_sqlite(
    connection: sqlite3.Connection, symbol: str, as_of: date
) -> FundamentalFacts | None:
    bank_rows = latest_bank_financial_reports(connection, symbol, as_of)
    if bank_rows:
        return _bank_facts(symbol, bank_rows)
    rows = latest_financial_reports(connection, symbol, as_of)
    if not rows:
        return None
    return _corporate_facts(symbol, rows)


def _corporate_facts(symbol: str, rows) -> FundamentalFacts:
    latest = rows[0]
    equity = latest["equity"]
    roe = revenue_growth = profit_growth = None
    if len(rows) >= 8:
        current, previous = rows[:4], rows[4:8]
        revenue_now = sum(row["revenue"] for row in current)
        revenue_before = sum(row["revenue"] for row in previous)
        profit_now = sum(row["net_profit"] for row in current)
        profit_before = sum(row["net_profit"] for row in previous)
        if equity > 0:
            roe = profit_now / equity * 100.0
        if revenue_before > 0:
            revenue_growth = (revenue_now / revenue_before - 1.0) * 100.0
        if profit_before > 0:
            profit_growth = (profit_now / profit_before - 1.0) * 100.0
    return FundamentalFacts(
        symbol=symbol,
        kind="CORPORATE",
        period=latest["report_period"],
        as_of=latest["public_date"],
        source=latest["source"],
        roe_percent=roe,
        revenue_growth_percent=revenue_growth,
        profit_growth_percent=profit_growth,
        debt_to_equity=latest["total_debt"] / equity if equity > 0 else None,
    )


def _bank_facts(symbol: str, rows) -> FundamentalFacts:
    by_period = {row["report_period"]: row for row in rows}
    periods = sorted(by_period, reverse=True)
    latest = by_period[periods[0]]
    equity = latest["equity"]
    roe = profit_growth = None
    standalone = _standalone_quarters(by_period, periods[:8])
    if standalone is not None and len(standalone) == 8:
        ordered = [standalone[period] for period in periods[:8]]
        profit_now = sum(value[1] for value in ordered[:4])
        profit_before = sum(value[1] for value in ordered[4:8])
        if equity > 0:
            roe = profit_now / equity * 100.0
        if profit_before > 0:
            profit_growth = (profit_now / profit_before - 1.0) * 100.0
    npl = latest["nonperforming_loans"]
    reserve = latest["loan_loss_reserve"]
    gross = latest["gross_loans"]
    return FundamentalFacts(
        symbol=symbol,
        kind="BANK",
        period=latest["report_period"],
        as_of=latest["public_date"],
        source=latest["source"],
        roe_percent=roe,
        profit_growth_percent=profit_growth,
        npl_percent=None if npl is None or not gross else npl / gross * 100.0,
        coverage_percent=None if not npl or reserve is None else reserve / npl * 100.0,
        car_percent=latest["car_percent"],
    )


def _standalone_quarters(by_period, periods) -> dict[str, tuple[float, float]] | None:
    """De-cumulate bank year-to-date rows; give up rather than approximate."""
    result: dict[str, tuple[float, float]] = {}
    for period in periods:
        row = by_period[period]
        quarter = int(period[-1])
        if quarter == 1:
            result[period] = (row["net_interest_income"], row["net_profit"])
            continue
        prior = by_period.get(f"{period[:4]}Q{quarter - 1}")
        if prior is None:
            return None
        result[period] = (
            row["net_interest_income"] - prior["net_interest_income"],
            row["net_profit"] - prior["net_profit"],
        )
    return result


def _from_csv(
    csv_path: str | Path | None, symbol: str, as_of: date
) -> FundamentalSnapshot | None:
    if not csv_path:
        return None
    path = Path(csv_path)
    if not path.exists():
        return None
    try:
        snapshots = load_fundamental_csv(path)
    except (OSError, ValueError):
        return None
    usable = [
        item for item in snapshots
        if item.symbol == symbol and item.as_of_date <= as_of
    ]
    if not usable:
        return None
    return max(usable, key=lambda item: item.as_of_date)
