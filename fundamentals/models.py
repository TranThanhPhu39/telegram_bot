"""Normalized fundamental snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite


@dataclass(frozen=True, slots=True)
class FundamentalSnapshot:
    symbol: str
    as_of_date: date
    source: str
    eps: float | None
    pe: float | None
    pb: float | None
    roe_percent: float | None
    revenue_growth_percent: float | None
    profit_growth_percent: float | None

    def __post_init__(self) -> None:
        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be non-empty and normalized")
        if not isinstance(self.as_of_date, date):
            raise TypeError("as_of_date must be a date")
        if not self.source or self.source != self.source.strip():
            raise ValueError("source provenance must be non-empty and trimmed")
        for name in (
            "eps", "pe", "pb", "roe_percent",
            "revenue_growth_percent", "profit_growth_percent",
        ):
            value = getattr(self, name)
            if value is not None and not isfinite(value):
                raise ValueError(f"{name} must be finite when present")

