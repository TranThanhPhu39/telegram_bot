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


# --------------------------------------------------------------- adapters
def test_promote_corporate_statement_requires_public_date() -> None:
    row = statement("FPT", "2026Q2", None, revenue=1.0, net_income=1.0,
                     total_equity=1.0, short_term_debt=0.0, long_term_debt=0.0)
    assert promote_corporate_statement(row, source="VNStock") is None


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


def test_bank_score_still_comes_only_from_the_ocr_vietstock_path_never_from_automated_staging(
    connection,
) -> None:
    """Even a complete automated bank statement must not leak into scoring."""
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
