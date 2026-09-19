"""Tests for shared-engine backtesting and performance metrics."""

import pytest

from backtest.engine import BacktestTrade, calculate_performance, format_performance, run_backtest
from data.market_regime import MarketRegime
from strategy.signal_engine import SignalEngine, SignalEngineConfig, SignalInputs


def observation(timestamp: int, price: float, **overrides: object) -> SignalInputs:
    values: dict[str, object] = dict(
        symbol="FPT", timestamp=timestamp, price=price,
        market_regime=MarketRegime.BULL, stock_trend_confirmed=True,
        relative_strength=3.0, rvol=2.0, breakout=False, exit_triggered=False,
    )
    values.update(overrides)
    return SignalInputs(**values)  # type: ignore[arg-type]


def lifecycle(start: int, entry: float, exit_price: float) -> list[SignalInputs]:
    return [
        observation(start, entry - 4), observation(start + 1, entry - 3),
        observation(start + 2, entry - 2, breakout=True),
        observation(start + 3, entry - 1, breakout=True),
        observation(start + 4, entry, breakout=True),
        observation(start + 5, exit_price, exit_triggered=True),
    ]


def test_backtest_reuses_signal_engine_and_closes_trades() -> None:
    engine = SignalEngine(SignalEngineConfig(1.5, 2.0, 0))
    observations = lifecycle(100, 100.0, 110.0) + [observation(106, 110.0)] + lifecycle(107, 100.0, 90.0)
    trades, report = run_backtest(engine, observations)
    assert [trade.return_percent for trade in trades] == pytest.approx([10.0, -10.0])
    assert report.trade_count == 2
    assert report.win_rate_percent == 50.0
    assert report.average_return_percent == pytest.approx(0.0)
    assert report.profit_factor == pytest.approx(1.0)
    assert report.max_drawdown_percent == pytest.approx(10.0)


def test_performance_uses_compounded_equity_drawdown() -> None:
    trades = (
        BacktestTrade("FPT", 1, 100, 2, 120, 20.0),
        BacktestTrade("FPT", 3, 100, 4, 90, -10.0),
        BacktestTrade("FPT", 5, 100, 6, 95, -5.0),
    )
    report = calculate_performance(trades, start_timestamp=1, end_timestamp=6, observation_count=6)
    assert report.win_rate_percent == pytest.approx(100 / 3)
    assert report.average_return_percent == pytest.approx(5 / 3)
    assert report.profit_factor == pytest.approx(20 / 15)
    assert report.max_drawdown_percent == pytest.approx(14.5)


def test_no_losses_has_explicit_undefined_profit_factor() -> None:
    report = calculate_performance(
        [BacktestTrade("FPT", 1, 100, 2, 110, 10.0)],
        start_timestamp=1, end_timestamp=2, observation_count=2,
    )
    assert report.profit_factor is None
    assert "N/A" in format_performance(report)


def test_no_trades_reports_zero_metrics_and_open_positions() -> None:
    engine = SignalEngine(SignalEngineConfig(1.5, 2.0, 0))
    _, report = run_backtest(engine, [observation(100, 100.0)])
    assert report.trade_count == 0
    assert report.win_rate_percent == 0.0
    assert report.average_return_percent == 0.0
    assert report.max_drawdown_percent == 0.0


def test_backtest_rejects_empty_or_out_of_order_observations() -> None:
    engine = SignalEngine(SignalEngineConfig(1.5, 2.0, 0))
    with pytest.raises(ValueError, match="at least one"):
        run_backtest(engine, [])
    with pytest.raises(ValueError, match="globally chronological"):
        run_backtest(engine, [observation(101, 100), observation(100, 100)])
