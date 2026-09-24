"""Persistable strategy-backtest result models.

These records describe completed/offline jobs.  They do not imply that a
strategy is validated and they are deliberately separate from live signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from math import isfinite
from typing import Any, Mapping


class BacktestRunStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class BacktestValidationStatus(str, Enum):
    ENGINE_ONLY = "ENGINE_ONLY"
    IN_SAMPLE_ONLY = "IN_SAMPLE_ONLY"
    OOS_AVAILABLE = "OOS_AVAILABLE"
    VALIDATED = "VALIDATED"


@dataclass(frozen=True, slots=True)
class BacktestRun:
    run_id: str
    strategy: str
    started_at: int
    completed_at: int | None
    start_date: date
    end_date: date
    symbols: tuple[str, ...]
    initial_capital: float
    final_equity: float | None
    trade_count: int
    open_position_count: int = 0
    status: BacktestRunStatus = BacktestRunStatus.SUCCESS
    validation_status: BacktestValidationStatus = BacktestValidationStatus.IN_SAMPLE_ONLY
    run_kind: str = "STRATEGY_BACKTEST"
    total_return_percent: float | None = None
    cagr_percent: float | None = None
    max_drawdown_percent: float | None = None
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None
    win_rate_percent: float | None = None
    average_return_percent: float | None = None
    profit_factor: float | None = None
    expectancy_percent: float | None = None
    average_win_percent: float | None = None
    average_loss_percent: float | None = None
    payoff_ratio: float | None = None
    best_trade_percent: float | None = None
    worst_trade_percent: float | None = None
    average_holding_sessions: float | None = None
    longest_losing_streak: int | None = None
    exposure_percent: float | None = None
    trades_per_year: float | None = None
    benchmark_return_percent: float | None = None
    benchmark_max_drawdown_percent: float | None = None
    excess_return_percent: float | None = None
    config: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    created_at: int | None = None

    def __post_init__(self) -> None:
        run_id = self.run_id.strip()
        strategy = self.strategy.strip().upper()
        symbols = tuple(symbol.strip().upper() for symbol in self.symbols)
        if not run_id:
            raise ValueError("run_id must not be empty")
        if strategy not in {"CL1", "ASMF"}:
            raise ValueError("strategy must be CL1 or ASMF")
        if self.run_kind != "STRATEGY_BACKTEST":
            raise ValueError("run_kind must be STRATEGY_BACKTEST")
        if self.started_at <= 0 or (self.completed_at is not None and self.completed_at < self.started_at):
            raise ValueError("invalid backtest timestamps")
        if self.status is BacktestRunStatus.SUCCESS and self.completed_at is None:
            raise ValueError("successful run requires completed_at")
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        if not symbols or any(not symbol or not symbol.isalnum() for symbol in symbols):
            raise ValueError("symbols must contain normalized alphanumeric tickers")
        if len(set(symbols)) != len(symbols):
            raise ValueError("symbols must not contain duplicates")
        if self.trade_count < 0 or self.open_position_count < 0:
            raise ValueError("trade counts must be non-negative")
        if not isfinite(self.initial_capital) or self.initial_capital <= 0:
            raise ValueError("initial_capital must be finite and positive")
        if self.final_equity is not None and (not isfinite(self.final_equity) or self.final_equity < 0):
            raise ValueError("final_equity must be finite and non-negative")
        for name in _OPTIONAL_FLOAT_FIELDS:
            value = getattr(self, name)
            if value is not None and not isfinite(value):
                raise ValueError(f"{name} must be finite when supplied")
        if self.longest_losing_streak is not None and self.longest_losing_streak < 0:
            raise ValueError("longest_losing_streak must be non-negative")
        if self.created_at is not None and self.created_at <= 0:
            raise ValueError("created_at must be positive")
        if any(not warning.strip() for warning in self.warnings):
            raise ValueError("warnings must not contain empty values")
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "strategy", strategy)
        object.__setattr__(self, "symbols", symbols)
        object.__setattr__(self, "config", dict(self.config))
        object.__setattr__(self, "warnings", tuple(item.strip() for item in self.warnings))


_OPTIONAL_FLOAT_FIELDS = (
    "total_return_percent", "cagr_percent", "max_drawdown_percent",
    "sharpe_ratio", "sortino_ratio", "calmar_ratio", "win_rate_percent",
    "average_return_percent", "profit_factor", "expectancy_percent",
    "average_win_percent", "average_loss_percent", "payoff_ratio",
    "best_trade_percent", "worst_trade_percent", "average_holding_sessions",
    "exposure_percent", "trades_per_year", "benchmark_return_percent",
    "benchmark_max_drawdown_percent", "excess_return_percent",
)
