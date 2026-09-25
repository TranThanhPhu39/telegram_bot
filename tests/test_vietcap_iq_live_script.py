"""Verdict semantics for the redacted Vietcap IQ live harness."""

from datetime import date

from fundamentals.providers.base import ProviderResult, ProviderStatus, StatementRow
from scripts.test_vietcap_iq_live import (
    FAIL, NOT_TESTED, PASS, UNSUPPORTED, evaluate_live_result,
)


def _row(period: str, *, complete: bool = True) -> StatementRow:
    values = {"revenue": 1.0}
    if complete:
        values.update({
            "net_income": 1.0,
            "net_income_parent": 1.0,
            "total_equity": 1.0,
            "short_term_debt": 0.0,
            "long_term_debt": 0.0,
        })
    return StatementRow("FPT", period, date(2026, 8, 22), values=values)


def test_live_harness_pass_requires_eight_complete_quarters(capsys) -> None:
    rows = tuple(_row(f"{year}Q{quarter}") for year, quarter in (
        (2024, 3), (2024, 4), (2025, 1), (2025, 2),
        (2025, 3), (2025, 4), (2026, 1), (2026, 2),
    ))
    result = ProviderResult(
        symbol="FPT", dataset="FINANCIALS", provider="VietcapIQ",
        status=ProviderStatus.AVAILABLE, statements=rows,
    )
    assert evaluate_live_result(result) == PASS
    output = capsys.readouterr().out
    assert "complete_quarters=8" in output and "latest=2026Q2" in output


def test_live_harness_auth_error_is_not_tested_and_redacted(capsys) -> None:
    result = ProviderResult.failed(
        "FPT", "FINANCIALS", "VietcapIQ", "upstream authentication failed",
        diagnostic_code="AUTH_FAILURE",
    )
    assert evaluate_live_result(result) == NOT_TESTED
    output = capsys.readouterr().out
    assert "NOT TESTED" in output
    assert "authentication failed" not in output


def test_live_harness_distinguishes_unsupported_schema(capsys) -> None:
    result = ProviderResult.failed(
        "VIX", "FINANCIALS", "VietcapIQ", "securities schema unsupported",
        diagnostic_code="UNSUPPORTED_SCHEMA",
    )
    assert evaluate_live_result(result) == UNSUPPORTED
    assert "UNSUPPORTED_SCHEMA" in capsys.readouterr().out


def test_live_harness_distinguishes_insufficient_data(capsys) -> None:
    result = ProviderResult.failed(
        "ACB", "FINANCIALS", "VietcapIQ", "no complete rows",
        diagnostic_code="INSUFFICIENT_DATA",
    )
    assert evaluate_live_result(result) == FAIL
    assert "INSUFFICIENT_DATA" in capsys.readouterr().out


def test_live_harness_accepts_eight_bank_quarters(capsys) -> None:
    rows = tuple(
        StatementRow(
            "ACB", f"{year}Q{quarter}", date(2026, 8, 22),
            values={
                "net_interest_income": 10.0, "net_profit": 2.0,
                "equity": 100.0, "gross_loans": 800.0,
                "loan_loss_reserve": 20.0,
            },
        )
        for year, quarter in (
            (2024, 3), (2024, 4), (2025, 1), (2025, 2),
            (2025, 3), (2025, 4), (2026, 1), (2026, 2),
        )
    )
    result = ProviderResult(
        symbol="ACB", dataset="FINANCIALS", provider="VietcapIQ",
        status=ProviderStatus.PARTIAL, statements=rows,
    )
    assert evaluate_live_result(result) == PASS
    assert "schema=bank" in capsys.readouterr().out


def test_live_harness_accepts_eight_securities_quarters(capsys) -> None:
    rows = tuple(_row(f"{year}Q{quarter}") for year, quarter in (
        (2024, 3), (2024, 4), (2025, 1), (2025, 2),
        (2025, 3), (2025, 4), (2026, 1), (2026, 2),
    ))
    result = ProviderResult(
        symbol="VIX", dataset="FINANCIALS", provider="VietcapIQ",
        status=ProviderStatus.AVAILABLE, statements=rows,
        statement_schema="securities",
    )
    assert evaluate_live_result(result) == PASS
    assert "schema=securities" in capsys.readouterr().out


def test_live_harness_accepts_eight_insurance_quarters(capsys) -> None:
    rows = tuple(_row(f"{year}Q{quarter}") for year, quarter in (
        (2024, 3), (2024, 4), (2025, 1), (2025, 2),
        (2025, 3), (2025, 4), (2026, 1), (2026, 2),
    ))
    result = ProviderResult(
        symbol="ABI", dataset="FINANCIALS", provider="VietcapIQ",
        status=ProviderStatus.AVAILABLE, statements=rows,
        statement_schema="insurance",
    )
    assert evaluate_live_result(result) == PASS
    assert "schema=insurance" in capsys.readouterr().out


def test_live_harness_incomplete_answer_is_fail(capsys) -> None:
    result = ProviderResult(
        symbol="FPT", dataset="FINANCIALS", provider="VietcapIQ",
        status=ProviderStatus.PARTIAL, statements=(_row("2026Q2", complete=False),),
    )
    assert evaluate_live_result(result) == FAIL
    assert "fewer than 8" in capsys.readouterr().out


def test_live_harness_requires_public_dates(capsys) -> None:
    rows = tuple(
        StatementRow(
            "FPT", f"2025Q{quarter}", None,
            values={
                "revenue": 1.0, "net_income_parent": 1.0,
                "total_equity": 1.0, "short_term_debt": 0.0,
                "long_term_debt": 0.0,
            },
        )
        for quarter in (1, 2, 3, 4, 1, 2, 3, 4)
    )
    result = ProviderResult(
        symbol="FPT", dataset="FINANCIALS", provider="VietcapIQ",
        status=ProviderStatus.AVAILABLE, statements=rows,
    )
    assert evaluate_live_result(result) == FAIL
    assert "INSUFFICIENT_DATA" in capsys.readouterr().out
