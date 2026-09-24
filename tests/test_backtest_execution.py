"""P5 execution chronology, accounting, benchmark and metric tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from backtest.adapters import HistoricalEvaluation
from backtest.analytics import calculate_performance_analytics, max_drawdown_percent
from backtest.execution import (
    BacktestExecutionConfig,
    EquityPoint,
    ExecutedTrade,
    ExecutionResult,
    FillSide,
    simulate_execution,
)
from backtest.repository import latest_successful_backtest
from backtest.runner import run_strategy_backtest
from data.database import connect_database
from data.migrations import bootstrap_schema
from data.models import OHLCVBar
from strategy.technical_strategies import StrategyAction, StrategyName, StrategyResult
from telegram_bot.performance_formatters import format_performance_detail


ICT = timezone(timedelta(hours=7))


def bars(symbol: str, opens=(100.0, 101.0, 110.0, 90.0, 95.0)) -> tuple[OHLCVBar, ...]:
    first = datetime(2026, 1, 5, tzinfo=ICT)
    return tuple(
        OHLCVBar(
            symbol, "ONE_DAY", int((first + timedelta(days=index)).timestamp()),
            value, value + 2, value - 2, value + 1, 1_000_000,
        )
        for index, value in enumerate(opens)
    )


def decision(bar: OHLCVBar, action: StrategyAction, strategy=StrategyName.CL1) -> StrategyResult:
    return StrategyResult(strategy, bar.symbol, bar.timestamp, action, None, (), (), ())


def config(**overrides) -> BacktestExecutionConfig:
    values = dict(
        settlement_sessions=0, commission_rate=0.0, sell_tax_rate=0.0,
        slippage_rate=0.0, lot_size=1, initial_capital=100_000.0,
    )
    values.update(overrides)
    return BacktestExecutionConfig(**values)


def round_trip(history, cfg=None):
    decisions = {
        "FPT": (
            decision(history[0], StrategyAction.BUY),
            decision(history[1], StrategyAction.SELL),
        )
    }
    return simulate_execution({"FPT": history}, decisions, cfg or config())


def test_close_t_signal_fills_at_open_t_plus_1_and_never_outside_ohlc() -> None:
    history = bars("FPT")
    result = round_trip(history, config(slippage_rate=.5))

    buy, sell = result.fills
    assert buy.side is FillSide.BUY and buy.signal_timestamp == history[0].timestamp
    assert buy.fill_timestamp == history[1].timestamp
    assert history[1].low <= buy.price <= history[1].high
    assert sell.fill_timestamp == history[2].timestamp
    assert history[2].low <= sell.price <= history[2].high


def test_transaction_costs_make_net_return_lower_than_gross_and_reduce_equity() -> None:
    history = bars("FPT")
    gross = round_trip(history, config())
    net = round_trip(history, config(
        commission_rate=.0015, sell_tax_rate=.001, slippage_rate=.002,
    ))

    assert net.trades[0].net_return_percent < net.trades[0].gross_return_percent
    assert net.trades[0].total_costs > 0
    assert net.equity_curve[-1].equity < gross.equity_curve[-1].equity


def test_sell_waits_until_configured_settlement_session() -> None:
    history = bars("FPT")
    result = round_trip(history, config(settlement_sessions=2))
    assert result.fills[0].fill_timestamp == history[1].timestamp
    assert result.fills[1].fill_timestamp == history[3].timestamp
    assert result.trades[0].holding_sessions == 2


def test_max_drawdown_comes_from_equity_curve() -> None:
    assert max_drawdown_percent([100.0, 120.0, 90.0, 95.0]) == pytest.approx(-25.0)


def analytics_fixture(trades=()):
    points = (
        EquityPoint(100, 100, 0, 100, 0),
        EquityPoint(200, 110, 0, 110, 0),
        EquityPoint(300, 105, 0, 105, 0),
    )
    return ExecutionResult(100, 105, (), tuple(trades), (), points, 0)


def trade(symbol, pnl, net_return):
    return ExecutedTrade(symbol, 100, 200, 1, 100, 100 + pnl,
                         pnl, net_return, 0, pnl, 1)


def test_profit_factor_and_trade_metrics_use_realized_trades() -> None:
    result = analytics_fixture((trade("FPT", 100, 10), trade("ACB", -50, -5)))
    metrics = calculate_performance_analytics(result, ())
    assert metrics.profit_factor == pytest.approx(2.0)
    assert metrics.win_rate_percent == 50.0
    assert metrics.average_return_percent == pytest.approx(2.5)
    assert metrics.payoff_ratio == pytest.approx(2.0)
    assert metrics.longest_losing_streak == 1


def test_zero_trades_does_not_fabricate_return_or_risk_metrics() -> None:
    metrics = calculate_performance_analytics(analytics_fixture(), ())
    assert metrics.win_rate_percent == 0.0
    assert metrics.profit_factor is None
    assert metrics.total_return_percent is None
    assert metrics.cagr_percent is None
    assert metrics.sharpe_ratio is None
    assert metrics.average_return_percent is None


def test_advanced_risk_metrics_exist_only_with_sufficient_equity_observations() -> None:
    values = [100.0]
    for index in range(1, 32):
        values.append(values[-1] * (1.01 if index % 3 else .995))
    curve = tuple(
        EquityPoint(1_700_000_000 + index * 86_400, value, 0, value, 25.0)
        for index, value in enumerate(values)
    )
    execution = ExecutionResult(
        100, values[-1], (), (trade("FPT", 10, 10),), (), curve, 0
    )
    metrics = calculate_performance_analytics(execution, ())
    assert metrics.cagr_percent is not None
    assert metrics.sharpe_ratio is not None
    assert metrics.sortino_ratio is not None
    assert metrics.calmar_ratio is not None
    assert metrics.exposure_percent == 25.0
    assert metrics.trades_per_year is not None


def test_benchmark_uses_exact_equity_date_range() -> None:
    benchmark = bars("VNINDEX", (90, 100, 105, 110, 120))
    timestamps = [bar.timestamp for bar in benchmark]
    curve = (
        EquityPoint(timestamps[1], 100, 0, 100, 0),
        EquityPoint(timestamps[2], 105, 0, 105, 0),
        EquityPoint(timestamps[3], 110, 0, 110, 0),
    )
    execution = ExecutionResult(
        100, 110, (), (trade("FPT", 10, 10),), (), curve, 0
    )
    metrics = calculate_performance_analytics(execution, benchmark)
    assert metrics.benchmark_start_timestamp == timestamps[1]
    assert metrics.benchmark_end_timestamp == timestamps[3]
    assert metrics.benchmark_return_percent == pytest.approx(
        (benchmark[3].close / benchmark[1].open - 1) * 100
    )
    assert metrics.excess_return_percent == pytest.approx(
        metrics.total_return_percent - metrics.benchmark_return_percent
    )


def test_runner_persists_cost_aware_execution_result_for_performance_command() -> None:
    stock = bars("FPT")
    benchmark = bars("VNINDEX", (100, 102, 104, 106, 108))

    class Data:
        def daily_bars(self, symbol):
            return stock if symbol == "FPT" else benchmark

    class Adapter:
        def evaluate(self, values, *, start_date, end_date):
            return HistoricalEvaluation("FPT", (
                decision(stock[0], StrategyAction.BUY),
                decision(stock[1], StrategyAction.SELL),
            ))

    database = connect_database("sqlite:///:memory:")
    bootstrap_schema(database)
    result = run_strategy_backtest(
        strategy="CL1", symbols=("FPT",), start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 9), data_port=Data(), connection=database,
        run_id="cl1-executed", now=lambda: 1_800_000_000,
        cl1_adapter=Adapter(),
        execution_config=config(
            settlement_sessions=1, commission_rate=.0015,
            sell_tax_rate=.001, slippage_rate=.002,
        ),
    )

    loaded = latest_successful_backtest(database, "CL1")
    assert loaded is not None and loaded.run_id == "cl1-executed"
    assert result.execution is not None and result.analytics is not None
    assert loaded.trade_count == 1
    assert loaded.total_return_percent is not None
    assert loaded.config["entry_mode"] == "OPEN_T_PLUS_1"
    assert loaded.config["settlement_days"] == 1
    text = format_performance_detail("CL1", loaded)
    assert "NET SAU CHI PHÍ" in text
    assert "Fee: 0.15%" in text
    assert "Settlement: T+1 phiên" in text
    assert "HISTORICAL SIGNAL EVALUATION" not in text


def test_execution_config_requires_explicit_valid_settlement() -> None:
    with pytest.raises(TypeError):
        BacktestExecutionConfig()  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="settlement_sessions"):
        config(settlement_sessions=-1)
    defaults = BacktestExecutionConfig(settlement_sessions=2)
    assert defaults.commission_rate == .0015
    assert defaults.sell_tax_rate == .001
    assert defaults.slippage_rate == .002
