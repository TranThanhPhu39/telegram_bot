"""P4 ASMF historical point-in-time adapter tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from asmf_data import scoring as asmf_scoring
from asmf_data.models import FinancialReport, SectorMembership
from asmf_data.store import upsert_financial_reports, upsert_sector_memberships
from backtest.adapters import ASMFHistoricalAdapter
from backtest.repository import latest_successful_backtest
from backtest.runner import run_strategy_backtest
from data.database import connect_database
from data.migrations import bootstrap_schema
from data.models import OHLCVBar
from strategy import technical_strategies
from strategy.technical_strategies import StrategyAction, StrategyName, StrategyResult
from telegram_bot.performance_formatters import format_performance_detail


ICT = timezone(timedelta(hours=7))


def bars(symbol: str, count: int = 205, *, start: date = date(2025, 7, 1)) -> tuple[OHLCVBar, ...]:
    first = datetime.combine(start, datetime.min.time(), tzinfo=ICT)
    return tuple(
        OHLCVBar(
            symbol, "ONE_DAY", int((first + timedelta(days=index)).timestamp()),
            100 + index * .1, 101 + index * .1, 99 + index * .1,
            100.5 + index * .1, 1_000_000 + index,
        )
        for index in range(count)
    )


class Data:
    def __init__(self, histories):
        self.histories = histories

    def daily_bars(self, symbol):
        return self.histories.get(symbol, ())


def database():
    value = connect_database("sqlite:///:memory:")
    bootstrap_schema(value)
    return value


def watch(stock, benchmark, **scores) -> StrategyResult:
    latest = stock[-1]
    return StrategyResult(
        StrategyName.ASMF, latest.symbol, latest.timestamp,
        StrategyAction.WATCH, scores.get("fundamental_score"), (), (), (), None,
    )


def test_adapter_reuses_production_evaluate_asmf_and_slices_all_prices(monkeypatch) -> None:
    db = database()
    members = ("FPT", "AAA", "BBB", "CCC", "DDD")
    upsert_sector_memberships(db, [
        SectorMembership(symbol, "TECH", "Technology", date(2020, 1, 1), None, "TEST")
        for symbol in members
    ])
    histories = {symbol: bars(symbol) for symbol in (*members, "VNINDEX")}
    calls = []
    sector_calls = []

    def evaluator(stock, benchmark, **scores):
        calls.append((tuple(stock), tuple(benchmark), scores))
        return watch(stock, benchmark, **scores)

    def sector_score(connection, symbol, as_of, member_histories, benchmark):
        sector_calls.append((as_of, member_histories, tuple(benchmark)))
        return 75.0

    monkeypatch.setattr(technical_strategies, "evaluate_asmf", evaluator)
    monkeypatch.setattr(asmf_scoring, "sector_strength_score", sector_score)
    current_date = date(2026, 1, 16)  # bar index 199
    result = ASMFHistoricalAdapter(db, Data(histories)).evaluate(
        histories["FPT"], start_date=current_date, end_date=current_date
    )

    assert len(result.decisions) == len(calls) == 1
    stock, benchmark, scores = calls[0]
    current_timestamp = stock[-1].timestamp
    assert len(stock) == len(benchmark) == 200
    assert max(bar.timestamp for bar in stock) == current_timestamp
    assert max(bar.timestamp for bar in benchmark) <= current_timestamp
    assert set(scores) == {"sector_score", "fundamental_score", "institutional_flow_score"}
    assert scores["sector_score"] == 75.0
    assert len(sector_calls) == 1
    _, member_histories, sector_benchmark = sector_calls[0]
    assert set(member_histories) == set(members)
    assert all(series and max(bar.timestamp for bar in series) <= current_timestamp
               for series in member_histories.values())
    assert max(bar.timestamp for bar in sector_benchmark) <= current_timestamp


def test_adapter_excludes_financial_report_published_after_as_of() -> None:
    db = database()
    reports = []
    for year in (2024, 2025):
        for quarter in range(1, 5):
            multiplier = 1.0 if year == 2024 else (1.4 if quarter == 4 else 1.2)
            reports.append(FinancialReport(
                "FPT", f"{year}Q{quarter}", date(year, quarter * 3, 28), True,
                100 * multiplier, 20 * multiplier, 100, 50, "VISIBLE",
            ))
    reports.append(FinancialReport(
        "FPT", "2026Q1", date(2026, 4, 28), True,
        1, 1, 10_000, 50_000, "FUTURE",
    ))
    upsert_financial_reports(db, reports)
    histories = {symbol: bars(symbol, 200) for symbol in ("FPT", "VNINDEX")}
    captured = []

    def evaluator(stock, benchmark, **scores):
        captured.append(scores["fundamental_score"])
        return watch(stock, benchmark, **scores)

    as_of = date(2026, 1, 16)
    ASMFHistoricalAdapter(db, Data(histories), evaluator).evaluate(
        histories["FPT"], start_date=as_of, end_date=as_of
    )
    assert captured == [100.0]


def test_missing_mandatory_layers_stay_blocked_like_live() -> None:
    db = database()
    histories = {symbol: bars(symbol, 200) for symbol in ("FPT", "VNINDEX")}
    as_of = date(2026, 1, 16)
    evaluation = ASMFHistoricalAdapter(db, Data(histories)).evaluate(
        histories["FPT"], start_date=as_of, end_date=as_of
    )
    decision = evaluation.decisions[0]
    assert decision.action is StrategyAction.BLOCKED
    assert set(decision.missing) == {
        "sức mạnh ngành/breadth",
        "chất lượng BCTC theo ngày công bố",
        "dòng tiền khối ngoại/tự doanh",
    }


def test_runner_persists_asmf_signal_only_result_without_metrics() -> None:
    db = database()
    histories = {symbol: bars(symbol, 200) for symbol in ("FPT", "VNINDEX")}
    as_of = date(2026, 1, 16)
    result = run_strategy_backtest(
        strategy="ASMF", symbols=("FPT",), start_date=as_of, end_date=as_of,
        data_port=Data(histories), connection=db, run_id="asmf-p4",
        now=lambda: 1_800_000_000,
    )
    loaded = latest_successful_backtest(db, "ASMF")
    assert loaded is not None and loaded.run_id == "asmf-p4"
    assert result.run.config["evaluator"].endswith("evaluate_asmf")
    assert result.run.config["action_counts"] == {"BLOCKED": 1}
    assert result.run.total_return_percent is None
    assert any("không phát SELL" in warning for warning in result.run.warnings)
    text = format_performance_detail("ASMF", loaded)
    assert "HISTORICAL SIGNAL EVALUATION" in text
    assert "Giao dịch đóng: N/A" in text
