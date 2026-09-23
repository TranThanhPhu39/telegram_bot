"""Valuation snapshot: market price + shares outstanding, kept out of quarterly reports.

Per the Issue 2.5 architecture:

    financial_reports  -> ROE, revenue growth, profit growth, Debt/Equity
    valuation snapshot -> EPS (TTM), P/E, P/B, price, shares outstanding, BVPS

This module deliberately stores only *raw* market inputs (price, shares
outstanding) rather than pre-computed multiples. EPS (TTM), P/E, P/B and BVPS
are derived here from those raw inputs plus figures the repository already
trusts (TTM net profit, latest equity) from ``financial_reports``. A
precomputed P/E sitting in a spreadsheet can silently drift from what the
reports actually say; deriving it here means the multiple can never disagree
with the underlying numbers the bot already validated.

Every output is ``None`` unless every input it depends on is present and
usable. Nothing here ever guesses, defaults, or fabricates a missing figure.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from math import isfinite
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ValuationSnapshot:
    """Raw market inputs for one symbol, as of a given date."""

    symbol: str
    as_of_date: date
    source: str
    price: float | None
    shares_outstanding: float | None

    def __post_init__(self) -> None:
        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be non-empty and normalized")
        if not isinstance(self.as_of_date, date):
            raise TypeError("as_of_date must be a date")
        if not self.source or self.source != self.source.strip():
            raise ValueError("source provenance must be non-empty and trimmed")
        for name in ("price", "shares_outstanding"):
            value = getattr(self, name)
            if value is not None and not isfinite(value):
                raise ValueError(f"{name} must be finite when present")


@dataclass(frozen=True, slots=True)
class ValuationMetrics:
    """Derived multiples. Any field may be ``None`` when an input was missing."""

    eps_ttm: float | None = None
    pe: float | None = None
    pb: float | None = None
    bvps: float | None = None


def compute_valuation(
    *,
    price: float | None,
    shares_outstanding: float | None,
    ttm_net_profit: float | None,
    equity: float | None,
) -> ValuationMetrics:
    """Derive EPS(TTM)/P/E/P/B/BVPS from raw inputs.

    No fallback, no estimation: a missing or non-positive input leaves every
    metric that depends on it as ``None``.
    """
    eps_ttm: float | None = None
    if (
        shares_outstanding is not None
        and shares_outstanding > 0
        and ttm_net_profit is not None
    ):
        eps_ttm = ttm_net_profit / shares_outstanding

    bvps: float | None = None
    if (
        shares_outstanding is not None
        and shares_outstanding > 0
        and equity is not None
        and equity > 0
    ):
        bvps = equity / shares_outstanding

    pe: float | None = None
    if price is not None and price > 0 and eps_ttm is not None and eps_ttm > 0:
        pe = price / eps_ttm

    pb: float | None = None
    if price is not None and price > 0 and bvps is not None and bvps > 0:
        pb = price / bvps

    return ValuationMetrics(eps_ttm=eps_ttm, pe=pe, pb=pb, bvps=bvps)


REQUIRED_COLUMNS = ("symbol", "as_of_date", "source", "price", "shares_outstanding")


def load_valuation_csv(path: str | Path) -> tuple[ValuationSnapshot, ...]:
    """Load a controlled CSV of raw valuation inputs.

    Deliberately does NOT accept eps/pe/pb columns directly: those must be
    computed from ``financial_reports`` + these raw inputs via
    :func:`compute_valuation`, so a stale precomputed multiple can never
    silently disagree with the reports the bot already trusts.
    """
    source_path = Path(path)
    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or tuple(reader.fieldnames) != REQUIRED_COLUMNS:
            raise ValueError("valuation CSV columns do not match the expected schema")
        snapshots: list[ValuationSnapshot] = []
        seen: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            symbol = row["symbol"].strip().upper()
            if symbol in seen:
                raise ValueError(f"duplicate valuation symbol at row {row_number}")
            seen.add(symbol)
            try:
                as_of = date.fromisoformat(row["as_of_date"].strip())
            except ValueError as exc:
                raise ValueError(f"invalid as_of_date at row {row_number}") from exc
            snapshots.append(
                ValuationSnapshot(
                    symbol=symbol,
                    as_of_date=as_of,
                    source=row["source"].strip(),
                    price=_optional_float(row["price"], "price", row_number),
                    shares_outstanding=_optional_float(
                        row["shares_outstanding"], "shares_outstanding", row_number
                    ),
                )
            )
    return tuple(snapshots)


def _optional_float(raw: str, name: str, row: int) -> float | None:
    value = raw.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"invalid {name} at row {row}") from exc
