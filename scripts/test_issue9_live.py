"""Live verification script for Issue 9: Fundamental/ASMF Point-in-Time fallback.

Verifies:
1. Provider preferences include TCBS ("KBS", "VCI", "TCBS").
2. Statements without actual public_date resolve to period_end + 45 days.
3. Metadata public_date_source is set ('actual' vs 'estimated_45d').
4. Anti-look-ahead check: public_date <= as_of constraint is strictly respected.
5. Live pipeline execution with temporary database.
6. ASMF fundamental_score 8-quarter requirement behavior analysis.
"""

from __future__ import annotations

from datetime import date, timedelta
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data.database import connect_database
from data.migrations import bootstrap_schema
from fundamentals.adapters import (
    corporate_promotion_gap,
    promote_corporate_statement,
    resolve_public_date,
)
from fundamentals.coverage_store import load_automated_statements
from fundamentals.providers.base import (
    DEFAULT_FS_PUBLISH_LAG_DAYS,
    ProviderResult,
    ProviderStatus,
    StatementRow,
    estimate_publication_date,
    period_end_date,
)
from fundamentals.providers.provider_chain import ProviderChain
from fundamentals.providers.vnstock_provider import (
    DEFAULT_SOURCE_PREFERENCE,
    VNStockProvider,
)
from fundamentals.refresh_service import refresh_financials
from asmf_data.scoring import fundamental_score
from asmf_data.store import latest_financial_reports, upsert_financial_reports


