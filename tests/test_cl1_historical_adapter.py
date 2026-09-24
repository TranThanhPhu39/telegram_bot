"""P3 chronological CL1 historical evaluation tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from backtest.adapters import CL1HistoricalAdapter
from backtest.data import SQLiteDailyBarData
from backtest.repository import latest_successful_backtest
from backtest.runner import run_strategy_backtest
from data.database import connect_database
from data.migrations import bootstrap_schema
from data.models import OHLCVBar
from strategy import technical_strategies
from strategy.technical_strategies import StrategyAction, StrategyName, StrategyResult
from telegram_bot.performance_formatters import format_performance_detail


ICT = timezone(timedelta(hours=7))


def bars(symbol: str, count: int = 205) -> tuple[OHLCVBar, ...]:
    start = datetime(2024, 1, 1, tzinfo=ICT)
    result = []
    for index in range(count):
        close = 100 + index * .1
        result.append(OHLCVBar(
            symbol, "ONE_DAY", int((start + timedelta(days=index)).timestamp()),
            close - .2, close + .5, close - .5, close, 1_000_000 + index,
        ))
    return tuple(result)


def watch(prefix) -> StrategyResult:
    latest = prefix[-1]
    return StrategyResult(
        StrategyName.CL1, latest.symbol, latest.timestamp,
        StrategyAction.WATCH, None, (), ("test",), (), 90.0,
    )


def test_adapter_resolves_and_reuses_production_evaluate_cl1(monkeypatch) -> None:
    calls = []

    def spy(prefix):
        calls.append(tuple(prefix))
        return watch(prefix)

    monkeypatch.setattr(technical_strategies, "evaluate_cl1", spy)
    history = bars("FPT")
    evaluation = CL1HistoricalAdapter().evaluate(
        history, start_date=date(2024, 7, 18), end_date=date(2024, 7, 20)
    )

    assert len(evaluation.decisions) == 3
    assert [len(prefix) for prefix in calls] == [200, 201, 202]
    assert all(prefix[-1].timestamp == decision.timestamp for prefix, decision in zip(calls, evaluation.decisions))


def test_adapter_never_exposes_future_bars_to_session_t() -> None:
    seen = []

    def spy(prefix):
        seen.append((prefix[-1].timestamp, max(bar.timestamp for bar in prefix)))
        return watch(prefix)

    history = bars("FPT")
    CL1HistoricalAdapter(spy).evaluate(
        history, start_date=date(2024, 7, 18), end_date=date(2024, 7, 22)
    )
    assert seen
    assert all(current == maximum for current, maximum in seen)
    assert all(maximum < history[index + 200].timestamp for index, (_, maximum) in enumerate(seen[:-1]))


def test_runner_supports_multi_symbol_and_persists_signals_only_result() -> None:
    class Data:
        histories = {symbol: bars(symbol) for symbol in ("FPT", "ACB")}

        def daily_bars(self, symbol):
            return self.histories[symbol]

    database = connect_database("sqlite:///:memory:")
    bootstrap_schema(database)
    result = run_strategy_backtest(
        strategy="CL1", symbols=("FPT", "ACB"),
        start_date=date(2024, 7, 18), end_date=date(2024, 7, 22),
        data_port=Data(), connection=database, run_id="cl1-p3",
        now=lambda: 1_800_000_000,
    )

    loaded = latest_successful_backtest(database, "CL1")
    assert loaded is not None and loaded.run_id == "cl1-p3"
    assert result.run.config["execution_mode"] == "SIGNALS_ONLY"
    assert result.run.config["decision_count"] == 10
    assert result.run.total_return_percent is None
    text = format_performance_detail("CL1", loaded)
    assert "HISTORICAL SIGNAL EVALUATION" in text
    assert "Giao dịch đóng: N/A" in text
    assert "Total Return: N/A" in text
    assert "Giao dịch đóng: 0" not in text


def test_runner_rejects_unknown_strategy_duplicates_and_short_history() -> None:
    class Data:
        def daily_bars(self, symbol):
            return bars(symbol, 199)

    database = connect_database("sqlite:///:memory:")
    bootstrap_schema(database)
    common = dict(
        start_date=date(2024, 1, 1), end_date=date(2025, 1, 1),
        data_port=Data(), connection=database, now=lambda: 1_800_000_000,
    )
    with pytest.raises(ValueError, match="strategy must be CL1 or ASMF"):
        run_strategy_backtest(strategy="UNKNOWN", symbols=("FPT",), **common)
    with pytest.raises(ValueError, match="duplicates"):
        run_strategy_backtest(strategy="CL1", symbols=("FPT", "FPT"), **common)
    with pytest.raises(ValueError, match="at least 200"):
        run_strategy_backtest(strategy="CL1", symbols=("FPT",), **common)


def test_sqlite_daily_bar_port_reads_chronologically() -> None:
    database = connect_database("sqlite:///:memory:")
    bootstrap_schema(database)
    database.execute("INSERT INTO symbols(symbol) VALUES ('FPT')")
    history = bars("FPT", 2)
    for bar in reversed(history):
        database.execute(
            "INSERT INTO candles(symbol,timeframe,timestamp,open,high,low,close,volume) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (bar.symbol, bar.timeframe, bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume),
        )
    database.commit()
    loaded = SQLiteDailyBarData(database).daily_bars("fpt")
    assert [bar.timestamp for bar in loaded] == sorted(bar.timestamp for bar in history)
