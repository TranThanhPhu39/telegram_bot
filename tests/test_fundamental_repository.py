"""Point-in-time fundamental facts: no look-ahead, no invented ratios."""

from datetime import date

from asmf_data.models import BankFinancialReport, FinancialReport
from asmf_data.store import upsert_bank_financial_reports, upsert_financial_reports
from data.database import connect_database
from data.migrations import bootstrap_schema
from fundamentals.repository import load_fundamental_facts


def connection():
    conn = connect_database("sqlite:///:memory:")
    bootstrap_schema(conn)
    return conn


def corporate_rows(symbol="FPT"):
    rows = []
    for index in range(8):
        year, quarter = 2025 + index // 4, index % 4 + 1
        rows.append(
            FinancialReport(
                symbol, f"{year}Q{quarter}", date(year, quarter * 3, 28), True,
                1_000.0 + index * 100, 100.0 + index * 20, 5_000.0, 2_500.0,
                "Vietstock",
            )
        )
    return rows


def test_corporate_facts_are_derived_from_stored_reports() -> None:
    conn = connection()
    upsert_financial_reports(conn, corporate_rows())
    facts = load_fundamental_facts(conn, "FPT", date(2027, 1, 1))
    assert facts is not None
    assert facts.kind == "CORPORATE"
    assert facts.period == "2026Q4"
    assert facts.debt_to_equity == 0.5
    assert facts.roe_percent is not None
    assert facts.revenue_growth_percent > 0
    assert facts.pe is None and facts.pb is None and facts.eps is None
    assert "P/E" in facts.missing_fields


def test_corporate_facts_hide_ttm_metrics_when_quarters_are_not_contiguous() -> None:
    conn = connection()
    rows = [row for row in corporate_rows() if row.report_period != "2025Q3"]
    rows.append(FinancialReport(
        "FPT", "2024Q4", date(2025, 2, 14), True,
        800.0, 80.0, 5_000.0, 2_500.0, "Vietstock",
    ))
    upsert_financial_reports(conn, rows)

    facts = load_fundamental_facts(conn, "FPT", date(2027, 1, 1))

    assert facts is not None
    assert facts.roe_percent is None
    assert facts.revenue_growth_percent is None
    assert facts.profit_growth_percent is None
    assert facts.debt_to_equity == 0.5
    assert facts.quality_issue == "Chưa đủ 8 quý liên tục để tính TTM. Thiếu: 2025Q3."


def test_reports_published_after_the_as_of_date_are_ignored() -> None:
    conn = connection()
    upsert_financial_reports(conn, corporate_rows())
    facts = load_fundamental_facts(conn, "FPT", date(2025, 6, 30))
    assert facts is not None
    assert facts.period == "2025Q2"
    assert facts.roe_percent is None


def test_unknown_symbol_returns_none() -> None:
    assert load_fundamental_facts(connection(), "ZZZ", date(2027, 1, 1)) is None


def bank_rows(symbol="ACB"):
    rows = []
    for index in range(8):
        year, quarter = 2025 + index // 4, index % 4 + 1
        rows.append(
            BankFinancialReport(
                symbol, f"{year}Q{quarter}", date(year, quarter * 3, 28), quarter * 3,
                1_000.0 * quarter + index * 10, 400.0 * quarter + index * 5,
                20_000.0, 100_000.0, 1_500.0, 1_800.0, 12.0, "Vietstock",
            )
        )
    return rows


def test_bank_facts_use_bank_specific_metrics_only() -> None:
    conn = connection()
    upsert_bank_financial_reports(conn, bank_rows())
    facts = load_fundamental_facts(conn, "ACB", date(2027, 1, 1))
    assert facts is not None
    assert facts.kind == "BANK"
    assert facts.npl_percent == 1.5
    assert facts.coverage_percent == 120.0
    assert facts.car_percent == 12.0
    assert facts.debt_to_equity is None
    assert "Debt/Equity" not in facts.missing_fields


