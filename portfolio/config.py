"""Centralised, validated Phase 23 thresholds (no magic numbers elsewhere)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os


@dataclass(frozen=True, slots=True)
class PortfolioConfig:
    single_stock_warning_pct: Decimal = Decimal("25")
    single_stock_high_pct: Decimal = Decimal("40")
    sector_warning_pct: Decimal = Decimal("40")
    sector_high_pct: Decimal = Decimal("60")
    default_risk_per_trade_pct: Decimal = Decimal("1")
    max_risk_per_trade_pct: Decimal = Decimal("5")
    risk_lookback: int = 120
    risk_min_sessions: int = 60

    def __post_init__(self) -> None:
        pairs = (
            ("PORTFOLIO_SINGLE_STOCK", self.single_stock_warning_pct, self.single_stock_high_pct),
            ("PORTFOLIO_SECTOR", self.sector_warning_pct, self.sector_high_pct),
        )
        for name, warning, high in pairs:
            if not (Decimal(0) < warning < high <= Decimal(100)):
                raise ValueError(f"{name}: require 0 < WARNING < HIGH <= 100")
        if not (Decimal(0) < self.default_risk_per_trade_pct <= self.max_risk_per_trade_pct):
            raise ValueError("DEFAULT_RISK_PER_TRADE_PCT must satisfy 0 < default <= max")
        if self.max_risk_per_trade_pct > Decimal(100):
            raise ValueError("MAX_RISK_PER_TRADE_PCT must be <= 100")
        if self.risk_min_sessions < 2 or self.risk_lookback < self.risk_min_sessions:
            raise ValueError("PORTFOLIO_RISK_LOOKBACK must be >= PORTFOLIO_RISK_MIN_SESSIONS >= 2")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "PortfolioConfig":
        env = os.environ if environ is None else environ
        defaults = cls.__dataclass_fields__

        def dec(name: str, field: str) -> Decimal:
            raw = env.get(name, "").strip()
            if not raw:
                return defaults[field].default
            try:
                value = Decimal(raw)
            except InvalidOperation as error:
                raise ValueError(f"{name} must be a number") from error
            if not value.is_finite():
                raise ValueError(f"{name} must be finite")
            return value

        def integer(name: str, field: str) -> int:
            raw = env.get(name, "").strip()
            if not raw:
                return defaults[field].default
            try:
                return int(raw)
            except ValueError as error:
                raise ValueError(f"{name} must be an integer") from error

        return cls(
            single_stock_warning_pct=dec("PORTFOLIO_SINGLE_STOCK_WARNING_PCT", "single_stock_warning_pct"),
            single_stock_high_pct=dec("PORTFOLIO_SINGLE_STOCK_HIGH_PCT", "single_stock_high_pct"),
            sector_warning_pct=dec("PORTFOLIO_SECTOR_WARNING_PCT", "sector_warning_pct"),
            sector_high_pct=dec("PORTFOLIO_SECTOR_HIGH_PCT", "sector_high_pct"),
            default_risk_per_trade_pct=dec("DEFAULT_RISK_PER_TRADE_PCT", "default_risk_per_trade_pct"),
            max_risk_per_trade_pct=dec("MAX_RISK_PER_TRADE_PCT", "max_risk_per_trade_pct"),
            risk_lookback=integer("PORTFOLIO_RISK_LOOKBACK", "risk_lookback"),
            risk_min_sessions=integer("PORTFOLIO_RISK_MIN_SESSIONS", "risk_min_sessions"),
        )