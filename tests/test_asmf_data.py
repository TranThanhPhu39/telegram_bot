"""Tests for strict point-in-time ASMF EOD inputs."""

from datetime import date
from pathlib import Path

from asmf_data.csv_source import load_bank_financial_csv, load_financial_csv, load_flow_csv, load_sector_csv
from asmf_data.models import BankFinancialReport, FinancialReport, InstitutionalFlow, SectorMembership
from asmf_data.scoring import bank_fundamental_score, fundamental_score, institutional_flow_score, sector_strength_score
from asmf_data.store import upsert_bank_financial_reports, upsert_financial_reports, upsert_institutional_flows, upsert_sector_memberships
from data.database import connect_database
from data.migrations import bootstrap_schema
from data.models import OHLCVBar


def connection():
    result = connect_database("sqlite:///:memory:")
    bootstrap_schema(result)
    return result


def history(symbol: str, growth: float = .001) -> tuple[OHLCVBar, ...]:
    result = []
    close = 100.0
    for index in range(200):
        close *= 1 + growth
        result.append(OHLCVBar(symbol, "ONE_DAY", 1_700_000_000 + index * 86400,
                              close, close + 1, close - 1, close, 1_000_000))
    return tuple(result)


def test_point_in_time_financial_and_flow_scores_ignore_future_rows() -> None:
    db = connection()
    reports = []
    for year in (2024, 2025):
        for quarter in range(1, 5):
            multiplier = 1.0 if year == 2024 else (1.4 if quarter == 4 else 1.2)
            reports.append(FinancialReport("FPT", f"{year}Q{quarter}",
                date(year, quarter * 3, 28), True, 100 * multiplier,
                20 * multiplier, 100, 50, "TEST"))
    reports.append(FinancialReport("FPT", "2026Q1", date(2026, 4, 28), True,
                                   9999, 9999, 100, 50, "FUTURE"))
    upsert_financial_reports(db, reports)
    assert fundamental_score(db, "FPT", date(2025, 12, 31)) == 100

    flows = [InstitutionalFlow("FPT", date(2025, 1, day), 100, 20, None, None, "TEST")
             for day in range(1, 11)]
    upsert_institutional_flows(db, flows)
    assert institutional_flow_score(db, "FPT", date(2025, 1, 10)) > 50


def test_fundamental_score_rejects_eight_rows_with_a_missing_quarter() -> None:
    db = connection()
    periods = (
        "2026Q2", "2026Q1", "2025Q4", "2025Q2",
        "2025Q1", "2024Q4", "2024Q3", "2024Q2",
    )
    upsert_financial_reports(db, [
        FinancialReport(
            "FPT", period, date(2026, 9, 1), True,
            100.0, 20.0, 100.0, 50.0, "TEST",
        )
        for period in periods
    ])

    assert fundamental_score(db, "FPT", date(2026, 12, 31)) is None


def test_sector_score_requires_five_members_and_uses_breadth() -> None:
    db = connection()
    members = tuple(f"S{i}" for i in range(5))
    upsert_sector_memberships(db, [SectorMembership(symbol, "TECH", "Technology",
        date(2020, 1, 1), None, "TEST") for symbol in members])
    histories = {symbol: history(symbol, .002) for symbol in members}
    score = sector_strength_score(db, "S0", date(2025, 1, 1), histories, history("VNINDEX", .001))
    assert score is not None and score > 50


def test_flow_without_proprietary_data_remains_usable() -> None:
    db = connection()
    upsert_institutional_flows(db, [InstitutionalFlow("ACB", date(2025, 1, day),
        50, 50, None, None, "TEST") for day in range(1, 6)])
    assert institutional_flow_score(db, "ACB", date(2025, 1, 5)) == 50