def test_csv_snapshot_supplies_only_ratios_sqlite_cannot_derive(tmp_path) -> None:
    conn = connection()
    upsert_financial_reports(conn, corporate_rows())
    csv_path = tmp_path / "fundamentals.csv"
    csv_path.write_text(
        "symbol,as_of_date,source,eps,pe,pb,roe_percent,"
        "revenue_growth_percent,profit_growth_percent\n"
        "FPT,2026-12-30,Vietstock snapshot,5000,14.2,3.1,,,\n",
        encoding="utf-8",
    )
    facts = load_fundamental_facts(conn, "FPT", date(2027, 1, 1), csv_path=csv_path)
    assert facts is not None
    assert facts.pe == 14.2 and facts.pb == 3.1 and facts.eps == 5000
    assert facts.roe_percent is not None
    assert "Vietstock snapshot" in facts.source


def test_missing_csv_path_is_not_an_error() -> None:
    conn = connection()
    upsert_financial_reports(conn, corporate_rows())
    facts = load_fundamental_facts(conn, "FPT", date(2027, 1, 1), csv_path="/nope.csv")
    assert facts is not None and facts.pe is None


def test_valuation_snapshot_derives_eps_pe_pb_bvps_from_reports(tmp_path) -> None:
    conn = connection()
    upsert_financial_reports(conn, corporate_rows())
    valuation_csv = tmp_path / "valuation.csv"
    # corporate_rows() gives the latest 4 quarters net_profit = 100+500+600+700
    # (index 4..7 -> 100.0 + index*20) => TTM net profit = 100+180+... see below.
    valuation_csv.write_text(
        "symbol,as_of_date,source,price,shares_outstanding\n"
        "FPT,2026-12-30,vietcap-eod,50000,1000000\n",
        encoding="utf-8",
    )
    facts = load_fundamental_facts(
        conn, "FPT", date(2027, 1, 1), valuation_csv_path=valuation_csv
    )
    assert facts is not None
    # rows[:4] are the 4 most recent quarters (index 4..7): net_profit values
    # 100+80*4=180, 200, 220, 240 -> equity is a fixed 5_000.0 in corporate_rows().
    assert facts.eps is not None
    assert facts.bvps == 5_000.0 / 1_000_000.0
    assert facts.pe is not None and facts.pe == 50_000.0 / facts.eps
    assert facts.pb == 50_000.0 / facts.bvps
    assert "vietcap-eod" in facts.source
    assert "P/E" not in facts.missing_fields
    assert "BVPS" not in facts.missing_fields


def test_valuation_snapshot_never_fabricates_when_shares_missing(tmp_path) -> None:
    conn = connection()
    upsert_financial_reports(conn, corporate_rows())
    valuation_csv = tmp_path / "valuation.csv"
    valuation_csv.write_text(
        "symbol,as_of_date,source,price,shares_outstanding\n"
        "FPT,2026-12-30,vietcap-eod,50000,\n",
        encoding="utf-8",
    )
    facts = load_fundamental_facts(
        conn, "FPT", date(2027, 1, 1), valuation_csv_path=valuation_csv
    )
    assert facts is not None
    assert facts.eps is None and facts.pe is None and facts.pb is None and facts.bvps is None


def test_legacy_csv_snapshot_still_overrides_derived_valuation(tmp_path) -> None:
    """An explicit, human-provided EPS/P/E/P/B (legacy V1 CSV) wins over a
    value merely derived from price + shares outstanding."""
    conn = connection()
    upsert_financial_reports(conn, corporate_rows())
    valuation_csv = tmp_path / "valuation.csv"
    valuation_csv.write_text(
        "symbol,as_of_date,source,price,shares_outstanding\n"
        "FPT,2026-12-30,vietcap-eod,50000,1000000\n",
        encoding="utf-8",
    )
    legacy_csv = tmp_path / "fundamentals.csv"
    legacy_csv.write_text(
        "symbol,as_of_date,source,eps,pe,pb,roe_percent,"
        "revenue_growth_percent,profit_growth_percent\n"
        "FPT,2026-12-30,Vietstock snapshot,5000,14.2,3.1,,,\n",
        encoding="utf-8",
    )
    facts = load_fundamental_facts(
        conn, "FPT", date(2027, 1, 1),
        csv_path=legacy_csv, valuation_csv_path=valuation_csv,
    )
    assert facts is not None
    assert facts.eps == 5000 and facts.pe == 14.2 and facts.pb == 3.1
    # BVPS has no legacy-CSV equivalent to override -- it still comes through.
    assert facts.bvps is not None
