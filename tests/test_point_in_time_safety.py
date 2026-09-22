"""No-look-ahead guarantees for the Phase 24 automated acquisition path.

These tests protect the single most safety-critical property in the whole
fundamentals pipeline: an analysis run as of date D must never be able to see
a report that was not yet public as of D, and it must never treat "we don't
know when this was published" as "it was published in time".
"""

from __future__ import annotations

from datetime import date

import pytest

from asmf_data.scoring import fundamental_score
from asmf_data.store import latest_financial_reports, upsert_financial_reports
from data.database import connect_database
from data.migrations import bootstrap_schema
from fundamentals.adapters import corporate_promotion_gap, promote_corporate_statement
from fundamentals.coverage_store import load_automated_statements
from fundamentals.providers.base import ProviderResult, ProviderStatus, StatementRow
from fundamentals.providers.provider_chain import ProviderChain
from fundamentals.providers.yfinance_provider import YFinanceProvider
from fundamentals.refresh_service import refresh_financials


@pytest.fixture()
def connection(tmp_path):
    conn = connect_database(f"sqlite:///{tmp_path / 'pit.sqlite3'}")
    bootstrap_schema(conn)
    conn.execute("INSERT INTO symbols(symbol) VALUES ('FPT')")
    conn.commit()
    return conn


def _full_statement(period: str, public_date) -> StatementRow:
    return StatementRow(
        "FPT", period, public_date, values={
            "revenue": 1000.0, "net_income": 100.0, "total_equity": 2000.0,
            "short_term_debt": 5.0, "long_term_debt": 5.0,
        },
    )


def test_a_report_published_after_the_analysis_date_is_invisible_to_that_analysis(
    connection,
) -> None:
    future_report = _full_statement("2026Q4", date(2027, 1, 20))
    report = promote_corporate_statement(future_report, source="VNStock/VCI")
    assert report is not None
    upsert_financial_reports(connection, [report])

    visible_before_publication = latest_financial_reports(connection, "FPT", date(2026, 12, 31))
    assert visible_before_publication == ()

    visible_after_publication = latest_financial_reports(connection, "FPT", date(2027, 1, 21))
    assert len(visible_after_publication) == 1


def test_missing_publication_date_and_period_never_promotes_to_the_point_in_time_table(connection) -> None:
    """A row with neither an actual publication date nor a parsable report
    period must not silently create point-in-time availability."""
    unusable = StatementRow(
        "FPT", "INVALID", None, values={
            "revenue": 1000.0, "net_income": 100.0, "total_equity": 2000.0,
            "short_term_debt": 5.0, "long_term_debt": 5.0,
        },
    )
    assert promote_corporate_statement(unusable, source="VNStock/VCI") is None
    assert corporate_promotion_gap(unusable) == "no public_date or parsable report_period"

    # Incomplete financial fields with valid period can stage in SQLite but never promote
    unpromotable = StatementRow(
        "FPT", "2026Q2", None, values={
            "revenue": 1000.0, "net_income": 100.0, "total_equity": 2000.0,
            # missing short_term_debt and long_term_debt
        },
    )
    assert promote_corporate_statement(unpromotable, source="VNStock/VCI") is None
    chain = ProviderChain([_FixedResultProvider(statements=(unpromotable,))])
    outcome = refresh_financials(connection, chain, "FPT")

    assert outcome.rows_promoted == 0
    assert latest_financial_reports(connection, "FPT", date(2099, 1, 1)) == ()
    staged = load_automated_statements(connection, "FPT")
    assert staged[0]["promoted_to_canonical"] == 0


