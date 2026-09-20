"""Validated provider-independent ASMF input records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite


@dataclass(frozen=True, slots=True)
class SectorMembership:
    symbol: str
    sector_code: str
    sector_name: str
    effective_from: date
    effective_to: date | None
    source: str

    def __post_init__(self) -> None:
        _normalized(self.symbol, "symbol")
        _normalized(self.sector_code, "sector_code")
        _text(self.sector_name, "sector_name")
        _text(self.source, "source")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not precede effective_from")


@dataclass(frozen=True, slots=True)
class FinancialReport:
    symbol: str
    report_period: str
    public_date: date
    consolidated: bool
    revenue: float
    net_profit: float
    equity: float
    total_debt: float
    source: str

    def __post_init__(self) -> None:
        _normalized(self.symbol, "symbol")
        _text(self.report_period, "report_period")
        _text(self.source, "source")
        for name in ("revenue", "net_profit", "equity", "total_debt"):
            if not isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if self.revenue < 0 or self.equity <= 0 or self.total_debt < 0:
            raise ValueError("revenue/debt must be non-negative and equity positive")


@dataclass(frozen=True, slots=True)
class InstitutionalFlow:
    symbol: str
    trading_date: date
    foreign_buy_value: float | None
    foreign_sell_value: float | None
    proprietary_buy_value: float | None
    proprietary_sell_value: float | None
    source: str

    def __post_init__(self) -> None:
        _normalized(self.symbol, "symbol")
        _text(self.source, "source")
        values = (
            self.foreign_buy_value, self.foreign_sell_value,
            self.proprietary_buy_value, self.proprietary_sell_value,
        )
        if all(value is None for value in values):
            raise ValueError("at least one flow value is required")
        if any(value is not None and (not isfinite(value) or value < 0) for value in values):
            raise ValueError("flow values must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class BankFinancialReport:
    """Cumulative bank income and point-in-time balance-sheet values."""

    symbol: str
    report_period: str
    public_date: date
    period_months: int
    net_interest_income: float
    net_profit: float
    equity: float
    gross_loans: float
    nonperforming_loans: float | None
    loan_loss_reserve: float | None
    car_percent: float | None
    source: str

    def __post_init__(self) -> None:
        _normalized(self.symbol, "symbol")
        _text(self.source, "source")
        if len(self.report_period) != 6 or self.report_period[4] != "Q" or self.report_period[-1] not in "1234":
            raise ValueError("report_period must use YYYYQn")
        expected_months = int(self.report_period[-1]) * 3
        if self.period_months != expected_months:
            raise ValueError("period_months must match the cumulative report quarter")
        for name in ("net_interest_income", "net_profit", "equity", "gross_loans"):
            if not isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if self.net_interest_income < 0 or self.equity <= 0 or self.gross_loans <= 0:
            raise ValueError("bank income must be non-negative and balance values positive")
        for name in ("nonperforming_loans", "loan_loss_reserve", "car_percent"):
            value = getattr(self, name)
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and non-negative when present")


def _normalized(value: str, name: str) -> None:
    if not value or value != value.strip().upper() or not value.replace("_", "").isalnum():
        raise ValueError(f"{name} must be normalized uppercase text")


def _text(value: str, name: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty and trimmed")