def test_strict_csv_templates_load(tmp_path) -> None:
    sector = tmp_path / "sectors.csv"
    sector.write_text("symbol,sector_code,sector_name,effective_from,effective_to,source\nFPT,TECH,Technology,2025-01-01,,TEST\n", encoding="utf-8")
    financial = tmp_path / "financial.csv"
    financial.write_text("symbol,report_period,public_date,consolidated,revenue,net_profit,equity,total_debt,source\nFPT,2025Q1,2025-04-20,true,100,20,80,30,TEST\n", encoding="utf-8")
    flow = tmp_path / "flow.csv"
    flow.write_text("symbol,trading_date,foreign_buy_value,foreign_sell_value,proprietary_buy_value,proprietary_sell_value,source\nFPT,2025-04-20,10,5,,,TEST\n", encoding="utf-8")
    assert load_sector_csv(sector)[0].sector_code == "TECH"
    assert load_financial_csv(financial)[0].public_date == date(2025, 4, 20)
    assert load_flow_csv(flow)[0].proprietary_buy_value is None


def test_bank_score_uses_bank_quality_not_debt_to_equity() -> None:
    db = connection()
    reports = []
    cumulative_nii = {2024: 0.0, 2025: 0.0}
    cumulative_profit = {2024: 0.0, 2025: 0.0}
    for year in (2024, 2025):
        for quarter in range(1, 5):
            growth = 1.0 if year == 2024 else 1.25
            cumulative_nii[year] += 100 * growth
            cumulative_profit[year] += 25 * growth
            reports.append(BankFinancialReport(
                "ACB", f"{year}Q{quarter}", date(year, quarter * 3, 28), quarter * 3,
                cumulative_nii[year], cumulative_profit[year], 500, 10_000,
                150, 180, 12, "TEST",
            ))
    upsert_bank_financial_reports(db, reports)
    assert bank_fundamental_score(db, "ACB", date(2025, 12, 31)) == 100
    assert fundamental_score(db, "ACB", date(2025, 12, 31)) == 100


def test_bank_score_blocks_when_car_or_asset_quality_is_missing() -> None:
    db = connection()
    reports = [BankFinancialReport(
        "ACB", f"{year}Q{quarter}", date(year, quarter * 3, 28), quarter * 3,
        quarter * 100, quarter * 25, 500, 10_000, None, None, None, "TEST",
    ) for year in (2024, 2025) for quarter in range(1, 5)]
    upsert_bank_financial_reports(db, reports)
    assert bank_fundamental_score(db, "ACB", date(2025, 12, 31)) is None


def test_incomplete_bank_data_never_falls_back_to_industrial_score() -> None:
    db = connection()
    bank_rows = [BankFinancialReport(
        "ACB", f"{year}Q{quarter}", date(year, quarter * 3, 28), quarter * 3,
        quarter * 100, quarter * 25, 500, 10_000, None, None, None, "TEST",
    ) for year in (2024, 2025) for quarter in range(1, 5)]
    industrial_rows = [FinancialReport(
        "ACB", f"{year}Q{quarter}", date(year, quarter * 3, 28), True,
        200, 50, 100, 10, "SHOULD_NOT_BE_USED",
    ) for year in (2024, 2025) for quarter in range(1, 5)]
    upsert_bank_financial_reports(db, bank_rows)
    upsert_financial_reports(db, industrial_rows)
    assert fundamental_score(db, "ACB", date(2025, 12, 31)) is None


def test_real_acb_ocr_dataset_imports_and_reads_back() -> None:
    path = Path(__file__).parent / "fixtures" / "asmf" / "acb_2026q2_ocr.csv"
    rows = load_bank_financial_csv(path)
    db = connection()
    assert upsert_bank_financial_reports(db, rows) == 1
    stored = db.execute(
        "SELECT * FROM bank_financial_reports WHERE symbol='ACB' AND report_period='2026Q2'"
    ).fetchone()
    assert stored["public_date"] == "2026-08-15"
    assert stored["net_interest_income"] == 14_773_853
    assert stored["net_profit"] == 8_612_866
    assert stored["equity"] == 99_314_518
    assert stored["gross_loans"] == 745_759_303
    assert stored["loan_loss_reserve"] == 8_065_344
    assert stored["nonperforming_loans"] == 7_657_409
    assert stored["car_percent"] is None
