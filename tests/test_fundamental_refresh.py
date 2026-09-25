"""Refresh service: idempotency, freshness policy, promotion, ASMF regression."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from asmf_data.scoring import fundamental_score
from asmf_data.store import (
    latest_bank_financial_reports,
    latest_financial_reports,
    recent_flows,
    upsert_financial_reports,
)
from asmf_data.models import FinancialReport
from data.database import connect_database
from data.migrations import bootstrap_schema
from fundamentals.adapters import (
    VIETCAP_BANK_SOURCE,
    corporate_promotion_gap,
    flow_row_to_institutional_flow,
    promote_bank_statement,
    promote_corporate_statement,
)
from fundamentals.coverage_store import (
    coverage_is_stale,
    load_all_coverage,
    load_automated_statements,
    load_coverage,
)
from fundamentals.providers.base import (
    FlowRow,
    FundamentalProvider,
    ProviderResult,
    ProviderStatus,
    StatementRow,
)
from fundamentals.providers.provider_chain import ProviderChain
from fundamentals.refresh_service import (
    RefreshResult,
    refresh_financials,
    refresh_institutional_flow,
)


def statement(symbol: str, period: str, public_date, **values: float) -> StatementRow:
    return StatementRow(symbol, period, public_date, values=values)


class StubProvider(FundamentalProvider):
    """A provider whose response is fixed per test, never touches a network."""

    name = "VNStock"

    def __init__(
        self,
        statements: tuple[StatementRow, ...] = (),
        flows: tuple[FlowRow, ...] = (),
        status: ProviderStatus = ProviderStatus.AVAILABLE,
        error: str | None = None,
    ) -> None:
        self._statements = statements
        self._flows = flows
        self._status = status
        self._error = error
        self.financial_calls = 0
        self.flow_calls = 0

    def available(self) -> bool:
        return True

    def fetch_financials(self, symbol: str, *, exchange: str | None = None) -> ProviderResult:
        self.financial_calls += 1
        if self._error:
            return ProviderResult.failed(symbol, "FINANCIALS", self.name, self._error)
        if not self._statements:
            return ProviderResult.missing(symbol, "FINANCIALS", self.name)
        return ProviderResult(
            symbol=symbol, dataset="FINANCIALS", provider=self.name,
            status=self._status, provider_source="VCI", statements=self._statements,
        )

    def fetch_institutional_flow(
        self, symbol: str, *, exchange: str | None = None, lookback_days: int = 30
    ) -> ProviderResult:
        self.flow_calls += 1
        if not self._flows:
            return ProviderResult.missing(symbol, "INSTITUTIONAL", self.name)
        return ProviderResult(
            symbol=symbol, dataset="INSTITUTIONAL", provider=self.name,
            status=self._status, provider_source="VCI", flows=self._flows,
        )


@pytest.fixture()
def connection(tmp_path):
    conn = connect_database(f"sqlite:///{tmp_path / 'test.sqlite3'}")
    bootstrap_schema(conn)
    conn.execute("INSERT INTO symbols(symbol, exchange) VALUES ('FPT', 'HOSE')")
    conn.commit()
    return conn


# --------------------------------------------------------------- financials
def test_full_statement_is_staged_and_promoted_to_canonical_storage(connection) -> None:
    row = statement(
        "FPT", "2026Q2", date(2026, 8, 15),
        revenue=1000.0, net_income=100.0, total_equity=2000.0,
        short_term_debt=5.0, long_term_debt=5.0,
    )
    chain = ProviderChain([StubProvider(statements=(row,))])

    outcome = refresh_financials(connection, chain, "fpt")

    assert outcome.result is RefreshResult.SUCCESS
    assert outcome.rows_stored == 1 and outcome.rows_promoted == 1
    assert len(latest_financial_reports(connection, "FPT", date(2026, 12, 31))) == 1
    staged = load_automated_statements(connection, "FPT")
    assert staged[0]["promoted_to_canonical"] == 1


def test_second_refresh_within_the_interval_is_skipped_without_calling_the_provider(connection) -> None:
    row = statement("FPT", "2026Q2", date(2026, 8, 15), revenue=1.0, net_income=1.0,
                     total_equity=1.0, short_term_debt=0.0, long_term_debt=0.0)
    provider = StubProvider(statements=(row,))
    chain = ProviderChain([provider])

    refresh_financials(connection, chain, "FPT")
    outcome = refresh_financials(connection, chain, "FPT")

    assert outcome.result is RefreshResult.SKIPPED_FRESH
    assert provider.financial_calls == 1  # the second call never reached the provider


def test_force_bypasses_the_freshness_skip(connection) -> None:
    row = statement("FPT", "2026Q2", date(2026, 8, 15), revenue=1.0, net_income=1.0,
                     total_equity=1.0, short_term_debt=0.0, long_term_debt=0.0)
    provider = StubProvider(statements=(row,))
    chain = ProviderChain([provider])

    refresh_financials(connection, chain, "FPT")
    outcome = refresh_financials(connection, chain, "FPT", force=True)

    assert outcome.result is RefreshResult.SUCCESS
    assert provider.financial_calls == 2


def test_rerunning_the_same_period_and_source_updates_the_staging_row_not_duplicates_it(connection) -> None:
    first = statement("FPT", "2026Q2", date(2026, 8, 15), revenue=1000.0, net_income=1.0,
                       total_equity=1.0, short_term_debt=0.0, long_term_debt=0.0)
    second = statement("FPT", "2026Q2", date(2026, 8, 16), revenue=1050.0, net_income=1.0,
                        total_equity=1.0, short_term_debt=0.0, long_term_debt=0.0)
    refresh_financials(connection, ProviderChain([StubProvider(statements=(first,))]), "FPT")
    refresh_financials(connection, ProviderChain([StubProvider(statements=(second,))]), "FPT", force=True)

    staged = load_automated_statements(connection, "FPT")
    assert len(staged) == 1
    assert staged[0]["revenue"] == 1050.0


def test_partial_result_is_staged_but_not_promoted_to_canonical(connection) -> None:
    row = statement("FPT", "2026Q1", date(2026, 5, 1), net_income=1.0)  # no revenue/equity/debt
    chain = ProviderChain([StubProvider(statements=(row,), status=ProviderStatus.PARTIAL)])

    outcome = refresh_financials(connection, chain, "FPT")

    assert outcome.result is RefreshResult.PARTIAL
    assert outcome.rows_stored == 1 and outcome.rows_promoted == 0
    assert latest_financial_reports(connection, "FPT", date(2026, 12, 31)) == ()


def test_usable_result_with_promotion_gap_is_visible_in_coverage_reason(
    connection,
) -> None:
    """When a provider answers with values but statements cannot be promoted
    due to missing required fields, that gap is explicit in coverage reason."""
    row_a = statement("FPT", "2026Q2", date(2026, 8, 15), revenue=1000.0, net_income=100.0,
                      total_equity=2000.0)  # missing debt legs
    row_b = statement("FPT", "2026Q1", date(2026, 5, 1), revenue=1000.0, net_income=100.0,
                      total_equity=2000.0)  # missing debt legs
    chain = ProviderChain([StubProvider(statements=(row_a, row_b), status=ProviderStatus.AVAILABLE)])

    outcome = refresh_financials(connection, chain, "FPT")

    assert outcome.result is RefreshResult.SUCCESS  # the raw fetch genuinely succeeded
    assert outcome.rows_stored == 2 and outcome.rows_promoted == 0
    assert latest_financial_reports(connection, "FPT", date(2026, 12, 31)) == ()
    assert outcome.coverage.status == "PARTIAL"
    assert outcome.coverage.error_reason is not None
    assert "no valid quarterly reports available" in outcome.coverage.error_reason
    assert "missing short_term_debt or long_term_debt" in outcome.coverage.error_reason
    assert outcome.error_reason == outcome.coverage.error_reason


def test_estimated_public_date_promotes_statement_with_45d_lag(connection) -> None:
    """Strategy rule: provider without actual public_date but with valid report_period
    promotes with estimated public_date = period_end_date + 45 days."""
    row = statement("FPT", "2026Q2", None, revenue=1000.0, net_income=100.0,
                     total_equity=2000.0, short_term_debt=5.0, long_term_debt=5.0)
    chain = ProviderChain([StubProvider(statements=(row,), status=ProviderStatus.AVAILABLE)])

    outcome = refresh_financials(connection, chain, "FPT")

    assert outcome.rows_stored == 1 and outcome.rows_promoted == 1
    assert "missing contiguous quarters" in outcome.error_reason
    reports = latest_financial_reports(connection, "FPT", date(2026, 12, 31))
    assert len(reports) == 1
    assert reports[0]["report_period"] == "2026Q2"
    assert reports[0]["public_date"] == "2026-08-14"  # 2026-06-30 + 45 days


def test_fully_promoted_short_history_reports_continuity_gap(connection) -> None:
    row = statement("FPT", "2026Q2", date(2026, 8, 15), revenue=1.0, net_income=1.0,
                     total_equity=1.0, short_term_debt=0.0, long_term_debt=0.0)
    chain = ProviderChain([StubProvider(statements=(row,))])

    outcome = refresh_financials(connection, chain, "FPT")

    assert outcome.rows_promoted == 1
    assert outcome.coverage.status == "PARTIAL"
    assert "missing contiguous quarters" in outcome.error_reason


def test_partially_promoted_result_reports_the_exact_promoted_ratio(connection) -> None:
    good = statement("FPT", "2026Q2", date(2026, 8, 15), revenue=1.0, net_income=1.0,
                      total_equity=1.0, short_term_debt=0.0, long_term_debt=0.0)
    bad = statement("FPT", "2026Q1", date(2026, 5, 1), revenue=1.0, net_income=1.0,
                     total_equity=1.0)  # missing debt legs -> not promotable
    chain = ProviderChain([StubProvider(statements=(good, bad), status=ProviderStatus.AVAILABLE)])

    outcome = refresh_financials(connection, chain, "FPT")

    assert outcome.rows_promoted == 1 and outcome.rows_stored == 2
    assert "1/2" in outcome.coverage.error_reason
    assert "missing short_term_debt or long_term_debt" in outcome.coverage.error_reason


def test_missing_result_is_recorded_for_a_brand_new_symbol_without_crashing(connection) -> None:
    chain = ProviderChain([StubProvider()])  # no statements at all -> MISSING

    outcome = refresh_financials(connection, chain, "VHM")  # never inserted into symbols

    assert outcome.result is RefreshResult.MISSING
    assert outcome.coverage.status == "MISSING"
    assert load_coverage(connection, "VHM", "FINANCIALS") is not None


def test_provider_error_is_recorded_as_failed_and_stays_retryable(connection) -> None:
    chain = ProviderChain([StubProvider(error="upstream 500")])

    outcome = refresh_financials(connection, chain, "FPT")

    assert outcome.result is RefreshResult.FAILED
    assert outcome.error_reason == "upstream 500"
    assert outcome.coverage.status == "ERROR"
    # a later successful attempt is not blocked by the earlier failure
    row = statement("FPT", "2026Q2", date(2026, 8, 15), revenue=1.0, net_income=1.0,
                     total_equity=1.0, short_term_debt=0.0, long_term_debt=0.0)
    retry = refresh_financials(connection, ProviderChain([StubProvider(statements=(row,))]), "FPT", force=True)
    assert retry.result is RefreshResult.SUCCESS


def test_coverage_attempts_accumulate_and_last_success_is_preserved_through_a_later_error(connection) -> None:
    row = statement("FPT", "2026Q2", date(2026, 8, 15), revenue=1.0, net_income=1.0,
                     total_equity=1.0, short_term_debt=0.0, long_term_debt=0.0)
    refresh_financials(connection, ProviderChain([StubProvider(statements=(row,))]), "FPT")
    success_time = load_coverage(connection, "FPT", "FINANCIALS").last_success_at

    refresh_financials(connection, ProviderChain([StubProvider(error="timeout")]), "FPT", force=True)
    after_error = load_coverage(connection, "FPT", "FINANCIALS")

    assert after_error.attempts == 2
    assert after_error.status == "ERROR"
    assert after_error.last_success_at == success_time


# ----------------------------------------------------------- institutional
def test_institutional_flow_is_persisted_via_the_existing_canonical_table(connection) -> None:
    flow = FlowRow("FPT", date(2026, 9, 1), foreign_buy_value=10.0, foreign_sell_value=5.0)
    chain = ProviderChain([StubProvider(flows=(flow,))])

    outcome = refresh_institutional_flow(connection, chain, "FPT")

    assert outcome.result is RefreshResult.SUCCESS
    rows = recent_flows(connection, "FPT", date(2026, 12, 31))
    assert len(rows) == 1 and rows[0]["foreign_buy_value"] == 10.0
    assert rows[0]["proprietary_buy_value"] is None  # missing leg stays missing, not 0


def test_institutional_flow_rerun_is_idempotent_on_symbol_and_date(connection) -> None:
    flow = FlowRow("FPT", date(2026, 9, 1), foreign_buy_value=10.0)
    chain = ProviderChain([StubProvider(flows=(flow,))])

    refresh_institutional_flow(connection, chain, "FPT")
    refresh_institutional_flow(connection, chain, "FPT", force=True)

    assert len(recent_flows(connection, "FPT", date(2026, 12, 31))) == 1


def test_institutional_flow_missing_leg_is_distinguished_from_available_leg(connection) -> None:
    flow = FlowRow("FPT", date(2026, 9, 1), foreign_buy_value=10.0, foreign_sell_value=5.0)
    outcome = refresh_institutional_flow(connection, ProviderChain([StubProvider(flows=(flow,))]), "FPT")
    assert outcome.result is RefreshResult.SUCCESS  # AVAILABLE requires both legs per StubProvider mapping

    both_missing = refresh_institutional_flow(connection, ProviderChain([StubProvider()]), "VHM")
    assert both_missing.result is RefreshResult.MISSING


def test_promote_corporate_statement_rejects_when_no_public_date_and_no_period() -> None:
    row = StatementRow("FPT", "INVALID", None, values={
        "revenue": 1.0, "net_income": 1.0, "total_equity": 1.0,
        "short_term_debt": 0.0, "long_term_debt": 0.0,
    })
    assert promote_corporate_statement(row, source="VNStock") is None
    assert corporate_promotion_gap(row) == "no public_date or parsable report_period"


# -------------------------------------------- Issue 9: Required tests A-F
def test_issue9_a_actual_public_date() -> None:
    """A. Có actual public_date -> dùng actual."""
    row = statement("FPT", "2026Q2", date(2026, 8, 20), revenue=100.0, net_income=10.0,
                     total_equity=200.0, short_term_debt=10.0, long_term_debt=10.0)
    report = promote_corporate_statement(row, source="VNStock/VCI")
    assert report is not None
    assert report.public_date == date(2026, 8, 20)
    assert report.public_date_source == "actual"


def test_issue9_b_estimated_public_date_from_report_period() -> None:
    """B. Không có actual, có report_period -> +45 ngày."""
    row = statement("FPT", "2026Q2", None, revenue=100.0, net_income=10.0,
                     total_equity=200.0, short_term_debt=10.0, long_term_debt=10.0)
    report = promote_corporate_statement(row, source="VNStock/TCBS")
    assert report is not None
    assert report.public_date == date(2026, 8, 14)
    assert report.public_date_source == "estimated_45d"
    # Anti-look-ahead check: must not use period_end directly
    assert report.public_date != date(2026, 6, 30)


def test_issue9_c_reject_when_neither_available() -> None:
    """C. Không có cả hai -> reject."""
    row = StatementRow("FPT", "INVALID", None, values={
        "revenue": 100.0, "net_income": 10.0, "total_equity": 200.0,
        "short_term_debt": 10.0, "long_term_debt": 10.0,
    })
    assert corporate_promotion_gap(row) == "no public_date or parsable report_period"
    assert promote_corporate_statement(row, source="VNStock") is None


def test_issue9_d_e_point_in_time_boundary(connection) -> None:
    """D. as_of trước estimated public_date -> chưa được dùng.
       E. as_of sau estimated public_date -> được dùng."""
    row = statement("FPT", "2026Q2", None, revenue=100.0, net_income=10.0,
                     total_equity=200.0, short_term_debt=10.0, long_term_debt=10.0)
    report = promote_corporate_statement(row, source="VNStock/TCBS")
    assert report is not None
    upsert_financial_reports(connection, [report])

    # D: Trước ngày công bố ước tính 2026-08-14 (ví dụ 2026-08-13) -> chưa dùng
    before = latest_financial_reports(connection, "FPT", as_of=date(2026, 8, 13))
    assert len(before) == 0

    # E: Tại và sau ngày công bố ước tính 2026-08-14 (ví dụ 2026-08-14) -> được dùng
    at_date = latest_financial_reports(connection, "FPT", as_of=date(2026, 8, 14))
    assert len(at_date) == 1
    assert at_date[0]["report_period"] == "2026Q2"
    assert at_date[0]["public_date"] == "2026-08-14"

    after = latest_financial_reports(connection, "FPT", as_of=date(2026, 8, 20))
    assert len(after) == 1


def test_issue9_f_eight_quarters_estimated_public_date_enables_score(connection) -> None:
    """F. TCBS/yfinance có đủ 8 quý -> fundamental_score không còn None chỉ vì thiếu public_date."""
    periods = [
        ("2026Q2", 150.0, 30.0), ("2026Q1", 140.0, 28.0),
        ("2025Q4", 130.0, 26.0), ("2025Q3", 120.0, 24.0),
        ("2025Q2", 100.0, 20.0), ("2025Q1", 95.0, 19.0),
        ("2024Q4", 90.0, 18.0), ("2024Q3", 85.0, 17.0),
    ]
    reports = []
    for period, rev, profit in periods:
        row = statement("FPT", period, None, revenue=rev, net_income=profit,
                         total_equity=100.0, short_term_debt=10.0, long_term_debt=10.0)
        report = promote_corporate_statement(row, source="VNStock/TCBS")
        assert report is not None
        assert report.public_date_source == "estimated_45d"
        reports.append(report)
    upsert_financial_reports(connection, reports)

    from asmf_data.scoring import fundamental_score
    score = fundamental_score(connection, "FPT", as_of=date(2026, 8, 20))
    assert score is not None
    assert score == 100.0


def test_corporate_promotion_gap_names_missing_debt_legs() -> None:
    row = statement("FPT", "2026Q2", date(2026, 8, 15), revenue=1.0, net_income=1.0,
                     total_equity=1.0, short_term_debt=1.0)  # long_term_debt missing
    assert corporate_promotion_gap(row) == "missing short_term_debt or long_term_debt"


def test_corporate_promotion_gap_is_none_exactly_when_the_row_promotes() -> None:
    row = statement("FPT", "2026Q2", date(2026, 8, 15), revenue=1.0, net_income=1.0,
                     total_equity=1.0, short_term_debt=0.0, long_term_debt=0.0)
    assert corporate_promotion_gap(row) is None
    assert promote_corporate_statement(row, source="VNStock") is not None


def test_promote_corporate_statement_requires_both_debt_legs_not_a_zero_guess() -> None:
    row = statement("FPT", "2026Q2", date(2026, 8, 15), revenue=1.0, net_income=1.0,
                     total_equity=1.0, short_term_debt=1.0)  # long_term_debt missing
    assert promote_corporate_statement(row, source="VNStock") is None


def test_promote_corporate_statement_prefers_net_income_parent() -> None:
    row = statement("FPT", "2026Q2", date(2026, 8, 15), revenue=1.0, net_income=999.0,
                     net_income_parent=5.0, total_equity=1.0,
                     short_term_debt=0.0, long_term_debt=0.0)
    promoted = promote_corporate_statement(row, source="VNStock")
    assert promoted is not None and promoted.net_profit == 5.0


def test_bank_statements_are_never_promoted_regardless_of_completeness() -> None:
    row = statement(
        "ACB", "2026Q2", date(2026, 8, 10),
        net_interest_income=50.0, net_profit=10.0, equity=900.0, gross_loans=8000.0,
    )
    assert promote_bank_statement(row, source="VNStock") is None


def test_verified_vietcap_bank_statement_promotes_as_cumulative_ytd() -> None:
    row = statement(
        "ACB", "2026Q2", date(2026, 8, 10),
        net_interest_income=50.0, net_profit=10.0, equity=900.0,
        gross_loans=8000.0, loan_loss_reserve=200.0,
    )
    report = promote_bank_statement(row, source=VIETCAP_BANK_SOURCE)
    assert report is not None
    assert report.period_months == 6
    assert report.loan_loss_reserve == 200.0


def test_flow_row_to_institutional_flow_keeps_missing_legs_missing() -> None:
    row = FlowRow("FPT", date(2026, 9, 1), foreign_buy_value=10.0)
    converted = flow_row_to_institutional_flow(row, source="VNStock/VCI")
    assert converted.proprietary_buy_value is None
    assert converted.source == "VNStock/VCI"


# ------------------------------------------------------- ASMF regression (§18)
def test_asmf_score_is_identical_whether_data_arrives_manually_or_via_automated_refresh(
    connection, tmp_path,
) -> None:
    """The single most important Phase 24 invariant: same stored inputs, same
    strategy output, whether a report reached the canonical table through the
    old manual path or through the new provider -> refresh_service path."""
    def eight_quarters() -> list[dict[str, float | str]]:
        rows = []
        for i in range(8):
            quarter = 4 - (i % 4)
            year = 2025 if i < 4 else 2024
            rows.append({
                "period": f"{year}Q{quarter}",
                "public_date": date(year, 3 * quarter if quarter < 4 else 12, 15),
                "revenue": 1000 + (50 if i < 4 else 0),
                "net_profit": 200 + (30 if i < 4 else 0) - i,
            })
        return rows

    manual_conn = connect_database(f"sqlite:///{tmp_path / 'manual.sqlite3'}")
    bootstrap_schema(manual_conn)
    manual_conn.execute("INSERT INTO symbols(symbol) VALUES ('FPT')")
    manual_conn.commit()
    manual_reports = [
        FinancialReport(
            "FPT", row["period"], row["public_date"], True,
            revenue=row["revenue"], net_profit=row["net_profit"],
            equity=2000.0, total_debt=1000.0, source="manual",
        )
        for row in eight_quarters()
    ]
    upsert_financial_reports(manual_conn, manual_reports)
    manual_score = fundamental_score(manual_conn, "FPT", date(2026, 1, 1))

    statements = tuple(
        statement(
            "FPT", row["period"], row["public_date"],
            revenue=row["revenue"], net_income=row["net_profit"],
            total_equity=2000.0, short_term_debt=600.0, long_term_debt=400.0,
        )
        for row in eight_quarters()
    )
    chain = ProviderChain([StubProvider(statements=statements)])
    outcome = refresh_financials(connection, chain, "FPT", force=True)
    automated_score = fundamental_score(connection, "FPT", date(2026, 1, 1))

    assert outcome.rows_promoted == 8
    assert manual_score is not None
    assert automated_score == manual_score


def test_unverified_automated_bank_rows_never_reach_canonical_scoring(
    connection,
) -> None:
    """A complete row without verified cumulative provenance stays staging-only."""
    bank_row = statement(
        "FPT", "2026Q2", date(2026, 8, 10),  # symbol reused, content shaped like a bank
        net_interest_income=50.0, net_profit=10.0, equity=900.0, gross_loans=8000.0,
    )
    chain = ProviderChain([StubProvider(statements=(bank_row,))])
    refresh_financials(connection, chain, "FPT", force=True)

    assert latest_bank_financial_reports(connection, "FPT", date(2026, 12, 31)) == ()
    assert fundamental_score(connection, "FPT", date(2026, 1, 1)) is None


# ------------------------------------------------------------- coverage_store
def test_coverage_is_stale_when_never_successfully_fetched() -> None:
    from fundamentals.coverage_store import CoverageStatus

    never = CoverageStatus(
        symbol="FPT", dataset="FINANCIALS", status="NEVER_ATTEMPTED",
        provider=None, provider_source=None, error_reason=None, attempts=0,
        last_attempt_at=None, last_success_at=None, updated_at=0,
    )
    assert coverage_is_stale(never, 999999)


def test_load_all_coverage_filters_by_dataset(connection) -> None:
    row = statement("FPT", "2026Q2", date(2026, 8, 15), revenue=1.0, net_income=1.0,
                     total_equity=1.0, short_term_debt=0.0, long_term_debt=0.0)
    refresh_financials(connection, ProviderChain([StubProvider(statements=(row,))]), "FPT")

    financials_only = load_all_coverage(connection, "FINANCIALS")
    institutional_only = load_all_coverage(connection, "INSTITUTIONAL")

    assert len(financials_only) == 1 and financials_only[0].symbol == "FPT"
    assert institutional_only == ()


# ------------------------------------------------------------- Issue 10 ASMF readiness
def test_issue10_eight_quarters_yields_ready_even_if_provider_result_partial(connection) -> None:
    """When a symbol has >= 8 canonical quarters promoted, coverage must be READY
    even if provider had a 9th unpromoted statement and status is PARTIAL."""
    def eight_valid_plus_one_bad() -> list[StatementRow]:
        rows = []
        for i in range(8):
            quarter = 4 - (i % 4)
            year = 2025 if i < 4 else 2024
            rows.append(statement(
                "FPT", f"{year}Q{quarter}", date(year, 3 * quarter if quarter < 4 else 12, 15),
                revenue=1000.0 + i * 50, net_income=100.0 + i * 10,
                total_equity=2000.0, short_term_debt=500.0, long_term_debt=500.0,
            ))
        # 9th statement missing revenue
        rows.append(statement(
            "FPT", "2023Q4", date(2024, 2, 15),
            revenue=None, net_income=50.0, total_equity=1000.0,
        ))
        return rows

    chain = ProviderChain([StubProvider(statements=tuple(eight_valid_plus_one_bad()), status=ProviderStatus.PARTIAL)])
    outcome = refresh_financials(connection, chain, "FPT", force=True)

    assert outcome.rows_stored == 9
    assert outcome.rows_promoted == 8
    assert outcome.coverage.status == "READY"
    assert "READY FOR ASMF (8 quarters available" in outcome.coverage.error_reason
    assert "BLOCKED BY DATA SOURCE" not in outcome.coverage.error_reason
    assert fundamental_score(connection, "FPT", date(2026, 9, 22)) is not None


def test_issue10_fewer_than_eight_quarters_yields_partial_when_provider_partial(connection) -> None:
    """When a symbol has < 8 canonical quarters promoted and provider status is PARTIAL,
    coverage must report PARTIAL with the exact continuity gap."""
    good = statement("FPT", "2026Q2", date(2026, 8, 15), revenue=1000.0, net_income=100.0,
                     total_equity=2000.0, short_term_debt=100.0, long_term_debt=100.0)
    bad = statement("FPT", "2026Q1", date(2026, 5, 1), revenue=None, net_income=100.0)
    chain = ProviderChain([StubProvider(statements=(good, bad), status=ProviderStatus.PARTIAL)])
    outcome = refresh_financials(connection, chain, "FPT", force=True)

    assert outcome.rows_promoted == 1
    assert outcome.coverage.status == "PARTIAL"
    assert "missing contiguous quarters" in outcome.coverage.error_reason


def test_financial_readiness_rejects_eight_noncontiguous_quarters(connection) -> None:
    periods = (
        "2026Q2", "2026Q1", "2025Q4", "2025Q2",
        "2025Q1", "2024Q4", "2024Q3", "2024Q2",
    )
    rows = tuple(
        statement(
            "FPT", period, date(2026, 9, 1), revenue=1000.0,
            net_income=100.0, total_equity=2000.0,
            short_term_debt=100.0, long_term_debt=100.0,
        )
        for period in periods
    )
    outcome = refresh_financials(
        connection, ProviderChain([StubProvider(statements=rows)]), "FPT", force=True
    )

    assert outcome.rows_promoted == 8
    assert outcome.coverage.status == "PARTIAL"
    assert "missing contiguous quarters: 2025Q3" in outcome.coverage.error_reason
    assert fundamental_score(connection, "FPT", date(2026, 9, 22)) is None


def test_yfinance_refresh_removes_legacy_rows_not_in_quarterly_snapshot(connection) -> None:
    legacy = FinancialReport(
        "FPT", "2024Q4", date(2025, 2, 14), True,
        60_000.0, 8_000.0, 30_000.0, 5_000.0, "yfinance/FPT.VN",
    )
    upsert_financial_reports(connection, [legacy])
    current = statement(
        "FPT", "2026Q2", None, revenue=18_000.0, net_income=2_500.0,
        total_equity=35_000.0, short_term_debt=1_000.0, long_term_debt=4_000.0,
    )

    class YahooProvider(StubProvider):
        name = "yfinance"

        def fetch_financials(self, symbol, *, exchange=None):
            return ProviderResult(
                symbol=symbol, dataset="FINANCIALS", provider=self.name,
                provider_source="FPT.VN", status=ProviderStatus.AVAILABLE,
                statements=(current,),
            )

    refresh_financials(connection, ProviderChain([YahooProvider()]), "FPT", force=True)

    periods = tuple(
        row["report_period"]
        for row in latest_financial_reports(connection, "FPT", date(2026, 12, 31))
    )
    assert periods == ("2026Q2",)
    assert "2024Q4" not in periods
    source = connection.execute(
        "SELECT source FROM financial_reports WHERE symbol='FPT' AND report_period='2026Q2'"
    ).fetchone()[0]
    assert source == "yfinance/FPT.VN/quarterly"
    assert fundamental_score(connection, "FPT", date(2026, 9, 22)) is None


def test_yfinance_fallback_never_overwrites_a_preferred_canonical_source(connection) -> None:
    trusted = FinancialReport(
        "FPT", "2026Q1", date(2026, 4, 30), True,
        777.0, 77.0, 2000.0, 500.0, "VNStock/KBS",
    )
    upsert_financial_reports(connection, [trusted])
    yahoo_rows = (
        statement(
            "FPT", "2026Q1", None, revenue=999.0, net_income=99.0,
            total_equity=2000.0, short_term_debt=100.0, long_term_debt=400.0,
        ),
        statement(
            "FPT", "2026Q2", None, revenue=1000.0, net_income=100.0,
            total_equity=2100.0, short_term_debt=100.0, long_term_debt=400.0,
        ),
    )

    class YahooProvider(StubProvider):
        name = "yfinance"

        def fetch_financials(self, symbol, *, exchange=None):
            return ProviderResult(
                symbol=symbol, dataset="FINANCIALS", provider=self.name,
                provider_source="FPT.VN", status=ProviderStatus.AVAILABLE,
                statements=yahoo_rows,
            )

    outcome = refresh_financials(
        connection, ProviderChain([YahooProvider()]), "FPT", force=True
    )

    rows = connection.execute(
        "SELECT report_period,revenue,source FROM financial_reports "
        "WHERE symbol='FPT' ORDER BY report_period"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("2026Q1", 777.0, "VNStock/KBS"),
        ("2026Q2", 1000.0, "yfinance/FPT.VN/quarterly"),
    ]
    assert outcome.rows_promoted == 1


def test_legacy_yfinance_rows_are_invisible_before_the_first_corrected_refresh(connection) -> None:
    rows = [
        FinancialReport(
            "FPT", f"{year}Q{quarter}", date(year, quarter * 3, 28), True,
            1000.0, 100.0, 2000.0, 500.0, "yfinance/FPT.VN",
        )
        for year in (2024, 2025)
        for quarter in range(1, 5)
    ]
    upsert_financial_reports(connection, rows)

    assert latest_financial_reports(connection, "FPT", date(2026, 1, 1)) == ()
    assert fundamental_score(connection, "FPT", date(2026, 1, 1)) is None


def test_verified_vietcap_bank_refresh_promotes_without_overwriting_manual_rows(connection) -> None:
    periods = (
        "2024Q3", "2024Q4", "2025Q1", "2025Q2",
        "2025Q3", "2025Q4", "2026Q1", "2026Q2",
    )
    rows = tuple(
        statement(
            "ACB", period, date(int(period[:4]), int(period[-1]) * 3, 28),
            net_interest_income=100.0 * int(period[-1]),
            net_profit=20.0 * int(period[-1]), equity=1000.0,
            gross_loans=8000.0, loan_loss_reserve=200.0,
        )
        for period in periods
    )

    class VietcapBankProvider(StubProvider):
        name = "VietcapIQ"

        def fetch_financials(self, symbol, *, exchange=None):
            return ProviderResult(
                symbol=symbol, dataset="FINANCIALS", provider=self.name,
                provider_source="IQ/financial-statement",
                status=ProviderStatus.PARTIAL, statements=rows,
                error_reason="bank BCTC available; NPL and CAR are absent",
            )

    outcome = refresh_financials(
        connection, ProviderChain([VietcapBankProvider(statements=rows)]),
        "ACB", force=True,
    )
    stored = latest_bank_financial_reports(connection, "ACB", date(2026, 12, 31))
    assert outcome.rows_promoted == 8
    assert outcome.coverage.status == "READY"
    assert len(stored) == 8
    assert stored[0]["source"] == VIETCAP_BANK_SOURCE
    assert fundamental_score(connection, "ACB", date(2026, 12, 31)) is None


def test_verified_securities_bctc_is_staged_but_not_scored_as_corporate(connection) -> None:
    upsert_financial_reports(connection, [FinancialReport(
        "VIX", "2026Q2", date(2026, 8, 20), True,
        999.0, 99.0, 2000.0, 600.0,
        "VietcapIQ/IQ/financial-statement/borrowings-v2",
    )])
    upsert_financial_reports(connection, [FinancialReport(
        "VIX", "2026Q1", date(2026, 5, 20), True,
        888.0, 88.0, 1900.0, 500.0, "manual-reviewed",
    )])
    rows = tuple(
        statement(
            "VIX", f"{year}Q{quarter}", date(year, quarter * 3, 28),
            revenue=1000.0, net_income_parent=100.0, total_equity=2000.0,
            short_term_debt=500.0, long_term_debt=100.0,
        )
        for year, quarter in (
            (2024, 3), (2024, 4), (2025, 1), (2025, 2),
            (2025, 3), (2025, 4), (2026, 1), (2026, 2),
        )
    )

    class VietcapSecuritiesProvider(StubProvider):
        name = "VietcapIQ"

        def fetch_financials(self, symbol, *, exchange=None):
            return ProviderResult(
                symbol=symbol, dataset="FINANCIALS", provider=self.name,
                provider_source="IQ/financial-statement",
                status=ProviderStatus.AVAILABLE, statements=rows,
                statement_schema="securities",
            )

    outcome = refresh_financials(
        connection, ProviderChain([VietcapSecuritiesProvider(statements=rows)]),
        "VIX", force=True,
    )

    assert outcome.result is RefreshResult.SUCCESS
    assert outcome.rows_stored == 8 and outcome.rows_promoted == 0
    assert outcome.coverage.status == "PARTIAL"
    assert "securities BCTC staged" in outcome.coverage.error_reason
    assert len(load_automated_statements(connection, "VIX")) == 8
    assert len(latest_financial_reports(connection, "VIX", date(2026, 12, 31))) == 1
    assert fundamental_score(connection, "VIX", date(2026, 12, 31)) is None
    remaining = connection.execute(
        "SELECT report_period,source FROM financial_reports WHERE symbol='VIX'"
    ).fetchall()
    assert [tuple(row) for row in remaining] == [("2026Q1", "manual-reviewed")]


def test_verified_insurance_bctc_is_staged_but_not_scored_as_corporate(connection) -> None:
    rows = tuple(
        statement(
            "ABI", f"{year}Q{quarter}", date(year, quarter * 3, 28),
            revenue=1000.0, net_income=100.0, total_equity=2000.0,
            short_term_debt=50.0, long_term_debt=10.0,
        )
        for year, quarter in (
            (2024, 3), (2024, 4), (2025, 1), (2025, 2),
            (2025, 3), (2025, 4), (2026, 1), (2026, 2),
        )
    )

    class VietcapInsuranceProvider(StubProvider):
        name = "VietcapIQ"

        def fetch_financials(self, symbol, *, exchange=None):
            return ProviderResult(
                symbol=symbol, dataset="FINANCIALS", provider=self.name,
                provider_source="IQ/financial-statement",
                status=ProviderStatus.AVAILABLE, statements=rows,
                statement_schema="insurance",
            )

    outcome = refresh_financials(
        connection, ProviderChain([VietcapInsuranceProvider(statements=rows)]),
        "ABI", force=True,
    )
    assert outcome.result is RefreshResult.SUCCESS
    assert outcome.rows_stored == 8 and outcome.rows_promoted == 0
    assert outcome.coverage.status == "PARTIAL"
    assert "insurance BCTC staged" in outcome.coverage.error_reason
    assert len(load_automated_statements(connection, "ABI")) == 8
    assert latest_financial_reports(connection, "ABI", date(2026, 12, 31)) == ()
    assert fundamental_score(connection, "ABI", date(2026, 12, 31)) is None


def test_legacy_vietcap_liability_mapped_rows_are_invisible(connection) -> None:
    row = FinancialReport(
        "FPT", "2026Q2", date(2026, 8, 22), True,
        1000.0, 100.0, 2000.0, 900.0,
        "VietcapIQ/IQ/financial-statement",
    )
    upsert_financial_reports(connection, [row])

    assert latest_financial_reports(connection, "FPT", date(2026, 12, 31)) == ()


def test_vietcap_canonical_source_cannot_be_downgraded_by_vnstock(connection) -> None:
    trusted = FinancialReport(
        "FPT", "2026Q2", date(2026, 8, 22), True,
        777.0, 77.0, 2000.0, 200.0,
        "VietcapIQ/IQ/financial-statement/borrowings-v2",
    )
    upsert_financial_reports(connection, [trusted])
    fallback_row = statement(
        "FPT", "2026Q2", date(2026, 8, 23), revenue=999.0,
        net_income=99.0, total_equity=2000.0,
        short_term_debt=100.0, long_term_debt=400.0,
    )

    outcome = refresh_financials(
        connection, ProviderChain([StubProvider(statements=(fallback_row,))]),
        "FPT", force=True,
    )

    stored = connection.execute(
        "SELECT revenue,source FROM financial_reports "
        "WHERE symbol='FPT' AND report_period='2026Q2'"
    ).fetchone()
    assert tuple(stored) == (
        777.0, "VietcapIQ/IQ/financial-statement/borrowings-v2"
    )
    assert outcome.rows_promoted == 0


def test_vietcap_canonical_source_upgrades_lower_priority_automated_data(connection) -> None:
    lower_priority = FinancialReport(
        "FPT", "2026Q2", date(2026, 8, 14), True,
        500.0, 50.0, 1900.0, 450.0, "VNStock/KBS",
    )
    upsert_financial_reports(connection, [lower_priority])
    iq_row = statement(
        "FPT", "2026Q2", date(2026, 8, 22), revenue=777.0,
        net_income=77.0, total_equity=2000.0,
        short_term_debt=125.0, long_term_debt=75.0,
    )

    class VietcapProvider(StubProvider):
        name = "VietcapIQ"

        def fetch_financials(self, symbol, *, exchange=None):
            return ProviderResult(
                symbol=symbol, dataset="FINANCIALS", provider=self.name,
                provider_source="IQ/financial-statement",
                status=ProviderStatus.AVAILABLE, statements=(iq_row,),
            )

    outcome = refresh_financials(
        connection, ProviderChain([VietcapProvider(statements=(iq_row,))]),
        "FPT", force=True,
    )

    stored = connection.execute(
        "SELECT revenue,total_debt,source FROM financial_reports "
        "WHERE symbol='FPT' AND report_period='2026Q2'"
    ).fetchone()
    assert tuple(stored) == (
        777.0, 200.0,
        "VietcapIQ/IQ/financial-statement/borrowings-v2",
    )
    assert outcome.rows_promoted == 1


def test_issue10_five_flow_sessions_yields_ready_for_institutional(connection) -> None:
    """When >= 5 flow sessions are persisted, institutional flow coverage is READY
    even if provider returned PARTIAL status."""
    from asmf_data.scoring import institutional_flow_score
    flows = tuple(
        FlowRow("FPT", date(2026, 9, 10 + i), foreign_buy_value=10.0 + i, foreign_sell_value=5.0)
        for i in range(5)
    )
    chain = ProviderChain([StubProvider(flows=flows, status=ProviderStatus.PARTIAL)])
    outcome = refresh_institutional_flow(connection, chain, "FPT", force=True)

    assert outcome.rows_promoted == 5
    assert outcome.coverage.status == "READY"
    assert institutional_flow_score(connection, "FPT", date(2026, 9, 22)) is not None