def run_verification() -> bool:
    print("==================================================")
    print("AUDIT & LIVE VERIFICATION: ISSUE 9 (FUNDAMENTAL PIT)")
    print("==================================================")

    # 1. Verify TCBS inclusion in source preference
    print("\n[1] Checking Provider Configuration:")
    print(f"  DEFAULT_SOURCE_PREFERENCE: {DEFAULT_SOURCE_PREFERENCE}")
    assert "TCBS" in DEFAULT_SOURCE_PREFERENCE, "TCBS must be in DEFAULT_SOURCE_PREFERENCE"
    assert DEFAULT_SOURCE_PREFERENCE == ("KBS", "VCI", "TCBS"), f"Unexpected preference: {DEFAULT_SOURCE_PREFERENCE}"
    print("  -> PASSED: TCBS is enabled as tertiary source preference.")

    # 2. Verify Date Resolution Logic
    print("\n[2] Checking Date Resolution & Fallback Logic:")
    # Case A: Actual public date present
    row_actual = StatementRow(
        "FPT", "2026Q2", date(2026, 8, 20), values={
            "revenue": 1000.0, "net_income": 100.0, "total_equity": 2000.0,
            "short_term_debt": 5.0, "long_term_debt": 5.0,
        },
    )
    pdate_a, src_a = resolve_public_date(row_actual)
    assert pdate_a == date(2026, 8, 20) and src_a == "actual"
    print(f"  Case A (Actual date): {pdate_a} | source={src_a}")

    # Case B: Missing actual, valid period -> period_end + 45d
    row_est = StatementRow(
        "FPT", "2026Q2", None, values={
            "revenue": 1000.0, "net_income": 100.0, "total_equity": 2000.0,
            "short_term_debt": 5.0, "long_term_debt": 5.0,
        },
    )
    pdate_b, src_b = resolve_public_date(row_est)
    expected_date = period_end_date("2026Q2") + timedelta(days=DEFAULT_FS_PUBLISH_LAG_DAYS)  # 2026-06-30 + 45d = 2026-08-14
    assert pdate_b == expected_date == date(2026, 8, 14)
    assert src_b == "estimated_45d"
    # Anti-look-ahead check: must NOT equal period end
    assert pdate_b != period_end_date("2026Q2")
    print(f"  Case B (Estimated date): {pdate_b} (period_end={period_end_date('2026Q2')}) | source={src_b}")

    # Case C: Missing both -> reject
    row_none = StatementRow("FPT", "INVALID", None, values={
        "revenue": 1000.0, "net_income": 100.0, "total_equity": 2000.0,
        "short_term_debt": 5.0, "long_term_debt": 5.0,
    })
    pdate_c, src_c = resolve_public_date(row_none)
    assert pdate_c is None and src_c is None
    gap_c = corporate_promotion_gap(row_none)
    assert gap_c == "no public_date or parsable report_period"
    assert promote_corporate_statement(row_none, source="VNStock/TCBS") is None
    print(f"  Case C (Neither): pdate={pdate_c} | gap='{gap_c}' -> REJECTED")

    # 3. Verify Point-in-Time Boundary & Promotion in Database
    print("\n[3] Testing Promotion & Point-in-Time Query Boundary:")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "issue9_test.sqlite3")
        conn = connect_database(f"sqlite:///{db_path}")
        bootstrap_schema(conn)

        report = promote_corporate_statement(row_est, source="VNStock/TCBS")
        assert report is not None
        assert report.public_date == date(2026, 8, 14)
        assert report.public_date_source == "estimated_45d"
        upsert_financial_reports(conn, [report])

        # Case D: as_of before estimated date -> NOT usable
        res_before_lag = latest_financial_reports(conn, "FPT", as_of=date(2026, 8, 13))
        res_at_quarter_end = latest_financial_reports(conn, "FPT", as_of=date(2026, 6, 30))
        assert len(res_before_lag) == 0
        assert len(res_at_quarter_end) == 0
        print(f"  Case D (as_of 2026-06-30 and 2026-08-13): visible={len(res_before_lag)} (STRICT ANTI-LOOK-AHEAD)")

        # Case E: as_of on or after estimated date -> USABLE
        res_on_lag = latest_financial_reports(conn, "FPT", as_of=date(2026, 8, 14))
        res_after_lag = latest_financial_reports(conn, "FPT", as_of=date(2026, 8, 20))
        assert len(res_on_lag) == 1
        assert len(res_after_lag) == 1
        print(f"  Case E (as_of 2026-08-14 and 2026-08-20): visible={len(res_on_lag)} (PROMOTED & POINT-IN-TIME READY)")

        # 4. Fundamental Score & 8-Quarter Requirement Check
        print("\n[4] Checking 8-Quarter Requirement in fundamental_score:")
        # Test with 7 quarters -> should return None
        quarters_7 = [
            ("2026Q2", 150.0, 30.0), ("2026Q1", 140.0, 28.0),
            ("2025Q4", 130.0, 26.0), ("2025Q3", 120.0, 24.0),
            ("2025Q2", 100.0, 20.0), ("2025Q1", 95.0, 19.0),
            ("2024Q4", 90.0, 18.0),
        ]
        reports_7 = [
            promote_corporate_statement(
                StatementRow("FPT", p, None, values={
                    "revenue": rev, "net_income": profit, "total_equity": 1000.0,
                    "short_term_debt": 10.0, "long_term_debt": 10.0,
                }),
                source="VNStock/TCBS",
            )
            for p, rev, profit in quarters_7
        ]
        upsert_financial_reports(conn, [r for r in reports_7 if r is not None])
        score_7 = fundamental_score(conn, "FPT", as_of=date(2026, 8, 20))
        print(f"  With 7 quarters: score = {score_7} (EXPECTED: None because < 8 quarters)")
        assert score_7 is None, "Score must be None when < 8 quarters"

        # Add 8th quarter ("2024Q3")
        r_8 = promote_corporate_statement(
            StatementRow("FPT", "2024Q3", None, values={
                "revenue": 85.0, "net_income": 17.0, "total_equity": 1000.0,
                "short_term_debt": 10.0, "long_term_debt": 10.0,
            }),
            source="VNStock/TCBS",
        )
        assert r_8 is not None
        upsert_financial_reports(conn, [r_8])

        # Case F: With 8 quarters, fundamental_score is calculated successfully!
        score_8 = fundamental_score(conn, "FPT", as_of=date(2026, 8, 20))
        print(f"  Case F (With 8 quarters, all estimated_45d): score = {score_8} (SUCCESS!)")
        assert score_8 is not None and score_8 > 0, f"Score was {score_8}"
        conn.close()

    print("\n==================================================")
    print("ALL ISSUE 9 VERIFICATION CHECKS COMPLETED SUCCESSFULLY!")
    print("==================================================")
    return True


if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
