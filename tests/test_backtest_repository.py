"""P2 persisted backtest-run storage and Telegram rendering."""

from datetime import date

from backtest.models import BacktestRun, BacktestRunStatus
from backtest.repository import latest_successful_backtest, save_backtest_run
from data.database import connect_database
from data.migrations import bootstrap_schema
from telegram_bot.performance_formatters import format_performance_detail
from runtime.bot_service import RuntimeBotDataService
from scanner.universe import ScannerInstrument
from tests.test_runtime_bot import FakeClient, payload


def run(run_id: str, strategy: str = "CL1", *, completed_at: int = 200) -> BacktestRun:
    return BacktestRun(
        run_id=run_id, strategy=strategy, started_at=100,
        completed_at=completed_at, start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31), symbols=("FPT", "ACB"),
        initial_capital=500_000_000, final_equity=550_000_000,
        trade_count=12, total_return_percent=10.0, cagr_percent=10.0,
        max_drawdown_percent=-8.0, sharpe_ratio=.7, sortino_ratio=1.1,
        win_rate_percent=50.0, average_return_percent=.8, profit_factor=1.3,
        benchmark_return_percent=6.0, excess_return_percent=4.0,
        average_holding_sessions=12.5,
        config={"entry_mode": "OPEN_T_PLUS_1", "commission_rate": .0015},
        warnings=("IN-SAMPLE ONLY",), created_at=completed_at,
    )


def connection():
    value = connect_database("sqlite:///:memory:")
    bootstrap_schema(value)
    return value


def test_latest_successful_run_is_strategy_specific_and_newest() -> None:
    database = connection()
    save_backtest_run(database, run("cl1-old", completed_at=200))
    save_backtest_run(database, run("cl1-new", completed_at=300))
    save_backtest_run(database, run("asmf", "ASMF", completed_at=400))

    assert latest_successful_backtest(database, "CL1").run_id == "cl1-new"
    assert latest_successful_backtest(database, "ASMF").run_id == "asmf"


def test_failed_run_does_not_replace_latest_successful() -> None:
    database = connection()
    save_backtest_run(database, run("good", completed_at=200))
    failed = run("failed", completed_at=300)
    failed = BacktestRun(
        **{name: getattr(failed, name) for name in failed.__dataclass_fields__ if name != "status"},
        status=BacktestRunStatus.FAILED,
    )
    save_backtest_run(database, failed)

    assert latest_successful_backtest(database, "CL1").run_id == "good"


def test_round_trip_preserves_nullable_metrics_config_and_warnings() -> None:
    database = connection()
    value = run("round-trip")
    save_backtest_run(database, value)

    loaded = latest_successful_backtest(database, "CL1")
    assert loaded == value


def test_detail_formatter_uses_persisted_result_and_explicit_na() -> None:
    text = format_performance_detail("CL1", run("format"))
    assert "Total Return: +10.00%" in text
    assert "VNINDEX: +6.00%" in text
    assert "Settlement: N/A — chưa có quy ước" in text
    assert "LIVE PERFORMANCE: NOT AVAILABLE" in text
    assert "ENGINE TEST" not in text


def test_detail_formatter_explains_persisted_blocked_reasons() -> None:
    value = run("blocked", "ASMF")
    value = BacktestRun(
        **{
            name: getattr(value, name)
            for name in value.__dataclass_fields__
            if name != "config"
        },
        config={
            "action_counts": {"BLOCKED": 4},
            "missing_reason_counts": {"chất lượng BCTC theo ngày công bố": 4},
        },
    )

    text = format_performance_detail("ASMF", value)
    assert "Actions: BLOCKED=4" in text
    assert "chất lượng BCTC theo ngày công bố: 4 quyết định" in text


def test_no_run_is_honest_and_never_uses_engine_smoke_test() -> None:
    text = format_performance_detail("ASMF", None)
    assert "Chưa có backtest ASMF hợp lệ" in text
    assert "engine smoke test" in text
    assert "0.00%" not in text


def test_runtime_summary_reads_each_strategy_without_cross_contamination() -> None:
    database = connection()
    save_backtest_run(database, run("cl1", "CL1", completed_at=200))
    save_backtest_run(database, run("asmf", "ASMF", completed_at=300))
    service = RuntimeBotDataService(
        FakeClient(payload()), database,
        (ScannerInstrument("FPT", "HOSE", "STOCK"),), now=lambda: 1_800_000_000,
    )

    summary = service.performance_overview()
    cl1 = service.performance_overview("CL1")
    asmf = service.performance_overview("ASMF")

    assert "CL1 — 01/01/2024" in summary
    assert "ASMF — 01/01/2024" in summary
    assert "CL1 — BACKTEST PERFORMANCE" in cl1
    assert "ASMF — BACKTEST PERFORMANCE" not in cl1
    assert "ASMF — BACKTEST PERFORMANCE" in asmf
    assert "CL1 — BACKTEST PERFORMANCE" not in asmf
