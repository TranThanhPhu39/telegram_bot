"""Deterministic fakes for coverage worker tests. No network, no real sleeping."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from data.database import connect_database
from data.migrations import bootstrap_schema
from fundamentals.providers.base import (
    FlowRow,
    FundamentalProvider,
    ProviderResult,
    ProviderStatus,
    StatementRow,
)
from fundamentals.providers.provider_chain import ProviderChain
from runtime.coverage_config import CoverageConfig
from runtime.sector_history_sync import HistoryFetch

T0 = datetime(2026, 9, 21, 3, 0, tzinfo=timezone.utc)


class Clock:
    """Mutable UTC clock so tests can move time without sleeping."""

    def __init__(self, start: datetime = T0) -> None:
        self.value = start

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: float) -> None:
        self.value = self.value + timedelta(**kwargs)


class Sleeper:
    """Records requested pauses instead of sleeping."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def make_connection(tmp_path, name: str = "coverage.sqlite3"):
    connection = connect_database(f"sqlite:///{(tmp_path / name).as_posix()}")
    bootstrap_schema(connection)
    return connection


def seed_symbols(connection, rows) -> None:
    """rows: iterable of (symbol, exchange, instrument_type, is_active)."""
    with connection:
        connection.executemany(
            "INSERT INTO symbols(symbol, exchange, instrument_type, is_active) VALUES (?,?,?,?)",
            list(rows),
        )


def statement(symbol: str, period: str = "2026Q2", public_date=date(2026, 8, 15), **values):
    defaults = dict(revenue=1000.0, net_income=100.0, total_equity=2000.0,
                    short_term_debt=5.0, long_term_debt=5.0)
    defaults.update(values)
    return StatementRow(symbol, period, public_date, values=defaults)


class ScriptedProvider(FundamentalProvider):
    """Per-symbol scripted behaviour.

    ``script[symbol]`` is a list consumed one entry per call (the last entry
    repeats): ``"ok"``, ``"partial"``, ``"missing"``, ``"error"``, ``"raise"``.
    Unlisted symbols default to ``default``.
    """

    name = "VNStock"

    def __init__(
        self, script=None, default: str = "ok", statement_count: int = 1, flow_count: int = 1
    ) -> None:
        self.script = {key: list(value) if isinstance(value, list) else [value]
                       for key, value in (script or {}).items()}
        self.default = default
        self.statement_count = statement_count
        self.flow_count = flow_count
        self.calls: list[tuple[str, str, str | None]] = []

    def available(self) -> bool:
        return True

    def _next(self, symbol: str, dataset: str | None = None) -> str:
        queue = self.script.get((symbol, dataset)) or self.script.get(symbol)
        if not queue:
            return self.default
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def fetch_financials(self, symbol, *, exchange=None):
        self.calls.append((symbol, "FINANCIALS", exchange))
        action = self._next(symbol, "FINANCIALS")
        if action == "ratelimit":
            return ProviderResult.failed(symbol, "FINANCIALS", self.name, "HTTP 429 Too Many Requests")
        if action == "raise":
            raise RuntimeError("boom for " + symbol)
        if action == "error":
            return ProviderResult.failed(symbol, "FINANCIALS", self.name, "upstream timeout")
        if action == "missing":
            return ProviderResult.missing(symbol, "FINANCIALS", self.name, reason="no data")
        status = ProviderStatus.PARTIAL if action == "partial" else ProviderStatus.AVAILABLE
        if action == "partial":
            statements = (statement(symbol, period="2026Q2"),)
        else:
            periods = ["2024Q3", "2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"]
            p_dates = [
                date(2024, 11, 15), date(2025, 2, 15), date(2025, 5, 15), date(2025, 8, 15),
                date(2025, 11, 15), date(2026, 2, 15), date(2026, 5, 15), date(2026, 8, 15),
            ]
            statements = tuple(
                statement(symbol, period=periods[i % len(periods)], public_date=p_dates[i % len(p_dates)])
                for i in range(self.statement_count)
            )
        return ProviderResult(
            symbol=symbol, dataset="FINANCIALS", provider=self.name, status=status,
            provider_source="VCI", statements=statements,
        )

    def fetch_institutional_flow(self, symbol, *, exchange=None, lookback_days=30):
        self.calls.append((symbol, "INSTITUTIONAL", exchange))
        action = self._next(symbol, "INSTITUTIONAL")
        if action == "raise":
            raise RuntimeError("boom for " + symbol)
        if action == "error":
            return ProviderResult.failed(symbol, "INSTITUTIONAL", self.name, "upstream timeout")
        if action == "missing":
            return ProviderResult.missing(symbol, "INSTITUTIONAL", self.name, reason="no data")
        status = ProviderStatus.PARTIAL if action == "partial" else ProviderStatus.AVAILABLE
        if action == "partial":
            flows = (FlowRow(symbol, date(2026, 9, 18), foreign_buy_value=10.0, foreign_sell_value=4.0),)
        else:
            flows = tuple(
                FlowRow(symbol, date(2026, 9, 18) - timedelta(days=i), foreign_buy_value=10.0,
                        foreign_sell_value=4.0)
                for i in range(self.flow_count)
            )
        return ProviderResult(
            symbol=symbol, dataset="INSTITUTIONAL", provider=self.name, status=status,
            provider_source="VCI",
            flows=flows,
        )

    def count(self, dataset: str) -> int:
        return sum(1 for _, ds, _ in self.calls if ds == dataset)

    def symbols_called(self, dataset: str) -> list[str]:
        return [sym for sym, ds, _ in self.calls if ds == dataset]


def chain_of(provider: FundamentalProvider) -> ProviderChain:
    return ProviderChain([provider])


class FakeHistory:
    """Stands in for SectorHistorySynchronizer.refresh_symbol_history."""

    minimum_bars = 200
    strategy_minimum_bars = 200

    def __init__(self, bars_by_symbol=None, errored=()) -> None:
        self.bars_by_symbol = bars_by_symbol or {}
        self.errored = set(errored)
        self.calls: list[str] = []

    def refresh_symbol_history(self, symbol):
        self.calls.append(symbol)
        if symbol in self.errored:
            return HistoryFetch((), True)
        count = self.bars_by_symbol.get(symbol, 0)
        from data.models import OHLCVBar

        bars = tuple(
            OHLCVBar(symbol, "ONE_DAY", 1_700_000_000 + i * 86_400, 1.0, 2.0, 0.5, 1.5, 100.0)
            for i in range(count)
        )
        return HistoryFetch(bars, False)


class FakeNews:
    def __init__(
        self, counts=None, error: Exception | None = None, known_tickers=None,
    ) -> None:
        from runtime.news_refresh import NewsRunResult

        self._result_type = NewsRunResult
        self.counts = counts or {}
        self.known_tickers = frozenset(known_tickers) if known_tickers is not None else frozenset()
        self.error = error
        self.calls: list[int] = []
        self.closed = False

    def run(self, limit):
        self.calls.append(limit)
        if self.error is not None:
            raise self.error
        return self._result_type(3, 1, dict(self.counts), known_tickers=self.known_tickers)

    def close(self):
        self.closed = True


def fast_config(**overrides) -> CoverageConfig:
    base = dict(
        batch_size=5, request_delay_seconds=0.5, max_retries=2,
        retry_backoff_seconds=2.0, error_cooldown_seconds=3600.0,
        startup_delay_seconds=0.0, worker_interval_seconds=1.0,
        datasets=("FINANCIALS", "INSTITUTIONAL"),
    )
    base.update(overrides)
    return CoverageConfig(**base)