def test_missing_actual_date_with_valid_period_promotes_with_45d_lag(connection) -> None:
    """A provider that establishes numbers and report_period but not actual public_date
    promotes with period_end + 45 days, maintaining anti-look-ahead safety."""
    undated = StatementRow(
        "FPT", "2026Q2", None, values={
            "revenue": 1000.0, "net_income": 100.0, "total_equity": 2000.0,
            "short_term_debt": 5.0, "long_term_debt": 5.0,
        },
    )
    report = promote_corporate_statement(undated, source="VNStock/TCBS")
    assert report is not None
    assert report.public_date == date(2026, 8, 14)
    assert report.public_date_source == "estimated_45d"

    chain = ProviderChain([_FixedResultProvider(statements=(undated,))])
    outcome = refresh_financials(connection, chain, "FPT")

    assert outcome.rows_promoted == 1
    # Anti-look-ahead: before 45d lag date, report is invisible
    assert latest_financial_reports(connection, "FPT", date(2026, 6, 30)) == ()
    assert latest_financial_reports(connection, "FPT", date(2026, 8, 13)) == ()
    # At and after 45d lag date, report is visible
    assert len(latest_financial_reports(connection, "FPT", date(2026, 8, 14))) == 1
    staged = load_automated_statements(connection, "FPT")
    assert staged[0]["public_date"] == "2026-08-14"
    assert staged[0]["promoted_to_canonical"] == 1


def test_yfinance_rows_never_carry_a_publication_date_by_construction() -> None:
    """Yahoo has no Vietnamese announcement-date field; the adapter must not
    invent one from the fiscal period end, which would fabricate point-in-time
    availability for every Yahoo-sourced statement."""
    import types

    class Ticker:
        def __init__(self, symbol: str) -> None:
            self.quarterly_financials = types.SimpleNamespace(
                to_dict=lambda: {date(2026, 6, 30): {"Total Revenue": 500.0}}
            )

    provider = YFinanceProvider(module=types.SimpleNamespace(Ticker=Ticker))
    result = provider.fetch_financials("FPT", exchange="HOSE")

    assert result.statements
    assert all(row.public_date is None for row in result.statements)
    assert all(promote_corporate_statement(row, source="yfinance") is None for row in result.statements)


def test_period_end_date_helper_is_never_used_as_a_publication_date_substitute() -> None:
    """period_end_date must never be used directly as public_date (which creates look-ahead).
    The strategy rule applies report_period + 45 days fallback instead."""
    from fundamentals.providers.base import period_end_date

    row = StatementRow("FPT", "2026Q2", None, values={
        "revenue": 1.0, "net_income": 1.0, "total_equity": 1.0,
        "short_term_debt": 0.0, "long_term_debt": 0.0,
    })
    # Sanity: the helper computes period end...
    assert period_end_date(row.period) == date(2026, 6, 30)
    # Promotion must NOT use period_end_date directly (anti-look-ahead)
    report = promote_corporate_statement(row, source="VNStock")
    assert report is not None
    assert report.public_date != date(2026, 6, 30)
    # Must use report_period + 45 days
    assert report.public_date == date(2026, 8, 14)
    assert report.public_date_source == "estimated_45d"


def test_asmf_fundamental_score_stays_none_until_eight_public_quarters_exist(
    connection,
) -> None:
    """Regression guard: partially-published history must not produce a score
    from fewer than the eight quarters the scoring function requires."""
    for i in range(5):  # fewer than the 8 quarters fundamental_score requires
        quarter = 4 - (i % 4)
        year = 2025 if i < 4 else 2024
        report = promote_corporate_statement(
            _full_statement(f"{year}Q{quarter}", date(year, 3 * quarter if quarter < 4 else 12, 15)),
            source="VNStock/VCI",
        )
        assert report is not None
        upsert_financial_reports(connection, [report])

    assert fundamental_score(connection, "FPT", date(2026, 1, 1)) is None


class _FixedResultProvider:
    """Minimal stand-in used only for the undated-statement test above."""

    name = "VNStock"

    def __init__(self, statements=()):
        self._statements = statements

    def available(self) -> bool:
        return True

    def fetch_financials(self, symbol, *, exchange=None):
        if not self._statements:
            return ProviderResult.missing(symbol, "FINANCIALS", self.name)
        return ProviderResult(
            symbol=symbol, dataset="FINANCIALS", provider=self.name,
            status=ProviderStatus.AVAILABLE, provider_source="VCI",
            statements=self._statements,
        )

    def fetch_institutional_flow(self, symbol, *, exchange=None, lookback_days=30):
        return ProviderResult.missing(symbol, "INSTITUTIONAL", self.name)
