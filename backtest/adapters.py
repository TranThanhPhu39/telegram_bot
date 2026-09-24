"""Chronological adapters around the production strategy evaluators."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import sqlite3
from typing import Protocol

from asmf_data import scoring as asmf_scoring
from asmf_data.store import active_sector, sector_members
from data.models import OHLCVBar
from strategy import technical_strategies
from strategy.technical_strategies import StrategyResult


VIETNAM_TIMEZONE = timezone(timedelta(hours=7))
CL1_MINIMUM_HISTORY = 200
ASMF_MINIMUM_HISTORY = 200


class HistoricalDataPort(Protocol):
    def daily_bars(self, symbol: str) -> Sequence[OHLCVBar]: ...


@dataclass(frozen=True, slots=True)
class HistoricalEvaluation:
    symbol: str
    decisions: tuple[StrategyResult, ...]


class CL1HistoricalAdapter:
    """Evaluate CL1 on every completed session using only bars available at T."""

    def __init__(
        self,
        evaluator: Callable[[Sequence[OHLCVBar]], StrategyResult] | None = None,
    ) -> None:
        # Resolve the production function at construction time so monkeypatching
        # technical_strategies.evaluate_cl1 proves this adapter uses that boundary.
        self._evaluator = evaluator or technical_strategies.evaluate_cl1

    def evaluate(
        self,
        bars: Sequence[OHLCVBar],
        *,
        start_date: date,
        end_date: date,
    ) -> HistoricalEvaluation:
        checked = _validate_history(bars)
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if len(checked) < CL1_MINIMUM_HISTORY:
            raise ValueError(
                f"{checked[0].symbol} requires at least {CL1_MINIMUM_HISTORY} completed daily bars"
            )

        decisions: list[StrategyResult] = []
        for index in range(CL1_MINIMUM_HISTORY - 1, len(checked)):
            current_date = _session_date(checked[index].timestamp)
            if current_date < start_date:
                continue
            if current_date > end_date:
                break
            # The prefix ends at T. Future bars are never visible to the strategy.
            result = self._evaluator(checked[: index + 1])
            if result.symbol != checked[index].symbol or result.timestamp != checked[index].timestamp:
                raise ValueError("CL1 evaluator result does not match the current completed bar")
            decisions.append(result)
        if not decisions:
            raise ValueError(f"{checked[0].symbol} has no evaluable session in the requested date range")
        return HistoricalEvaluation(checked[0].symbol, tuple(decisions))


class ASMFHistoricalAdapter:
    """Build every ASMF layer point-in-time, then call the production evaluator."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        data_port: HistoricalDataPort,
        evaluator: Callable[..., StrategyResult] | None = None,
    ) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if not hasattr(data_port, "daily_bars"):
            raise TypeError("data_port must provide daily_bars(symbol)")
        self.connection = connection
        self.data_port = data_port
        self._evaluator = evaluator or technical_strategies.evaluate_asmf
        self._history_cache: dict[str, tuple[OHLCVBar, ...]] = {}

    def evaluate(
        self,
        bars: Sequence[OHLCVBar],
        *,
        start_date: date,
        end_date: date,
    ) -> HistoricalEvaluation:
        checked = _validate_history(bars)
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if len(checked) < ASMF_MINIMUM_HISTORY:
            raise ValueError(
                f"{checked[0].symbol} requires at least {ASMF_MINIMUM_HISTORY} completed daily bars"
            )
        self._history_cache[checked[0].symbol] = checked
        benchmark_full = self._full_history("VNINDEX", required=True)

        decisions: list[StrategyResult] = []
        for index in range(ASMF_MINIMUM_HISTORY - 1, len(checked)):
            current = checked[index]
            as_of = _session_date(current.timestamp)
            if as_of < start_date:
                continue
            if as_of > end_date:
                break
            stock_prefix = checked[: index + 1]
            benchmark_prefix = self._completed("VNINDEX", current.timestamp)
            if len(benchmark_prefix) < ASMF_MINIMUM_HISTORY:
                raise ValueError(
                    f"VNINDEX requires at least {ASMF_MINIMUM_HISTORY} completed daily bars at {as_of}"
                )

            membership = active_sector(self.connection, current.symbol, as_of)
            members = () if membership is None else sector_members(
                self.connection, membership["sector_code"], as_of
            )
            histories = {
                member: self._completed(member, current.timestamp)
                for member in members
            }
            sector_score = asmf_scoring.sector_strength_score(
                self.connection, current.symbol, as_of, histories, benchmark_prefix
            )
            fundamental_score = asmf_scoring.fundamental_score(
                self.connection, current.symbol, as_of
            )
            result = self._evaluator(
                stock_prefix,
                benchmark_prefix,
                sector_score=sector_score,
                fundamental_score=fundamental_score,
            )
            if result.symbol != current.symbol or result.timestamp != current.timestamp:
                raise ValueError("ASMF evaluator result does not match the current completed bar")
            decisions.append(result)
        if not decisions:
            raise ValueError(f"{checked[0].symbol} has no evaluable session in the requested date range")
        return HistoricalEvaluation(checked[0].symbol, tuple(decisions))

    def _full_history(self, symbol: str, *, required: bool = False) -> tuple[OHLCVBar, ...]:
        normalized = symbol.strip().upper()
        if normalized not in self._history_cache:
            raw = tuple(self.data_port.daily_bars(normalized))
            if not raw:
                if required:
                    raise ValueError(f"{normalized} historical bars are unavailable")
                self._history_cache[normalized] = ()
            else:
                checked = _validate_history(raw)
                if checked[0].symbol != normalized:
                    raise ValueError(f"historical data port returned the wrong symbol for {normalized}")
                self._history_cache[normalized] = checked
        return self._history_cache[normalized]

    def _completed(self, symbol: str, timestamp: int) -> tuple[OHLCVBar, ...]:
        history = self._full_history(symbol)
        stop = bisect_right(tuple(bar.timestamp for bar in history), timestamp)
        return history[:stop]


def _validate_history(bars: Sequence[OHLCVBar]) -> tuple[OHLCVBar, ...]:
    checked = tuple(bars)
    if not checked:
        raise ValueError("historical bars must not be empty")
    if any(not isinstance(bar, OHLCVBar) for bar in checked):
        raise TypeError("historical bars must contain OHLCVBar values")
    symbol = checked[0].symbol
    if any(bar.symbol != symbol for bar in checked):
        raise ValueError("historical bars must contain exactly one symbol")
    if any(bar.timeframe != "ONE_DAY" for bar in checked):
        raise ValueError("historical strategy adapters accept only ONE_DAY bars")
    if any(left.timestamp >= right.timestamp for left, right in zip(checked, checked[1:])):
        raise ValueError("historical bars must be strictly chronological")
    return checked


def _session_date(timestamp: int) -> date:
    return datetime.fromtimestamp(timestamp, VIETNAM_TIMEZONE).date()
